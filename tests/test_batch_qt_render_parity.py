from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt._builder import build_batch_scene
from mf4_analyzer.batch_render_qt._export import render_scene_image
from mf4_analyzer.qt_chart_fonts import chart_font
from tools.verify_batch_qt_render_parity import (
    _axis_font_matches_spec,
    _cases,
    _plot_corner_ink_counts,
    _range_close,
    _scene_integration_assertions,
    _visible_text_collisions,
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


def test_parity_tool_declares_complete_batch3_heatmap_matrix():
    source = TOOL.read_text(encoding="utf-8")
    for case in (
        "fft-time-linear-auto",
        "fft-time-db-manual",
        "fft-time-invalid-cmap",
        "order-time-linear-manual",
        "order-time-db-auto",
        "order-time-invalid-cmap",
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
        # Drive the button through pyqtgraph's own visibility rule rather than
        # forcing autoBtn.show(): the export re-runs updateButtons(), so a
        # hand-forced button would simply be hidden again and the guard would
        # never see the pixels it is supposed to catch.
        plot.showButtons()
        plot.mouseHovering = True
        plot.updateButtons()
        shown = render_scene_image(scene)
        assert plot.autoBtn.isVisible()
        assert max(_plot_corner_ink_counts(scene, shown), default=0) >= 160
    finally:
        scene.close()


def test_integration_guard_rejects_enabled_native_plot_menu(qapp):
    case = _cases()[0]
    scene = build_batch_scene(
        case.payload,
        params=case.params,
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=case.context,
    )
    try:
        clean = render_scene_image(scene)
        assert _scene_integration_assertions(scene, clean)["no_native_chrome"]

        scene.plots[0].setMenuEnabled(True)
        mutated = render_scene_image(scene)
        assert not _scene_integration_assertions(
            scene, mutated,
        )["no_native_chrome"]
    finally:
        scene.close()


def test_integration_guard_rejects_main_navigation_label(qapp):
    import pyqtgraph as pg

    case = _cases()[0]
    scene = build_batch_scene(
        case.payload,
        params=case.params,
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=case.context,
    )
    try:
        clean = render_scene_image(scene)
        assert _scene_integration_assertions(scene, clean)["no_main_navigation"]

        navigation = pg.LabelItem("时域 / FFT / FFT vs Time / 阶次")
        scene.page_labels = (*scene.page_labels, navigation)
        mutated = render_scene_image(scene)
        assert not _scene_integration_assertions(
            scene, mutated,
        )["no_main_navigation"]
    finally:
        scene.close()


def _range_record(
    *, x=(0.0, 1.0), y, data_y, auto_y=True, data_x=(0.0, 1.0), auto_x=False
):
    return {
        "x": list(x),
        "y": list(y),
        "data_x": None if data_x is None else list(data_x),
        "data_y": None if data_y is None else list(data_y),
        "auto": [bool(auto_x), bool(auto_y)],
    }


def test_axis_font_guard_checks_each_side_against_its_own_spec():
    """The two renderers run different sizes on purpose; pooling them drifted.

    ``axis_font_pt`` was deliberately raised to 12.0 for the report page while
    the interactive canvases stayed on ``chart_font``'s default, so an
    assertion that demands one number across both sides can only ever fail.
    """

    batch = {"axis_font_points": [12.0, 12.0], "axis_font_expected_pt": 12.0}
    reference = {"axis_font_points": [9.0], "axis_font_expected_pt": 9.0}
    assert _axis_font_matches_spec(batch)
    assert _axis_font_matches_spec(reference)

    # Drift on either side is still caught.
    assert not _axis_font_matches_spec(
        {"axis_font_points": [12.0, 9.0], "axis_font_expected_pt": 12.0}
    )
    assert not _axis_font_matches_spec(
        {"axis_font_points": [11.0], "axis_font_expected_pt": 9.0}
    )
    # An empty recording must not pass vacuously: deleting the measurement is
    # exactly how a guard like this quietly stops guarding.
    assert not _axis_font_matches_spec(
        {"axis_font_points": [], "axis_font_expected_pt": 12.0}
    )


def test_axis_font_expectation_tracks_font_scale_not_a_constant(qapp):
    """The expected size follows theme * font_scale, so it cannot be re-pinned."""

    case = _cases()[0]
    options = BatchRenderOptions(width_px=960, height_px=640)

    def applied(params):
        scene = build_batch_scene(
            case.payload, params=params, options=options, context=case.context,
        )
        try:
            render_scene_image(scene)
            points = [
                float(plot.getAxis("bottom").style["tickFont"].pointSizeF())
                for plot in scene.plots
            ]
            return float(scene.theme.axis_font_pt), points
        finally:
            scene.close()

    base_pt, base_points = applied({})
    scaled_pt, scaled_points = applied({"font_scale": 1.5})

    assert base_points and all(abs(v - base_pt) <= 0.01 for v in base_points)
    assert scaled_points and all(abs(v - scaled_pt) <= 0.01 for v in scaled_points)
    # The recipe's scale really moved the ruler, and the expectation moved with
    # it rather than staying on whatever the 100% number happens to be.
    assert scaled_pt == pytest.approx(base_pt * 1.5)
    assert scaled_pt != pytest.approx(base_pt)


def test_range_guard_ignores_viewport_padding_but_catches_real_drift():
    """Auto-ranged y differs by ``suggestPadding`` alone; that is not drift.

    The report's stacked panels are shorter than the single-file canvas's, so
    pyqtgraph pads them proportionally more. Everything the two sides must
    actually agree on — the data, the centre, the framing — still has to hold.
    """

    data = (-1.0, 1.0)
    batch = [_range_record(y=(-1.20, 1.20), data_y=data)]
    reference = [_range_record(y=(-1.10, 1.10), data_y=data)]
    assert _range_close(batch, reference)

    # Same padding story, but the data underneath moved.
    assert not _range_close(
        batch, [_range_record(y=(-1.10, 1.10), data_y=(-1.0, 1.05))]
    )
    # Range shifted off the data centre.
    assert not _range_close(
        batch, [_range_record(y=(-0.90, 1.30), data_y=data)]
    )
    # Data clipped by the view.
    assert not _range_close(
        batch, [_range_record(y=(-0.50, 1.10), data_y=data)]
    )
    # Framing far past pyqtgraph's own padding allowance.
    assert not _range_close(
        batch, [_range_record(y=(-2.5, 2.5), data_y=data)]
    )
    # One side silently stopped auto-ranging.
    assert not _range_close(
        batch, [_range_record(y=(-1.10, 1.10), data_y=data, auto_y=False)]
    )
    # x is never padding-tolerant.
    assert not _range_close(
        batch, [_range_record(x=(0.0, 1.001), y=(-1.10, 1.10), data_y=data)]
    )


def test_range_guard_keeps_manual_y_exact():
    """A pinned range is an explicit spec, so it is still compared exactly."""

    manual = [_range_record(y=(0.0, 1.1), data_y=(0.1, 1.0), auto_y=False)]
    assert _range_close(manual, list(manual))
    assert not _range_close(
        manual, [_range_record(y=(0.0, 1.155), data_y=(0.1, 1.0), auto_y=False)]
    )


def test_text_overlap_guard_measures_ink_not_layout_boxes(qapp):
    """A rotated label's box is padding-heavy; only its ink can collide.

    On the 8-panel page the left-axis label boxes intersect by a few pixels of
    QTextDocument margin while the glyphs keep a clear gap, so the box-level
    screen alone reports overlaps the render does not have. Grow the label font
    far enough and the ink really does collide — the guard must still say so.
    """

    case = next(item for item in _cases() if item.name == "time-subplot8")
    scene = build_batch_scene(
        case.payload,
        params=case.params,
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=case.context,
    )
    try:
        render_scene_image(scene)
        assert len(scene.plots) == 8
        assert _visible_text_collisions(scene) == []

        for plot in scene.plots:
            plot.getAxis("left").label.setFont(
                chart_font(scene.theme.axis_font_pt * 2.4)
            )
        render_scene_image(scene)
        assert _visible_text_collisions(scene) != []
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
    assert len(evidence["cases"]) == 14
    assert all(case["status"] == "PASS" for case in evidence["cases"])
    assert all(
        all(case["batch"]["widget_chrome"].values())
        and max(case["batch"]["plot_corner_ink_pixels"], default=0) < 160
        for case in evidence["cases"]
    )
    assert (tmp_path / "time-contact-sheet.png").is_file()
    assert (tmp_path / "fft-contact-sheet.png").is_file()
    assert (tmp_path / "fft_time-contact-sheet.png").is_file()
    assert (tmp_path / "order_time-contact-sheet.png").is_file()
    heatmap_cases = [
        case
        for case in evidence["cases"]
        if case["module"] in {"fft_time", "order_time"}
    ]
    assert len(heatmap_cases) == 6
    assert all(
        case["batch"]["axis_order"] == "row-major"
        and case["batch"]["colorbar_menu_disabled"] is True
        and len(case["batch"]["matrix_corners"]) == 4
        and len(case["batch"]["corner_pixels"]) == 4
        for case in heatmap_cases
    )
