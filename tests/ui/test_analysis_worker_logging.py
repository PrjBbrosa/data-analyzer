import logging

from mf4_analyzer.ui.analysis_worker import AnalysisComputeWorker


def test_analysis_worker_failure_keeps_traceback_observable(caplog):
    worker = AnalysisComputeWorker(
        lambda _worker: (_ for _ in ()).throw(RuntimeError("frf boom"))
    )
    failures = []
    worker.failed.connect(failures.append)

    with caplog.at_level(logging.ERROR, logger="mf4_analyzer.ui.analysis_worker"):
        worker.run()

    assert failures == ["frf boom"]
    assert "frf boom" in caplog.text
    assert "Traceback" in caplog.text
