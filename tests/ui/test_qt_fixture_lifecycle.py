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
