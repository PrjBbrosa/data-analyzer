"""Tests for the process-wide diagnostics infrastructure."""

from __future__ import annotations

import io
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from mf4_analyzer import diagnostics


@pytest.fixture(autouse=True)
def _isolate_diagnostics_state():
    root = logging.getLogger()
    old_level = root.level
    old_handlers = list(root.handlers)
    old_last_sweep = getattr(diagnostics, "_last_sweep", None)
    diagnostics._THROTTLE_STATE.clear()
    if old_last_sweep is not None:
        diagnostics._last_sweep = 0.0
    yield
    diagnostics._THROTTLE_STATE.clear()
    if old_last_sweep is not None:
        diagnostics._last_sweep = old_last_sweep
    for handler in list(root.handlers):
        if handler not in old_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(old_level)


def test_logging_level_maps_names_numbers_and_unknowns(monkeypatch):
    monkeypatch.delenv("TRACELAB_LOG_LEVEL", raising=False)

    assert diagnostics._logging_level("DEBUG") == logging.DEBUG
    assert diagnostics._logging_level("INFO") == logging.INFO
    assert diagnostics._logging_level("WARNING") == logging.WARNING
    assert diagnostics._logging_level("ERROR") == logging.ERROR
    assert diagnostics._logging_level("CRITICAL") == logging.CRITICAL
    assert diagnostics._logging_level("15") == 15
    assert diagnostics._logging_level(25) == 25
    assert diagnostics._logging_level(None) == logging.INFO
    assert diagnostics._logging_level("not-a-level") == logging.INFO


def test_logging_level_does_not_require_python311_mapping_api(monkeypatch):
    monkeypatch.delattr(logging, "getLevelNamesMapping", raising=False)

    assert diagnostics._logging_level("DEBUG") == logging.DEBUG
    assert diagnostics._logging_level("INFO") == logging.INFO
    assert diagnostics._logging_level("not-a-level") == logging.INFO


@pytest.mark.parametrize(
    ("platform", "environment", "expected"),
    [
        (
            "win32",
            {"LOCALAPPDATA": "/windows/local"},
            Path("/windows/local/TraceLab/logs"),
        ),
        (
            "darwin",
            {},
            Path.home() / "Library" / "Logs" / "TraceLab",
        ),
        (
            "linux",
            {"XDG_STATE_HOME": "/xdg/state"},
            Path("/xdg/state/TraceLab/logs"),
        ),
    ],
)
def test_resolve_log_dir_is_platform_correct(
    monkeypatch, platform, environment, expected,
):
    monkeypatch.setattr(diagnostics.sys, "platform", platform)
    for name in ("TRACELAB_LOG_DIR", "LOCALAPPDATA", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert diagnostics.resolve_log_dir() == expected


def test_resolve_log_dir_honours_override(monkeypatch, tmp_path):
    target = tmp_path / "operator-selected"
    monkeypatch.setenv("TRACELAB_LOG_DIR", str(target))
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")

    assert diagnostics.resolve_log_dir() == target


def test_diagnostics_import_does_not_require_pyqt():
    script = """
import sys
sys.modules['PyQt5'] = None
import mf4_analyzer.diagnostics
print('clean')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean"


def test_setup_logging_writes_and_configures_5mib_by_5_rotation(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("TRACELAB_LOG_DIR", str(tmp_path))
    log_dir = diagnostics.setup_logging(level="INFO")
    logger = logging.getLogger("mf4_analyzer.tests.diagnostics.rotation")
    logger.info("first record")

    file_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, RotatingFileHandler)
        and getattr(handler, "_tracelab_diagnostics_handler", False)
    ]
    assert log_dir == tmp_path
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 5
    handler.flush()
    assert "first record" in (tmp_path / diagnostics.LOG_FILENAME).read_text(
        encoding="utf-8"
    )

    # Exercise retention without writing 30 MiB: RotatingFileHandler's own
    # rollover operation must retain no more than backupCount generations.
    for index in range(8):
        logger.info("generation %d", index)
        handler.flush()
        handler.doRollover()
    backups = sorted(tmp_path.glob(f"{diagnostics.LOG_FILENAME}.*"))
    assert len(backups) == 5
    assert backups[-1].name.endswith(".5")


def test_file_handler_filters_third_party_info_but_keeps_warnings_and_app_info(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("TRACELAB_LOG_DIR", str(tmp_path))
    diagnostics.setup_logging(level="DEBUG")

    logging.getLogger("numexpr.utils").info("third-party info noise")
    logging.getLogger("numexpr.utils").warning("third-party warning signal")
    logging.getLogger("mf4_analyzer.runtime").info("application info signal")
    logging.getLogger("mf4_analyzer_plugin").info("lookalike info noise")
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = (tmp_path / diagnostics.LOG_FILENAME).read_text(encoding="utf-8")
    assert "third-party info noise" not in text
    assert "lookalike info noise" not in text
    assert "third-party warning signal" in text
    assert "application info signal" in text


def test_setup_logging_unwritable_target_degrades_to_stderr(
    monkeypatch, tmp_path,
):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("TRACELAB_LOG_DIR", str(blocker / "logs"))
    stderr = io.StringIO()
    monkeypatch.setattr(diagnostics.sys, "stderr", stderr)

    resolved = diagnostics.setup_logging(level="INFO")
    logging.getLogger("tests.diagnostics.fallback").warning("stderr fallback")

    assert resolved == blocker / "logs"
    assert "stderr fallback" in stderr.getvalue()
    assert not any(
        isinstance(handler, RotatingFileHandler)
        and getattr(handler, "_tracelab_diagnostics_handler", False)
        for handler in logging.getLogger().handlers
    )


def _capture_logger(name):
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger(name)
    logger.handlers[:] = [_Capture()]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, records


def test_throttled_burst_suppression_summary_and_reopen(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: now[0])
    logger, records = _capture_logger("tests.diagnostics.throttle")

    for index in range(diagnostics.BURST + 4):
        diagnostics.throttled(
            logger, "stable-seam", logging.WARNING, "failure %d", index
        )

    assert [record.getMessage() for record in records] == [
        "failure 0",
        "failure 1",
        "failure 2",
    ]

    now[0] += diagnostics.WINDOW + 0.01
    diagnostics.throttled(
        logger, "stable-seam", logging.WARNING, "failure %d", 99
    )

    messages = [record.getMessage() for record in records]
    assert messages[-2] == "suppressed 4 occurrences in 60s for stable-seam"
    assert messages[-1] == "failure 99"


def test_throttled_state_is_bounded_oldest_first(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: now[0])
    logger = logging.getLogger("tests.diagnostics.bound")
    logger.handlers[:] = [logging.NullHandler()]
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)

    for index in range(diagnostics.MAX_KEYS + 1):
        diagnostics.throttled(
            logger, f"key-{index}", logging.WARNING, "failure"
        )
        now[0] += 0.001

    assert len(diagnostics._THROTTLE_STATE) == diagnostics.MAX_KEYS
    assert (logger.name, "key-0") not in diagnostics._THROTTLE_STATE
    assert (logger.name, f"key-{diagnostics.MAX_KEYS}") in diagnostics._THROTTLE_STATE


def test_throttled_10000_repeats_emit_only_the_burst(monkeypatch):
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: 10.0)
    logger, records = _capture_logger("tests.diagnostics.ten_thousand")

    for _index in range(10_000):
        diagnostics.throttled(
            logger, "persistent-seam", logging.WARNING, "persistent failure"
        )

    state = diagnostics._THROTTLE_STATE[(logger.name, "persistent-seam")]
    assert len(records) == diagnostics.BURST
    assert state[2] == 10_000 - diagnostics.BURST


def test_throttled_cross_key_sweep_reports_a_quiet_burst(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: now[0])
    logger, records = _capture_logger("tests.diagnostics.cross_key_sweep")

    for _index in range(10_000):
        diagnostics.throttled(
            logger, "quiet-seam", logging.WARNING, "persistent failure"
        )

    now[0] += diagnostics.WINDOW + 0.01
    diagnostics.throttled(
        logger, "different-seam", logging.WARNING, "different failure"
    )

    messages = [record.getMessage() for record in records]
    assert messages.count(
        "suppressed 9997 occurrences in 60s for quiet-seam"
    ) == 1
    assert messages[-1] == "different failure"


def test_manual_flush_reports_pending_count_once_without_full_window_claim(
    monkeypatch,
):
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: 10.0)
    logger, records = _capture_logger("tests.diagnostics.manual_flush")
    for _index in range(diagnostics.BURST + 4):
        diagnostics.throttled(
            logger, "quiet-seam", logging.WARNING, "persistent failure"
        )

    diagnostics.flush_throttle_summaries()
    diagnostics.flush_throttle_summaries()

    summaries = [
        record.getMessage()
        for record in records
        if record.getMessage().startswith("suppressed ")
    ]
    assert summaries == [
        "suppressed 4 occurrences before manual flush for quiet-seam"
    ]
    assert "60s" not in summaries[0]


def test_manual_flush_after_window_needs_no_further_throttled_call(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: now[0])
    logger, records = _capture_logger("tests.diagnostics.expired_manual_flush")
    for _index in range(diagnostics.BURST + 4):
        diagnostics.throttled(
            logger, "quiet-seam", logging.WARNING, "persistent failure"
        )

    now[0] += diagnostics.WINDOW + 0.01
    diagnostics.flush_throttle_summaries()

    assert [
        record.getMessage()
        for record in records
        if record.getMessage().startswith("suppressed ")
    ] == ["suppressed 4 occurrences before manual flush for quiet-seam"]


def test_oldest_key_eviction_reports_pending_count(monkeypatch):
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: 10.0)
    logger, records = _capture_logger("tests.diagnostics.eviction")
    for _index in range(diagnostics.BURST + 2):
        diagnostics.throttled(
            logger, "oldest-seam", logging.ERROR, "persistent failure"
        )
    for index in range(diagnostics.MAX_KEYS - 1):
        diagnostics.throttled(
            logger, f"filler-{index}", logging.WARNING, "filler failure"
        )

    diagnostics.throttled(
        logger, "overflow-seam", logging.WARNING, "overflow failure"
    )

    summary_records = [
        record
        for record in records
        if "throttle-key eviction" in record.getMessage()
    ]
    assert [record.getMessage() for record in summary_records] == [
        "suppressed 2 occurrences before throttle-key eviction for oldest-seam"
    ]
    assert summary_records[0].levelno == logging.ERROR
    assert (logger.name, "oldest-seam") not in diagnostics._THROTTLE_STATE


def test_setup_logging_registers_one_atexit_flush(monkeypatch, tmp_path):
    registrations = []
    monkeypatch.setenv("TRACELAB_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(diagnostics, "_throttle_flush_registered", False)
    monkeypatch.setattr(diagnostics.atexit, "register", registrations.append)

    diagnostics.setup_logging(level="INFO")
    diagnostics.setup_logging(level="INFO")

    assert registrations == [diagnostics._flush_at_exit]


def test_orderly_process_exit_flushes_pending_count_to_file(tmp_path):
    script = """
import logging
from mf4_analyzer import diagnostics

diagnostics.setup_logging(level="INFO")
logger = logging.getLogger("mf4_analyzer.tests.shutdown_flush")
for _index in range(diagnostics.BURST + 4):
    diagnostics.throttled(
        logger, "shutdown-seam", logging.WARNING, "persistent failure"
    )
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "TRACELAB_LOG_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    text = (tmp_path / diagnostics.LOG_FILENAME).read_text(encoding="utf-8")
    assert "suppressed 4 occurrences before shutdown flush for shutdown-seam" in text


def test_throttle_logging_occurs_only_after_releasing_state_lock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(diagnostics, "_monotonic", lambda: now[0])
    lock_states = []

    class _LockProbe(logging.Handler):
        def emit(self, record):
            lock_states.append(diagnostics._THROTTLE_LOCK.locked())

    logger = logging.getLogger("tests.diagnostics.lock_probe")
    logger.handlers[:] = [_LockProbe()]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for _index in range(diagnostics.BURST + 4):
        diagnostics.throttled(
            logger, "quiet-seam", logging.WARNING, "persistent failure"
        )
    now[0] += diagnostics.WINDOW + 0.01
    diagnostics.throttled(
        logger, "different-seam", logging.WARNING, "different failure"
    )

    assert lock_states
    assert not any(lock_states)


def test_sys_and_thread_excepthooks_log_tracebacks_chain_and_notify(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("TRACELAB_LOG_DIR", str(tmp_path))
    diagnostics.setup_logging(level="DEBUG")
    chained = []
    notices = []

    def previous_sys(exc_type, exc_value, traceback):
        chained.append(("sys", exc_type, str(exc_value), traceback))

    def previous_thread(args):
        chained.append(("thread", args.exc_type, str(args.exc_value), args.exc_traceback))

    monkeypatch.setattr(diagnostics.sys, "excepthook", previous_sys)
    monkeypatch.setattr(diagnostics.threading, "excepthook", previous_thread)
    diagnostics.install_excepthooks(on_error=notices.append)

    try:
        raise RuntimeError("main-hook-boom")
    except RuntimeError:
        main_info = sys.exc_info()
    diagnostics.sys.excepthook(*main_info)

    try:
        raise ValueError("thread-hook-boom")
    except ValueError:
        thread_info = sys.exc_info()
    diagnostics.threading.excepthook(
        SimpleNamespace(
            exc_type=thread_info[0],
            exc_value=thread_info[1],
            exc_traceback=thread_info[2],
            thread=SimpleNamespace(name="diagnostics-worker"),
        )
    )

    for handler in logging.getLogger().handlers:
        handler.flush()
    text = (tmp_path / diagnostics.LOG_FILENAME).read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in text
    assert "RuntimeError: main-hook-boom" in text
    assert "ValueError: thread-hook-boom" in text
    assert "diagnostics-worker" in text
    assert [item[0] for item in chained] == ["sys", "thread"]
    assert len(notices) == 2
    assert all("发生内部错误" in notice for notice in notices)
    assert all(str(tmp_path / diagnostics.LOG_FILENAME) in notice for notice in notices)


def test_qt_message_handler_maps_levels_and_contains_failures(monkeypatch):
    from PyQt5 import QtCore

    installed = []
    calls = []
    monkeypatch.setattr(
        QtCore, "qInstallMessageHandler", lambda handler: installed.append(handler)
    )

    def capture(logger, key, level, msg, *args, **kwargs):
        calls.append((key, level, msg, args, kwargs))

    monkeypatch.setattr(diagnostics, "throttled", capture)
    diagnostics.install_qt_message_handler()
    assert len(installed) == 1
    handler = installed[0]
    context = SimpleNamespace(category="qt.paint")
    expected = [
        (QtCore.QtDebugMsg, logging.DEBUG),
        (QtCore.QtInfoMsg, logging.INFO),
        (QtCore.QtWarningMsg, logging.WARNING),
        (QtCore.QtCriticalMsg, logging.ERROR),
        (QtCore.QtFatalMsg, logging.ERROR),
    ]
    for msg_type, _level in expected:
        handler(msg_type, context, "repeated message " + "x" * 100)

    assert [call[1] for call in calls] == [level for _msg, level in expected]
    assert all(call[0].startswith("qt:qt.paint:repeated message") for call in calls)
    assert all(len(call[0].split(":", 2)[-1]) == 80 for call in calls)

    monkeypatch.setattr(
        diagnostics,
        "throttled",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("logger failed")),
    )
    handler(QtCore.QtWarningMsg, context, "must not escape")


def test_app_main_wires_diagnostics_in_required_order(monkeypatch, tmp_path):
    from mf4_analyzer import app as app_module

    events = []
    windows = []
    error_callbacks = []

    class _FakeApplication:
        def __init__(self, argv):
            events.append("qapplication")

        def setStyle(self, style):
            events.append("style")

        def setWindowIcon(self, icon):
            raise AssertionError("icon was stubbed to None")

        def exec_(self):
            events.append("exec")
            return 0

    class _FakeWindow:
        def __init__(self):
            events.append("window")
            windows.append(self)

        def toast(self, message, level="info"):
            events.append(("toast", message, level))

        def show(self):
            events.append("show")

    qtwidgets = ModuleType("PyQt5.QtWidgets")
    qtwidgets.QApplication = _FakeApplication
    fonts = ModuleType("mf4_analyzer.ui.pg_canvas.fonts")
    fonts.apply_global_chart_font = lambda app: events.append("chart-font")
    monkeypatch.setitem(sys.modules, "PyQt5.QtWidgets", qtwidgets)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.ui.pg_canvas.fonts", fonts)

    symbols = {
        ("ui", "MainWindow"): _FakeWindow,
        ("ui_kit", "setup_chinese_font"): lambda: events.append("chinese-font"),
        ("ui_kit", "load_stylesheet"): lambda app: events.append("stylesheet"),
        ("ui_kit", "install_glass_tooltips"): lambda app: events.append("tooltips"),
    }
    monkeypatch.setattr(
        app_module, "_import_symbol", lambda module, symbol: symbols[(module, symbol)]
    )
    monkeypatch.setattr(
        app_module,
        "setup_logging",
        lambda **kwargs: events.append("setup-logging") or tmp_path,
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "install_qt_message_handler",
        lambda: events.append("qt-handler"),
        raising=False,
    )

    def install_hooks(*, on_error):
        error_callbacks.append(on_error)
        events.append("exception-hooks")

    monkeypatch.setattr(
        app_module, "install_excepthooks", install_hooks, raising=False
    )
    monkeypatch.setattr(
        app_module, "_configure_high_dpi", lambda: events.append("high-dpi")
    )
    monkeypatch.setattr(app_module, "_load_app_icon", lambda: None)
    monkeypatch.setattr(app_module.sys, "exit", lambda code: events.append(("exit", code)))

    app_module.main()

    assert events == [
        "setup-logging",
        "high-dpi",
        "chinese-font",
        "qapplication",
        "qt-handler",
        "chart-font",
        "style",
        "stylesheet",
        "tooltips",
        "window",
        "exception-hooks",
        "show",
        "exec",
        ("exit", 0),
    ]
    assert len(error_callbacks) == 1
    error_callbacks[0]("probe error")
    assert events[-1] == ("toast", "probe error", "error")
