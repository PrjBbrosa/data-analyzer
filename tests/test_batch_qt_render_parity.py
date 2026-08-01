from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt._builder import build_batch_scene
from mf4_analyzer.batch_render_qt._export import render_scene_image
from tools.verify_batch_qt_render_parity import (
    _cases,
    _plot_corner_ink_counts,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "verify_batch_qt_render_parity.py"


def test_production_qt_renderer_does_not_import_main_ui_or_concrete_canvases():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "mf4_analyzer" / "batch_render_qt").glob("*.py"))
    )
    for forbidden in (
        "main_window",
        "chart_stack",
        "analysis_section_page",
        "TimeDomainCanvasPG",
        "PgLineCanvas",
        "PgHeatmapCanvas",
    ):
        assert forbidden not in source


def test_parity_tool_declares_complete_batch2_matrix():
    source = TOOL.read_text(encoding="utf-8")
    for case in (
        "time-single",
        "time-raw-filtered",
        "time-dual-y",
        "time-subplot8",
        "time-custom-x",
        "fft-linear",
        "fft-db",
        "fft-manual-range",
    ):
        assert case in source


def test_plot_corner_pixel_guard_detects_native_auto_range_button(qapp):
    case = _cases()[0]
    scene = build_batch_scene(
        case.payload,
        params=case.params,
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=case.context,
    )
    try:
        clean = render_scene_image(scene)
        assert max(_plot_corner_ink_counts(scene, clean), default=0) < 160

        plot = scene.plots[0]
        plot.showButtons()
        plot.autoBtn.show()
        plot.autoBtn.setVisible(True)
        shown = render_scene_image(scene)
        assert plot.autoBtn.isVisible()
        assert max(_plot_corner_ink_counts(scene, shown), default=0) >= 160
    finally:
        scene.close()


def test_parity_tool_generates_current_machine_evidence(tmp_path):
    env = dict(os.environ)
    env.update(
        TMPDIR="/tmp",
        QT_QPA_PLATFORM="offscreen",
        MPLCONFIGDIR="/tmp",
        PYTHONPATH=str(ROOT),
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--output-dir",
            str(tmp_path),
            "--width",
            "960",
            "--height",
            "640",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "PASS"
    assert evidence["qt_platform"] == "offscreen"
    assert evidence["commit_sha"]
    assert len(evidence["cases"]) == 8
    assert all(case["status"] == "PASS" for case in evidence["cases"])
    assert all(
        all(case["batch"]["widget_chrome"].values())
        and max(case["batch"]["plot_corner_ink_pixels"], default=0) < 160
        for case in evidence["cases"]
    )
    assert (tmp_path / "time-contact-sheet.png").is_file()
    assert (tmp_path / "fft-contact-sheet.png").is_file()
