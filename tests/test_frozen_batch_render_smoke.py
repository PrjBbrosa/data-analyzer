from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFY_TOOL = ROOT / "tools" / "verify_frozen_batch_render.py"


def _source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment["MPLBACKEND"] = "Agg"
    return environment


def test_runtime_smoke_cli_generates_four_kinds_in_three_formats(tmp_path):
    output_directory = tmp_path / "outputs"
    child_json = tmp_path / "child.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mf4_analyzer.batch_render_smoke",
            "--output-dir",
            str(output_directory),
            "--json",
            str(child_json),
        ],
        cwd=ROOT,
        env=_source_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(child_json.read_text(encoding="utf-8"))
    expected = {
        f"{kind}.{image_format}"
        for kind in ("time", "fft", "fft_time", "order_time")
        for image_format in ("png", "pdf", "svg")
    }
    assert result["ok"] is True
    assert {Path(record["path"]).name for record in result["outputs"]} == expected
    assert all(record["bytes"] > 0 for record in result["outputs"])
    assert result["glyph_warnings"] == []
    assert result["title"] == "单帧振动加速度"


def test_artifact_verifier_checks_cjk_pdf_visual_and_turbo_samples(tmp_path):
    output_directory = tmp_path / "outputs"
    child_json = tmp_path / "child.json"
    evidence_json = tmp_path / "evidence.json"
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "mf4_analyzer.batch_render_smoke",
            "--output-dir",
            str(output_directory),
            "--json",
            str(child_json),
        ],
        cwd=ROOT,
        env=_source_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert child.returncode == 0, child.stderr

    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_TOOL),
            "--artifacts",
            str(output_directory),
            "--child-json",
            str(child_json),
            "--evidence-json",
            str(evidence_json),
        ],
        cwd=ROOT,
        env=_source_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert evidence["ok"] is True
    assert evidence["artifact_count"] == 12
    assert evidence["cjk_glyph_warnings"] == []
    assert evidence["pdf_text_extractable"] is True
    assert evidence["pdf_visual_nonempty"] is True
    assert evidence["turbo_samples"] == {
        "low_rgb": [48, 18, 59],
        "high_rgb": [122, 4, 3],
    }
    assert evidence["title"] == "单帧振动加速度"


def test_windowed_runtime_smoke_does_not_require_console_streams(tmp_path, monkeypatch):
    from mf4_analyzer.batch_render_smoke import run

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    result = run(tmp_path / "outputs", tmp_path / "result.json")

    assert result == 0


def test_application_entry_routes_frozen_render_smoke_without_starting_gui(
    tmp_path, monkeypatch
):
    calls: list[tuple[str, Path, Path] | tuple[str]] = []
    fake_smoke = ModuleType("mf4_analyzer.batch_render_smoke")
    fake_app = ModuleType("mf4_analyzer.app")

    def smoke_run(output_directory, result_json):
        calls.append(("smoke", output_directory, result_json))
        return 7

    def app_main():
        calls.append(("gui",))

    fake_smoke.run = smoke_run
    fake_app.main = app_main
    monkeypatch.setitem(sys.modules, "mf4_analyzer.batch_render_smoke", fake_smoke)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    output_directory = tmp_path / "outputs"
    result_json = tmp_path / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--batch-render-runtime-smoke",
            "--output-dir",
            str(output_directory),
            "--json",
            str(result_json),
        ],
    )

    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(ROOT / "MF4 Data Analyzer V1.py"), run_name="__main__")

    assert stopped.value.code == 7
    assert calls == [("smoke", output_directory, result_json)]
