"""Unit contracts for the Qt-free analysis-job orchestration service."""
from __future__ import annotations

import inspect
import threading

import pytest

from mf4_analyzer.ui.analysis_jobs import AnalysisJobService


@pytest.fixture
def service():
    instance = AnalysisJobService()
    yield instance
    instance.shutdown()
    instance.deleteLater()


def test_service_runs_jobs_fifo_one_active_per_section(qtbot, service):
    started = []
    finished = []
    first_started = threading.Event()
    release_first = threading.Event()

    def first(_worker):
        started.append("first")
        first_started.set()
        assert release_first.wait(2)
        return "first-result"

    def second(_worker):
        started.append("second")
        return "second-result"

    service.finished.connect(
        lambda section, ctx, result: finished.append((section, ctx, result))
    )
    service.submit("fft_time", first, "first-context")
    service.submit("fft_time", second, "second-context")

    qtbot.waitUntil(first_started.is_set, timeout=1000)
    assert started == ["first"]
    assert service.is_running("fft_time")

    release_first.set()
    qtbot.waitUntil(lambda: len(finished) == 2, timeout=2000)

    assert started == ["first", "second"]
    assert finished == [
        ("fft_time", "first-context", "first-result"),
        ("fft_time", "second-context", "second-result"),
    ]
    qtbot.waitUntil(lambda: not service.is_running("fft_time"), timeout=1000)


def test_service_parallel_sections_do_not_block_each_other(qtbot, service):
    fft_started = threading.Event()
    order_started = threading.Event()
    release = threading.Event()

    def fft_job(_worker):
        fft_started.set()
        assert release.wait(2)
        return "fft"

    def order_job(_worker):
        order_started.set()
        assert release.wait(2)
        return "order"

    finished = []
    service.finished.connect(
        lambda section, _ctx, result: finished.append((section, result))
    )
    service.submit("fft_time", fft_job, object())
    service.submit("order", order_job, object())

    qtbot.waitUntil(fft_started.is_set, timeout=1000)
    qtbot.waitUntil(order_started.is_set, timeout=1000)
    assert service.is_running("fft_time")
    assert service.is_running("order")

    release.set()
    qtbot.waitUntil(lambda: len(finished) == 2, timeout=2000)
    assert set(finished) == {("fft_time", "fft"), ("order", "order")}


def test_service_progress_counts_match_total_and_completed(qtbot, service):
    progress = []
    service.progress.connect(
        lambda section, done, total: progress.append((section, done, total))
    )

    def half_done(worker):
        worker.progress.emit(1, 2)
        return "done"

    service.submit("fft_time", half_done, "first")
    service.submit("fft_time", half_done, "second")

    qtbot.waitUntil(
        lambda: bool(progress) and progress[-1] == ("fft_time", 1000, 1000),
        timeout=2000,
    )

    assert progress == [
        ("fft_time", 250, 1000),
        ("fft_time", 500, 1000),
        ("fft_time", 750, 1000),
        ("fft_time", 1000, 1000),
    ]


def test_submit_batch_counts_skipped_items_without_starting_a_worker(qtbot, service):
    """A pane rejected during synchronous input preparation still consumes
    its original batch progress slot, but never creates a worker.

    This is the multi-pane contract formerly implemented by the two mixin
    queue pumps: skip reasons are collected by the UI adapter, while service
    owns the authoritative completed/total accounting.
    """
    started = []
    progress = []

    def runnable(_worker):
        started.append("runnable")
        return "result"

    service.progress.connect(
        lambda section, done, total: progress.append((section, done, total))
    )
    service.submit_batch(
        "fft_time",
        [
            (None, {"skip": "missing source"}),
            (runnable, {"pane_idx": 1}),
        ],
    )

    qtbot.waitUntil(
        lambda: bool(progress) and progress[-1] == ("fft_time", 1000, 1000),
        timeout=2000,
    )

    assert started == ["runnable"]
    assert progress[-1] == ("fft_time", 1000, 1000)
    assert service.progress_counts("fft_time") == (2, 2)


def test_cancel_clears_section_queue_and_suppresses_finished(qtbot, service):
    first_started = threading.Event()
    second_started = threading.Event()
    observed_cancel = threading.Event()
    finished = []

    def cancellable(worker):
        first_started.set()
        while not worker.cancelled():
            threading.Event().wait(0.005)
        observed_cancel.set()
        return "cancelled-result"

    def queued(_worker):
        second_started.set()
        return "queued-result"

    service.finished.connect(lambda *_args: finished.append(_args))
    service.submit("fft_time", cancellable, "active")
    service.submit("fft_time", queued, "queued")

    qtbot.waitUntil(first_started.is_set, timeout=1000)
    service.cancel("fft_time")
    qtbot.waitUntil(observed_cancel.is_set, timeout=1000)
    qtbot.waitUntil(lambda: not service.is_running("fft_time"), timeout=1000)
    qtbot.wait(30)

    assert not second_started.is_set()
    assert finished == []


def test_superseding_request_cancels_active_worker(qtbot, service):
    first_started = threading.Event()
    first_cancelled = threading.Event()
    second_started = threading.Event()
    finished = []

    def old_job(worker):
        first_started.set()
        while not worker.cancelled():
            threading.Event().wait(0.005)
        first_cancelled.set()
        return "old-result"

    def replacement(_worker):
        second_started.set()
        return "new-result"

    service.finished.connect(
        lambda section, ctx, result: finished.append((section, ctx, result))
    )
    service.submit("order", old_job, "old")
    qtbot.waitUntil(first_started.is_set, timeout=1000)
    service.submit("order", replacement, "new", replace=True)

    qtbot.waitUntil(first_cancelled.is_set, timeout=1000)
    qtbot.waitUntil(second_started.is_set, timeout=2000)
    qtbot.waitUntil(lambda: len(finished) == 1, timeout=2000)

    assert finished == [("order", "new", "new-result")]


class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _FakeWorker:
    instances = []

    def __init__(self, job):
        self.job = job
        self.progress = _FakeSignal()
        self.finished = _FakeSignal()
        self.failed = _FakeSignal()
        self.cancelled = False
        self.__class__.instances.append(self)

    def moveToThread(self, _thread):
        pass

    def cancel(self):
        self.cancelled = True

    def run(self):
        pass

    def deleteLater(self):
        pass


class _FakeThread:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self.running = False
        self.quit_called = False
        self.terminate_called = False
        self.wait_calls = []
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def quit(self):
        self.quit_called = True

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return len(self.wait_calls) > 1

    def terminate(self):
        self.terminate_called = True
        self.running = False

    def deleteLater(self):
        pass


def test_section_stays_active_until_thread_finished_cleanup(monkeypatch):
    """A stopped QThread still owns the section until the service cleanup slot.

    Qt can report ``isRunning() == False`` before the queued
    ``thread.finished`` receiver runs on the service's thread.  A UI caller
    must remain busy through that window so a second request joins the current
    FIFO batch instead of being treated as a fresh batch.
    """
    import mf4_analyzer.ui.analysis_jobs as jobs_mod

    _FakeWorker.instances = []
    _FakeThread.instances = []
    monkeypatch.setattr(jobs_mod, "AnalysisComputeWorker", _FakeWorker)
    monkeypatch.setattr(jobs_mod, "QThread", _FakeThread)

    service = jobs_mod.AnalysisJobService()
    service.submit("fft_time", lambda _worker: "first", "first")
    thread = _FakeThread.instances[-1]
    thread.running = False  # thread finished physically; service slot not run

    assert service.is_running("fft_time")

    service.submit("fft_time", lambda _worker: "second", "second")

    state = service._sections["fft_time"]
    assert _FakeThread.instances == [thread]
    assert len(state.queue) == 1
    assert service.progress_counts("fft_time") == (0, 2)


def test_shutdown_joins_threads_with_terminate_fallback(monkeypatch):
    import mf4_analyzer.ui.analysis_jobs as jobs_mod

    _FakeWorker.instances = []
    _FakeThread.instances = []
    monkeypatch.setattr(jobs_mod, "AnalysisComputeWorker", _FakeWorker)
    monkeypatch.setattr(jobs_mod, "QThread", _FakeThread)

    service = jobs_mod.AnalysisJobService()
    service.submit("fft_time", lambda _worker: None, object())
    service.shutdown()

    worker = _FakeWorker.instances[-1]
    thread = _FakeThread.instances[-1]
    assert worker.cancelled
    assert thread.quit_called
    assert thread.wait_calls == [2000, 500]
    assert thread.terminate_called


def test_service_module_has_no_qtwidgets_import():
    import mf4_analyzer.ui.analysis_jobs as jobs_mod

    source = inspect.getsource(jobs_mod)
    assert "QtWidgets" not in source


def test_failed_job_emits_failed_not_finished(qtbot, service):
    finished = []
    failed = []
    service.finished.connect(lambda *_args: finished.append(_args))
    service.failed.connect(lambda *_args: failed.append(_args))

    def boom(_worker):
        raise RuntimeError("expected failure")

    service.submit("order", boom, "failure-context")
    qtbot.waitUntil(lambda: len(failed) == 1, timeout=1000)

    assert finished == []
    assert failed == [("order", "failure-context", "expected failure")]
