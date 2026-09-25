"""FRF live cursor layout: structured metrics, reversible modes, painted geometry."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import QRect

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.cursor_display import (
    build_frf_cursor_presentation,
    render_cursor_presentation,
)
from mf4_analyzer.ui.chart_stack.cursor_table_layout import TableLayoutPlan
from mf4_analyzer.ui.chart_stack.pinning.presentation import PinPanelProjector
from mf4_analyzer.ui.cursor_display_model import (
    FrfCursorPoint,
    FrfCursorSample,
    PinnedCursorSample,
)
from mf4_analyzer.ui.pinned_cursor_state import PinnedCursorIntent


@pytest.fixture
def production_style(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


def _result(*, magnitude_nan=False):
    transfer = np.array([1 + 0j, 2 + 0j, 4 + 0j])
    coherence = np.array([1.0, 0.95, 0.5])
    if magnitude_nan:
        transfer = np.array([1 + 0j, np.nan + 1j * np.nan, 4 + 0j])
        coherence = np.array([1.0, np.nan, 0.5])
    return SimpleNamespace(
        frequencies=np.array([1.0, 10.0, 100.0]),
        transfer=transfer,
        coherence=coherence,
        effective=SimpleNamespace(fs=1000.0, df=1.0, segments=4),
        warnings=(),
    )


def _arm(qtbot, qapp, *, width, height, result=None, params=None):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(width, height)
    cs.show()
    qapp.processEvents()
    qtbot.waitExposed(cs)
    cs.set_mode("frf")
    qapp.processEvents()
    canvas = cs.canvas_frf
    canvas.set_result(
        result if result is not None else _result(),
        params or {"frequency_scale": "linear", "magnitude_scale": "linear"},
        {},
    )
    qapp.processEvents()
    return cs, canvas


def _safe_rect(cs):
    canvas = cs.canvas_frf
    host = canvas.frequency_cursor_host_rect()
    assert host is not None and host.isValid()
    mapped = QRect(
        canvas.mapTo(cs.stack, host.topLeft()),
        canvas.mapTo(cs.stack, host.bottomRight()),
    ).intersected(cs.stack.contentsRect()).adjusted(8, 8, -8, -8)
    assert mapped.isValid()
    return mapped


def _assert_inside(pill, safe, slack=1):
    geo = pill.geometry()
    assert geo.left() >= safe.left() - slack, (geo, safe)
    assert geo.top() >= safe.top() - slack, (geo, safe)
    assert geo.right() <= safe.right() + slack, (geo, safe)
    assert geo.bottom() <= safe.bottom() + slack, (geo, safe)


def _assert_document_fits(pill):
    if not pill.has_detail():
        return
    doc = pill._detail.document
    assert doc.size().width() <= pill._detail.width() + 1.5
    text = pill.detail_text()
    assert "—" in text or any(ch.isdigit() for ch in text)


def _layout_plan():
    return TableLayoutPlan(
        "horizontal", 85.0, 160.0, 150.0, 2, 28.0, 80.0, 2, 500.0, 1, 1, 3,
    )


def _sample(**overrides):
    data = dict(
        frequency_hz=10.0,
        magnitude=12345.678,
        phase_deg=1.25,
        coherence=0.12345,
        magnitude_unit=" dB",
    )
    data.update(overrides)
    return FrfCursorSample(**data)


def test_frf_builder_keeps_live_precision_short_labels_and_signed_delta():
    single = build_frf_cursor_presentation(_sample(), mini=False)
    assert single.x_mode == "frf"
    assert single.retain_mini_labels is True
    assert single.overflow_noun == "项指标"
    assert single.blocks[0].channel_label == "幅值 |H|"
    assert single.blocks[1].channel_label == "相位 φ"
    assert single.blocks[2].channel_label == "相干度 γ²"
    assert single.blocks[0].metric_texts == (format(12345.678, ".5g"),)
    assert single.blocks[0].unit_text == "dB"
    assert single.blocks[1].unit_text == "°"
    assert single.blocks[2].unit_text == ""
    assert single.blocks[2].metric_texts == (format(0.12345, ".4g"),)
    assert format(12345.678, ".4g") not in single.blocks[0].metric_texts

    mini = build_frf_cursor_presentation(_sample(), mini=True)
    assert [block.channel_label for block in mini.blocks] == ["|H|", "φ", "γ²"]
    assert "幅值" not in mini.html
    assert "|H|" in mini.html and "φ" in mini.html and "γ²" in mini.html

    dual = FrfCursorSample(
        magnitude_unit=" dB",
        a=FrfCursorPoint(10.0, 1.0, 0.0, 0.5),
        b=FrfCursorPoint(20.0, 3.5, None, 0.9),
        delta_frequency_hz=10.0,
        delta_magnitude=2.5,
        delta_phase_deg=None,
        delta_coherence=0.4,
    )
    full = build_frf_cursor_presentation(dual, mini=False)
    assert full.metric_labels == ("A", "B", "Δ")
    assert full.blocks[0].metric_texts == ("1", "3.5", "+2.5")
    assert full.blocks[1].metric_texts[1] == "—"
    assert full.blocks[1].metric_texts[2] == "—"
    compact = build_frf_cursor_presentation(dual, mini=True)
    assert compact.metric_labels == ("Δ",)
    assert compact.blocks[0].channel_label == "|H|"
    assert compact.blocks[0].metric_texts == ("+2.5",)
    assert compact.blocks[0].unit_text == "dB"

    html = render_cursor_presentation(
        full, layout_plan=_layout_plan(), visible_count=1,
    )
    assert "+2 项指标" in html
    assert "channels" not in html

    intent = PinnedCursorIntent(
        record_id="r", ordinal=1, mode="single", domain="frf", presentation="mini",
    )
    pinned = PinPanelProjector.presentation_for(
        object(),
        intent,
        PinnedCursorSample(domain="frf", mode="single", frf_sample=_sample()),
    )
    assert pinned.html == mini.html
    assert pinned.blocks[0].metric_texts == mini.blocks[0].metric_texts


def test_frf_single_full_mini_round_trip_keeps_short_labels(
    qapp, qtbot, production_style,
):
    cs, canvas = _arm(qtbot, qapp, width=1048, height=700)
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_cursor_frequency(10.0)
    qapp.processEvents()
    pill = cs._pill
    assert pill.isVisible()
    assert "f=10 Hz" in pill.primary_text()
    assert "coherence=" not in pill.primary_text()
    full = pill.detail_text()
    assert "幅值 |H|" in full and "相位 φ" in full and "相干度 γ²" in full
    full_right = pill.x() + pill.width()

    evaluates = {"single": 0, "dual": 0}
    original_single = canvas.evaluate_frequency_cursor
    original_dual = canvas.evaluate_dual_frequency_cursor

    def count_single(*args, **kwargs):
        evaluates["single"] += 1
        return original_single(*args, **kwargs)

    def count_dual(*args, **kwargs):
        evaluates["dual"] += 1
        return original_dual(*args, **kwargs)

    canvas.evaluate_frequency_cursor = count_single
    canvas.evaluate_dual_frequency_cursor = count_dual
    pill._toggle_mode()
    qapp.processEvents()
    mini = pill.detail_text()
    assert pill.display_mode() == "mini"
    assert "|H|" in mini and "φ" in mini and "γ²" in mini
    assert "幅值" not in mini
    assert abs((pill.x() + pill.width()) - full_right) <= 1
    pill._toggle_mode()
    qapp.processEvents()
    assert "幅值 |H|" in pill.detail_text()
    assert abs((pill.x() + pill.width()) - full_right) <= 1
    assert evaluates == {"single": 0, "dual": 0}
    _assert_inside(pill, _safe_rect(cs))
    _assert_document_fits(pill)


def test_frf_dual_round_trip_awaiting_b_and_clear(qapp, qtbot, production_style):
    cs, canvas = _arm(qtbot, qapp, width=1048, height=700)
    cs.set_cursor_mode_for_canvas(canvas, "dual")
    canvas.set_dual_cursor_frequencies(1.0, 100.0)
    qapp.processEvents()
    pill = cs._pill
    assert "Δf=" in pill.primary_text()
    assert "background-color:#e8f1ff" in pill.primary_text()
    detail = pill.detail_text()
    assert ">A</td>" in detail and ">B</td>" in detail and ">Δ</td>" in detail
    assert "+3" in detail
    pill._toggle_mode()
    qapp.processEvents()
    mini = pill.detail_text()
    assert ">A</td>" not in mini and ">B</td>" not in mini
    assert "|H|" in mini and "+3" in mini
    pill._toggle_mode()
    qapp.processEvents()
    assert ">A</td>" in pill.detail_text()

    canvas.set_dual_cursor_frequencies(10.0, None)
    qapp.processEvents()
    assert "A=10 Hz" in pill.primary_text()
    assert "点击 B 选择第二点" in pill.primary_text()
    assert "+3" not in pill.detail_text()
    assert not pill.has_detail()
    cached = cs._cursor_rows_by_canvas[canvas][2]
    assert cached.awaiting_b is True
    assert cached.sample is None

    cs.set_cursor_mode_for_canvas(canvas, "off")
    qapp.processEvents()
    assert canvas not in cs._cursor_rows_by_canvas
    assert not pill.isVisible()


@pytest.mark.parametrize("width,height", [(1048, 700), (650, 420)])
def test_frf_pill_stays_inside_three_plot_safe_rect(
    qapp, qtbot, production_style, width, height,
):
    cs, canvas = _arm(qtbot, qapp, width=width, height=height)
    cs.set_cursor_mode_for_canvas(canvas, "dual")
    canvas.set_dual_cursor_frequencies(1.0, 100.0)
    qapp.processEvents()
    pill = cs._pill
    assert pill.isVisible()
    assert pill.awaiting_space() is False
    _assert_inside(pill, _safe_rect(cs))
    _assert_document_fits(pill)
    assert "幅值 |H|" in pill.detail_text()
    assert "相位 φ" in pill.detail_text()
    assert "相干度 γ²" in pill.detail_text()


def test_frf_nonfinite_keeps_frequency_and_does_not_invent_zero(
    qapp, qtbot, production_style,
):
    cs, canvas = _arm(
        qtbot, qapp, width=1048, height=700, result=_result(magnitude_nan=True),
    )
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_cursor_frequency(10.0)
    qapp.processEvents()
    pill = cs._pill
    assert "f=10 Hz" in pill.primary_text()
    detail = pill.detail_text()
    assert "—" in detail
    assert ">0<" not in detail and ">0.0<" not in detail


def test_frf_display_change_follows_owner_arrays(qapp, qtbot, production_style):
    cs, canvas = _arm(
        qtbot, qapp, width=1048, height=700,
        params={"frequency_scale": "log", "magnitude_scale": "linear"},
    )
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_cursor_frequency(10.0)
    qapp.processEvents()
    assert "f=10 Hz" in cs._pill.primary_text()
    assert "log" not in cs._pill.primary_text()
    linear = format(float(canvas._draw_magnitude[
        canvas._nearest_frequency_index(10.0)
    ]), ".5g")
    assert linear in cs._pill.detail_text()

    canvas.set_display_params({"magnitude_scale": "db"})
    qapp.processEvents()
    assert not cs._pill.isVisible()
    canvas.set_cursor_frequency(10.0)
    qapp.processEvents()
    db_value = format(float(canvas._draw_magnitude[
        canvas._nearest_frequency_index(10.0)
    ]), ".5g")
    assert db_value != linear
    assert db_value in cs._pill.detail_text()
    assert "dB" in cs._pill.detail_text()
    assert "f=10 Hz" in cs._pill.primary_text()


def test_frf_dual_display_change_resamples_without_a_new_click(
    qapp, qtbot, production_style,
):
    cs, canvas = _arm(qtbot, qapp, width=1048, height=700)
    cs.set_cursor_mode_for_canvas(canvas, "dual")
    canvas.set_dual_cursor_frequencies(1.0, 100.0)
    qapp.processEvents()
    before = cs._pill.detail_text()
    canvas.set_display_params({"magnitude_scale": "db"})
    qapp.processEvents()
    after = cs._pill.detail_text()
    assert cs._pill.isVisible()
    assert "dB" in after
    assert after != before
    assert "Hz" in cs._pill.primary_text()


def test_hidden_frf_clear_does_not_erase_the_time_pill(qapp, qtbot, production_style):
    cs, canvas = _arm(qtbot, qapp, width=1048, height=700)
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    cs.canvas_time.plot_channels(
        [(
            "speed", True,
            np.asarray([0.0, 0.5, 1.0]),
            np.asarray([1.0, 2.0, 3.0]),
            "#1769e0", "rpm", "fid-a",
        )],
        mode="overlay",
    )
    qapp.processEvents()
    cs.canvas_time._emit_single_cursor_html(0.5)
    qapp.processEvents()
    assert "t=" in cs._pill.primary_text()

    cs.set_mode("frf")
    qapp.processEvents()
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_cursor_frequency(10.0)
    qapp.processEvents()
    assert "f=10 Hz" in cs._pill.primary_text()

    cs.set_mode("time")
    qapp.processEvents()
    assert "t=" in cs._pill.primary_text()
    assert "f=10" not in cs._pill.primary_text()
    time_detail = cs._pill.detail_text()

    cs.set_cursor_mode_for_canvas(canvas, "off")
    qapp.processEvents()
    assert "t=0.5000s" in cs._pill.primary_text()
    assert cs._pill.detail_text() == time_detail
    assert canvas not in cs._cursor_rows_by_canvas

    cs.set_mode("frf")
    qapp.processEvents()
    assert not cs._pill.isVisible()
    assert "t=" not in cs._pill.primary_text()
