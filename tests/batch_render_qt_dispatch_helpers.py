"""Test-only Batch Qt GUI-dispatch lifecycle helpers.

Not product code. Do not ``QThread.terminate()``. Never-cooperative hangs
belong in an outer-limited subprocess; cooperative workers are joined.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PyQt5.QtCore import QEventLoop


WORKER_JOIN_TIMEOUT_S = 1.0
LIFECYCLE_WORKER_NAME = "batch-qt-dispatch-lifecycle-worker"
FORCED_FAILURE_MESSAGE = "forced post-dispatch assertion failure"


def qt_child_environment(repo_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(repo_root),
            "QT_QPA_PLATFORM": "offscreen",
            "TMPDIR": "/tmp",
            "MPLCONFIGDIR": "/tmp",
        }
    )
    return environment


def finalize_dispatch_worker(
    thread: threading.Thread, *, join_timeout_s: float = WORKER_JOIN_TIMEOUT_S
) -> bool:
    """Cooperative join only. Returns True when the worker is no longer alive."""

    if thread.is_alive():
        thread.join(join_timeout_s)
    return not thread.is_alive()


def pump_gui_until_thread_finishes(qapp, thread: threading.Thread, *, timeout_s: float) -> None:
    """Pump GUI events with an in-loop deadline. ``processEvents`` itself is capped."""

    deadline = time.monotonic() + float(timeout_s)
    while thread.is_alive():
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break
        qapp.processEvents(QEventLoop.AllEvents, remaining_ms)
        thread.join(0.01)


def run_gui_dispatch_worker(
    qapp,
    request,
    worker_fn: Callable[[], None],
    *,
    timeout_s: float,
    name: str,
) -> threading.Thread:
    """Start a daemon worker, pump GUI events, and always join before returning.

    ``request.addfinalizer`` is registered before ``start()`` so assert failure
    and timeout still join the thread before monkeypatch teardown.
    """

    thread = threading.Thread(target=worker_fn, daemon=True, name=name)
    request.addfinalizer(lambda: finalize_dispatch_worker(thread))
    thread.start()
    try:
        pump_gui_until_thread_finishes(qapp, thread, timeout_s=timeout_s)
        if thread.is_alive():
            pytest.fail(
                f"{name} did not finish within {timeout_s}s while GUI events were pumped"
            )
    finally:
        finalize_dispatch_worker(thread)
    return thread


def leftover_named_threads(name: str) -> list[str]:
    return [thread.name for thread in threading.enumerate() if thread.name == name]


def test_lifecycle_assert_failure_cleans_worker(qapp, request):
    from mf4_analyzer.batch_render_qt._dispatch import render_on_gui_thread

    observed = {}

    def worker():
        observed["result"] = render_on_gui_thread(lambda: "ok")

    thread = threading.Thread(
        target=worker, daemon=True, name=LIFECYCLE_WORKER_NAME
    )
    request.addfinalizer(lambda: finalize_dispatch_worker(thread))
    thread.start()
    try:
        pump_gui_until_thread_finishes(qapp, thread, timeout_s=15.0)
        assert not thread.is_alive()
        assert observed["result"] == "ok"
        raise AssertionError(FORCED_FAILURE_MESSAGE)
    finally:
        assert finalize_dispatch_worker(thread)
        assert leftover_named_threads(LIFECYCLE_WORKER_NAME) == []


def test_lifecycle_followup_node_is_not_polluted(qapp):
    from mf4_analyzer.batch_render_qt._dispatch import render_on_gui_thread

    assert leftover_named_threads(LIFECYCLE_WORKER_NAME) == []
    assert render_on_gui_thread(lambda: 41) == 41
