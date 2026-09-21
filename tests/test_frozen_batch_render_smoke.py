from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import shutil
from types import ModuleType, SimpleNamespace
import runpy
import subprocess
import sys

import numpy as np
import pytest
from PyQt5.QtGui import QColor, QImage, QPainter


ROOT = Path(__file__).resolve().parents[1]
VERIFY_TOOL = ROOT / "tools" / "verify_frozen_batch_render.py"


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_frozen_failure_preserves_child_streams_and_artifacts(tmp_path, monkeypatch, failure):
    from tools import verify_frozen_batch_render as verifier

    exe = tmp_path / "probe.exe"
    exe.touch()
    diagnostics = tmp_path / "diagnostics"

    def failed_child(command, **kwargs):
        kwargs["stdout"].write(b"child stdout\n")
        kwargs["stderr"].write(b"Qt platform/font diagnostic\n")
        outputs = Path(command[command.index("--output-dir") + 1])
        outputs.mkdir()
        (outputs / "partial.png").write_bytes(b"partial artifact")
        Path(command[command.index("--json") + 1]).write_text('{"ok": false}')
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 23)

    monkeypatch.setattr(verifier.subprocess, "run", failed_child)
    error = RuntimeError if failure == "exit" else subprocess.TimeoutExpired
    with pytest.raises(error):
        verifier.verify_frozen(exe, "offscreen", diagnostics_dir=diagnostics)
    assert (diagnostics / "stdout.log").read_bytes() == b"child stdout\n"
    assert (diagnostics / "stderr.log").read_bytes() == b"Qt platform/font diagnostic\n"
    assert (diagnostics / "outputs/partial.png").exists()
    assert json.loads((diagnostics / "child.json").read_text()) == {"ok": False}


def _array_owns_stable_storage(array: np.ndarray) -> bool:
    """True when the buffer is a NumPy allocation, not a QImage bits() view."""
    root = array
    while getattr(root, "base", None) is not None:
        root = root.base
    return isinstance(root, np.ndarray) and bool(root.flags["OWNDATA"])


def _overwrite_qimage_buffers(color: tuple[int, int, int] = (210, 120, 30)) -> list[QImage]:
    """Supplementary allocator pressure; ownership is the deterministic gate."""
    retained: list[QImage] = []
    fill = QColor(*color)
    for _ in range(32):
        image = QImage(64, 64, QImage.Format_RGB888)
        image.fill(fill)
        retained.append(image)
    return retained


def _padded_rgb888_pattern(width: int = 5, height: int = 3) -> tuple[QImage, np.ndarray]:
    image = QImage(width, height, QImage.Format_RGB888)
    assert not image.isNull()
    assert image.bytesPerLine() > width * 3
    expected = np.empty((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            color = (
                (x * 17 + 12) % 256,
                (y * 29 + 34) % 256,
                (x * 3 + y * 5 + 56) % 256,
            )
            image.setPixelColor(x, y, QColor(*color))
            expected[y, x] = color
    return image, expected


class TestPixelRgbArrayOwnership:
    def test_padded_rgb888_survives_source_and_converted_destruction(self):
        from tools import verify_frozen_batch_render as verifier

        image, expected = _padded_rgb888_pattern()
        pixels = verifier._pixel_rgb_array(image)
        assert pixels.shape == expected.shape
        assert pixels.dtype == np.uint8
        assert _array_owns_stable_storage(pixels)

        del image
        gc.collect()
        retained = _overwrite_qimage_buffers()
        np.testing.assert_array_equal(pixels, expected)
        assert tuple(int(channel) for channel in pixels[0, 0]) != (210, 120, 30)
        assert retained  # keep allocations alive across the content check

    def test_argb32_input_survives_source_and_converted_destruction(self):
        from tools import verify_frozen_batch_render as verifier

        image = QImage(4, 2, QImage.Format_ARGB32)
        image.fill(QColor(12, 34, 56, 200))
        pixels = verifier._pixel_rgb_array(image)
        assert pixels.shape == (2, 4, 3)
        assert _array_owns_stable_storage(pixels)

        del image
        gc.collect()
        retained = _overwrite_qimage_buffers()
        np.testing.assert_array_equal(
            pixels, np.full((2, 4, 3), (12, 34, 56), dtype=np.uint8)
        )
        assert retained

    def test_empty_image_raises_clear_value_error(self):
        from tools import verify_frozen_batch_render as verifier

        with pytest.raises(ValueError, match="empty"):
            verifier._pixel_rgb_array(QImage())
        with pytest.raises(ValueError, match="empty"):
            verifier._pixel_rgb_array(QImage(0, 0, QImage.Format_RGB888))

    def test_contains_rgb_consumers_count_stable_copy(self):
        from tools import verify_frozen_batch_render as verifier

        padded, expected = _padded_rgb888_pattern()
        unique = tuple(int(channel) for channel in expected[0, 0])
        assert verifier._contains_rgb(padded, unique) >= 1
        # Interior crop of a small padded image still sees the body, not row padding.
        assert verifier._contains_rgb_in_interior(padded, unique, margin_frac=0.0) >= 1

        image = QImage(8, 8, QImage.Format_ARGB32)
        image.fill(QColor(1, 2, 3))
        for y in range(2, 6):
            for x in range(2, 6):
                image.setPixelColor(x, y, QColor(12, 34, 56))
        assert verifier._contains_rgb(image, (12, 34, 56)) == 16
        assert verifier._contains_rgb(image, (1, 2, 3)) == 48
        assert verifier._contains_rgb_in_interior(image, (12, 34, 56)) == 16
        assert verifier._contains_rgb_in_interior(image, (1, 2, 3)) == 0

    def test_pixel_consumers_read_through_pixel_rgb_array(self):
        source = VERIFY_TOOL.read_text(encoding="utf-8")
        assert source.count("pixels = _pixel_rgb_array(image)") >= 2
        assert "def _contains_rgb(" in source
        assert "def _contains_rgb_in_interior(" in source


def _source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    # Hard-asserted offscreen smoke must not inherit a cocoa parent platform.
    environment["QT_QPA_PLATFORM"] = "offscreen"
    return environment


def _run_source_smoke(output_directory: Path, child_json: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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


@pytest.fixture(scope="module")
def frozen_smoke_png_artifacts(tmp_path_factory):
    """One 6-PNG smoke child. Qt dies with that process; files are immutable."""

    root = tmp_path_factory.mktemp("frozen-smoke")
    output_directory = root / "outputs"
    child_json = root / "child.json"
    completed = _run_source_smoke(output_directory, child_json)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(child_json.read_text(encoding="utf-8"))
    return SimpleNamespace(
        output_directory=output_directory,
        child_json=child_json,
        result=result,
        stderr=completed.stderr,
    )


def test_runtime_smoke_cli_generates_heatmap_png_kinds(frozen_smoke_png_artifacts):
    result = frozen_smoke_png_artifacts.result
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
    layout = result["layout_diagnostics"]
    assert layout["export_font_dpi"] == 96.0
    assert layout["page"]["artifact"] == "time.png"
    assert layout["page"]["title"]["rect"][2] > 0
    assert layout["page"]["legend"]["rect"][2] > 0
    assert len(layout["page"]["ticks"]) >= 2
    assert layout["page"]["same_axis_tick_overlaps"] == []


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


def test_artifact_verifier_checks_qt_cjk_proof_and_turbo_samples(
    tmp_path, frozen_smoke_png_artifacts
):
    evidence_json = tmp_path / "evidence.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_TOOL),
            "--artifacts",
            str(frozen_smoke_png_artifacts.output_directory),
            "--child-json",
            str(frozen_smoke_png_artifacts.child_json),
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
    layout = evidence["layout_diagnostics"]
    assert layout["export_font_dpi"] == 96.0
    assert layout["logical_dpi_x"] > 0
    assert layout["axis_font_device_px"] > 0
    page = layout["page"]
    assert page["artifact"] == "time.png"
    assert len(page["title"]["rect"]) == 4
    assert len(page["legend"]["rect"]) == 4
    assert len(page["ticks"]) >= 2
    assert page["same_axis_tick_overlaps"] == []
    proof = evidence["page_layout_proof"]
    assert proof["title_ink_pixels"] >= 120
    assert proof["legend_ink_pixels"] >= 120
    assert proof["tick_ink_pixels"] >= 120
    assert proof["same_axis_tick_overlaps"] == []


def test_artifact_verifier_rejects_requested_actual_platform_mismatch(
    tmp_path, frozen_smoke_png_artifacts
):
    evidence_json = tmp_path / "evidence.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_TOOL),
            "--artifacts",
            str(frozen_smoke_png_artifacts.output_directory),
            "--child-json",
            str(frozen_smoke_png_artifacts.child_json),
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
    assert evidence["outputs"] == []


def test_runtime_smoke_fails_closed_when_cjk_font_has_no_ink(tmp_path, monkeypatch):
    from PyQt5.QtGui import QFont

    from mf4_analyzer import batch_render_smoke

    monkeypatch.setattr(
        batch_render_smoke, "resolve_cjk_font", lambda: QFont("Microsoft YaHei UI", 12)
    )

    def fake_proof(font, text=""):
        return {
            "font": font.family(),
            "supports": True,
            "ink_pixels": 0,
            "empty_ink_pixels": 0,
            "pass": False,
        }

    monkeypatch.setattr(batch_render_smoke, "header_ink_proof", fake_proof)

    result_json = tmp_path / "result.json"
    exit_code = batch_render_smoke.run(tmp_path / "outputs", result_json)

    assert exit_code == 1
    evidence = json.loads(result_json.read_text(encoding="utf-8"))
    assert evidence["ok"] is False
    assert evidence["cjk_proof"]["pass"] is False
    assert evidence["cjk_proof"]["supports"] is True
    assert evidence["outputs"] == []
    assert "ink" in str(evidence.get("environment_gate", "")).lower()


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


def _clone_smoke_case(tmp_path: Path, frozen_smoke_png_artifacts) -> tuple[Path, Path, dict]:
    artifacts = tmp_path / "outputs"
    shutil.copytree(frozen_smoke_png_artifacts.output_directory, artifacts)
    child_json = tmp_path / "child.json"
    payload = json.loads(frozen_smoke_png_artifacts.child_json.read_text(encoding="utf-8"))
    child_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifacts, child_json, payload


def _run_artifact_verifier(artifacts: Path, child_json: Path, evidence_json: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFY_TOOL),
            "--artifacts",
            str(artifacts),
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
        timeout=60,
    )


def _fill_rect_with_background(image_path: Path, rect: list[float]) -> None:
    from tools.verify_frozen_batch_render import _theme_background_rgb

    image = QImage(str(image_path))
    assert not image.isNull()
    painter = QPainter(image)
    painter.fillRect(
        int(rect[0]) - 4,
        int(rect[1]) - 4,
        int(rect[2]) + 8,
        int(rect[3]) + 8,
        QColor(*_theme_background_rgb()),
    )
    painter.end()
    assert image.save(str(image_path), "PNG")


def test_artifact_verifier_rejects_blank_title_and_legend_regions(
    tmp_path, frozen_smoke_png_artifacts
):
    artifacts, child_json, payload = _clone_smoke_case(tmp_path / "title", frozen_smoke_png_artifacts)
    page = payload["layout_diagnostics"]["page"]
    _fill_rect_with_background(artifacts / "time.png", page["title"]["rect"])
    evidence = tmp_path / "title-evidence.json"
    completed = _run_artifact_verifier(artifacts, child_json, evidence)
    assert completed.returncode == 1
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "title PNG region" in report["error"]

    artifacts, child_json, payload = _clone_smoke_case(tmp_path / "legend", frozen_smoke_png_artifacts)
    page = payload["layout_diagnostics"]["page"]
    _fill_rect_with_background(artifacts / "time.png", page["legend"]["rect"])
    evidence = tmp_path / "legend-evidence.json"
    completed = _run_artifact_verifier(artifacts, child_json, evidence)
    assert completed.returncode == 1
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "legend PNG region" in report["error"]


def test_artifact_verifier_rejects_overlapping_ticks_even_when_child_ok(
    tmp_path, frozen_smoke_png_artifacts
):
    """F4: historical windows.json was ok=true with overlapping 192-DPI ticks."""
    artifacts, child_json, payload = _clone_smoke_case(tmp_path, frozen_smoke_png_artifacts)
    page = payload["layout_diagnostics"]["page"]
    first, second = page["ticks"][0], dict(page["ticks"][1])
    second["side"] = first["side"]
    second["panel"] = first.get("panel", 0)
    second["rect"] = list(first["rect"])
    second["rect"][0] = first["rect"][0] + 4
    page["ticks"][1] = second
    page["same_axis_tick_overlaps"] = []
    payload["ok"] = True
    child_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence = tmp_path / "overlap-evidence.json"
    completed = _run_artifact_verifier(artifacts, child_json, evidence)
    assert completed.returncode == 1
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "overlapping tick labels" in report["error"]


def test_artifact_verifier_rejects_known_192dpi_overlap_layout(
    tmp_path, frozen_smoke_png_artifacts
):
    from tools.verify_frozen_batch_render import same_axis_tick_overlaps, verify_page_layout

    artifacts, _child_json, payload = _clone_smoke_case(tmp_path, frozen_smoke_png_artifacts)
    known = ROOT / ".state/lite-review-20260921/render-windows/outputs/time.png"
    image_path = artifacts / "time.png"
    if known.is_file():
        shutil.copyfile(known, image_path)
    ticks = [
        {"side": "bottom", "text": "0.00", "rect": [80, 300, 48, 20], "panel": 0},
        {"side": "bottom", "text": "0.25", "rect": [100, 300, 48, 20], "panel": 0},
    ]
    assert same_axis_tick_overlaps(ticks)
    layout = {
        "export_font_dpi": 96.0,
        "logical_dpi_x": 192.0,
        "axis_font_device_px": 41.0,
        "page": {
            "kind": "time",
            "artifact": "time.png",
            "title": payload["layout_diagnostics"]["page"]["title"],
            "legend": payload["layout_diagnostics"]["page"]["legend"],
            "ticks": ticks,
            "same_axis_tick_overlaps": [],
            "adjacent_overlaps": [],
            "overflow": [],
        },
    }
    with pytest.raises(RuntimeError, match="overlapping tick labels"):
        verify_page_layout(QImage(str(image_path)), layout)


def test_artifact_verifier_rejects_non_png_format(
    tmp_path, frozen_smoke_png_artifacts
):
    artifacts, child_json, _payload = _clone_smoke_case(tmp_path, frozen_smoke_png_artifacts)
    jpeg = QImage(str(artifacts / "time.png"))
    assert jpeg.save(str(artifacts / "time.png"), "JPEG")
    evidence = tmp_path / "format-evidence.json"
    completed = _run_artifact_verifier(artifacts, child_json, evidence)
    assert completed.returncode == 1
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "invalid PNG artifact" in report["error"]


def test_artifact_verifier_rejects_missing_layout_diagnostics(
    tmp_path, frozen_smoke_png_artifacts
):
    artifacts, child_json, payload = _clone_smoke_case(tmp_path, frozen_smoke_png_artifacts)
    payload.pop("layout_diagnostics")
    child_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence = tmp_path / "missing-layout.json"
    completed = _run_artifact_verifier(artifacts, child_json, evidence)
    assert completed.returncode == 1
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "layout diagnostics" in report["error"]
