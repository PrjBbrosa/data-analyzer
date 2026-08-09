from __future__ import annotations

import inspect
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter

from mf4_analyzer._palette import FILE_PALETTES
from mf4_analyzer.batch_image_options import BatchRenderOptions


def _qt_api():
    from mf4_analyzer.batch_render_qt import (
        BatchRenderContext,
        BatchSeries,
        BatchTimeFigureSpec,
        render_batch_image,
    )
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    return (
        BatchRenderContext,
        BatchSeries,
        BatchTimeFigureSpec,
        render_batch_image,
        build_batch_scene,
    )


def _context(**overrides):
    BatchRenderContext, *_ = _qt_api()
    values = {
        "source_display_name": "单帧振动.mf4",
        "group": "source group",
        "channel": 'accel["front"]',
        "unit": "g",
        "method": "time",
        "task_id": "T2-proof",
        "effective_facts": {
            "window": "Hann",
            "nfft_effective": 4096,
            "weighting": "A",
            "averaging": "linear",
            "overlap": 0.5,
            "actual_fs": 10_000,
            "members": "2/2",
        },
    }
    values.update(overrides)
    return BatchRenderContext(**values)


def _series(count=2, *, dual_y=False, panels=False):
    _, BatchSeries, *_ = _qt_api()
    x = np.linspace(0.0, 2.0, 401)
    items = []
    for index in range(count):
        unit = "rpm" if dual_y and index % 2 else "g"
        y = (index + 1) * np.sin(2 * np.pi * (index + 1) * x)
        items.append(
            BatchSeries(
                x=x,
                y=y,
                label=f"curve-{index + 1}",
                unit=unit,
                linestyle="--" if index % 2 else "-",
                panel=index if panels else 0,
            )
        )
    return tuple(items)


def _time_spec(*, count=2, dual_y=False, layout="overlay", titles=()):
    _, _, BatchTimeFigureSpec, *_ = _qt_api()
    return BatchTimeFigureSpec(
        series=_series(count, dual_y=dual_y, panels=layout == "subplot"),
        layout=layout,
        panel_titles=tuple(titles),
    )


def _open_scene(qapp, payload, *, params=None, context=None, options=None):
    *_, build_batch_scene = _qt_api()
    scene = build_batch_scene(
        payload,
        params=params,
        context=context or _context(),
        options=options or BatchRenderOptions(width_px=960, height_px=640),
    )
    scene.show_and_settle()
    qapp.processEvents()
    return scene


def _pen_signature(curve):
    pen = curve.opts["pen"]
    return pen.color().name(), pen.style(), pen.widthF()


def test_batch_qt_public_signature_and_default_line_width():
    *_, render_batch_image, _ = _qt_api()
    assert BatchRenderOptions().line_width == pytest.approx(1.5)
    assert list(inspect.signature(render_batch_image).parameters) == [
        "payload",
        "path",
        "params",
        "options",
        "context",
        "warnings_out",
    ]


def test_theme_contract_uses_timedomain_palette_and_precision_tokens():
    from mf4_analyzer.batch_render_qt._theme import THEMES, SERIES_COLORS

    assert SERIES_COLORS is FILE_PALETTES[0]
    assert THEMES["white"].background.name() == "#ffffff"
    assert THEMES["white"].axis == "#9ca3af"
    assert THEMES["white"].grid_alpha == pytest.approx(0.28)
    # Report pages are exported at 1920×1080 and up; the on-screen 9pt chart
    # scale is unreadable there, so the batch baseline runs larger.
    assert THEMES["white"].axis_font_pt == pytest.approx(12.0)
    assert THEMES["white"].panel_title_font_pt == pytest.approx(13.0)
    assert THEMES["white"].header_font_pt == pytest.approx(15.0)


def test_render_style_defaults_beat_the_pyqtgraph_adaptive_x_density(qapp):
    """The 1920px report page must not settle for a screen-width tick count."""
    from mf4_analyzer.batch_render_qt._builder import _axis_tick_text_records
    from mf4_analyzer.batch_render_style import RenderStyle

    scene = _open_scene(
        qapp,
        ("time", _time_spec(count=2)),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    try:
        assert scene.style == RenderStyle()
        x_labels = _axis_tick_text_records(scene.plots[0].getAxis("bottom"))
        assert len(x_labels) >= 11
    finally:
        scene.close()


def test_recipe_tick_density_and_font_scale_reach_the_axes(qapp):
    from mf4_analyzer.batch_render_qt._builder import _axis_tick_text_records

    sparse = _open_scene(
        qapp,
        ("time", _time_spec(count=2)),
        params={"tick_density_x": 4, "tick_density_y": 3, "font_scale": 0.8},
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    dense = _open_scene(
        qapp,
        ("time", _time_spec(count=2)),
        params={"tick_density_x": 24, "tick_density_y": 16, "font_scale": 1.5},
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    try:
        sparse_x = _axis_tick_text_records(sparse.plots[0].getAxis("bottom"))
        dense_x = _axis_tick_text_records(dense.plots[0].getAxis("bottom"))
        assert len(dense_x) > len(sparse_x)

        sparse_y = _axis_tick_text_records(sparse.plots[0].getAxis("left"))
        dense_y = _axis_tick_text_records(dense.plots[0].getAxis("left"))
        assert len(dense_y) > len(sparse_y)

        # font_scale multiplies every text size on the page, not just the ticks.
        assert dense.theme.axis_font_pt == pytest.approx(
            sparse.theme.axis_font_pt / 0.8 * 1.5
        )
        assert dense.theme.header_font_pt > sparse.theme.header_font_pt
        dense_tick_font = dense.plots[0].getAxis("bottom").style["tickFont"]
        sparse_tick_font = sparse.plots[0].getAxis("bottom").style["tickFont"]
        assert dense_tick_font.pointSizeF() > sparse_tick_font.pointSizeF()

        assert dense.adjacent_text_overlaps() == []
    finally:
        sparse.close()
        dense.close()


def test_manual_signed_x_range_is_kept_verbatim_with_ticks_inside(qapp):
    """A channel X range (rack travel ±) must not be widened to nice bounds."""
    from mf4_analyzer.batch_render_qt._builder import _axis_tick_text_records

    _, BatchSeries, BatchTimeFigureSpec, *_rest = _qt_api()
    x = np.linspace(-83.0, 83.0, 801)
    spec = BatchTimeFigureSpec(
        (BatchSeries(x, np.sin(x / 8.0), "rack", unit="N", x_unit="mm"),),
        x_source="channel",
        x_label="Weg (mm)",
    )
    scene = _open_scene(
        qapp,
        ("time", spec),
        params={"x_auto": False, "x_min": -100.0, "x_max": 100.0},
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    try:
        lo, hi = scene.plots[0].vb.viewRange()[0]
        assert (lo, hi) == pytest.approx((-100.0, 100.0))
        values = [
            float(text)
            for _rect, text in _axis_tick_text_records(
                scene.plots[0].getAxis("bottom")
            )
        ]
        assert values
        assert min(values) >= -100.0
        assert max(values) <= 100.0
        assert any(value < 0.0 for value in values)
    finally:
        scene.close()


def _residue_only(value: float, x: np.ndarray) -> np.ndarray:
    """A channel that is ``value`` everywhere, to within float64 rounding.

    Built the way the Inspector's channel maths builds one (``3a - 2a - a`` is
    algebraically zero but each product rounds independently) rather than by
    perturbing bits by hand, so the residue is the real thing.
    """
    ramp = value + np.sin(x) * value * 1e-3
    signal = value + (ramp * 3.0 - ramp * 2.0 - ramp)
    assert signal.min() < signal.max(), "precondition: the residue is a real span"
    assert signal.max() - signal.min() < abs(value) * 1e-12, (
        "precondition: and it is only residue"
    )
    return signal


def test_residue_only_channel_exports_a_y_axis_that_still_carries_numbers(qapp):
    """Reported 2026-08-09: a computed channel exported with a BARE Y axis.

    A channel produced by two-channel maths is constant in intent but not
    bit-exact, so pyqtgraph's auto-range — whose degeneracy test is exact
    equality — framed Y onto ~1e-13 of float64 residue. ``_fit_axis_ticks``
    then derived a ~1e-14 per-division step and ``_fmt_tick`` faithfully
    printed 16 significant digits, so the labels measured 136 px against the
    25 px the axis realized. ``AxisItem.generateDrawSpecs`` DROPS a label that
    does not fit rather than clipping it, which is why this shipped as a
    silently broken artifact instead of an ugly one: the report PNG went out
    with a Y axis carrying no numbers at all.

    Hence the three assertions, in the order they failed: the axis is wide
    enough for what it is carrying (so nothing gets dropped), there is more
    than one label left, and the labels are engineering-length. The ordinary
    control is here so the test still says something if the residue case ever
    regresses all the way to "no ticks at all" — that state would otherwise
    satisfy a width bound trivially.
    """
    from mf4_analyzer.ui_kit.axis_metrics import (
        axis_tick_texts,
        left_axis_width_for_ticks,
    )

    _, BatchSeries, BatchTimeFigureSpec, *_rest = _qt_api()
    x = np.linspace(0.0, 2.0, 4001)

    def _left_axis_facts(y):
        spec = BatchTimeFigureSpec(
            (BatchSeries(x, y, "mActiveReturnMotorTorq_calc", unit="Nm"),),
        )
        scene = _open_scene(
            qapp,
            ("time", spec),
            context=_context(channel="mActiveReturnMotorTorq_calc", unit="Nm"),
        )
        try:
            axis = scene.plots[0].getAxis("left")
            return (
                axis_tick_texts(axis),
                left_axis_width_for_ticks(axis),
                float(axis.width()),
                tuple(float(v) for v in scene.plots[0].vb.viewRange()[1]),
            )
        finally:
            scene.close()

    residue_ticks, residue_needs, residue_has, residue_y = _left_axis_facts(
        _residue_only(35.0, x)
    )
    normal_ticks, normal_needs, normal_has, _normal_y = _left_axis_facts(
        35.0 + np.sin(x) * 0.7
    )

    # Control: the ordinary channel is unaffected, so a failure below is about
    # the residue case and not about the harness or the axis metrics.
    assert len(normal_ticks) >= 2, normal_ticks
    assert normal_needs <= normal_has + 0.5, (
        f"control channel already overflows: {normal_needs:.1f}px of "
        f"{normal_ticks!r} into a {normal_has:.1f}px axis"
    )

    assert residue_needs <= residue_has + 0.5, (
        f"residue channel needs {residue_needs:.1f}px for {residue_ticks!r} but "
        f"the axis realized {residue_has:.1f}px — generateDrawSpecs drops every "
        f"label that does not fit, so this exports a bare Y axis"
    )
    assert len(residue_ticks) >= 2, (
        f"only {residue_ticks!r} survived on Y=[{residue_y[0]!r}, "
        f"{residue_y[1]!r}]"
    )
    assert max(len(text) for text in residue_ticks) <= 8, residue_ticks
    assert residue_y[0] < 35.0 < residue_y[1], residue_y
    assert residue_y[1] - residue_y[0] > 1.0, (
        f"Y is still framed on the float residue: {residue_y!r}"
    )


def test_manual_y_range_survives_a_residue_only_channel_verbatim(qapp):
    """The bound on the fix above: it may only touch AUTO-ranged Y.

    ``_widen_residue_only_auto_y`` skips any view whose Y auto-range is
    already disabled, which is precisely the population — manual ``y_min`` /
    ``y_max``, ``settle_primary`` / ``settle_nice``, the FRF and slice rows —
    whose bounds the report contract promises verbatim. Without that skip the
    same collapse would silently widen a manually entered range, which is the
    contract ``nice_ticks_within`` exists to keep.
    """
    _, BatchSeries, BatchTimeFigureSpec, *_rest = _qt_api()
    x = np.linspace(0.0, 2.0, 4001)
    spec = BatchTimeFigureSpec(
        (BatchSeries(x, _residue_only(35.0, x), "calc", unit="Nm"),),
    )
    scene = _open_scene(
        qapp,
        ("time", spec),
        params={"y_auto": False, "y_min": 34.0, "y_max": 36.0},
    )
    try:
        lo, hi = scene.plots[0].vb.viewRange()[1]
        assert (lo, hi) == pytest.approx((34.0, 36.0))
    finally:
        scene.close()


def test_time_overlay_uses_one_palette_across_dual_y_and_distinct_styles(qapp):
    scene = _open_scene(qapp, ("time", _time_spec(count=4, dual_y=True)))
    try:
        signatures = [_pen_signature(curve) for curve in scene.curves]
        assert [item[0] for item in signatures] == [
            QColor(color).name() for color in FILE_PALETTES[0][:4]
        ]
        assert len({(color, style) for color, style, _width in signatures}) == 4
        assert [style for _color, style, _width in signatures] == [
            Qt.SolidLine,
            Qt.DashLine,
            Qt.SolidLine,
            Qt.DashLine,
        ]
        assert all(width == pytest.approx(1.5) for *_rest, width in signatures)
        assert len(scene.auxiliary_views) == 1
        assert len(scene.legend.items) == 4
    finally:
        scene.close()


def test_time_overlay_duplicate_labels_still_get_distinct_visual_signatures(qapp):
    _, BatchSeries, BatchTimeFigureSpec, *_ = _qt_api()
    x = np.linspace(0.0, 1.0, 101)
    spec = BatchTimeFigureSpec(
        (
            BatchSeries(x, np.sin(x), "same-name", unit="g"),
            BatchSeries(x, np.cos(x), "same-name", unit="rpm"),
        )
    )
    scene = _open_scene(qapp, ("time", spec))
    try:
        signatures = [
            (color, style)
            for color, style, _width in map(_pen_signature, scene.curves)
        ]
        assert len(signatures) == len(set(signatures)) == 2
    finally:
        scene.close()


def test_time_statistics_card_and_diagnostic_are_part_of_the_export_scene(qapp):
    from mf4_analyzer.batch_statistics import (
        BatchChartDiagnostic,
        BatchStatisticRow,
    )
    from mf4_analyzer.batch_render_qt._builder import _StatisticsCard

    _, BatchSeries, BatchTimeFigureSpec, *_ = _qt_api()
    x = np.array([0.0, 1.0, 2.0])
    series = BatchSeries(
        x, np.array([1.0, 3.0, 2.0]), "rack", unit="N", series_key="rack",
    )
    row = BatchStatisticRow(
        series_key="rack", family_key="rack", label="rack", variant="value",
        panel=0, branch_label="全程", direction="", sample_count=3,
        x_min=0.0, x_max=2.0, minimum=1.0, maximum=3.0, mean=2.0,
        argmin_x=0.0, argmax_x=1.0,
    )
    normal = _open_scene(
        qapp, ("time", BatchTimeFigureSpec((series,), statistics=(row,))),
        params={"chart_statistics": {"metrics": ["max", "min"]}},
    )
    diagnostic = _open_scene(
        qapp,
        ("time", BatchTimeFigureSpec(
            (series,), diagnostics=(BatchChartDiagnostic(
                code="chart_statistics.multiple_x_reversals",
                message="too many reversals", suggestion="split data",
            ),),
        )),
    )
    try:
        assert any("图内统计" in text for text in normal.texts())
        assert any("N=3" in text for text in normal.texts())
        markers = [
            item for item in normal.plots[0].vb.addedItems
            if isinstance(item, pg.ScatterPlotItem)
        ]
        assert len(markers) == 2
        assert {marker.opts["symbol"] for marker in markers} == {"o"}
        # Solid red/green dot with a white keyline. The size is small because
        # the export now compensates for the supersampling downscale instead of
        # the builder over-drawing to survive it; the rendered proof lives in
        # tests/ui/test_batch_chart_statistics.py.
        assert {marker.opts["brush"].color().name() for marker in markers} == {
            "#dc2626", "#16a34a",
        }
        assert {marker.opts["pen"].color().name() for marker in markers} == {
            "#ffffff",
        }
        assert all(marker.opts["size"] >= 11 for marker in markers)
        cards = [
            item for item in normal.panel_text_items[0]
            if isinstance(item, _StatisticsCard)
        ]
        assert len(cards) == 1
        assert cards[0].body_font_pt == pytest.approx(
            normal.theme.axis_font_pt * 0.84
        )
        scaled = _open_scene(
            qapp, ("time", BatchTimeFigureSpec((series,), statistics=(row,))),
            params={"chart_statistics": {"metrics": ["max", "min"]}, "font_scale": 1.5},
        )
        try:
            scaled_card = next(
                item for item in scaled.panel_text_items[0]
                if isinstance(item, _StatisticsCard)
            )
            assert scaled_card.body_font_pt > cards[0].body_font_pt
        finally:
            scaled.close()
        assert len(normal.curves) == 1
        assert any("ERROR" in text for text in diagnostic.texts())
        assert not any("路径　最大值" in text for text in diagnostic.texts())
    finally:
        normal.close()
        diagnostic.close()


def test_time_statistics_card_title_states_the_range_mode_not_only_the_actual_span(qapp):
    """Auto and custom cards must not read identically (design D-D1).

    Before this fix the title only ever showed the *actual* clipped span, so
    a ±80 mm custom request that silently fell back to full-range rendered a
    card indistinguishable from an honest auto/full-range one — exactly the
    ambiguity that let a bad statistic ship unnoticed.
    """
    from mf4_analyzer.batch_statistics import BatchStatisticRow

    _, BatchSeries, BatchTimeFigureSpec, *_ = _qt_api()
    x = np.array([0.0, 1.0, 2.0])
    series = BatchSeries(
        x, np.array([1.0, 3.0, 2.0]), "rack", unit="mm", series_key="rack",
    )
    row = BatchStatisticRow(
        series_key="rack", family_key="rack", label="rack", variant="value",
        panel=0, branch_label="全程", direction="", sample_count=3,
        x_min=-79.97, x_max=79.97, minimum=1.0, maximum=3.0, mean=2.0,
        argmin_x=0.0, argmax_x=1.0,
    )
    auto_scene = _open_scene(
        qapp, ("time", BatchTimeFigureSpec((series,), statistics=(row,))),
        params={
            "chart_statistics": {"metrics": ["max", "min"], "range_mode": "full"},
        },
    )
    custom_scene = _open_scene(
        qapp, ("time", BatchTimeFigureSpec((series,), statistics=(row,))),
        params={
            "chart_statistics": {
                "metrics": ["max", "min"], "range_mode": "custom",
                "x_min": -80.0, "x_max": 80.0,
            },
        },
    )
    try:
        auto_text = " ".join(auto_scene.texts())
        custom_text = " ".join(custom_scene.texts())
        assert "全时段" in auto_text
        assert "实际" in auto_text and "-79.97" in auto_text and "79.97" in auto_text
        assert "设定" in custom_text
        assert "-80" in custom_text and "80" in custom_text
        assert "实际" in custom_text and "-79.97" in custom_text and "79.97" in custom_text
        assert auto_text != custom_text
    finally:
        auto_scene.close()
        custom_scene.close()


def test_time_overlay_rejects_more_than_two_y_units(qapp):
    _, BatchSeries, BatchTimeFigureSpec, *_ = _qt_api()
    x = np.arange(3.0)
    spec = BatchTimeFigureSpec(
        tuple(
            BatchSeries(x, x + index, f"s{index}", unit=unit)
            for index, unit in enumerate(("g", "rpm", "V"))
        )
    )
    with pytest.raises(ValueError, match="supports at most two y units"):
        _open_scene(qapp, ("time", spec))


def test_time_raw_filtered_dataframe_linestyle_contract(qapp):
    frame = pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 0.0, 1.0],
            "series": ["original", "original", "filtered", "filtered"],
            "value": [0.0, 1.0, 0.1, 0.9],
        }
    )
    scene = _open_scene(qapp, ("time", frame))
    try:
        assert [_pen_signature(curve)[1] for curve in scene.curves] == [
            Qt.SolidLine,
            Qt.DashLine,
        ]
        assert [_pen_signature(curve)[0] for curve in scene.curves] == [
            FILE_PALETTES[0][0],
            FILE_PALETTES[0][0],
        ]
        assert len(
            {
                (_pen_signature(curve)[0], _pen_signature(curve)[1])
                for curve in scene.curves
            }
        ) == 2
    finally:
        scene.close()


def test_fft_color_db_and_manual_ranges(qapp):
    frame = pd.DataFrame(
        {
            "frequency_hz": [0.0, 100.0, 200.0],
            "amplitude": [1.0, 0.1, 0.01],
        }
    )
    scene = _open_scene(
        qapp,
        ("fft", frame),
        params={
            "amplitude_mode": "amplitude_db",
            "db_reference_mode": "manual",
            "db_reference": 1.0,
            "x_auto": False,
            "x_min": 25.0,
            "x_max": 175.0,
            "y_auto": False,
            "y_min": -45.0,
            "y_max": 5.0,
        },
        context=_context(method="fft", unit="g"),
    )
    try:
        x, y = scene.curves[0].getData()
        assert x.tolist() == [0.0, 100.0, 200.0]
        assert y.tolist() == pytest.approx([0.0, -20.0, -40.0])
        assert _pen_signature(scene.curves[0])[0] == "#1769e0"
        assert scene.legend is not None
        assert len(scene.legend.items) == 1
        assert scene.plots[0].vb.viewRange()[0] == pytest.approx([25.0, 175.0])
        assert scene.plots[0].vb.viewRange()[1] == pytest.approx([-45.0, 5.0])
        assert scene.plots[0].getAxis("left").labelText in (
            scene.page_labels[2].item.toPlainText()
        )
    finally:
        scene.close()


def test_report_page_facts_footer_legend_and_no_raw_identity_leak(qapp):
    raw_group_key = '["/private/raw/source.mf4","accel"]'
    raw_source = "/private/raw/source.mf4"
    context = _context(
        source_display_name="source.mf4",
        group="human group",
        channel='accel["front"]',
    )
    scene = _open_scene(
        qapp,
        ("time", _time_spec()),
        params={"group_key": raw_group_key, "source_identity": raw_source},
        context=context,
    )
    try:
        texts = "\n".join(scene.texts())
        assert "source.mf4 · human group" in texts
        # The analysis row carries the channel alone — the method name is
        # already implied by the axes, so it is not printed.
        assert scene.page_labels[1].item.toPlainText() == 'accel["front"]'
        assert "window=Hann" in texts
        assert "NFFT=4096" in texts
        assert "weighting=A" in texts
        assert "averaging=linear" in texts
        assert "overlap=50%" in texts
        assert "members=2/2" in texts
        assert "TraceLab batch export" in texts
        assert "T2-proof" not in texts
        assert "Task" not in texts
        assert raw_group_key not in texts
        assert raw_source not in texts
        assert '["front"]' in texts
    finally:
        scene.close()


@pytest.mark.parametrize("raw_group", ["default", "Default", "  default  "])
def test_report_header_drops_the_noisy_default_group(qapp, raw_group):
    context = _context(source_display_name="source.mf4", group=raw_group)
    scene = _open_scene(qapp, ("time", _time_spec()), context=context)
    try:
        identity_text = scene.page_labels[0].item.toPlainText()
        assert identity_text == "source.mf4"
        assert "default" not in identity_text.lower()
    finally:
        scene.close()


def test_report_header_keeps_a_real_group_label(qapp):
    context = _context(source_display_name="source.mf4", group="cycle-A")
    scene = _open_scene(qapp, ("time", _time_spec()), context=context)
    try:
        identity_text = scene.page_labels[0].item.toPlainText()
        assert identity_text == "source.mf4 · cycle-A"
    finally:
        scene.close()


def test_grouped_header_drops_the_bare_method_row(qapp):
    """按通道/按信号源分组时 context 没有单一通道，第二行曾退化成一个孤零零的
    小写 ``time`` 挂在标题下面（用户反馈：不知道那是什么）。现在整行不画。"""
    context = _context(
        source_display_name="Fzyl 1 [E3]",
        group="",
        channel="",
        effective_facts={},
    )
    scene = _open_scene(qapp, ("time", _time_spec()), params={}, context=context)
    try:
        header_labels = scene.page_labels[:-1]
        assert len(header_labels) == 1
        assert header_labels[0].item.toPlainText() == "Fzyl 1 [E3]"
        assert not any(
            label.item.toPlainText().strip() == "time"
            for label in scene.page_labels
        )
    finally:
        scene.close()


def test_report_header_skips_the_facts_row_when_there_are_no_facts(qapp):
    context = _context(
        source_display_name="source.mf4", group="default", effective_facts={}
    )
    scene = _open_scene(qapp, ("time", _time_spec()), params={}, context=context)
    try:
        # Only identity + analysis rows: no blank facts label sits between
        # the header and the first plot.
        header_labels = scene.page_labels[:-1]
        assert len(header_labels) == 2
        texts = "\n".join(scene.texts())
        assert "window=" not in texts
        assert "NFFT=" not in texts
    finally:
        scene.close()


def test_every_plot_has_no_native_chrome_and_curves_are_aliased(qapp):
    scene = _open_scene(
        qapp,
        ("time", _time_spec(count=8, layout="subplot", titles=range(8))),
    )
    try:
        assert len(scene.plots) == 8
        # Antialiasing belongs to the exporter's supersampling pass, not to
        # the curves; see mf4_analyzer/batch_render_qt/_export.py.
        assert all(curve.opts.get("antialias") is False for curve in scene.curves)
        for plot in scene.plots:
            auto_button = getattr(plot, "autoBtn", None)
            assert auto_button is None or not auto_button.isVisible()
            assert plot.menuEnabled() is False
            assert plot.vb.state["mouseEnabled"] == [False, False]
        widget = scene.widget
        assert widget.frameShape() == widget.NoFrame
        assert widget.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert widget.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert widget.focusPolicy() == Qt.NoFocus
        forbidden = ("时域", "FFT vs Time", "阶次")
        assert not any(token in "\n".join(scene.texts()) for token in forbidden)
    finally:
        scene.close()


def test_eight_subplot_text_geometry_and_shared_x_contract(qapp):
    titles = tuple(f"Channel {index + 1}" for index in range(8))
    scene = _open_scene(
        qapp,
        ("time", _time_spec(count=8, layout="subplot", titles=titles)),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
    )
    try:
        assert scene.panel_titles == titles
        assert [plot.getAxis("bottom").labelText for plot in scene.plots[:-1]] == [
            ""
        ] * 7
        assert scene.plots[-1].getAxis("bottom").labelText == "Time (s)"
        x_ranges = [plot.vb.viewRange()[0] for plot in scene.plots]
        assert all(value == pytest.approx(x_ranges[0]) for value in x_ranges[1:])
        assert scene.adjacent_text_overlaps() == []
        assert scene.plot_ink_pixel_count() > 2_000
    finally:
        scene.close()


def test_subplot_export_draws_before_writing_dpi_metadata_and_contains_ticks(
    qapp, tmp_path, monkeypatch
):
    _, BatchSeries, BatchTimeFigureSpec, *_rest, build_batch_scene = _qt_api()
    from mf4_analyzer.batch_render_qt import _export as qt_export
    from mf4_analyzer.batch_render_qt._builder import _axis_tick_text_records
    from mf4_analyzer.batch_render_qt._export import render_scene_image

    # Render 1:1 so the widget.render() reference below stays a valid
    # comparison. That pins two things at once: the exporter still draws
    # before it stamps DPI, and QGraphicsScene.render() at 1:1 is
    # byte-identical to the widget.render() primitive it replaced.
    monkeypatch.setattr(qt_export, "supersample_factor", lambda width, height: 1)

    x = np.linspace(7.0, 128.0, 401)
    spec = BatchTimeFigureSpec(
        (
            BatchSeries(x, np.full(x.size, 0.25), "small", panel=0),
            BatchSeries(x, np.full(x.size, 3276.95), "large", panel=1),
        ),
        layout="subplot",
        panel_titles=("small", "large"),
    )
    scene = build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
        context=_context(channel="flat magnitudes", unit=""),
    )
    reference_scene = build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
        context=_context(channel="flat magnitudes", unit=""),
    )
    try:
        image = render_scene_image(scene)
        reference_scene.show_and_settle()
        for plot in reference_scene.plots:
            for side in ("left", "right", "bottom", "top"):
                plot.getAxis(side).picture = None
        reference = QImage(1920, 1080, QImage.Format_ARGB32_Premultiplied)
        reference.fill(reference_scene.theme.background)
        painter = QPainter(reference)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        reference_scene.widget.render(painter)
        painter.end()

        assert image == reference
        expected_dpm = round(144 / 0.0254)
        assert image.dotsPerMeterX() == expected_dpm
        assert image.dotsPerMeterY() == expected_dpm
        target = tmp_path / "flat-subplot-dpi-safe.png"
        assert image.save(str(target), "PNG")
        reloaded = QImage(str(target))
        assert reloaded.dotsPerMeterX() == expected_dpm
        assert reloaded.dotsPerMeterY() == expected_dpm

        panel_tick_texts = []
        for plot in scene.plots:
            panel_rect = plot.sceneBoundingRect()
            records = _axis_tick_text_records(plot.getAxis("left"))
            assert records
            assert all(panel_rect.contains(rect) for rect, _text in records)
            panel_tick_texts.append([text for _rect, text in records])
        assert all(abs(float(text)) < 10.0 for text in panel_tick_texts[0])
        assert all(float(text) > 3000.0 for text in panel_tick_texts[1])
        assert scene.adjacent_text_overlaps() == []
    finally:
        scene.close()
        reference_scene.close()


@pytest.mark.parametrize(
    ("group_by", "titles"),
    [
        ("source", ("accel", "speed")),
        ("channel", ("run-a.mf4", "run-b.mf4")),
    ],
)
def test_subplot_panel_title_semantics_are_uniform(qapp, group_by, titles):
    scene = _open_scene(
        qapp,
        ("time", _time_spec(count=2, layout="subplot", titles=titles)),
        params={"render_group_by": group_by},
    )
    try:
        assert scene.panel_titles == titles
        assert all(title in scene.texts() for title in titles)
    finally:
        scene.close()


def test_subplot_titles_preserve_each_panel_amplitude_unit(qapp):
    scene = _open_scene(
        qapp,
        (
            "time",
            _time_spec(
                count=2,
                dual_y=True,
                layout="subplot",
                titles=("acceleration", "speed"),
            ),
        ),
    )
    try:
        assert [plot.getAxis("left").labelText for plot in scene.plots] == [
            "Amplitude (g)", "Amplitude (rpm)",
        ]
    finally:
        scene.close()


def test_save_png_rejects_null_qimage_without_creating_target(tmp_path):
    from mf4_analyzer.batch_render_qt._export import save_png

    target = tmp_path / "null.png"
    with pytest.raises(RuntimeError, match="null QImage"):
        save_png(QImage(), target)

    assert not target.exists()


@pytest.mark.parametrize(
    ("background", "expected"),
    [
        ("white", QColor(255, 255, 255, 255)),
        ("transparent", QColor(0, 0, 0, 0)),
        ("dark", QColor("#101418")),
    ],
)
def test_png_exact_pixels_dpi_metadata_theme_and_no_corner_chrome(
    qapp, tmp_path, background, expected
):
    *_, render_batch_image, _ = _qt_api()
    target = tmp_path / f"{background}.png"
    options = BatchRenderOptions(
        width_px=640,
        height_px=360,
        dpi=144,
        background=background,
    )
    render_batch_image(
        ("time", _time_spec(count=1)),
        target,
        options=options,
        context=_context(),
    )
    image = QImage(str(target))
    assert (image.width(), image.height()) == (640, 360)
    assert image.dotsPerMeterX() == round(144 / 0.0254)
    assert image.text("Title") == "单帧振动.mf4 · accel[\"front\"] · time"
    assert image.text("Creator") == "TraceLab batch renderer"
    for x, y in ((1, 1), (638, 1), (1, 358), (638, 358)):
        assert image.pixelColor(x, y) == expected


def test_cjk_font_support_and_header_ink_proof(qapp):
    from mf4_analyzer.batch_render_qt._fonts import (
        CJK_CONTRACT_TEXT,
        header_ink_proof,
        resolve_cjk_font,
        supports_contract_text,
    )

    font = resolve_cjk_font()
    if font is None:
        pytest.skip("environment has no CJK-capable Qt font")
    assert supports_contract_text(font, CJK_CONTRACT_TEXT)
    proof = header_ink_proof(font, CJK_CONTRACT_TEXT)
    assert proof["pass"] is True
    assert proof["ink_pixels"] > proof["empty_ink_pixels"] + 120


def test_render_on_gui_thread_marshals_result_and_exception(qapp):
    from mf4_analyzer.batch_render_qt._dispatch import render_on_gui_thread

    observed = {}

    def worker():
        observed["result"] = render_on_gui_thread(
            lambda: (threading.get_ident(), "ok")
        )
        try:
            render_on_gui_thread(lambda: (_ for _ in ()).throw(ValueError("boom")))
        except BaseException as exc:
            observed["exception"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    while thread.is_alive():
        qapp.processEvents()
        thread.join(0.01)
    assert observed["result"][1] == "ok"
    assert observed["result"][0] == threading.get_ident()
    assert isinstance(observed["exception"], ValueError)
    assert str(observed["exception"]) == "boom"
    assert "rendered on Qt GUI thread" in "\n".join(
        getattr(observed["exception"], "__notes__", [])
    )


def test_worker_render_preserves_warnings_out_on_gui_thread(
    qapp, monkeypatch, tmp_path
):
    import mf4_analyzer.batch_render_qt as qt_render

    original_builder = qt_render.build_batch_scene
    warnings = []
    observed = {}

    def warning_builder(*args, warnings_out=None, **kwargs):
        assert threading.get_ident() == threading.main_thread().ident
        warnings_out.append("render warning")
        return original_builder(*args, warnings_out=warnings_out, **kwargs)

    monkeypatch.setattr(qt_render, "build_batch_scene", warning_builder)

    def worker():
        try:
            observed["path"] = qt_render.render_batch_image(
                ("time", _time_spec(count=1)),
                tmp_path / "worker-warning.png",
                options=BatchRenderOptions(width_px=640, height_px=360),
                context=_context(),
                warnings_out=warnings,
            )
        except BaseException as exc:
            observed["exception"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    while thread.is_alive():
        qapp.processEvents()
        thread.join(0.01)

    assert "exception" not in observed
    assert observed["path"].is_file()
    assert warnings == ["render warning"]


def test_worker_render_paints_on_gui_thread_and_encodes_on_caller_thread(
    qapp, monkeypatch, tmp_path
):
    import mf4_analyzer.batch_render_qt as qt_render

    original_builder = qt_render.build_batch_scene
    original_render = qt_render.render_scene_image
    original_save = qt_render.save_png
    observed = {}

    def tracked_builder(*args, **kwargs):
        observed["build_thread"] = threading.get_ident()
        return original_builder(*args, **kwargs)

    def tracked_render(*args, **kwargs):
        observed["paint_thread"] = threading.get_ident()
        return original_render(*args, **kwargs)

    def tracked_save(image, path):
        observed["save_thread"] = threading.get_ident()
        observed["image_size"] = (image.width(), image.height())
        return original_save(image, path)

    monkeypatch.setattr(qt_render, "build_batch_scene", tracked_builder)
    monkeypatch.setattr(qt_render, "render_scene_image", tracked_render)
    monkeypatch.setattr(qt_render, "save_png", tracked_save)

    def worker():
        observed["caller_thread"] = threading.get_ident()
        try:
            observed["path"] = qt_render.render_batch_image(
                ("time", _time_spec(count=1)),
                tmp_path / "worker-thread-split.png",
                options=BatchRenderOptions(width_px=640, height_px=360),
                context=_context(),
            )
        except BaseException as exc:
            observed["exception"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    while thread.is_alive():
        qapp.processEvents()
        thread.join(0.01)

    assert "exception" not in observed
    assert observed["build_thread"] == threading.main_thread().ident
    assert observed["paint_thread"] == threading.main_thread().ident
    assert observed["save_thread"] == observed["caller_thread"]
    assert observed["save_thread"] != threading.main_thread().ident
    assert observed["image_size"] == (640, 360)
    assert observed["path"].is_file()


def test_gui_render_paints_and_encodes_on_gui_thread(qapp, monkeypatch, tmp_path):
    import mf4_analyzer.batch_render_qt as qt_render

    original_builder = qt_render.build_batch_scene
    original_render = qt_render.render_scene_image
    original_save = qt_render.save_png
    observed = {}

    def tracked_builder(*args, **kwargs):
        observed["build_thread"] = threading.get_ident()
        return original_builder(*args, **kwargs)

    def tracked_render(*args, **kwargs):
        observed["paint_thread"] = threading.get_ident()
        return original_render(*args, **kwargs)

    def tracked_save(image, path):
        observed["save_thread"] = threading.get_ident()
        return original_save(image, path)

    monkeypatch.setattr(qt_render, "build_batch_scene", tracked_builder)
    monkeypatch.setattr(qt_render, "render_scene_image", tracked_render)
    monkeypatch.setattr(qt_render, "save_png", tracked_save)

    target = qt_render.render_batch_image(
        ("time", _time_spec(count=1)),
        tmp_path / "gui-thread.png",
        options=BatchRenderOptions(width_px=640, height_px=360),
        context=_context(),
    )

    assert target.is_file()
    assert observed == {
        "build_thread": threading.main_thread().ident,
        "paint_thread": threading.main_thread().ident,
        "save_thread": threading.main_thread().ident,
    }


def test_worker_png_encode_failure_is_raised_unchanged_on_caller_thread(
    qapp, monkeypatch, tmp_path
):
    import mf4_analyzer.batch_render_qt as qt_render

    marker = RuntimeError("png-encode-marker")
    observed = {}

    def fail_save(_image, _path):
        observed["save_thread"] = threading.get_ident()
        raise marker

    monkeypatch.setattr(qt_render, "save_png", fail_save)

    def worker():
        observed["caller_thread"] = threading.get_ident()
        try:
            qt_render.render_batch_image(
                ("time", _time_spec(count=1)),
                tmp_path / "encode-failure.png",
                options=BatchRenderOptions(width_px=640, height_px=360),
                context=_context(),
            )
        except BaseException as exc:
            observed["exception"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    while thread.is_alive():
        qapp.processEvents()
        thread.join(0.01)

    assert observed["save_thread"] == observed["caller_thread"]
    assert observed["exception"] is marker
    assert not getattr(marker, "__notes__", [])
    assert not (tmp_path / "encode-failure.png").exists()


def test_non_main_thread_without_app_fails_clearly_in_subprocess(tmp_path):
    script = tmp_path / "no_app_worker.py"
    script.write_text(
        """
import threading
from mf4_analyzer.batch_render_qt._dispatch import ensure_app
result = []
def run():
    try:
        ensure_app()
    except BaseException as exc:
        result.append(type(exc).__name__ + ':' + str(exc))
t = threading.Thread(target=run); t.start(); t.join()
print(result[0])
""".strip(),
        encoding="utf-8",
    )
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.update(
        TMPDIR="/tmp",
        QT_QPA_PLATFORM="offscreen",
        MPLCONFIGDIR="/tmp",
        PYTHONPATH=str(Path.cwd()),
    )
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "RuntimeError" in completed.stdout
    assert "non-main thread" in completed.stdout


def test_existing_qcore_application_fails_clearly_in_subprocess(tmp_path):
    script = tmp_path / "qcore_only.py"
    script.write_text(
        """
from PyQt5.QtCore import QCoreApplication
from mf4_analyzer.batch_render_qt._dispatch import ensure_app
app = QCoreApplication([])
try:
    ensure_app()
except BaseException as exc:
    print(type(exc).__name__ + ':' + str(exc))
""".strip(),
        encoding="utf-8",
    )
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.update(TMPDIR="/tmp", QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(Path.cwd()))
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "RuntimeError" in completed.stdout
    assert "QCoreApplication cannot host QWidget rendering" in completed.stdout


def test_application_exiting_state_rejects_render_in_subprocess(tmp_path):
    script = tmp_path / "app_exiting.py"
    script.write_text(
        """
from mf4_analyzer.batch_render_qt._dispatch import (
    _dispatcher_for,
    ensure_app,
    render_on_gui_thread,
)
app = ensure_app()
_dispatcher_for(app)._mark_quitting()
try:
    render_on_gui_thread(lambda: "should not run")
except BaseException as exc:
    print(type(exc).__name__ + ':' + str(exc))
""".strip(),
        encoding="utf-8",
    )
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.update(TMPDIR="/tmp", QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(Path.cwd()))
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "RuntimeError" in completed.stdout
    assert "application is exiting" in completed.stdout
