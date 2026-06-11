"""AnalysisComputeWorker: generic QObject worker contract tests."""
import pytest

from mf4_analyzer.ui.analysis_worker import AnalysisComputeWorker


def test_job_result_emitted_via_finished(qapp):
    got = []
    worker = AnalysisComputeWorker(lambda w: 42)
    worker.finished.connect(got.append)
    worker.run()
    assert got == [42]


def test_job_exception_emitted_via_failed(qapp):
    errs, oks = [], []

    def job(w):
        raise ValueError("boom")

    worker = AnalysisComputeWorker(job)
    worker.failed.connect(errs.append)
    worker.finished.connect(oks.append)
    worker.run()
    assert errs == ["boom"] and oks == []


def test_cancel_flag_visible_to_job(qapp):
    seen = []
    worker = AnalysisComputeWorker(lambda w: seen.append(w.cancelled()) or 1)
    worker.cancel()
    worker.run()
    assert seen == [True]


def test_progress_relay(qapp):
    ticks = []

    def job(w):
        w.progress.emit(1, 4)
        return None

    worker = AnalysisComputeWorker(job)
    worker.progress.connect(lambda c, t: ticks.append((c, t)))
    worker.run()
    assert ticks == [(1, 4)]
