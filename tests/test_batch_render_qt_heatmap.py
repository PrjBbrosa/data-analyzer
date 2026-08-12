from __future__ import annotations

import warnings
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QFontMetricsF

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt import BatchRenderContext
from mf4_analyzer.batch_render_qt import _builder as batch_render_builder
from mf4_analyzer.batch_render_qt._builder import BuiltBatchScene, build_batch_scene
from mf4_analyzer.batch_render_qt._fonts import chart_font
from mf4_analyzer.batch_render_qt._palette import SLICE_COOL, SLICE_WARM


GOLDEN = "tests/data/colormap_golden.npz"


def _spectro(*, metadata=None):
    return SimpleNamespace(
        x=np.asarray([10.0, 20.0, 40.0]),
        y=np.asarray([1.0, 4.0]),
        # BatchRunner's _Spectro2D producer is x-major: X rows, Y columns.
        matrix=np.asarray(
            [
                [0.10, 0.20],
                [0.30, 0.40],
                [0.50, 0.60],
            ]
        ),
        x_name="time_s",
        y_name="frequency_hz",
        metadata=dict(metadata or {}),
    )


def _context(*, unit="g", method="FFT vs Time"):
    return BatchRenderContext(
        source_display_name="单帧热图.mf4",
        channel="Acceleration",
        unit=unit,
        method=method,
        task_id="T3-heatmap",
    )


def _open_scene(qapp, kind, *, payload=None, params=None, warnings_out=None):
    scene = build_batch_scene(
        (kind, _spectro() if payload is None else payload),
        params=params,
        context=_context(method="Order" if kind == "order_time" else "FFT vs Time"),
        options=BatchRenderOptions(width_px=960, height_px=640),
        warnings_out=warnings_out,
    )
    scene.show_and_settle()
    qapp.processEvents()
    return scene


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_uses_row_major_turbo_golden_and_has_no_native_chrome(qapp, kind):
    scene = _open_scene(
        qapp,
        kind,
        params={"amplitude_mode": "amplitude", "cmap": "turbo"},
    )
    try:
        golden = np.load(GOLDEN)["turbo"]
        assert scene.image_item.axisOrder == "row-major"
        np.testing.assert_array_equal(scene.heatmap_lut, golden)
        assert scene.colorbar.colorMapMenu is False
        assert scene.colorbar.vb.menuEnabled() is False
        assert scene.colorbar.vb.state["mouseEnabled"] == [False, False]
        assert scene.plots[0].menuEnabled() is False
        assert scene.plots[0].vb.state["mouseEnabled"] == [False, False]
        auto_button = getattr(scene.plots[0], "autoBtn", None)
        assert auto_button is None or not auto_button.isVisible()
        assert scene.widget.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert scene.widget.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert scene.widget.focusPolicy() == Qt.NoFocus
    finally:
        scene.close()


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_x_major_payload_becomes_one_row_major_display_matrix(qapp, kind):
    payload = _spectro(metadata={"coverage_start": 2.0, "coverage_end": 60.0})
    if kind == "order_time":
        payload.y_name = "order"
    scene = _open_scene(
        qapp,
        kind,
        payload=payload,
        params={"amplitude_mode": "amplitude"},
    )
    try:
        expected = np.asarray([[0.10, 0.30, 0.50], [0.20, 0.40, 0.60]])
        np.testing.assert_array_equal(scene.display_matrix, expected)
        np.testing.assert_array_equal(scene.image_item.image, expected)
        assert scene.display_matrix[0, 0] == pytest.approx(0.10)
        assert scene.display_matrix[0, -1] == pytest.approx(0.50)
        assert scene.display_matrix[-1, 0] == pytest.approx(0.20)
        assert scene.display_matrix[-1, -1] == pytest.approx(0.60)
        # Only time/X uses frame coverage. Frequency/order Y follows the real
        # single-file axis endpoints, not half-cell expansion.
        expected_rect = QRectF(2.0, 1.0, 58.0, 3.0)
        assert scene.heatmap_rect == expected_rect
        assert scene.image_item.mapRectToParent(
            scene.image_item.boundingRect()
        ) == expected_rect
        assert tuple(scene.plots[0].vb.viewRange()[0]) == pytest.approx((2.0, 60.0))
        assert tuple(scene.plots[0].vb.viewRange()[1]) == pytest.approx((1.0, 4.0))
    finally:
        scene.close()


def test_heatmap_dataframe_pivot_has_same_orientation_as_object_payload(qapp):
    payload = _spectro()
    frame = pd.DataFrame(
        {
            "time_s": np.repeat(payload.x, payload.y.size),
            "order": np.tile(payload.y, payload.x.size),
            "amplitude": payload.matrix.reshape(-1),
        }
    )
    scene = _open_scene(
        qapp,
        "order_time",
        payload=frame,
        params={"amplitude_mode": "amplitude"},
    )
    try:
        np.testing.assert_array_equal(
            scene.display_matrix,
            np.asarray([[0.10, 0.30, 0.50], [0.20, 0.40, 0.60]]),
        )
        assert scene.plots[0].getAxis("bottom").labelText == "Time (s)"
        assert scene.plots[0].getAxis("left").labelText == "Order"
    finally:
        scene.close()


@pytest.mark.parametrize(
    ("kind", "params", "expected_levels", "expected_label"),
    [
        (
            "fft_time",
            {
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
                "z_auto": False,
                "z_floor": -42.5,
                "z_ceiling": -3.5,
            },
            (-42.5, -3.5),
            "Amplitude (dB re 1×10⁰)",
        ),
        (
            "order_time",
            {
                "amplitude_mode": "amplitude",
                "z_auto": False,
                "z_floor": 0.15,
                "z_ceiling": 0.55,
            },
            (0.15, 0.55),
            "Amplitude (g)",
        ),
    ],
)
def test_heatmap_manual_levels_and_colorbar_label_are_exact(
    qapp, kind, params, expected_levels, expected_label
):
    scene = _open_scene(qapp, kind, params=params)
    try:
        assert tuple(scene.heatmap_levels) == pytest.approx(expected_levels)
        assert tuple(scene.image_item.getLevels()) == pytest.approx(expected_levels)
        assert tuple(scene.colorbar.levels()) == pytest.approx(expected_levels)
        assert scene.colorbar.getAxis("left").labelText == expected_label
    finally:
        scene.close()


@pytest.mark.parametrize(
    ("kind", "params", "expected"),
    [
        (
            "fft_time",
            {"amplitude_mode": "amplitude", "z_auto": True},
            (0.10, 0.60),
        ),
        (
            "order_time",
            {
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
                "z_auto": True,
            },
            None,
        ),
    ],
)
def test_heatmap_auto_levels_are_exact(qapp, kind, params, expected):
    if expected is None:
        from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

        matrix = SpectrogramAnalyzer.amplitude_to_db(
            _spectro().matrix.T, reference=1.0
        )
        ceiling = float(np.percentile(matrix[np.isfinite(matrix)], 99.0))
        expected = (ceiling - 30.0, ceiling)
    scene = _open_scene(qapp, kind, params=params)
    try:
        assert tuple(scene.heatmap_levels) == pytest.approx(expected)
        assert tuple(scene.image_item.getLevels()) == pytest.approx(expected)
        assert tuple(scene.colorbar.levels()) == pytest.approx(expected)
    finally:
        scene.close()


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_db_conversion_calls_spectrogram_analyzer_once(
    qapp, monkeypatch, kind
):
    from mf4_analyzer.batch_render_qt import _builder

    calls = []

    def fake_amplitude_to_db(values, reference=1.0):
        calls.append((np.asarray(values).copy(), float(reference)))
        return np.asarray(values, dtype=float) + 7.0

    monkeypatch.setattr(
        _builder.SpectrogramAnalyzer,
        "amplitude_to_db",
        staticmethod(fake_amplitude_to_db),
    )
    scene = _open_scene(
        qapp,
        kind,
        params={
            "amplitude_mode": "amplitude_db",
            "db_reference_mode": "manual",
            "db_reference": 2.0,
        },
    )
    try:
        assert len(calls) == 1
        np.testing.assert_array_equal(calls[0][0], _spectro().matrix.T)
        assert calls[0][1] == pytest.approx(2.0)
        np.testing.assert_array_equal(scene.display_matrix, _spectro().matrix.T + 7.0)
    finally:
        scene.close()


def test_valid_non_turbo_heatmap_colormap_remains_available(qapp):
    scene = _open_scene(
        qapp,
        "order_time",
        params={"amplitude_mode": "amplitude", "cmap": "viridis"},
    )
    try:
        np.testing.assert_array_equal(
            scene.heatmap_lut, np.load(GOLDEN)["viridis"]
        )
    finally:
        scene.close()


def test_invalid_heatmap_colormap_falls_back_to_default_and_warns(qapp):
    warnings_out = []
    scene = _open_scene(
        qapp,
        "order_time",
        params={"amplitude_mode": "amplitude", "cmap": "not-a-real-map"},
        warnings_out=warnings_out,
    )
    try:
        np.testing.assert_array_equal(
            scene.heatmap_lut, np.load(GOLDEN)["gnuplot2"]
        )
        assert warnings_out == [
            "Invalid colormap 'not-a-real-map'; using 'gnuplot2'."
        ]
    finally:
        scene.close()


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_without_cmap_uses_the_interactive_canvas_default(qapp, kind):
    """无 ``cmap`` 键时批处理必须落在画布的默认色图上。

    批处理面板不提供色图控件，所以导出走的就是这条缺省路径。它以前硬编码
    "turbo"，而画布默认 gnuplot2 —— 同一份数据两种配色。字节级比对 golden，
    并直接对照 ``qt_analysis_shared`` 的解析结果，任何一侧再漂移都会红。
    """
    from mf4_analyzer.qt_analysis_shared import (
        DEFAULT_HEATMAP_CMAP, _resolve_colormap,
    )

    scene = _open_scene(qapp, kind, params={"amplitude_mode": "amplitude"})
    try:
        np.testing.assert_array_equal(
            scene.heatmap_lut, np.load(GOLDEN)["gnuplot2"]
        )
        np.testing.assert_array_equal(
            scene.heatmap_lut,
            np.asarray(
                _resolve_colormap(DEFAULT_HEATMAP_CMAP).getLookupTable(
                    0.0, 1.0, 256, alpha=True
                ),
                dtype=np.ubyte,
            ),
        )
    finally:
        scene.close()


def test_heatmap_scene_text_has_semantic_labels_without_main_navigation(qapp):
    scene = _open_scene(
        qapp,
        "fft_time",
        params={
            "amplitude_mode": "amplitude_db",
            "db_reference_mode": "manual",
            "db_reference": 1.0,
        },
    )
    try:
        texts = "\n".join(scene.texts())
        assert "Time (s)" in texts
        assert "Frequency (Hz)" in texts
        assert "Amplitude (dB re 1×10⁰)" in texts
        assert "TraceLab batch export" in texts
        assert "T3-heatmap" not in texts
        assert "Task" not in texts
        # 方法名不再印在页眉——三条坐标轴标题已经说清楚这是什么图；页眉第二行
        # 只留通道名。主窗口那整条导航行更不能泄漏进导出图。
        assert "Acceleration" in texts
        assert "FFT vs Time" not in texts
        assert "时域" not in texts
        assert "阶次" not in texts
    finally:
        scene.close()


# --------------------------------------------------------------------------
# Slice plan — pure data, no Qt (design §4.3)
# --------------------------------------------------------------------------


TIMES = np.asarray([0.0, 10.0, 20.0, 30.0])
FREQS = np.asarray([0.0, 100.0, 200.0])


def _plan(axis, positions, **extra):
    from mf4_analyzer.batch_render_qt._models import plan_heatmap_slice

    spec = {"enabled": True, "axis": axis, "positions": list(positions)}
    spec.update(extra)
    return plan_heatmap_slice(TIMES, FREQS, {"slice": spec})


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {"slice": None},
        {"slice": {"enabled": False, "axis": "time", "positions": [10.0]}},
        {"slice": {"enabled": True, "axis": "time", "positions": []}},
        {"slice": {"enabled": True, "axis": "time", "positions": "10"}},
    ],
)
def test_slice_plan_is_disabled_without_usable_positions(params):
    from mf4_analyzer.batch_render_qt._models import plan_heatmap_slice

    plan = plan_heatmap_slice(TIMES, FREQS, params)
    assert not plan.enabled
    assert plan.picks == ()


def test_slice_plan_snaps_each_request_to_the_nearest_grid_center():
    plan = _plan("time", [9.0, 21.0])
    assert [pick.index for pick in plan.picks] == [1, 2]
    assert [pick.value for pick in plan.picks] == pytest.approx([10.0, 20.0])
    assert [pick.requested for pick in plan.picks] == pytest.approx([9.0, 21.0])
    assert not any(pick.clamped for pick in plan.picks)


def test_slice_plan_reads_the_axis_it_is_told_to_fix():
    assert _plan("y", [90.0]).picks[0].value == pytest.approx(100.0)
    assert _plan("time", [90.0]).picks[0].value == pytest.approx(30.0)


def test_slice_plan_clamps_out_of_range_requests_without_failing():
    plan = _plan("time", [-5.0, 45.0])
    assert [pick.value for pick in plan.picks] == pytest.approx([0.0, 30.0])
    assert all(pick.clamped for pick in plan.picks)
    assert plan.clamped_picks == plan.picks


def test_slice_plan_merges_requests_that_land_on_one_cell():
    plan = _plan("time", [40.0, 50.0, 60.0])
    assert len(plan.picks) == 1
    assert plan.merged == 2
    assert plan.picks[0].value == pytest.approx(30.0)


def test_slice_plan_caps_positions_at_four():
    plan = _plan("y", [0.0, 100.0, 200.0, 100.0, 0.0])
    assert len(plan.picks) + plan.merged == 4


def test_slice_plan_normalizes_an_unknown_axis_to_time():
    assert _plan("frequency", [10.0]).axis == "time"
    assert _plan("Y", [100.0]).axis == "y"


# --------------------------------------------------------------------------
# Slice overlay (design §5)
# --------------------------------------------------------------------------


def _slice_params(axis, positions, **extra):
    params = {"amplitude_mode": "amplitude"}
    params.update(extra)
    params["slice"] = {
        "enabled": True, "axis": axis, "positions": list(positions),
    }
    return params


def _sweep_spectro(*, dc_dead=False):
    """A ridge that walks up in frequency, optionally with a dead 0 Hz bin."""
    times = np.linspace(0.0, 39.0, 40)
    freqs = np.linspace(0.0, 2300.0, 24)
    matrix = np.empty((times.size, freqs.size))
    for index, moment in enumerate(times):
        peak = 400.0 + 40.0 * moment
        matrix[index] = 0.02 + 0.9 * np.exp(
            -((freqs - peak) ** 2) / (2 * 180.0**2)
        )
    if dc_dead:
        # De-mean / A-weighting zero the 0 Hz bin; amplitude_to_db floors it to
        # ≈ -6153 dB. Without the dead-zone guard this alone owns the axis.
        matrix[:, 0] = 0.0
    return SimpleNamespace(
        x=times, y=freqs, matrix=matrix,
        x_name="time_s", y_name="frequency_hz", metadata={},
    )


def _png_bytes(kind, *, params, tmp_path, name):
    from mf4_analyzer.batch_render_qt import render_batch_image

    target = tmp_path / f"{name}.png"
    render_batch_image(
        (kind, _spectro()), target, params=params,
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=_context(),
    )
    return target.read_bytes()


def test_slice_disabled_adds_no_row_and_no_items(qapp):
    scene = _open_scene(
        qapp, "fft_time",
        params={
            "amplitude_mode": "amplitude",
            "slice": {"enabled": False, "axis": "time", "positions": [20.0]},
        },
    )
    try:
        assert len(scene.plots) == 1
        assert scene.slice_plan is not None and not scene.slice_plan.enabled
        assert scene.slice_plot is None
        assert scene.slice_curves == ()
        assert scene.slice_marker_bands == ()
        assert scene.slice_marker_lines == ()
        assert scene.slice_legend is None
    finally:
        scene.close()


def test_slice_disabled_png_is_byte_identical_to_no_slice_field(qapp, tmp_path):
    """The whole point of D6: opening the feature must not touch old presets."""
    without = _png_bytes(
        "fft_time", params={"amplitude_mode": "amplitude"},
        tmp_path=tmp_path, name="without",
    )
    disabled = _png_bytes(
        "fft_time",
        params={
            "amplitude_mode": "amplitude",
            "slice": {"enabled": False, "axis": "time", "positions": [20.0]},
        },
        tmp_path=tmp_path, name="disabled",
    )
    assert disabled == without


@pytest.mark.parametrize("font_size", [None, 20])
def test_slice_main_bottom_label_stays_inside_its_axis_above_slice_row(
    qapp, font_size,
):
    """The main title must use its own axis reserve, never the slice row."""
    scene = _open_scene(
        qapp, "fft_time", params=_slice_params("time", [20.0]),
    )
    try:
        main_axis = scene.plots[0].getAxis("bottom")
        main_label = main_axis.label
        if font_size is not None:
            main_label.setFont(chart_font(font_size))
            scene.show_and_settle()
            qapp.processEvents()

        label_rect = main_label.sceneBoundingRect()
        axis_rect = main_axis.sceneBoundingRect()
        slice_top = scene.slice_plot.vb.sceneBoundingRect().top()
        assert label_rect.bottom() <= slice_top + 0.5
        assert axis_rect.contains(label_rect)
    finally:
        scene.close()


def test_slice_on_time_axis_reads_matrix_columns(qapp):
    """Fixed time → the curve is a *column*, plotted against the Y coordinates.

    ``_extract_heatmap`` hands over a row-major matrix whose rows are Y
    (frequency/order) and whose columns are X (time). Getting this backwards
    still produces a plausible-looking chart, so the payload is deliberately
    non-square (2 frequencies × 3 times): a transposed read cannot even match
    the length.
    """
    scene = _open_scene(qapp, "fft_time", params=_slice_params("time", [20.0]))
    try:
        matrix = scene.display_matrix
        assert matrix.shape == (2, 3)
        (pick,) = scene.slice_plan.picks
        assert pick.index == 1 and pick.value == pytest.approx(20.0)
        x_data, y_data = scene.slice_curves[0].getData()
        np.testing.assert_allclose(y_data, matrix[:, 1])
        np.testing.assert_allclose(y_data, [0.30, 0.40])
        np.testing.assert_allclose(x_data, [1.0, 4.0])  # the Y coordinates
        assert scene.slice_plot.getAxis("bottom").labelText == "Frequency (Hz)"
    finally:
        scene.close()


def test_slice_on_y_axis_reads_matrix_rows(qapp):
    """Fixed frequency → the curve is a *row*, plotted against the X coords."""
    scene = _open_scene(qapp, "fft_time", params=_slice_params("y", [4.0]))
    try:
        matrix = scene.display_matrix
        (pick,) = scene.slice_plan.picks
        assert pick.index == 1 and pick.value == pytest.approx(4.0)
        x_data, y_data = scene.slice_curves[0].getData()
        np.testing.assert_allclose(y_data, matrix[1, :])
        np.testing.assert_allclose(y_data, [0.20, 0.40, 0.60])
        np.testing.assert_allclose(x_data, [10.0, 20.0, 40.0])  # the X coords
        assert scene.slice_plot.getAxis("bottom").labelText == "Time (s)"
    finally:
        scene.close()


def test_slice_fixed_time_is_warm_with_vertical_markers(qapp):
    scene = _open_scene(
        qapp, "fft_time", params=_slice_params("time", [10.0, 20.0, 40.0]),
    )
    try:
        assert len(scene.plots) == 2
        assert len(scene.slice_curves) == 3
        colors = [
            curve.opts["pen"].color().name() for curve in scene.slice_curves
        ]
        assert colors == list(SLICE_WARM[:3])
        # Each position gets a white underlay plus the matching colour line.
        assert len(scene.slice_marker_lines) == 6
        assert {line.angle for line in scene.slice_marker_lines} == {90.0}
        assert [
            line.pen.color().name() for line in scene.slice_marker_lines
        ] == [
            "#ffffff", SLICE_WARM[0],
            "#ffffff", SLICE_WARM[1],
            "#ffffff", SLICE_WARM[2],
        ]
        assert [
            line.value() for line in scene.slice_marker_lines
        ] == pytest.approx([10.0, 10.0, 20.0, 20.0, 40.0, 40.0])
        # Design D-B5: 3.6/2.0 -> 5.2/2.6 (wider white underlay, thicker
        # colour line on top) so the colour survives against a turbo backdrop.
        widths = {line.pen.widthF() for line in scene.slice_marker_lines}
        assert widths == {5.2, 2.6}
        for line in scene.slice_marker_lines:
            assert line in scene.plots[0].items
        # Design D-B6: 3+ overlaid curves in one panel get a lighter stroke
        # (not transparency, which would just wash them out to grey on white).
        curve_widths = {curve.opts["pen"].widthF() for curve in scene.slice_curves}
        assert curve_widths == {scene.options.line_width * 0.85}
    finally:
        scene.close()


def test_slice_fixed_frequency_is_cool_with_horizontal_markers(qapp):
    scene = _open_scene(qapp, "fft_time", params=_slice_params("y", [1.0, 4.0]))
    try:
        colors = [
            curve.opts["pen"].color().name() for curve in scene.slice_curves
        ]
        assert colors == list(SLICE_COOL[:2])
        assert {line.angle for line in scene.slice_marker_lines} == {0.0}
        assert [
            line.value() for line in scene.slice_marker_lines
        ] == pytest.approx([1.0, 1.0, 4.0, 4.0])
        # Design D-B6: below 3 curves, no thinning — full options.line_width.
        curve_widths = {curve.opts["pen"].widthF() for curve in scene.slice_curves}
        assert curve_widths == {scene.options.line_width}
    finally:
        scene.close()


@pytest.mark.parametrize(
    ("axis", "positions", "angle"),
    [
        ("time", [10.0, 20.0], 90.0),
        ("y", [1.0, 4.0], 0.0),
    ],
)
def test_slice_markers_have_transparent_red_highlight_bands(
    qapp, axis, positions, angle,
):
    """The heatmap cut remains visible without replacing its curve colour."""
    scene = _open_scene(qapp, "fft_time", params=_slice_params(axis, positions))
    try:
        assert len(scene.slice_marker_bands) == len(positions)
        assert {band.angle for band in scene.slice_marker_bands} == {angle}
        assert [band.value() for band in scene.slice_marker_bands] == pytest.approx(
            positions,
        )
        for band in scene.slice_marker_bands:
            assert band.pen.widthF() == pytest.approx(18.0)
            assert band.pen.color().getRgb() == (255, 45, 85, 90)
            assert band.zValue() == pytest.approx(898.0)
            assert band in scene.plots[0].items
    finally:
        scene.close()


def _srgb_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _hex_to_lab(color: str) -> tuple[float, float, float]:
    """Minimal sRGB (D65) -> CIELAB conversion (no scipy/colormath deps).

    Only used to keep the slice palette's intra-family distinguishability
    (design D-B4) from silently regressing — see
    ``docs/analyzer/specs/2026-08-03-batch-acceptance-followup-design.md`` §B3
    for the derivation and the full pairwise matrix.
    """
    color = color.lstrip("#")
    r, g, b = (int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    r, g, b = (_srgb_to_linear(c) for c in (r, g, b))
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        delta = 6.0 / 29.0
        if t > delta**3:
            return t ** (1.0 / 3.0)
        return t / (3.0 * delta**2) + 4.0 / 29.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _delta_e_cie76(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(lab1, lab2)) ** 0.5


#: Empirical bar (design D-B4): below this, two lines on the same slice panel
#: read as indistinguishable. The previous palette's #2563eb/#4f46e5 pair sat
#: at 21.0 -- that pairing is the readability bug this constant guards against.
_MIN_FAMILY_DELTA_E = 25.0


@pytest.mark.parametrize("family", [SLICE_WARM, SLICE_COOL], ids=["warm", "cool"])
def test_slice_palette_family_is_pairwise_distinguishable(family):
    """Every colour in a slice family must read apart from every other.

    CIE76 delta-E in CIELAB space, computed with a from-scratch sRGB->Lab
    conversion (design constraint: no scipy/colormath). This is a structural
    guard, not a visual one -- this machine's Qt has no fonts and cannot
    render the actual chart (see the F7 plan notes); real readability still
    needs a look at a real screen.
    """
    labs = [_hex_to_lab(color) for color in family]
    for i in range(len(labs)):
        for j in range(i + 1, len(labs)):
            delta_e = _delta_e_cie76(labs[i], labs[j])
            assert delta_e >= _MIN_FAMILY_DELTA_E, (
                f"{family[i]} vs {family[j]}: delta-E={delta_e:.1f} "
                f"< {_MIN_FAMILY_DELTA_E}"
            )


def test_slice_shares_the_main_plot_horizontal_range(qapp):
    """axis="y" reads along time, so it must sit under the same X window."""
    scene = _open_scene(qapp, "fft_time", params=_slice_params("y", [4.0]))
    try:
        assert tuple(scene.slice_plot.vb.viewRange()[0]) == pytest.approx(
            tuple(scene.plots[0].vb.viewRange()[0])
        )
    finally:
        scene.close()


def test_slice_fixed_time_horizontal_range_follows_the_main_y_axis(qapp):
    scene = _open_scene(
        qapp, "fft_time",
        params=_slice_params(
            "time", [20.0], y_auto=False, y_min=1.5, y_max=3.5,
        ),
    )
    try:
        assert tuple(scene.slice_plot.vb.viewRange()[0]) == pytest.approx(
            (1.5, 3.5)
        )
    finally:
        scene.close()


def test_slice_rows_share_the_same_plot_area_edges(qapp):
    """The colorbar gutter is spacered out so both rows read as one chart."""
    scene = _open_scene(
        qapp, "fft_time", params=_slice_params("time", [10.0, 40.0]),
    )
    try:
        main = scene.plots[0].vb.sceneBoundingRect()
        slice_rect = scene.slice_plot.vb.sceneBoundingRect()
        assert slice_rect.left() == pytest.approx(main.left(), abs=1.0)
        assert slice_rect.right() == pytest.approx(main.right(), abs=1.0)
        # 6 : 3 — the map keeps roughly twice the slice's height.
        assert main.height() > slice_rect.height()
        assert main.height() / slice_rect.height() == pytest.approx(2.0, abs=0.5)
    finally:
        scene.close()


def _main_left_axis_width(qapp, params):
    scene = _open_scene(
        qapp, "fft_time", payload=_sweep_spectro(), params=params,
    )
    try:
        return float(scene.plots[0].getAxis("left").width())
    finally:
        scene.close()


def _tick_texts(axis):
    return [text for level in (axis._tickLevels or []) for _value, text in level]


def _alignment_callback(scene):
    (align,) = [
        callback
        for callback in scene._layout_callbacks
        if getattr(callback, "runs_after_tick_density", False)
        and callback.__name__ == "align"
    ]
    return align


def test_slice_row_never_narrows_the_main_left_axis(qapp):
    """Turning the slice row on must not shrink the axis it aligns.

    The alignment callback pins both left axes to one width, and a pinned
    ``AxisItem`` stops re-measuring itself. Deriving that width from
    ``axis.width()`` sampled the paint-time ``textWidth`` attribute, which on a
    never-painted axis is pyqtgraph's initial ``30`` — the row froze at 57.4 px
    against the 95.4 px the very same ticks occupy with the slice row off, and
    the rotated axis title came down on top of the numbers.
    """
    without = _main_left_axis_width(qapp, {"amplitude_mode": "amplitude"})
    with_slice = _main_left_axis_width(
        qapp, _slice_params("time", [5.0, 15.0, 25.0]),
    )
    assert with_slice >= without


def test_slice_alignment_keeps_painted_axis_width_when_tick_measurement_is_low(
    qapp, monkeypatch,
):
    without = _main_left_axis_width(qapp, {"amplitude_mode": "amplitude"})
    scene = _open_scene(
        qapp, "fft_time", payload=_sweep_spectro(),
        params=_slice_params("time", [5.0, 15.0, 25.0]),
    )
    try:
        real_measure = batch_render_builder._left_axis_width_for_ticks
        monkeypatch.setattr(
            batch_render_builder,
            "_left_axis_width_for_ticks",
            lambda axis: real_measure(axis) - 6.0,
        )

        _alignment_callback(scene)()
        qapp.processEvents()

        assert float(scene.plots[0].getAxis("left").width()) >= without
    finally:
        scene.close()


def test_slice_alignment_measures_the_ticks_that_are_actually_installed(qapp):
    """Longer tick strings have to move the pin, not be clipped behind it.

    ``_apply_tick_density`` swaps the tick strings at the very end of
    ``show_and_settle``, so an alignment that trusts a previously measured
    width answers for labels that are no longer on the axis.
    """
    scene = _open_scene(
        qapp, "fft_time", payload=_sweep_spectro(),
        params=_slice_params("time", [5.0, 15.0, 25.0]),
    )
    try:
        align = _alignment_callback(scene)
        main_axis = scene.plots[0].getAxis("left")
        slice_axis = scene.slice_plot.getAxis("left")
        before = float(main_axis.width())
        assert max(len(text) for text in _tick_texts(main_axis)) == 4

        # Same values, six-digit labels: nothing but the strings changes.
        main_axis.setTicks(
            [[(value, f"{text}00") for value, text in main_axis._tickLevels[0]], []]
        )
        align()
        # A pinned width reaches the enclosing layout through a posted
        # LayoutRequest, so the realized geometry needs a drain — the same one
        # ``show_and_settle`` performs right after running these callbacks.
        qapp.processEvents()

        assert max(len(text) for text in _tick_texts(main_axis)) == 6
        assert float(main_axis.width()) > before
        # Font-independent statement of the contract: whatever the fallback
        # font measures, the axis is wider than its own widest tick string, so
        # the rotated title cannot land on the numbers.
        metrics = QFontMetricsF(main_axis.style["tickFont"])
        assert float(main_axis.width()) > max(
            metrics.width(text) for text in _tick_texts(main_axis)
        )
        # Both rows stay pinned to the same width, or the two plot areas
        # stop lining up.
        assert float(slice_axis.width()) == pytest.approx(
            float(main_axis.width())
        )
        assert scene.slice_plot.vb.sceneBoundingRect().left() == pytest.approx(
            scene.plots[0].vb.sceneBoundingRect().left(), abs=1.0
        )
    finally:
        scene.close()


def test_vertical_labels_fit_uses_glyph_height_without_leading():
    class StubMetrics:
        def height(self):
            return 24.0

        def ascent(self):
            return 12.0

        def descent(self):
            return 4.0

    assert BuiltBatchScene._labels_fit(
        [str(value) for value in range(10)],
        StubMetrics(),
        260.0,
        horizontal=False,
    )


def _wide_label_spectro():
    """A sweep that reaches five-figure frequencies.

    Its legend then has to hold ``13500.0 Hz``; the reported clipping was
    ``3000.0 Hz`` against a card hard-coded to 86 px of content.
    """
    times = np.linspace(0.0, 39.0, 40)
    freqs = np.linspace(0.0, 13500.0, 28)
    matrix = np.empty((times.size, freqs.size))
    for index, moment in enumerate(times):
        peak = 2000.0 + 250.0 * moment
        matrix[index] = 0.02 + 0.9 * np.exp(
            -((freqs - peak) ** 2) / (2 * 900.0**2)
        )
    return SimpleNamespace(
        x=times, y=freqs, matrix=matrix,
        x_name="time_s", y_name="frequency_hz", metadata={},
    )


def _wide_label_scene(qapp):
    return _open_scene(
        qapp, "fft_time", payload=_wide_label_spectro(),
        params=_slice_params("y", [13500.0, 12500.0, 11000.0, 10000.0]),
    )


def _page_right_limit(scene):
    """Scene x the page's content may reach: ``ci`` less its right margin."""
    ci = scene.widget.ci
    return (
        float(ci.sceneBoundingRect().right())
        - float(ci.layout.getContentsMargins()[2])
    )


def test_slice_legend_card_is_wide_enough_for_its_own_longest_label(qapp):
    """The frame has to cover the text, not crop it.

    ``_StatisticsCard`` hands ``content_width`` to
    ``QTextDocument.setTextWidth`` and builds its frame from the same number,
    but the legend rows carry ``white-space:nowrap``: too small a width does
    not wrap the label, it lays the document out wider than the frame and
    paints the overflow outside the card, where the page edge cuts it off.
    Stating this as ``idealWidth <= textWidth`` keeps it true for whatever
    font is installed — this machine has none.
    """
    scene = _wide_label_scene(qapp)
    try:
        assert "13500.0 Hz" in scene.slice_legend.toPlainText()
        document = scene.slice_legend._text.document()
        assert document.idealWidth() <= document.textWidth() + 0.5
    finally:
        scene.close()


def test_slice_legend_never_crosses_the_page_right_margin(qapp):
    """Positioning off the colorbar's left edge alone does not bound the card."""
    scene = _wide_label_scene(qapp)
    try:
        assert scene.slice_legend.sceneBoundingRect().right() <= (
            _page_right_limit(scene) + 0.5
        )
    finally:
        scene.close()


def test_wide_slice_legend_reserves_its_gutter_on_both_rows(qapp):
    """Widening the card must not cost the alignment F1 established.

    The right-hand reserve is ``max(colorbar chrome, legend + gap)`` and both
    rows take it, so the two plot areas keep the same edges. Clamping the card
    without paying for the reserve would instead have parked it on the data.
    """
    scene = _wide_label_scene(qapp)
    try:
        main = scene.plots[0].vb.sceneBoundingRect()
        slice_rect = scene.slice_plot.vb.sceneBoundingRect()
        assert slice_rect.left() == pytest.approx(main.left(), abs=1.0)
        assert slice_rect.right() == pytest.approx(main.right(), abs=1.0)
        assert scene.slice_legend.sceneBoundingRect().left() >= main.right() - 0.5
    finally:
        scene.close()


def test_slice_amplitude_axis_ends_on_whole_nice_steps(qapp):
    """D19/D19b: take only the step from ``_nice_per_div``, round each end out.

    ``_frame_to_nice`` would force exactly ``tick_density_y`` equal divisions
    on top of an already-rounded-up step and blow the axis out to ``[-100, 0]``
    for this data; the ends here have to hug the curve instead.
    """
    scene = build_batch_scene(
        ("fft_time", _sweep_spectro()),
        params=_slice_params(
            "time", [5.0, 15.0, 25.0],
            amplitude_mode="amplitude_db",
            db_reference_mode="manual",
            db_reference=1.0,
        ),
        context=_context(),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    scene.show_and_settle()
    qapp.processEvents()
    try:
        bottom, top = scene.slice_plot.vb.viewRange()[1]
        values = np.concatenate(
            [curve.getData()[1] for curve in scene.slice_curves]
        )
        bounds = batch_render_builder._slice_amp_bounds(values)
        expected = batch_render_builder._nice_amp_range(
            *bounds, scene.style.tick_density_y
        )
        assert (bottom, top) == pytest.approx(expected)
        step = (top - bottom) / scene.style.tick_density_y
        assert bottom / step == pytest.approx(round(bottom / step))
        assert top / step == pytest.approx(round(top / step))
        # At most one step of headroom at either end — the whole point of not
        # using ``_frame_to_nice``.
        assert float(np.min(values)) - bottom < step
        assert top - float(np.max(values)) < step
        ticks = scene.slice_plot.getAxis("left")._tickLevels[0]
        tick_values = [value for value, _label in ticks]
        assert tick_values
        assert min(tick_values) >= bottom - 1e-9
        assert max(tick_values) <= top + 1e-9
    finally:
        scene.close()


def test_slice_amplitude_axis_ignores_the_dc_dead_zone(qapp):
    """A 0 Hz bin floored to ≈ -6153 dB must not crush the real signal."""
    scene = build_batch_scene(
        ("fft_time", _sweep_spectro(dc_dead=True)),
        params=_slice_params(
            "time", [5.0, 15.0, 25.0],
            amplitude_mode="amplitude_db",
            db_reference_mode="manual",
            db_reference=1.0,
        ),
        context=_context(),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    scene.show_and_settle()
    qapp.processEvents()
    try:
        values = np.concatenate(
            [curve.getData()[1] for curve in scene.slice_curves]
        )
        # The dead bin is still in the curve data — only the view range skips it.
        assert float(np.min(values)) < -1000.0
        bottom, top = scene.slice_plot.vb.viewRange()[1]
        bounds = batch_render_builder._slice_amp_bounds(values)
        expected = batch_render_builder._nice_amp_range(
            *bounds, scene.style.tick_density_y
        )
        assert (bottom, top) == pytest.approx(expected)
    finally:
        scene.close()


def test_slice_manual_z_range_survives_verbatim(qapp):
    """D20: a hand-entered window is never widened onto nice steps."""
    scene = _open_scene(
        qapp, "fft_time",
        params=_slice_params(
            "time", [20.0], z_auto=False, z_floor=0.17, z_ceiling=0.53,
        ),
    )
    try:
        assert tuple(scene.slice_plot.vb.viewRange()[1]) == pytest.approx(
            (0.17, 0.53)
        )
        assert tuple(scene.heatmap_levels) == pytest.approx((0.17, 0.53))
    finally:
        scene.close()


def test_slice_position_out_of_range_is_clamped_and_warned(qapp):
    warnings_out = []
    scene = _open_scene(
        qapp, "fft_time",
        params=_slice_params("time", [20.0, 400.0]),
        warnings_out=warnings_out,
    )
    try:
        picks = scene.slice_plan.picks
        assert [pick.value for pick in picks] == pytest.approx([20.0, 40.0])
        assert [pick.clamped for pick in picks] == [False, True]
        assert len(scene.slice_curves) == 2
        assert len(warnings_out) == 1
        message = warnings_out[0]
        assert message.startswith("slice.position_clamped:")
        assert "400.000" in message and "40.000" in message
        assert "夹取" in scene.slice_legend.toPlainText()
    finally:
        scene.close()


def test_slice_clamp_warning_uses_finite_bounds_when_coordinates_contain_nan(qapp):
    payload = _spectro()
    payload.x = np.asarray([10.0, np.nan, 40.0])
    warnings_out = []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scene = _open_scene(
            qapp,
            "fft_time",
            payload=payload,
            params=_slice_params("time", [400.0]),
            warnings_out=warnings_out,
        )

    try:
        assert not any(item.category is RuntimeWarning for item in caught)
        assert len(warnings_out) == 1
        message = warnings_out[0]
        assert "[10.000, 40.000]" in message
        assert "nan" not in message.casefold()
    finally:
        scene.close()


def test_slice_positions_colliding_after_clamp_are_merged(qapp):
    """D13: two out-of-range requests land on one cell → one curve, one note."""
    warnings_out = []
    scene = _open_scene(
        qapp, "fft_time",
        params=_slice_params("time", [400.0, 500.0]),
        warnings_out=warnings_out,
    )
    try:
        assert len(scene.slice_plan.picks) == 1
        assert scene.slice_plan.merged == 1
        assert len(scene.slice_curves) == 1
        assert len(scene.slice_marker_lines) == 2
        assert "2 个位置夹取后合并为 1 个" in warnings_out[0]
    finally:
        scene.close()


def test_slice_legend_names_the_fixed_dimension_and_positions(qapp):
    scene = _open_scene(
        qapp, "fft_time", params=_slice_params("time", [10.0, 40.0]),
    )
    try:
        text = scene.slice_legend.toPlainText()
        assert "固定时间" in text
        assert "10.00 s" in text and "40.00 s" in text
        assert "夹取" not in text
    finally:
        scene.close()


def test_slice_legend_for_fixed_frequency_uses_hz(qapp):
    scene = _open_scene(qapp, "fft_time", params=_slice_params("y", [4.0]))
    try:
        text = scene.slice_legend.toPlainText()
        assert "固定频率" in text
        assert "4.0 Hz" in text
    finally:
        scene.close()


def test_order_time_slice_speaks_orders_never_hertz(qapp):
    payload = _spectro()
    payload.y_name = "order"
    scene = _open_scene(
        qapp, "order_time", payload=payload,
        params=_slice_params("y", [4.0]),
    )
    try:
        text = scene.slice_legend.toPlainText()
        assert "固定阶次" in text
        assert "4.00" in text
        assert "Hz" not in text
        assert "固定频率" not in text
        assert scene.slice_plot.getAxis("bottom").labelText == "Time (s)"
    finally:
        scene.close()


def test_order_time_fixed_order_slice_plots_against_order_axis(qapp):
    payload = _spectro()
    payload.y_name = "order"
    scene = _open_scene(
        qapp, "order_time", payload=payload,
        params=_slice_params("time", [20.0]),
    )
    try:
        assert scene.slice_plot.getAxis("bottom").labelText == "Order"
        texts = "\n".join(scene.texts())
        assert "Frequency (Hz)" not in texts
    finally:
        scene.close()


def test_slice_amplitude_axis_label_matches_the_colorbar(qapp):
    scene = _open_scene(
        qapp, "fft_time",
        params=_slice_params(
            "time", [20.0],
            amplitude_mode="amplitude_db",
            db_reference_mode="manual",
            db_reference=1.0,
        ),
    )
    try:
        assert (
            scene.slice_plot.getAxis("left").labelText
            == scene.colorbar.getAxis("left").labelText
        )
    finally:
        scene.close()
