"""FFT cursor shared-table geometry, identity, and update-path contracts."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QRect, QSettings
from PyQt5.QtGui import QTextDocument

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.cursor_display import (
    build_fft_cursor_presentation,
)
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayChannel,
    CursorDisplayOptions,
    FrequencyCursorChannel,
)
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


REPO_ROOT = Path(__file__).resolve().parents[2]
COLORS = (
    "#2563eb", "#dc2626", "#059669", "#d97706",
    "#7c3aed", "#db2777", "#0f766e", "#ea580c",
)


@pytest.fixture
def production_style(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


def _spectrum_entry(name, color, scale=1.0, *, fid=None, channel=None, long_name=False):
    label = ("VeryLongSpectrumIdentity_" + name) if long_name else name
    freq = np.array([1.0, 10.0, 100.0, 200.0])
    amp = np.array([2.0, 3.0, 4.0, 5.0], dtype=float) * scale
    entry = {
        "freq": freq,
        "amp": amp,
        "label": label,
        "color": color,
        "time": np.array([0.0, 1.0]),
        "signal": np.array([0.0, 1.0]),
    }
    if fid is not None:
        entry["fid"] = fid
        entry["channel"] = channel or name
    return entry


def _entries(count, *, long_name=False, distinct_sources=False):
    rows = []
    for index in range(count):
        fid = f"file-{index % 3}" if distinct_sources else None
        rows.append(_spectrum_entry(
            f"CH{index:02d}",
            COLORS[index % len(COLORS)],
            scale=1.0 if index == 0 else 0.5,
            fid=fid,
            channel=f"CH{index:02d}",
            long_name=long_name,
        ))
    return rows


def _make_fft_stack(qtbot, qapp, *, width, height, count, long_name=False):
    # The UI fixture provides a current-item INI for the bare constructor.
    # A fixed /tmp filename would share cursor state across items.
    settings = QSettings()
    cs = ChartStack(cursor_settings=settings)
    qtbot.addWidget(cs)
    cs.resize(width, height)
    cs.show()
    qapp.processEvents()
    qtbot.waitExposed(cs)
    cs.set_mode("fft")
    qapp.processEvents()
    canvas = cs.canvas_fft
    canvas.plot_spectra(
        _entries(count, long_name=long_name),
        xlim=(0.0, 200.0),
        amp_label="Amplitude",
        title="FFT",
    )
    qapp.processEvents()
    return cs, canvas


def _spectrum_safe_rect(cs):
    canvas = cs.canvas_fft
    host = canvas.frequency_cursor_host_rect()
    assert host is not None and host.isValid()
    mapped = QRect(
        canvas.mapTo(cs.stack, host.topLeft()),
        canvas.mapTo(cs.stack, host.bottomRight()),
    ).intersected(cs.stack.contentsRect()).adjusted(8, 8, -8, -8)
    assert mapped.isValid()
    return mapped


def _arm_dual(cs, canvas, qapp, a=10.0, b=200.0):
    cs._fft_card.set_cursor_mode("dual")
    canvas.set_dual_cursor_frequencies(a, b)
    qapp.processEvents()


def _arm_single(cs, canvas, qapp, freq=100.0):
    cs._fft_card.set_cursor_mode("single")
    canvas.set_cursor_frequency(freq)
    qapp.processEvents()


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


def test_cursor_display_model_stays_qt_free():
    src = REPO_ROOT / "mf4_analyzer" / "ui" / "cursor_display_model.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert all("Qt" not in name and "PyQt" not in name for name in imported)


def test_fft_projection_keeps_a_b_delta_and_escapes_names():
    channels = (
        FrequencyCursorChannel(
            identity=("run-a", "L <A&B>"),
            source_label="run-a",
            channel_label="L <A&B>",
            color="#2563eb",
            a_value=1.25,
            b_value=0.5,
            delta_ab=-0.75,
        ),
        FrequencyCursorChannel(
            identity=("run-b", "L <A&B>"),
            source_label="run-b",
            channel_label="L <A&B>",
            color="#dc2626",
            a_value=2.0,
            b_value=3.0,
            delta_ab=1.0,
        ),
    )
    projection = build_fft_cursor_presentation(
        channels, cursor_mode="dual", mini=False,
    )
    assert projection.x_mode == "frequency"
    assert projection.metric_labels == ("A", "B", "Δ")
    assert projection.omit_visible_source_prefix is False
    assert projection.blocks[0].table_rows[0].metric_texts == ("1.25", "0.5", "-0.75")
    html = projection.html
    assert "L &lt;A&amp;B&gt;" in html
    assert "min_value" not in html
    mini = build_fft_cursor_presentation(channels, cursor_mode="dual", mini=True)
    assert mini.metric_labels == ("Δ",)
    assert "L &lt;A&amp;B&gt;" not in mini.html
    assert "-0.75" in mini.html


def test_fft_single_projection_keeps_relative_primary_delta():
    channels = (
        FrequencyCursorChannel(
            identity="a", source_label="", channel_label="MOTOR Y",
            color="#2563eb", value=4.0,
        ),
        FrequencyCursorChannel(
            identity="b", source_label="", channel_label="MOTOR X",
            color="#dc2626", value=2.0, delta_to_primary=-2.0,
        ),
    )
    projection = build_fft_cursor_presentation(
        channels, cursor_mode="single", mini=False,
    )
    assert projection.metric_labels == ("Value",)
    assert projection.blocks[0].table_rows[0].metric_texts == ("4",)
    assert "Δ-2" in projection.blocks[1].table_rows[0].metric_texts[0]
    mini = build_fft_cursor_presentation(channels, cursor_mode="single", mini=True)
    assert "MOTOR Y" not in mini.html
    assert "4" in mini.html


@pytest.mark.parametrize("width,height,count,long_name,mode", [
    (1000, 700, 16, False, "dual"),
    (650, 420, 8, False, "dual"),
    (650, 420, 2, True, "dual"),
    (1000, 700, 8, False, "single"),
    (650, 420, 8, False, "single"),
])
@pytest.mark.parametrize("mini", [False, True])
def test_fft_pill_stays_inside_spectrum_safe_rect(
    qapp, qtbot, production_style, width, height, count, long_name, mode, mini,
):
    cs, canvas = _make_fft_stack(
        qtbot, qapp, width=width, height=height, count=count, long_name=long_name,
    )
    if mode == "dual":
        _arm_dual(cs, canvas, qapp)
    else:
        _arm_single(cs, canvas, qapp)
    pill = cs._pill
    if mini:
        pill._toggle_mode()
        qapp.processEvents()
    assert pill.isVisible() or pill.awaiting_space()
    if pill.awaiting_space():
        return
    safe = _spectrum_safe_rect(cs)
    _assert_inside(pill, safe)
    _assert_document_fits(pill)
    if long_name and pill.isVisible():
        assert pill.width() <= safe.width() + 1


def test_fft_fifty_channels_stay_inside_spectrum_safe_rect(
    qapp, qtbot, production_style,
):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=1000, height=700, count=50)
    _arm_dual(cs, canvas, qapp)
    pill = cs._pill
    if pill.awaiting_space():
        return
    visible = pill.visible_channel_count()
    assert 0 < visible < 50
    omitted = 50 - visible
    assert f"+{omitted} channels" in pill.detail_text()
    _assert_inside(pill, _spectrum_safe_rect(cs))
    _assert_document_fits(pill)


def test_fft_low_height_omits_whole_channel_blocks(qapp, qtbot, production_style):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=650, height=280, count=16)
    _arm_dual(cs, canvas, qapp)
    pill = cs._pill
    if pill.awaiting_space():
        return
    projection = pill._display_projection
    assert projection is not None
    visible = pill.visible_channel_count()
    assert 0 < visible <= len(projection.blocks)
    if visible < len(projection.blocks):
        omitted = len(projection.blocks) - visible
        assert f"+{omitted} channels" in pill.detail_text()
    _assert_inside(pill, _spectrum_safe_rect(cs))
    _assert_document_fits(pill)


def test_fft_live_update_writes_projection_once(qapp, qtbot, production_style):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=1000, height=700, count=2)
    pill = cs._pill
    counts = {"projection": 0, "single_detail": 0, "detail": 0, "freq_rows": 0}
    orig_projection = pill.set_display_projection
    orig_single = pill.set_single_detail_html
    orig_detail = pill.set_detail_html
    orig_freq = pill.set_frequency_dual_rows

    def set_display_projection(*args, **kwargs):
        counts["projection"] += 1
        return orig_projection(*args, **kwargs)

    def set_single_detail_html(*args, **kwargs):
        counts["single_detail"] += 1
        return orig_single(*args, **kwargs)

    def set_detail_html(*args, **kwargs):
        counts["detail"] += 1
        return orig_detail(*args, **kwargs)

    def set_frequency_dual_rows(*args, **kwargs):
        counts["freq_rows"] += 1
        return orig_freq(*args, **kwargs)

    pill.set_display_projection = set_display_projection
    pill.set_single_detail_html = set_single_detail_html
    pill.set_detail_html = set_detail_html
    pill.set_frequency_dual_rows = set_frequency_dual_rows

    _arm_dual(cs, canvas, qapp)
    assert counts["projection"] == 1
    assert counts["single_detail"] == 0
    assert counts["detail"] == 0
    assert counts["freq_rows"] == 0

    counts["projection"] = 0
    _arm_single(cs, canvas, qapp)
    assert counts["projection"] == 1
    assert counts["single_detail"] == 0


def test_fft_toggle_does_not_replay_time_cache(qapp, qtbot, production_style, tmp_path):
    settings = QSettings(str(tmp_path / "fft-cursor-toggle.ini"), QSettings.IniFormat)
    cs = ChartStack(cursor_settings=settings)
    qtbot.addWidget(cs)
    cs.resize(1000, 700)
    cs.show()
    qapp.processEvents()
    cs.set_mode("time")
    cs.set_cursor_mode("dual")
    from mf4_analyzer.ui.cursor_display_model import CursorDisplayChannel

    time_channel = CursorDisplayChannel(
        identity="speed", source_label="", channel_label="speed",
        color="#1769e0", min_value=1.0, max_value=9.0, avg_value=5.0, delta=8.0,
    )
    cs.canvas_time.dual_cursor_rows.emit((time_channel,))
    qapp.processEvents()
    assert "speed" in cs._pill.detail_text()
    assert "Min" in cs._pill.detail_text()

    cs.set_mode("fft")
    qapp.processEvents()
    canvas = cs.canvas_fft
    canvas.plot_spectra(
        _entries(2), xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    _arm_dual(cs, canvas, qapp)
    assert cs._pill._display_projection.x_mode == "frequency"
    assert "Min" not in cs._pill.detail_text()
    assert "CH00" in cs._pill.detail_text()
    cs._pill._toggle_mode()
    qapp.processEvents()
    assert cs._pill.display_mode() == "mini"
    assert "speed" not in cs._pill.detail_text()
    assert "Min" not in cs._pill.detail_text()
    cs._pill._toggle_mode()
    qapp.processEvents()
    assert "CH00" in cs._pill.detail_text()
    assert cs._pill._display_projection.metric_labels == ("A", "B", "Δ")

    cs.set_mode("time")
    qapp.processEvents()
    assert "CH00" not in cs._pill.detail_text()
    assert "Min" in cs._pill.detail_text()
    assert "speed" in cs._pill.detail_text()

    cs.set_mode("fft")
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert "Min" not in cs._pill.detail_text()
    assert "CH00" in cs._pill.detail_text()
    assert cs._pill._display_projection.x_mode == "frequency"


def test_switching_to_fft_hides_time_pill_before_spectrum_readout(
    qapp, qtbot, production_style, tmp_path,
):
    settings = QSettings(str(tmp_path / "fft-cursor-hide.ini"), QSettings.IniFormat)
    cs = ChartStack(cursor_settings=settings)
    qtbot.addWidget(cs)
    cs.resize(900, 600)
    cs.show()
    qapp.processEvents()
    cs.set_mode("time")
    cs.set_cursor_mode("dual")
    from mf4_analyzer.ui.cursor_display_model import CursorDisplayChannel

    cs.canvas_time.dual_cursor_rows.emit((
        CursorDisplayChannel(
            identity="speed", source_label="", channel_label="speed",
            color="#1769e0", min_value=1.0, max_value=9.0, avg_value=5.0,
            delta=8.0,
        ),
    ))
    qapp.processEvents()
    assert cs._pill.isVisible()
    cs.set_mode("fft")
    qapp.processEvents()
    assert not cs._pill.isVisible()


def test_time_display_options_do_not_rewrite_fft_projection(qapp, qtbot, production_style):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=900, height=600, count=2)
    _arm_dual(cs, canvas, qapp)
    before = cs._pill.detail_text()
    cs._on_cursor_display_options_changed(
        CursorDisplayOptions(
            show_min_value=False, show_max_value=False,
            show_avg_value=False, show_delta_value=False,
        )
    )
    qapp.processEvents()
    assert cs._pill.detail_text() == before
    assert cs._pill._display_projection.metric_labels == ("A", "B", "Δ")


def test_fft_a_only_off_and_empty_clear_paths(qapp, qtbot, production_style):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=900, height=600, count=2)
    cs._fft_card.set_cursor_mode("dual")
    canvas.set_dual_cursor_frequencies(10.0, None)
    qapp.processEvents()
    assert "点击 B" in cs._pill.primary_text()
    assert cs._pill._display_projection is not None
    assert cs._pill._display_projection.blocks == ()

    canvas.set_dual_cursor_frequencies(10.0, 200.0)
    qapp.processEvents()
    assert cs._pill.has_detail()

    cs._fft_card.set_cursor_mode("off")
    qapp.processEvents()
    assert not cs._pill.isVisible()

    canvas.plot_spectra([], xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT")
    cs._fft_card.set_cursor_mode("dual")
    empty = canvas.set_dual_cursor_frequencies(10.0, 200.0)
    assert empty == ""
    qapp.processEvents()
    assert not cs._pill.has_detail()


def test_fft_units_stay_empty_and_identity_is_not_merged(qapp, qtbot, production_style):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=1000, height=700, count=2)
    canvas.plot_spectra(
        [
            _spectrum_entry("same", "#2563eb", fid="file-a", channel="torque"),
            _spectrum_entry("same", "#dc2626", fid="file-b", channel="torque"),
        ],
        xlim=(0.0, 200.0), amp_label="Amplitude (dB)", title="FFT",
    )
    _arm_dual(cs, canvas, qapp)
    projection = cs._pill._display_projection
    assert projection.blocks[0].unit_text == ""
    assert projection.blocks[1].unit_text == ""
    assert projection.blocks[0].identity != projection.blocks[1].identity
    rows = canvas._frequency_cursor_rows(10.0, 200.0)
    assert rows[0][4] == ""


def test_fft_value_updates_keep_top_right_anchor(qapp, qtbot, production_style):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=1000, height=700, count=4)
    _arm_dual(cs, canvas, qapp)
    pill = cs._pill
    pill.mark_user_placed(True)
    safe = _spectrum_safe_rect(cs)
    pill.move(safe.left() + 20, safe.top() + 30)
    right = pill.x() + pill.width()
    top = pill.y()
    for step in range(12):
        canvas.set_dual_cursor_frequencies(10.0 + step, 180.0 - step)
        qapp.processEvents()
        assert abs((pill.x() + pill.width()) - right) <= 2
        assert abs(pill.y() - top) <= 2
        _assert_inside(pill, _spectrum_safe_rect(cs))


def test_fft_host_rect_excludes_time_preview(qapp, qtbot):
    canvas = PgLineCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(640, 480)
    canvas.show()
    qapp.processEvents()
    canvas.plot_spectra(
        _entries(2), xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    qapp.processEvents()
    host = canvas.frequency_cursor_host_rect()
    assert host is not None
    assert host.height() < canvas.height()
    assert host.bottom() < canvas.height() - 20
    amp = canvas._plot_amp.vb.sceneBoundingRect()
    preview = canvas._plot_time.vb.sceneBoundingRect()
    assert amp.bottom() <= preview.top() + 2
    received = []
    canvas.frequency_cursor_channels.connect(received.append)
    canvas.set_cursor_mode("single")
    canvas.set_cursor_frequency(100.0)
    assert received
    assert received[-1][0].delta_to_primary is None
    assert received[-1][1].delta_to_primary == pytest.approx(
        received[-1][1].value - received[-1][0].value
    )
    canvas.set_cursor_mode("dual")
    canvas.set_dual_cursor_frequencies(10.0, 200.0)
    last = received[-1]
    assert last[0].a_value is not None and last[0].b_value is not None
    assert last[0].delta_ab == pytest.approx(last[0].b_value - last[0].a_value)


def test_fft_structured_snapshot_does_not_fall_back_to_unbounded_html(
    qapp, qtbot, production_style,
):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=650, height=420, count=8)
    _arm_dual(cs, canvas, qapp)
    snapshot = cs.cursor_pill_snapshot()
    assert snapshot.get("display_projection") is not None
    cs._pill.set_detail_html("<div>" + ("wide " * 80) + "</div>")
    cs.restore_cursor_pill_snapshot(snapshot)
    qapp.processEvents()
    assert cs._pill._display_projection is not None
    _assert_inside(cs._pill, _spectrum_safe_rect(cs))
    _assert_document_fits(cs._pill)


def _arm_time_dual(cs, qapp, a_text="1 s", b_text="2 s"):
    cs.set_mode("time")
    cs.set_cursor_mode("dual")
    cs.canvas_time.cursor_info.emit(
        f"A <b>{a_text}</b> &nbsp;│&nbsp; B <b>{b_text}</b>"
    )
    cs.canvas_time.dual_cursor_rows.emit((CursorDisplayChannel(
        identity="speed", source_label="", channel_label="speed",
        min_value=1., max_value=9., avg_value=5., delta=8.,
        unit_suffix="rpm",
    ),))
    qapp.processEvents()


def test_shared_pill_restores_primary_with_same_domain_rows(
    qapp, qtbot, production_style,
):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=1000, height=700, count=2)
    _arm_time_dual(cs, qapp)
    time_primary = cs._pill.primary_text()
    time_detail = cs._pill.detail_text()
    time_doc = cs._pill._detail.document.toPlainText()
    assert "s" in time_primary
    assert "Hz" not in time_primary
    assert "speed" in time_doc.lower() or "min" in time_doc.lower()

    cs.set_mode("fft")
    _arm_dual(cs, canvas, qapp, a=10., b=200.)
    fft_primary = cs._pill.primary_text()
    fft_detail = cs._pill.detail_text()
    assert "Hz" in fft_primary
    assert fft_primary != time_primary

    cs.set_mode("time")
    qapp.processEvents()
    frame = cs.grab()
    assert not frame.isNull()
    assert cs._pill._display_projection.x_mode == "time"
    assert cs._pill.primary_text() == time_primary
    assert "Hz" not in cs._pill.primary_text()
    restored_doc = cs._pill._detail.document.toPlainText()
    assert restored_doc == time_doc
    assert cs._pill.detail_text() == time_detail
    assert "Min" in restored_doc or "min" in restored_doc.lower()

    cs._pill._toggle_mode()
    qapp.processEvents()
    assert cs._pill.display_mode() == "mini"
    assert cs._pill.primary_text() == time_primary
    assert cs._pill._display_projection.x_mode == "time"
    cs._pill._toggle_mode()
    qapp.processEvents()

    cs.set_mode("fft")
    qapp.processEvents()
    assert cs._pill.primary_text() == fft_primary
    assert cs._pill._display_projection.x_mode == "frequency"
    assert "Hz" in cs._pill.primary_text()
    assert cs._pill.detail_text() == fft_detail
    fft_doc = cs._pill._detail.document.toPlainText()
    assert "A" in fft_doc or "10" in fft_doc


def test_shared_pill_single_and_a_only_restore_matching_primary(
    qapp, qtbot, production_style,
):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=1000, height=700, count=2)
    cs.set_mode("time")
    cs.set_cursor_mode("single")
    cs.canvas_time.cursor_info.emit("t = <b>0.40 s</b>")
    cs.canvas_time.single_cursor_rows.emit((CursorDisplayChannel(
        identity="torque", source_label="", channel_label="torque",
        current_value=3.5, unit_suffix="Nm",
    ),))
    qapp.processEvents()
    time_primary = cs._pill.primary_text()
    assert "s" in time_primary

    cs.set_mode("fft")
    cs._fft_card.set_cursor_mode("dual")
    canvas.set_dual_cursor_frequencies(10.0, None)
    qapp.processEvents()
    fft_primary = cs._pill.primary_text()
    assert "点击 B" in fft_primary

    cs.set_mode("time")
    qapp.processEvents()
    assert cs._pill.primary_text() == time_primary
    assert cs._pill._display_projection.x_mode == "time"
    cs.set_mode("fft")
    qapp.processEvents()
    assert "点击 B" in cs._pill.primary_text()
    assert cs._pill._display_projection.x_mode == "frequency"


def test_missing_primary_does_not_inherit_other_domain(
    qapp, qtbot, production_style,
):
    cs, canvas = _make_fft_stack(qtbot, qapp, width=900, height=600, count=2)
    _arm_dual(cs, canvas, qapp, a=10., b=200.)
    fft_primary = cs._pill.primary_text()
    assert "Hz" in fft_primary
    cs.set_mode("time")
    cs.set_cursor_mode("dual")
    cs.canvas_time.dual_cursor_rows.emit((CursorDisplayChannel(
        identity="speed", source_label="", channel_label="speed",
        min_value=1., max_value=9., avg_value=5., delta=8.,
    ),))
    qapp.processEvents()
    cs.set_mode("fft")
    qapp.processEvents()
    cs.set_mode("time")
    qapp.processEvents()
    assert "Hz" not in cs._pill.primary_text()
    assert cs._pill._display_projection.x_mode == "time"


def test_mainwindow_retained_fft_keeps_frequency_primary(
    qapp, qtbot, loaded_csv,
):
    from tests.ui.test_section_page_transition import (
        _ensure_section,
        _pause_page_transition,
        _seed_all_section_cache_homes,
    )
    from tests.ui.test_view_switch_integration import _make_loaded_window

    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _seed_all_section_cache_homes(qtbot, qapp, window)
    _pause_page_transition(window)
    cs = window.chart_stack
    cs.set_cursor_mode_for_canvas(window.canvas_time, "dual")
    window.canvas_time._cursor.ax = 0.1
    window.canvas_time._cursor.bx = 0.5
    window.canvas_time._emit_dual_cursor_html()
    _ensure_section(qtbot, qapp, window, "fft")
    cs._fft_card.set_cursor_mode("dual")
    cs.canvas_fft.set_dual_cursor_frequencies(10., 100.)
    qapp.processEvents()
    _ensure_section(qtbot, qapp, window, "time")
    _ensure_section(qtbot, qapp, window, "fft")
    assert cs._pill.isVisible()
    assert "Hz" in cs._pill.primary_text()
