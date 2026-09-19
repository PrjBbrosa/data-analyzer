"""Pinned-cursor marker geometry (Task 3). Measure painted items, not a detached document."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPointF, QSettings, Qt
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import QApplication, QPushButton

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.pg_canvas.pinned_cursor_overlay import (
    PINNED_OFFSCREEN_TEXT,
    PinnedAxisLabel,
    cluster_label_text,
    layout_pinned_axis_labels,
)
from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record


@pytest.fixture
def production_style(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


def _settings(name):
    return QSettings(
        str(Path("/tmp") / f"pinned-geom-{name}.ini"),
        QSettings.IniFormat,
    )


def _make_stack(qtbot, qapp, *, width=1100, height=640):
    cs = ChartStack(cursor_settings=_settings(f"{width}x{height}"))
    qtbot.addWidget(cs)
    cs.resize(width, height)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()
    return cs


def _plot_time(canvas, *, mode="overlay", extra=None):
    t = np.linspace(0.0, 1.0, 200)
    rows = [
        ("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-a"),
    ]
    if extra:
        rows.extend(extra)
    canvas.plot_channels(rows, mode=mode)


def _fft_entries():
    freq = np.array([1.0, 10.0, 50.0, 100.0, 200.0])
    return [
        {
            "freq": freq,
            "amp": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
            "label": "force",
            "channel": "force",
            "fid": "fid-a",
            "color": "#2563eb",
            "time": np.linspace(0.0, 1.0, 8),
            "signal": np.zeros(8),
        }
    ]


def _frf_result(*, log=False):
    from types import SimpleNamespace

    frequencies = (
        np.array([1.0, 10.0, 100.0, 1000.0]) if log
        else np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    )
    transfer = np.ones(frequencies.size, dtype=complex)
    coherence = np.linspace(0.9, 0.4, frequencies.size)
    return SimpleNamespace(
        frequencies=frequencies,
        transfer=transfer,
        coherence=coherence,
        effective=SimpleNamespace(fs=1000.0, df=1.0, segments=4),
        warnings=(),
    )


def _collection(domain, values, *, mode="single"):
    collection = empty_collection()
    unit = "s" if domain == "time" else "Hz"
    for value in values:
        payload = {"mode": mode, "domain": domain, "x_unit": unit}
        if mode == "dual":
            payload["ax"] = float(value[0])
            payload["bx"] = float(value[1])
        else:
            payload["x"] = float(value)
        collection, _ = next_record(collection, payload)
    return collection


def _wait_host(qtbot, canvas):
    overlay = canvas._pinned_overlay
    qtbot.waitUntil(lambda: overlay.host_rect() is not None, timeout=3000)
    return overlay.host_rect()


def _scene_x(line):
    vb = line.getViewBox()
    return float(vb.mapViewToScene(QPointF(float(line.value()), 0.0)).x())


def _pin(cs, canvas, values, *, domain="time", mode="single"):
    cs.set_pinned_cursors_for_canvas(
        canvas, _collection(domain, values, mode=mode),
    )
    QApplication.processEvents()
    return cs.pinned_cursors_for_canvas(canvas).records


def test_cluster_label_text_consecutive_and_plus_n():
    assert cluster_label_text((3,)) == "P3"
    assert cluster_label_text((3, 4, 5, 6, 7)) == "P3–P7"
    assert cluster_label_text((1, 3, 8)) == "+3"


def test_layout_does_not_shove_infinitely_left(qapp):
    fm = QFontMetrics(QFont())
    endpoints = [
        {
            "record_id": f"id-{index}",
            "ordinal": index + 1,
            "endpoint": "x",
            "text": f"P{index + 1}",
            "canvas_x": 40.0 + index * 2.0,
            "offscreen": None,
        }
        for index in range(12)
    ]
    items = layout_pinned_axis_labels(
        endpoints, axis_left=20, axis_right=120, axis_top=80, axis_height=16,
        fm=fm,
    )
    assert items
    assert all(item.canvas_rect[0] >= 20 for item in items)
    assert all(
        item.canvas_rect[0] + item.canvas_rect[2] <= 120
        for item in items
    )


def test_time_overlay_line_tracks_physical_x_after_pan_zoom(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(canvas, "single")
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)

    records = _pin(cs, canvas, [0.35])
    overlay = canvas._pinned_overlay
    physical = records[0].x
    lines = overlay.lines_for(records[0].record_id, "x")
    assert lines
    assert lines[0].value() == pytest.approx(physical)
    before = _scene_x(lines[0])
    expected = canvas._pinned_overlay.lines_for(records[0].record_id)[0]
    vb = expected.getViewBox()
    assert before == pytest.approx(
        float(vb.mapViewToScene(QPointF(physical, 0.0)).x()), abs=0.75,
    )

    canvas.set_xlim(0.2, 0.8)
    qapp.processEvents()
    overlay.reproject()
    lines = overlay.lines_for(records[0].record_id, "x")
    assert lines[0].value() == pytest.approx(physical)
    after = _scene_x(lines[0])
    vb = lines[0].getViewBox()
    assert after == pytest.approx(
        float(vb.mapViewToScene(QPointF(physical, 0.0)).x()), abs=0.75,
    )
    assert after != pytest.approx(before, abs=0.05)
    lo, hi = vb.viewRange()[0]
    assert lo <= physical <= hi
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert labels
    assert any("P1" in (label.geom().text if label.geom() else "") for label in labels)


def test_time_subplot_draws_a_line_in_each_shared_x_plot(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels(
        [
            ("speed", True, t, np.sin(t), "#1769e0", "rpm", "fid-a"),
            ("torque", True, t, np.cos(t), "#16a34a", "Nm", "fid-a"),
        ],
        mode="subplot",
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [0.4])
    lines = canvas._pinned_overlay.lines_for(records[0].record_id, "x")
    boxes = {id(line.getViewBox()) for line in lines}
    data_boxes = {
        id(handle.view_box)
        for handle in canvas.axes_list
        if not getattr(handle, "placeholder", False)
    }
    assert len(lines) == len(data_boxes)
    assert boxes == data_boxes
    for line in lines:
        assert line.value() == pytest.approx(records[0].x)


def test_fft_lines_only_in_spectrum_and_host_excludes_preview(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    cs.set_mode("fft")
    qapp.processEvents()
    canvas = cs.canvas_fft
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.plot_spectra(
        _fft_entries(), xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    qapp.processEvents()
    host = _wait_host(qtbot, canvas)
    assert host == canvas.frequency_cursor_host_rect()
    preview = canvas._plot_time.vb.sceneBoundingRect()
    glw = canvas._glw
    preview_top = glw.mapTo(
        canvas,
        glw.mapFromScene(preview.topLeft()),
    ).y()
    assert host.bottom() <= preview_top + 8
    records = _pin(cs, canvas, [100.0], domain="frequency")
    overlay = canvas._pinned_overlay
    lines = overlay.lines_for(records[0].record_id)
    assert lines
    for line in lines:
        assert line.getViewBox() is canvas._plot_amp.vb
        assert line.getViewBox() is not canvas._plot_time.vb
        assert line.value() == pytest.approx(100.0)
    stack_host = cs.pinned_cursor_host_on_stack(canvas)
    assert stack_host is not None
    assert stack_host != cs.stack.rect()
    transient = {id(item) for item in canvas.iter_transient_overlay_items()}
    for line in overlay.iter_lines():
        assert id(line) not in transient


def test_frf_linear_and_log_three_plots_keep_hz(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, height=820)
    cs.set_mode("frf")
    qapp.processEvents()
    canvas = cs.canvas_frf
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_result(
        _frf_result(log=False),
        {"frequency_scale": "linear", "magnitude_scale": "linear"},
        {},
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    assert canvas.frequency_cursor_host_rect() is not None
    records = _pin(cs, canvas, [2.0], domain="frf")
    assert records[0].x == pytest.approx(2.0)
    lines = canvas._pinned_overlay.lines_for(records[0].record_id)
    assert len(lines) == 3
    assert {id(line.getViewBox()) for line in lines} == {
        id(plot.vb) for plot in canvas.plots
    }
    for line in lines:
        assert line.value() == pytest.approx(2.0)

    canvas.set_result(
        _frf_result(log=True),
        {"frequency_scale": "log", "magnitude_scale": "db"},
        {},
    )
    qapp.processEvents()
    records = _pin(cs, canvas, [10.0], domain="frf")
    assert records[0].x == pytest.approx(10.0)
    assert records[0].x != pytest.approx(1.0)
    lines = canvas._pinned_overlay.lines_for(records[0].record_id)
    assert len(lines) == 3
    for line in lines:
        assert line.value() == pytest.approx(canvas._hz_to_view_x(10.0))
        assert line.value() == pytest.approx(1.0)


def test_one_two_eight_twenty_pins_labels_discoverable_ticks_untouched(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    bottom = canvas._primary_xaxis_ax._ax("bottom") if canvas._primary_xaxis_ax else None
    title_before = bottom.labelText if bottom is not None else None
    ticks_before = list(getattr(bottom, "_tickLevels", None) or [])

    for count in (1, 2, 8, 20):
        xs = [0.08 + (0.84 * index / max(1, count - 1)) for index in range(count)]
        records = _pin(cs, canvas, xs)
        assert len(records) == count
        overlay = canvas._pinned_overlay
        assert len(list(overlay.iter_lines())) >= count
        labels = cs._pinned_cursors.axis_labels_for(canvas)
        assert labels
        texts = " ".join(
            (label.geom().text if label.geom() else "") for label in labels
        )
        assert "P" in texts or "+" in texts
        for label in labels:
            assert label.parent() is cs.stack
            assert label.isVisible()
            geom = label.geom()
            assert geom is not None
            document = label._caption
            assert document.text()
        if bottom is not None:
            assert bottom.labelText == title_before
            for label in labels:
                ancestor = label.parentWidget()
                while ancestor is not None:
                    assert ancestor is not bottom
                    ancestor = ancestor.parentWidget()

    if bottom is not None and ticks_before:
        qapp.processEvents()
        assert getattr(bottom, "_tickLevels", None)


def test_same_x_cluster_hover_expands_numbers(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [0.42] * 8)
    assert len(records) == 8
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    clusters = [
        label for label in labels
        if label.geom() is not None and label.geom().kind == "cluster"
    ]
    assert clusters
    cluster = clusters[0]
    assert "–" in cluster.geom().text or cluster.geom().text.startswith("+")
    assert len(cluster.geom().members) == 8
    QApplication.sendEvent(cluster, QEvent(QEvent.Enter))
    qapp.processEvents()
    member_buttons = [
        child for child in cluster.findChildren(QPushButton)
        if child.objectName() == "pinnedAxisLabelMember"
    ]
    assert len(member_buttons) == 8


def test_offscreen_endpoint_is_not_clamped_and_marks_out_of_view(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [0.15, 0.85], mode="single")
    canvas.set_xlim(0.4, 0.6)
    qapp.processEvents()
    canvas._pinned_overlay.reproject()
    overlay = canvas._pinned_overlay
    left = records[0]
    right = records[1]
    for record, side in ((left, "left"), (right, "right")):
        lines = overlay.lines_for(record.record_id, "x")
        assert lines
        value = float(lines[0].value())
        assert value == pytest.approx(record.x)
        vb = lines[0].getViewBox()
        lo, hi = vb.viewRange()[0]
        assert not (lo <= record.x <= hi)
        assert value != pytest.approx(lo)
        assert value != pytest.approx(hi)
        assert record.record_id in overlay.offscreen_record_ids()
    pills = cs._pinned_cursors.pills_for(canvas)
    assert any(bool(pill.property("pinnedOffscreen")) for pill in pills)
    assert any(pill.toolTip() == PINNED_OFFSCREEN_TEXT for pill in pills)
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    texts = [label.geom().text for label in labels if label.geom()]
    assert any(text.startswith("◀") for text in texts)
    assert any(text.endswith("▶") for text in texts)


def test_host_pending_and_tiny_window_keep_discoverable_ordinals(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.3, 0.6])
    assert cs.pinned_cursor_host_on_stack(canvas) is not None

    cs.resize(80, 80)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    overlay.reproject()
    layout = overlay.layout()
    if layout.pending:
        assert cs.pinned_cursor_host_on_stack(canvas) is None
        assert cs.pinned_cursor_host_on_stack(canvas) != cs.rect()
    else:
        texts = [item.text for item in layout.items]
        assert texts
        assert any("P" in text or "+" in text for text in texts)
    assert overlay.records()
    assert len(cs.pinned_cursors_for_canvas(canvas).records) == 2


def test_click_label_raises_pill_without_changing_placement(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_cursor_mode_for_canvas(canvas, "dual")
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    canvas.restore_cursor_placement({"ax": 0.25, "bx": 0.7})
    before = canvas.snapshot_cursor_placement()
    records = _pin(cs, canvas, [(0.25, 0.7)], mode="dual")
    assert canvas.snapshot_cursor_placement() == before
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert labels
    label = labels[0]
    qtbot.mouseClick(label, Qt.LeftButton, pos=label.rect().center())
    qapp.processEvents()
    assert canvas.snapshot_cursor_placement() == before
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    assert pills[0].isVisible()
    assert records[0].ax == pytest.approx(0.25)
    assert records[0].bx == pytest.approx(0.7)


def test_coaxis_dual_extrema_keep_every_member(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    t = np.array([0.0, 0.25, 0.50, 0.75, 1.0], dtype=np.float64)
    group = {"axis_group": 1}
    canvas.plot_channels(
        [
            ("torque", True, t, np.array([1.0, -3.0, 2.0, 5.0, 0.0]),
             "#ef4444", "Nm", "fid-1", group),
            ("angle", True, t, np.array([4.0, 7.0, -2.0, 1.0, 0.0]),
             "#06b6d4", "deg", "fid-1", group),
            ("current", True, t, np.array([2.0, 0.0, 8.0, -4.0, 1.0]),
             "#8b5cf6", "A", "fid-1", group),
        ],
        mode="overlay",
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [(0.20, 0.80)], mode="dual")
    sample = cs._pinned_cursors._owner(canvas).samples[records[0].record_id]
    assert len(sample.extrema) == 3
    markers = canvas._pinned_overlay.extrema_items()
    assert markers
    xs, ys = markers[0].getData()
    assert len(xs) == 6
    assert sorted(ys) == pytest.approx(sorted([-3.0, 5.0, -2.0, 7.0, -4.0, 8.0]))
    transient = {id(item) for item in canvas.iter_transient_overlay_items()}
    for marker in markers:
        assert id(marker) not in transient


def test_dual_ab_merge_and_a_b_colors(qapp, qtbot, production_style):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    equal = _pin(cs, canvas, [(0.4, 0.4)], mode="dual")
    overlay = canvas._pinned_overlay
    assert overlay.lines_for(equal[0].record_id, "ab")
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert any(
        label.geom() and "A/B" in label.geom().text for label in labels
    )
    split = _pin(cs, canvas, [(0.2, 0.8)], mode="dual")
    a_lines = overlay.lines_for(split[-1].record_id, "a")
    b_lines = overlay.lines_for(split[-1].record_id, "b")
    assert a_lines and b_lines
    a_pen = a_lines[0].pen
    b_pen = b_lines[0].pen
    if callable(a_pen):
        a_pen = a_pen()
    if callable(b_pen):
        b_pen = b_pen()
    assert a_pen.color().name() != b_pen.color().name()
