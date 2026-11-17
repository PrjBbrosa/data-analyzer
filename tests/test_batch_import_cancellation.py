from dataclasses import replace
import sys
import threading

import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.io.import_process import ImportProcessError, run_import
from mf4_analyzer.io.source_adapters import stable_source_id, canonical_source_path


@pytest.mark.parametrize("method", ["time", "frf"])
def test_cancel_during_real_child_load_records_cancelled_and_can_retry(tmp_path, monkeypatch, method):
    from mf4_analyzer.io import import_process
    from mf4_analyzer.batch_types import FrfPairRule
    path = tmp_path / "measurement.csv"
    path.write_text("Time,signal\n0,1\n.1,2\n.2,3\n")
    source_id = stable_source_id("tabular", canonical_source_path(path), "root")
    preset = replace(AnalysisPreset.free_config(
        name="cancel import", method=method, target_signals=("signal",),
        params={} if method == "time" else {"t_win_s": .5},
        outputs=BatchOutput(export_data=True, export_image=False),
    ), source_ids=(source_id,), source_paths=(str(path),),
        frf_pair_rules=(FrfPairRule("signal", ("response",)),) if method == "frf" else ())
    runner = BatchRunner({})
    runner.seed_source_channels({source_id: ("signal", "response")})
    cancel = threading.Event()
    events = []
    real_command = import_process._worker_command
    def command(request):
        cancel.set()
        return [sys.executable, "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(import_process, "_worker_command", command)
    result = runner.run(preset, tmp_path / "out", cancel_token=cancel, on_event=events.append)
    assert result.status == "cancelled"
    assert result.items and all(item.status == "cancelled" for item in result.items)
    assert not any(event.kind == "task_failed" for event in events)
    assert len([event for event in events if event.kind == "run_finished"]) == 1
    assert not runner._disk_cache
    monkeypatch.setattr(import_process, "_worker_command", real_command)
    # ContextVar is reset after run; the cancelled event cannot leak to the next caller.
    assert run_import("load_csv", path)[0]["signal"].tolist() == [1, 2, 3]


@pytest.mark.parametrize("method", ["time", "frf"])
def test_metadata_preflight_cancellation_finishes_once(tmp_path, monkeypatch, method):
    from mf4_analyzer.io import import_process
    from mf4_analyzer.batch_types import FrfPairRule
    from tests._helpers.mf4_factory import write_single_channel_mf4
    path = write_single_channel_mf4(tmp_path / "measurement.mf4", name="signal")
    preset = replace(AnalysisPreset.free_config(
        name="metadata cancel", method=method, target_signals=("signal",),
        params={} if method == "time" else {"t_win_s": .5},
        outputs=BatchOutput(export_data=True, export_image=False),
    ), source_paths=(str(path),),
       frf_pair_rules=(FrfPairRule("signal", ("response",)),) if method == "frf" else ())
    runner = BatchRunner({})
    cancel = threading.Event()
    events = []

    def command(request):
        cancel.set()
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    monkeypatch.setattr(import_process, "_worker_command", command)
    result = runner.run(preset, tmp_path / "out", cancel_token=cancel, on_event=events.append)
    assert cancel.is_set(), "test must enter real metadata preflight"
    assert result.status == "cancelled"
    assert not result.blocked
    assert [event.final_status for event in events if event.kind == "run_finished"] == ["cancelled"]
    assert not runner._disk_cache
    assert not runner._descriptor_probe_failures
