"""Process-wide diagnostic logging with bounded failure reporting.

This module intentionally has no PyQt import at module load. GUI entry points
install the Qt message handler lazily after ``QApplication`` exists, while
batch/CLI code can still configure the standard-library logger safely.
"""

from __future__ import annotations

import atexit
from collections import OrderedDict
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable


LOG_FILENAME = "tracelab.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
BURST = 3
WINDOW = 60.0
MAX_KEYS = 512

_LOGGER = logging.getLogger(__name__)
_HANDLER_MARKER = "_tracelab_diagnostics_handler"
_THROTTLE_STATE: OrderedDict[tuple[str, str], list[float | int]] = OrderedDict()
_THROTTLE_LOCK = threading.Lock()
_monotonic = time.monotonic
_last_sweep = _monotonic()
_throttle_flush_registered = False
_active_log_file: Path | None = None
_qt_message_handler = None


def resolve_log_dir() -> Path:
    """Return TraceLab's platform-conventional diagnostics directory."""
    override = os.environ.get("TRACELAB_LOG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        return base / "TraceLab" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "TraceLab"
    base = Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
    )
    return base / "TraceLab" / "logs"


def _logging_level(value: str | int | None) -> int:
    if value is None:
        value = os.environ.get("TRACELAB_LOG_LEVEL", "INFO")
    if isinstance(value, int):
        return value
    text = str(value).strip().upper()
    if text.isdigit():
        return int(text)
    resolved = logging.getLevelName(text)
    return resolved if isinstance(resolved, int) else logging.INFO


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, _HANDLER_MARKER, False):
            continue
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _mark_handler(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _HANDLER_MARKER, True)
    return handler


class _DiagnosticsFileFilter(logging.Filter):
    """Keep application detail while retaining third-party warnings/errors."""

    def filter(self, record: logging.LogRecord) -> bool:
        return bool(
            record.name == "mf4_analyzer"
            or record.name.startswith("mf4_analyzer.")
            or record.levelno >= logging.WARNING
        )


def _emit_throttle_summaries(summaries) -> None:
    for logger_name, key, level, count, reason in summaries:
        logger = logging.getLogger(logger_name)
        if reason == "window":
            logger.log(
                level,
                "suppressed %d occurrences in %ds for %s",
                count,
                int(WINDOW),
                key,
            )
        elif reason == "eviction":
            logger.log(
                level,
                "suppressed %d occurrences before throttle-key eviction for %s",
                count,
                key,
            )
        else:
            logger.log(
                level,
                "suppressed %d occurrences before %s flush for %s",
                count,
                reason,
                key,
            )


def _pending_summary(state_key, state, reason):
    count = int(state[2])
    if not count:
        return None
    logger_name, key = state_key
    return (logger_name, key, int(state[3]), count, reason)


def _collect_expired_summaries_locked(now: float):
    summaries = []
    for state_key, state in _THROTTLE_STATE.items():
        if now - float(state[0]) < WINDOW:
            continue
        summary = _pending_summary(state_key, state, "window")
        if summary is not None:
            summaries.append(summary)
        # A sweep starts a fresh window without inventing an emitted event.
        state[:] = [now, 0, 0, logging.NOTSET]
    return summaries


def flush_throttle_summaries(*, reason: str = "manual") -> None:
    """Emit pending suppressed counts without waiting for another event."""
    summaries = []
    with _THROTTLE_LOCK:
        for state_key, state in _THROTTLE_STATE.items():
            summary = _pending_summary(state_key, state, reason)
            if summary is None:
                continue
            summaries.append(summary)
            state[2] = 0
    _emit_throttle_summaries(summaries)


def _flush_at_exit() -> None:
    try:
        flush_throttle_summaries(reason="shutdown")
    except BaseException:
        # Interpreter teardown must not be delayed by diagnostics cleanup.
        pass


def _ensure_throttle_flush_registered() -> None:
    global _throttle_flush_registered
    with _THROTTLE_LOCK:
        if _throttle_flush_registered:
            return
        atexit.register(_flush_at_exit)
        _throttle_flush_registered = True


def setup_logging(*, level: str | int | None = None) -> Path:
    """Configure rotating diagnostics and degrade safely to stderr.

    The resolved directory is returned even when it is not writable. Callers
    can display the conventional location without making startup depend on the
    filesystem being healthy.
    """
    global _active_log_file

    log_dir = resolve_log_dir()
    selected_level = _logging_level(level)
    root = logging.getLogger()
    _remove_managed_handlers(root)
    if root.level == logging.NOTSET:
        root.setLevel(selected_level)
    else:
        root.setLevel(min(root.level, selected_level))

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    )
    stderr_handler = None
    if sys.stderr is not None:
        try:
            stderr_handler = _mark_handler(logging.StreamHandler(sys.stderr))
            stderr_handler.setLevel(logging.WARNING)
            stderr_handler.setFormatter(formatter)
            root.addHandler(stderr_handler)
        except Exception:
            stderr_handler = None

    file_handler = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / LOG_FILENAME
        file_handler = _mark_handler(
            RotatingFileHandler(
                log_file,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
        )
        file_handler.setLevel(selected_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(_DiagnosticsFileFilter())
        root.addHandler(file_handler)
        _active_log_file = log_file
        _LOGGER.info("Diagnostics initialized: %s", log_file)
    except Exception:
        if file_handler is not None:
            try:
                file_handler.close()
            except Exception:
                pass
        _active_log_file = None
        # The stream handler is best-effort too: a Windows --windowed build can
        # legitimately expose stderr as None.
        try:
            _LOGGER.error(
                "Diagnostics file is unavailable; using stderr only: %s",
                log_dir,
                exc_info=True,
            )
        except Exception:
            pass
    _ensure_throttle_flush_registered()
    return log_dir


def throttled(
    logger: logging.Logger,
    key: str,
    level: int,
    msg: str,
    *args,
    exc_info=False,
) -> None:
    """Emit a bounded burst per ``(logger.name, key)`` and summarize drops."""
    global _last_sweep

    state_key = (logger.name, key)
    now = _monotonic()
    summaries = []
    emit_record = False

    with _THROTTLE_LOCK:
        if now - _last_sweep >= WINDOW:
            summaries.extend(_collect_expired_summaries_locked(now))
            _last_sweep = now

        state = _THROTTLE_STATE.get(state_key)
        if state is None:
            if len(_THROTTLE_STATE) >= MAX_KEYS:
                evicted_key, evicted_state = _THROTTLE_STATE.popitem(last=False)
                summary = _pending_summary(evicted_key, evicted_state, "eviction")
                if summary is not None:
                    summaries.append(summary)
            # [window start, emitted count, suppressed count, highest level]
            _THROTTLE_STATE[state_key] = [now, 1, 0, level]
            emit_record = True
        elif now - state[0] >= WINDOW:
            summary = _pending_summary(state_key, state, "window")
            if summary is not None:
                summaries.append(summary)
            state[:] = [now, 1, 0, level]
            emit_record = True
        elif state[1] < BURST:
            state[1] += 1
            state[3] = max(int(state[3]), level)
            emit_record = True
        else:
            state[2] += 1
            state[3] = max(int(state[3]), level)

    if summaries:
        _emit_throttle_summaries(summaries)
    if emit_record:
        logger.log(level, msg, *args, exc_info=exc_info)


def _error_notice() -> str:
    if _active_log_file is not None:
        return f"发生内部错误，详情已记录到日志：{_active_log_file}"
    return "发生内部错误，诊断日志不可写，请查看标准错误输出"


def _previous_hook(hook):
    if getattr(hook, "_tracelab_excepthook", False):
        return getattr(hook, "_tracelab_previous_hook", None)
    return hook


def install_excepthooks(
    *, on_error: Callable[[str], None] | None = None,
) -> None:
    """Install main/worker exception hooks while preserving prior hooks."""
    previous_sys = _previous_hook(sys.excepthook)
    previous_thread = _previous_hook(threading.excepthook)

    def notify() -> None:
        if on_error is None:
            return
        try:
            on_error(_error_notice())
        except BaseException:
            # A broken notification surface must not mask the original error.
            pass

    def sys_hook(exc_type, exc_value, traceback) -> None:
        try:
            _LOGGER.critical(
                "Unhandled exception in main thread",
                exc_info=(exc_type, exc_value, traceback),
            )
        except BaseException:
            pass
        notify()
        if callable(previous_sys):
            previous_sys(exc_type, exc_value, traceback)

    def thread_hook(args) -> None:
        thread = getattr(args, "thread", None)
        thread_name = getattr(thread, "name", None) or "unknown"
        try:
            _LOGGER.critical(
                "Unhandled exception in worker thread %s",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        except BaseException:
            pass
        notify()
        if callable(previous_thread):
            previous_thread(args)

    for hook, previous in (
        (sys_hook, previous_sys),
        (thread_hook, previous_thread),
    ):
        setattr(hook, "_tracelab_excepthook", True)
        setattr(hook, "_tracelab_previous_hook", previous)
    sys.excepthook = sys_hook
    threading.excepthook = thread_hook


def install_qt_message_handler() -> None:
    """Install a lazily-imported, rate-limited Qt message bridge."""
    global _qt_message_handler

    try:
        from PyQt5 import QtCore

        levels = {
            QtCore.QtDebugMsg: logging.DEBUG,
            QtCore.QtInfoMsg: logging.INFO,
            QtCore.QtWarningMsg: logging.WARNING,
            QtCore.QtCriticalMsg: logging.ERROR,
            QtCore.QtFatalMsg: logging.ERROR,
        }

        def handler(msg_type, context, message) -> None:
            try:
                category = getattr(context, "category", None) or "qt"
                text = str(message)
                throttled(
                    _LOGGER,
                    f"qt:{category}:{text[:80]}",
                    levels.get(msg_type, logging.WARNING),
                    "Qt message category=%s: %s",
                    category,
                    text,
                )
            except BaseException:
                # Raising from a Qt message callback can terminate the process.
                pass

        _qt_message_handler = handler
        QtCore.qInstallMessageHandler(handler)
    except Exception:
        try:
            _LOGGER.exception("Failed to install Qt message handler")
        except Exception:
            pass
