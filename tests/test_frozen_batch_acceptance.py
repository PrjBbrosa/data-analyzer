from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType

import numpy as np
import pytest

from tests._helpers.mf4_factory import write_single_channel_mf4


ROOT = Path(__file__).resolve().parents[1]
CHANNEL = "EpsDrvrSteerTq"


def _write_acceptance_sources(directory: Path) -> list[Path]:
    timestamps = np.arange(256, dtype=float) / 128.0
    paths = []
    for index in range(3):
        path = directory / f"steering_{index + 1}.mf4"
        samples = (index + 1) * np.sin(2.0 * np.pi * (index + 2) * timestamps)
        write_single_channel_mf4(
            path,
            name=CHANNEL,
            unit="Nm",
            timestamps=timestamps,
            samples=samples,
        )
        paths.append(path)
    return paths


def test_frozen_batch_acceptance_uses_batch_runner_for_three_mf4_csv_pdf_sets(
    tmp_path, monkeypatch
):
    from mf4_analyzer.frozen_batch_acceptance import run

    sources = _write_acceptance_sources(tmp_path)
    output_dir = tmp_path / "outputs"
    evidence_json = tmp_path / "acceptance.json"
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    exit_code = run(sources, output_dir, evidence_json, channel=CHANNEL)

    assert exit_code == 0
    evidence = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert evidence["ok"] is True
    assert evidence["execution"] == "production-batch-runner"
    assert evidence["source_count"] == 3
    assert evidence["source_identity_count"] == 3
    assert evidence["channel"] == CHANNEL
    assert evidence["artifact_count"] == 6
    assert evidence["residual_paths"] == []

    manifest_path = Path(evidence["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_status"] == "done"
    assert manifest["summary"] == {
        "cancelled": 0,
        "done": 3,
        "failed": 0,
        "resumed": 0,
        "skipped": 0,
        "total": 3,
    }
    assert len(manifest["entries"]) == 3
    assert {entry["channel"] for entry in manifest["entries"]} == {CHANNEL}
    assert len({entry["source"]["identity"] for entry in manifest["entries"]}) == 3

    artifact_paths = []
    for entry in manifest["entries"]:
        assert entry["status"] == "done"
        assert entry["degraded_reason"] == ""
        assert entry["requested_outputs"] == {"data": "csv", "image": "pdf"}
        assert entry["effective_outputs"] == {"data": "csv", "image": "pdf"}
        assert set(entry["artifacts"]) == {"data", "image"}
        for kind, expected_format in (("data", "csv"), ("image", "pdf")):
            artifact = entry["artifacts"][kind]
            path = Path(artifact["path"])
            content = path.read_bytes()
            assert artifact["format"] == expected_format
            assert artifact["size"] == len(content) > 0
            assert artifact["checksum_status"] == "complete"
            assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
            artifact_paths.append(path)

    assert len(set(artifact_paths)) == 6
    assert len(list(output_dir.glob("*.csv"))) == 3
    assert len(list(output_dir.glob("*.pdf"))) == 3
    assert not list(output_dir.glob("*.partial.json"))
    assert not list(output_dir.glob(".*.batch-stage.*"))
    assert not list(output_dir.glob(".*.batch-reserve"))


def test_frozen_batch_acceptance_fails_closed_and_writes_json_for_bad_scope(tmp_path):
    from mf4_analyzer.frozen_batch_acceptance import run

    source = tmp_path / "one.mf4"
    output_dir = tmp_path / "outputs"
    evidence_json = tmp_path / "acceptance.json"

    exit_code = run([source, source, source], output_dir, evidence_json, channel=CHANNEL)

    assert exit_code != 0
    evidence = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert evidence["ok"] is False
    assert "three distinct" in evidence["error"]
    assert not output_dir.exists()


def test_application_entry_routes_frozen_batch_acceptance_without_starting_gui(
    tmp_path, monkeypatch
):
    calls: list[tuple] = []
    fake_acceptance = ModuleType("mf4_analyzer.frozen_batch_acceptance")
    fake_app = ModuleType("mf4_analyzer.app")

    def acceptance_run(source_paths, output_directory, result_json, *, channel):
        calls.append(
            ("acceptance", tuple(source_paths), output_directory, result_json, channel)
        )
        return 9

    def app_main():
        calls.append(("gui",))

    fake_acceptance.run = acceptance_run
    fake_app.main = app_main
    monkeypatch.setitem(
        sys.modules, "mf4_analyzer.frozen_batch_acceptance", fake_acceptance
    )
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    sources = [tmp_path / f"source-{index}.mf4" for index in range(3)]
    output_dir = tmp_path / "outputs"
    result_json = tmp_path / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--frozen-batch-acceptance",
            *sum((["--batch-source", str(path)] for path in sources), []),
            "--batch-channel",
            CHANNEL,
            "--output-dir",
            str(output_dir),
            "--json",
            str(result_json),
        ],
    )

    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(ROOT / "MF4 Data Analyzer V1.py"), run_name="__main__")

    assert stopped.value.code == 9
    assert calls == [
        ("acceptance", tuple(sources), output_dir, result_json, CHANNEL)
    ]
