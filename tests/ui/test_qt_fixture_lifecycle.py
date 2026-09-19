"""Regression contracts for UI fixture teardown ownership.

The lifecycle assertion deliberately runs in a fresh child pytest process.
The second child item is entered only after pytest has completed teardown of
the first one, including every fixture finalizer and both pytest hook-wrapper
post-yield halves.  A test-body assertion would be too early to prove this
boundary.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_THIS_FILE = Path(__file__).resolve()
_CHILD_ENV = "MF4_QT_FIXTURE_LIFECYCLE_CHILD"

# This is intentionally a strong reference.  pytest-qt stores only a weak
# reference for ``qtbot.addWidget``; keeping this reference lets the next item
# distinguish an undelivered DeferredDelete event from ordinary Python GC.
_CHILD_CHART_STACK = None


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env[_CHILD_ENV] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(_REPO_ROOT), env.get("PYTHONPATH")) if part
    )
    env["TMPDIR"] = "/tmp"
    env["MPLCONFIGDIR"] = "/tmp"
    return env


def _run_child() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(_THIS_FILE),
            "-k",
            "fixture_lifecycle_child",
        ],
        cwd=_REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(
    os.environ.get(_CHILD_ENV) != "1",
    reason="executed only by the outer bounded child-process regression",
)
def test_fixture_lifecycle_child_creates_tracked_chart_stack(qapp, qtbot):
    """Exercise both pytest-qt ownership and ``_own_chartstacks`` tracking."""
    from PyQt5 import sip
    from mf4_analyzer.ui.chart_stack import ChartStack

    global _CHILD_CHART_STACK
    chart_stack = ChartStack()
    qtbot.addWidget(chart_stack)
    _CHILD_CHART_STACK = chart_stack
    assert not sip.isdeleted(chart_stack)


@pytest.mark.skipif(
    os.environ.get(_CHILD_ENV) != "1",
    reason="executed only by the outer bounded child-process regression",
)
def test_fixture_lifecycle_child_observes_prior_item_after_full_teardown(qapp):
    """This body starts only after the prior item's complete teardown."""
    from PyQt5 import sip

    assert _CHILD_CHART_STACK is not None
    assert sip.isdeleted(_CHILD_CHART_STACK), (
        "the prior item's ChartStack reached this item with DeferredDelete "
        "still pending; drain owned DeferredDelete events after pytest-qt has "
        "called deleteLater(), before the next item begins"
    )


def test_fixture_teardown_drains_owned_deferred_deletes_in_bounded_child():
    """A tracked ChartStack must be deleted before a following item starts."""
    result = _run_child()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout, result.stdout


def test_static_source_ratchets_do_not_construct_qapplication(tmp_path):
    """AST ratchets under tests/ui must not pay session qapp / ChartStack."""
    plugin = tmp_path / "probe_plugin.py"
    out = tmp_path / "qapp-probe.txt"
    plugin.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    from PyQt5.QtWidgets import QApplication\n"
        "    app = QApplication.instance()\n"
        "    Path(os.environ['T3_QAPP_PROBE']).write_text(\n"
        "        'none' if app is None else 'present'\n"
        "    )\n",
        encoding="utf-8",
    )
    env = _child_env()
    env["T3_QAPP_PROBE"] = str(out)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(tmp_path), env.get("PYTHONPATH")) if part
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "probe_plugin",
            "tests/ui/test_main_window_state_ownership.py",
            "tests/ui/test_no_lambda_signal_connections.py",
            "tests/ui/test_import_boundaries.py",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.read_text(encoding="utf-8") == "none", result.stdout + result.stderr


def test_pin_filter_registry_matches_heap_scan_after_chart_stack_item(qapp):
    """Registry cross-check: a real ChartStack item must agree with gc.get_objects()."""
    from PyQt5.QtCore import QCoreApplication, QEvent

    from mf4_analyzer.ui.chart_stack import ChartStack
    from tests.ui import conftest as ui_conftest

    ui_conftest._ensure_pin_filter_registry()
    stack = ChartStack()
    try:
        heap_r, heap_c = ui_conftest._installed_from_heap()
        reg_r, reg_c = ui_conftest._installed_from_registry()
        assert {id(obj) for obj in heap_r} == {id(obj) for obj in reg_r}
        assert {id(obj) for obj in heap_c} == {id(obj) for obj in reg_c}
    finally:
        stack.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()


def test_pinned_cursor_filter_guard_surfaces_unexpected_import_failure(request):
    """F08: a broken controller import is infrastructure failure, not a pass."""
    import builtins

    from tests.ui import conftest as ui_conftest

    original_import = builtins.__import__

    def _fail_only_controller_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mf4_analyzer.ui.chart_stack.pinned_cursor_controller":
            raise RuntimeError("synthetic controller import failure")
        return original_import(name, globals, locals, fromlist, level)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builtins, "__import__", _fail_only_controller_import)
        with pytest.raises(RuntimeError, match="synthetic controller import failure"):
            ui_conftest._assert_pinned_cursor_filters_not_accumulated(request)
