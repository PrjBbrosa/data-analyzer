"""Section-serial Qt job orchestration for analysis compute work.

This module deliberately owns only worker lifecycle and queueing.  It has no
knowledge of result caches, canvases, or widgets; callers receive opaque job
contexts back through its signals and perform those UI-facing actions there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .analysis_worker import AnalysisComputeWorker


Job = Callable[[AnalysisComputeWorker], object]


@dataclass
class _QueuedJob:
    job: Job | None
    ctx: object
    generation: int


@dataclass
class _ActiveRun:
    section: str
    ctx: object
    generation: int
    run_id: int
    worker: AnalysisComputeWorker
    thread: QThread


@dataclass
class _SectionState:
    queue: list[_QueuedJob] = field(default_factory=list)
    worker: AnalysisComputeWorker | None = None
    thread: QThread | None = None
    generation: int = 0
    next_run_id: int = 0
    active_run_id: int | None = None
    total_jobs: int = 0
    completed_jobs: int = 0


class AnalysisJobService(QObject):
    """Run analysis jobs one at a time per section and in parallel by section.

    ``submit`` normally appends to the section's current FIFO batch.  Callers
    that deliberately replace a section request use ``replace=True``; this
    cancels the active cooperative worker, drops queued work, and suppresses
    all stale callbacks before starting the replacement when the old thread
    has drained.
    """

    finished = pyqtSignal(str, object, object)
    failed = pyqtSignal(str, object, object)
    progress = pyqtSignal(str, int, int)

    _PROGRESS_TOTAL = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, _SectionState] = {}
        self._worker_runs: dict[int, _ActiveRun] = {}
        self._thread_runs: dict[int, _ActiveRun] = {}
        self._shutting_down = False

    def submit(self, section: str, job: Job, ctx=None, *, replace: bool = False):
        """Queue ``job`` under ``section`` and return after starting if idle.

        ``ctx`` is opaque to the service and is passed through unchanged in
        terminal signals.  This lets subscribers associate a result with its
        cache key and render target without giving the service cache/canvas
        knowledge.
        """
        self.submit_batch(section, [(job, ctx)], replace=replace)

    def submit_batch(self, section: str, jobs, *, replace: bool = False) -> None:
        """Atomically append one logical batch of jobs for ``section``.

        Each item is a ``(job, ctx)`` pair.  ``job=None`` is a synchronous
        skip that still advances the batch's completed/total progress slot;
        callers have already recorded the user-facing skip reason.  Building
        the full queue before starting the first worker preserves split-pane
        batch totals even when the first worker finishes immediately.
        """
        if self._shutting_down:
            raise RuntimeError("analysis job service is shut down")
        section = self._validate_section(section)
        jobs = list(jobs)
        for job, _ctx in jobs:
            if job is not None and not callable(job):
                raise TypeError("analysis job must be callable or None")
        if not jobs:
            return
        if replace:
            self.cancel(section)
        state = self._state_for(section)
        if state.thread is None and not state.queue and state.completed_jobs >= state.total_jobs:
            state.total_jobs = 0
            state.completed_jobs = 0
        state.queue.extend(
            _QueuedJob(job, ctx, state.generation) for job, ctx in jobs
        )
        state.total_jobs += len(jobs)
        self._start_next(section)

    def cancel(self, section: str) -> None:
        """Cancel active work and discard queued work for one section."""
        section = self._validate_section(section)
        state = self._state_for(section)
        state.generation += 1
        state.queue.clear()
        state.total_jobs = 0
        state.completed_jobs = 0
        worker = state.worker
        if worker is not None:
            worker.cancel()

    def is_running(self, section: str) -> bool:
        """Whether ``section`` remains active through service cleanup.

        A QThread can clear its own running bit before the queued
        ``thread.finished`` slot has released this section's worker/context.
        Treat the section as busy until that slot clears ``state.thread`` so a
        caller cannot begin a fresh request in the teardown window.
        """
        section = self._validate_section(section)
        return self._state_for(section).thread is not None

    def shutdown(self) -> None:
        """Cancel every section and synchronously drain active worker threads."""
        if self._shutting_down:
            return
        self._shutting_down = True
        for state in self._sections.values():
            state.generation += 1
            state.queue.clear()
            state.total_jobs = 0
            state.completed_jobs = 0
            worker = state.worker
            thread = state.thread
            if worker is not None:
                worker.cancel()
            if thread is None or not thread.isRunning():
                continue
            thread.quit()
            if not thread.wait(2000):
                thread.terminate()
                thread.wait(500)

    def _state_for(self, section: str) -> _SectionState:
        return self._sections.setdefault(section, _SectionState())

    @staticmethod
    def _validate_section(section: str) -> str:
        section = str(section)
        if not section:
            raise ValueError("analysis section must be non-empty")
        return section

    def _start_next(self, section: str) -> None:
        if self._shutting_down:
            return
        state = self._state_for(section)
        if state.thread is not None:
            return
        while state.queue:
            queued = state.queue.pop(0)
            if queued.generation != state.generation:
                continue
            if queued.job is None:
                state.completed_jobs = min(
                    state.completed_jobs + 1, state.total_jobs
                )
                self._emit_progress(section, state, 0.0)
                continue
            self._start_run(section, state, queued)
            return

    def _start_run(
        self, section: str, state: _SectionState, queued: _QueuedJob
    ) -> None:
        worker = AnalysisComputeWorker(queued.job)
        thread = QThread(self)
        worker.moveToThread(thread)

        state.next_run_id += 1
        run = _ActiveRun(
            section=section,
            ctx=queued.ctx,
            generation=queued.generation,
            run_id=state.next_run_id,
            worker=worker,
            thread=thread,
        )
        state.worker = worker
        state.thread = thread
        state.active_run_id = run.run_id
        self._worker_runs[id(worker)] = run
        self._thread_runs[id(thread)] = run

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.progress.connect(self._on_worker_progress)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _current_run_for_sender(self) -> _ActiveRun | None:
        sender = self.sender()
        if sender is None:
            return None
        return self._worker_runs.get(id(sender))

    @pyqtSlot(object)
    def _on_worker_finished(self, result) -> None:
        run = self._current_run_for_sender()
        if not self._is_current_generation(run):
            return
        assert run is not None
        self.finished.emit(run.section, run.ctx, result)

    @pyqtSlot(str)
    def _on_worker_failed(self, error: str) -> None:
        run = self._current_run_for_sender()
        if not self._is_current_generation(run):
            return
        assert run is not None
        self.failed.emit(run.section, run.ctx, str(error))

    @pyqtSlot(int, int)
    def _on_worker_progress(self, current: int, total: int) -> None:
        run = self._current_run_for_sender()
        if not self._is_current_generation(run):
            return
        assert run is not None
        state = self._state_for(run.section)
        fraction = 0.0
        if total > 0:
            fraction = max(0.0, min(1.0, current / total))
        self._emit_progress(run.section, state, fraction)

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        sender = self.sender()
        if sender is None:
            return
        run = self._thread_runs.pop(id(sender), None)
        if run is None:
            return
        self._worker_runs.pop(id(run.worker), None)
        state = self._state_for(run.section)
        if state.active_run_id == run.run_id:
            state.worker = None
            state.thread = None
            state.active_run_id = None
        if self._is_current_generation(run):
            state.completed_jobs = min(state.completed_jobs + 1, state.total_jobs)
            self._emit_progress(run.section, state, 0.0)
        # ``thread.finished`` means the event loop has stopped.  Waiting here
        # completes the normal quit()+wait() ownership path before a section's
        # next worker is launched; shutdown retains the terminate fallback.
        try:
            run.thread.wait()
        except RuntimeError:
            pass
        self._start_next(run.section)

    def progress_counts(self, section: str) -> tuple[int, int]:
        """Return ``(completed_jobs, total_jobs)`` for the active batch."""
        state = self._state_for(self._validate_section(section))
        return state.completed_jobs, state.total_jobs

    def _is_current_generation(self, run: _ActiveRun | None) -> bool:
        if run is None or self._shutting_down:
            return False
        return self._state_for(run.section).generation == run.generation

    def _emit_progress(
        self, section: str, state: _SectionState, job_fraction: float
    ) -> None:
        if state.total_jobs <= 0:
            return
        overall = (state.completed_jobs + job_fraction) / state.total_jobs
        done = int(round(max(0.0, min(1.0, overall)) * self._PROGRESS_TOTAL))
        self.progress.emit(section, done, self._PROGRESS_TOTAL)
