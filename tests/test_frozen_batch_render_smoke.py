from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest
from PyQt5.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]
VERIFY_TOOL = ROOT / "tools" / "verify_frozen_batch_render.py"


def _source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    return environment


def test_runtime_smoke_cli_generates_heatmap_png_kinds(tmp_path):
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
        f"{kind}.png"
        for kind in ("time", "fft", "fft_time", "order_time")
    } | {
        f"{kind}_default_cmap.png"
        for kind in ("fft_time", "order_time")
    }
    assert result["ok"] is True
    assert {Path(record["path"]).name for record in result["outputs"]} == expected
    assert all(record["bytes"] > 0 for record in result["outputs"])
    assert result["title"] == "单帧振动加速度"
    assert result["qt_qpa_platform"] == "offscreen"
    assert result["qt_platform_name"] == "offscreen"
    assert result["cjk_proof"]["supports"] is True
    assert result["cjk_proof"]["pass"] is True
    assert result["cjk_proof"]["ink_pixels"] > (
        result["cjk_proof"]["empty_ink_pixels"] + 120
    )


def test_runtime_smoke_renders_time_spec_through_public_renderer(
    tmp_path, monkeypatch
):
    from mf4_analyzer import batch_render_smoke
    from mf4_analyzer.batch_render import BatchTimeFigureSpec

    rendered_payloads = []
    public_renderer = batch_render_smoke.render_batch_image

    def render_and_record(payload, *args, **kwargs):
        rendered_payloads.append(payload)
        return public_renderer(payload, *args, **kwargs)

    monkeypatch.setattr(batch_render_smoke, "render_batch_image", render_and_record)
    output_directory = tmp_path / "outputs"

    assert batch_render_smoke.run(output_directory, tmp_path / "result.json") == 0
    assert isinstance(rendered_payloads[0][1], BatchTimeFigureSpec)

    time_image = output_directory / "time.png"
    assert time_image.stat().st_size > 0
    image = QImage(str(time_image))
    assert not image.isNull()
    assert (image.width(), image.height()) == (640, 360)


def test_artifact_verifier_checks_qt_cjk_proof_and_turbo_samples(tmp_path):
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
            "--platform",
            "offscreen",
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
    assert evidence["artifact_count"] == 6
    assert evidence["qt_qpa_platform"] == "offscreen"
    assert evidence["qt_platform_name"] == "offscreen"
    assert evidence["cjk_proof"]["supports"] is True
    assert evidence["cjk_proof"]["pass"] is True
    assert evidence["cjk_proof"]["ink_pixels"] > (
        evidence["cjk_proof"]["empty_ink_pixels"] + 120
    )
    # Endpoints are read back at verify time; pin the live turbo LUT shape so
    # a silent literal re-declaration cannot drift unnoticed.
    import pyqtgraph as pg

    turbo = pg.colormap.get("turbo").getLookupTable(0.0, 1.0, 256, alpha=False)
    assert evidence["turbo_samples"] == {
        "low_rgb": [int(channel) for channel in turbo[0][:3]],
        "high_rgb": [int(channel) for channel in turbo[-1][:3]],
    }
    from mf4_analyzer.qt_analysis_shared import (
        DEFAULT_HEATMAP_CMAP,
        _resolve_colormap,
    )

    default_lut = _resolve_colormap(DEFAULT_HEATMAP_CMAP).getLookupTable(
        0.0, 1.0, 256, alpha=False
    )
    assert evidence["default_cmap_samples"] == {
        "cmap": DEFAULT_HEATMAP_CMAP,
        "low_rgb": [int(channel) for channel in default_lut[0][:3]],
        "high_rgb": [int(channel) for channel in default_lut[-1][:3]],
    }
    assert evidence["title"] == "单帧振动加速度"


def test_artifact_verifier_rejects_requested_actual_platform_mismatch(tmp_path):
    artifacts = tmp_path / "outputs"
    child_json = tmp_path / "child.json"
    evidence_json = tmp_path / "evidence.json"
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "mf4_analyzer.batch_render_smoke",
            "--output-dir",
            str(artifacts),
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
            str(artifacts),
            "--child-json",
            str(child_json),
            "--platform",
            "windows",
            "--evidence-json",
            str(evidence_json),
        ],
        cwd=ROOT,
        env=_source_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 1
    evidence = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert evidence["ok"] is False
    assert "requested Qt platform windows" in evidence["error"]


def test_runtime_smoke_fails_closed_when_cjk_font_coverage_is_unavailable(
    tmp_path, monkeypatch
):
    from mf4_analyzer import batch_render_smoke

    monkeypatch.setattr(batch_render_smoke, "resolve_cjk_font", lambda: None)

    result_json = tmp_path / "result.json"
    exit_code = batch_render_smoke.run(tmp_path / "outputs", result_json)

    assert exit_code == 1
    evidence = json.loads(result_json.read_text(encoding="utf-8"))
    assert evidence["ok"] is False
    assert evidence["cjk_proof"]["pass"] is False
    assert evidence["cjk_proof"]["supports"] is False
    assert "CJK" in evidence["environment_gate"]


def test_frozen_artifact_verifier_has_no_pillow_or_vector_format_dependency():
    source = VERIFY_TOOL.read_text(encoding="utf-8")

    assert "PIL" not in source
    assert "Pillow" not in source
    assert "pdftotext" not in source
    assert "pdftocairo" not in source
    assert 'FORMATS = ("png",)' in source


def test_frozen_verifier_measures_final_internal_tree(tmp_path):
    from tools import verify_frozen_batch_render

    internal = tmp_path / "_internal"
    (internal / "nested").mkdir(parents=True)
    (internal / "one.bin").write_bytes(b"one")
    (internal / "nested" / "two.bin").write_bytes(b"twice")

    assert verify_frozen_batch_render._tree_measurement(internal) == {
        "path": str(internal.resolve()),
        "bytes": 8,
        "files": 2,
    }
    assert 'evidence["internal"] = _tree_measurement(exe.parent / "_internal")' in (
        VERIFY_TOOL.read_text(encoding="utf-8")
    )


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
