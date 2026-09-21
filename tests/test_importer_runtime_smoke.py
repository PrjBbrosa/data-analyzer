from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from scipy.io import savemat

from mf4_analyzer.io.importer_runtime_smoke import run


def test_runtime_smoke_writes_nonzero_channel_count_for_legacy_mat(tmp_path):
    """Catch a frozen importer probe that reports success without loading data."""
    sample = tmp_path / "legacy.mat"
    savemat(
        sample,
        {
            "time": np.array([0.0, 0.1, 0.2]),
            "signal": np.array([1.0, 2.0, 3.0]),
        },
    )
    output = tmp_path / "importer-smoke.json"

    assert run([sample], output) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result == {
        "files": [{"path": str(sample), "channels": 2}],
    }


def test_generated_fixtures_exercise_legacy_v73_and_audio_imports(tmp_path):
    """Catch a fixture generator that misses a MAT or PyAV import path."""
    pytest.importorskip("h5py")
    pytest.importorskip("av")
    from tools.verify_lite_importer_runtime import create_fixtures

    legacy_mat, hdf5_mat, wav, mp4 = create_fixtures(tmp_path)
    output = tmp_path / "importer-smoke.json"

    assert run([legacy_mat, hdf5_mat, wav, mp4], output) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert [record["channels"] for record in result["files"]] == [2, 2, 1, 1]


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_importer_verifier_preserves_result_fixtures_and_logs(tmp_path, monkeypatch, failure):
    pytest.importorskip("h5py")
    pytest.importorskip("av")
    from tools import verify_lite_importer_runtime as tool

    exe = tmp_path / "probe.exe"
    exe.write_bytes(b"fake-frozen-importer")
    diagnostics = tmp_path / "diagnostics"

    def failed_child(command, **kwargs):
        kwargs["stdout"].write(b"importer stdout\n")
        kwargs["stderr"].write(b"importer diagnostic\n")
        json_path = Path(command[command.index("--json") + 1])
        json_path.write_text('{"files": []}', encoding="utf-8")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 9)

    monkeypatch.setattr(tool.subprocess, "run", failed_child)
    assert tool.verify(exe, diagnostics_dir=diagnostics, timeout=12) != 0
    assert (diagnostics / "stdout.log").read_bytes() == b"importer stdout\n"
    assert (diagnostics / "stderr.log").read_bytes() == b"importer diagnostic\n"
    assert json.loads((diagnostics / "result.json").read_text(encoding="utf-8")) == {
        "files": []
    }
    assert (diagnostics / "fixtures/legacy.mat").is_file()
    assert (diagnostics / "fixtures/sample-v73.mat").is_file()
    assert (diagnostics / "fixtures/sample.wav").is_file()
    assert (diagnostics / "fixtures/sample.mp4").is_file()
    if failure == "timeout":
        timeout_payload = json.loads((diagnostics / "timeout.json").read_text(encoding="utf-8"))
        assert timeout_payload["timed_out"] is True
        assert timeout_payload["timeout_seconds"] == 12


def test_importer_verifier_does_not_require_console_streams(tmp_path, monkeypatch):
    pytest.importorskip("h5py")
    pytest.importorskip("av")
    from tools import verify_lite_importer_runtime as tool

    exe = tmp_path / "probe.exe"
    exe.write_bytes(b"fake-frozen-importer")
    diagnostics = tmp_path / "diagnostics"

    def ok_child(command, **kwargs):
        kwargs["stdout"].write(b"")
        kwargs["stderr"].write(b"")
        json_path = Path(command[command.index("--json") + 1])
        json_path.write_text(
            json.dumps(
                {
                    "files": [
                        {"path": "legacy.mat", "channels": 2},
                        {"path": "sample-v73.mat", "channels": 2},
                        {"path": "sample.wav", "channels": 1},
                        {"path": "sample.mp4", "channels": 1},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(tool.subprocess, "run", ok_child)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert tool.verify(exe, diagnostics_dir=diagnostics) == 0
    evidence = json.loads((diagnostics / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["ok"] is True
