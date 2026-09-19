"""Pinned-cursor copy/export compositing and UltraView digest (Task 5)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QRect, QSettings, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record
from mf4_analyzer.ui.ultraview_capture_facts import hide_transient_overlays
from tests.ui.test_ultraview_capture import _make_coord, _ref


def _settings(_name):
    """Use the UI fixture's per-item QSettings store, never a shared /tmp INI."""
    return QSettings()


def _make_stack(qtbot, qapp, *, width=1100, height=640):
    cs = ChartStack(cursor_settings=_settings(f"{width}x{height}"))
    qtbot.addWidget(cs)
    cs.resize(width, height)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()
    return cs


def _plot_time(canvas):
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels(
        [("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-a")]
    )


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


def _collection(domain, values, *, mode="single"):
    collection = empty_collection()
    unit = "s" if domain == "time" else "Hz"
    channel = "speed" if domain == "time" else "force"
    for value in values:
        payload = {
            "mode": mode,
            "domain": domain,
            "x_unit": unit,
            "bindings": [{"fid": "fid-a", "channel": channel}],
        }
        if mode == "dual":
            payload["ax"] = float(value[0])
            payload["bx"] = float(value[1])
        else:
            payload["x"] = float(value)
        collection, _ = next_record(collection, payload)
    return collection


def _pin(cs, canvas, values, *, domain="time", mode="single", expand=False):
    cs.set_pinned_cursors_for_canvas(
        canvas, _collection(domain, values, mode=mode),
    )
    QApplication.processEvents()
    if expand:
        controller = cs._pinned_cursors
        for record in cs.pinned_cursors_for_canvas(canvas).records:
            controller.toggle_record_panel(canvas, record.record_id)
        QApplication.processEvents()
    return cs.pinned_cursors_for_canvas(canvas).records


def _hide_live(cs):
    cs._pill.setVisible(False)
    if cs._pill_secondary is not None:
        cs._pill_secondary.setVisible(False)


def _place_on_canvas(cs, canvas, widget, *, x=36, y=28):
    origin = canvas.mapTo(cs.stack, canvas.rect().topLeft())
    widget.move(origin.x() + int(x), origin.y() + int(y))
    widget.setVisible(True)
    widget.raise_()
    QApplication.processEvents()


def _mapped_rect(cs, canvas, widget, pix):
    origin = canvas.mapTo(cs.stack, canvas.rect().topLeft())
    geo = widget.geometry()
    scale_x = float(pix.width()) / float(max(1, canvas.width()))
    scale_y = float(pix.height()) / float(max(1, canvas.height()))
    return QRect(
        int(round((geo.x() - origin.x()) * scale_x)),
        int(round((geo.y() - origin.y()) * scale_y)),
        int(round(geo.width() * scale_x)),
        int(round(geo.height() * scale_y)),
    )


def _count_color(img, color, *, rect=None, step=2, tol=40):
    target = QColor(color)
    x0, y0 = 0, 0
    x1, y1 = img.width(), img.height()
    if rect is not None:
        x0 = max(0, rect.x())
        y0 = max(0, rect.y())
        x1 = min(img.width(), rect.x() + rect.width())
        y1 = min(img.height(), rect.y() + rect.height())
    hits = 0
    for x in range(x0, max(x0 + 1, x1), step):
        for y in range(y0, max(y0 + 1, y1), step):
            sample = img.pixelColor(x, y)
            if (
                abs(sample.red() - target.red()) <= tol
                and abs(sample.green() - target.green()) <= tol
                and abs(sample.blue() - target.blue()) <= tol
            ):
                hits += 1
    return hits


def _install_chrome_colors(cs, mapping, monkeypatch):
    def fake_grab(scale, pill=None):
        color = mapping.get(id(pill), QColor("#000000"))
        width = 8
        height = 8
        if pill is not None:
            try:
                width = max(8, int(pill.width()))
                height = max(8, int(pill.height()))
            except RuntimeError:
                pass
        pix = QPixmap(width, height)
        pix.fill(color)
        return pix

    monkeypatch.setattr(cs, "_grab_pill_scaled", fake_grab)


def test_copy_includes_pinned_pill_pixels(qapp, qtbot, monkeypatch):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()
    records = _pin(cs, canvas, [0.35], expand=True)
    assert records
    assert records[0].panel_expanded is True
    pills = cs._pinned_cursors.pills_for(canvas)
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert pills
    _hide_live(cs)
    _place_on_canvas(cs, canvas, pills[0])
    magenta = QColor("#ff00aa")
    mapping = {id(pills[0]): magenta}
    for label in labels:
        mapping[id(label)] = QColor("#00ccff")
    _install_chrome_colors(cs, mapping, monkeypatch)

    captured = []
    cs.image_captured.connect(captured.append)
    cs._copy_card_image(cs._time_card)
    qapp.processEvents()
    assert captured
    pix = captured[-1]
    assert pix.devicePixelRatioF() == 1.0
    img = pix.toImage()
    pill_rect = _mapped_rect(cs, canvas, pills[0], pix)
    assert pill_rect.width() > 0 and pill_rect.height() > 0
    assert _count_color(img, magenta, rect=pill_rect) > 0
    outside = QRect(0, 0, min(12, img.width()), min(12, img.height()))
    assert _count_color(img, magenta, rect=outside) == 0


def test_copy_composites_pinned_chrome_inside_hidpi_pixmap(
    qapp, qtbot, monkeypatch,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()
    _pin(cs, canvas, [0.4], expand=True)
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    _hide_live(cs)
    _place_on_canvas(cs, canvas, pills[0], x=80, y=24)

    source = QPixmap(1000, 600)
    source.fill(QColor("#ffffff"))
    source.setDevicePixelRatio(2.0)

    monkeypatch.setattr(canvas, "grab_pixmap", lambda scale=1.0: QPixmap(source))
    red = QColor("#ff0000")
    _install_chrome_colors(cs, {id(pills[0]): red}, monkeypatch)

    captured = []
    cs.image_captured.connect(captured.append)
    cs._copy_card_image(cs._time_card)
    pix = captured[-1]
    assert pix.devicePixelRatioF() == 1.0
    img = pix.toImage()
    pill_rect = _mapped_rect(cs, canvas, pills[0], pix)
    assert pill_rect.right() < img.width()
    assert pill_rect.bottom() < img.height()
    assert _count_color(img, red, rect=pill_rect) > 0


def test_grab_presentation_includes_overlay_line_and_pill_values(
    qapp, qtbot, monkeypatch,
):
    import pyqtgraph as pg

    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()
    records = _pin(cs, canvas, [0.35], expand=True)
    overlay = canvas._pinned_overlay
    lines = overlay.lines_for(records[0].record_id, "x")
    assert lines
    for line in overlay.iter_lines():
        line.setPen(pg.mkPen(QColor("#ff00aa"), width=4))
        line.setVisible(True)
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    _hide_live(cs)
    _place_on_canvas(cs, canvas, pills[0])
    magenta = QColor("#22aa00")
    _install_chrome_colors(cs, {id(pills[0]): magenta}, monkeypatch)

    pix = cs.grab_presentation_pixmap(canvas, scale=1.0)
    assert pix is not None and not pix.isNull()
    img = pix.toImage()
    pill_rect = _mapped_rect(cs, canvas, pills[0], pix)
    assert _count_color(img, magenta, rect=pill_rect) > 0
    assert _count_color(img, QColor("#ff00aa"), tol=70) > 0


def test_time_split_primary_pins_stay_on_primary_half(qapp, qtbot, monkeypatch):
    cs = _make_stack(qtbot, qapp, width=1280, height=640)
    cs.set_mode("time")
    cs.enter_split()
    qapp.processEvents()
    primary = cs.canvas_time
    secondary = cs.secondary_canvas()
    _plot_time(primary)
    _plot_time(secondary)
    qapp.processEvents()
    _pin(cs, primary, [0.3], expand=True)
    _pin(cs, secondary, [0.7], expand=True)
    primary_pills = cs._pinned_cursors.pills_for(primary)
    secondary_pills = cs._pinned_cursors.pills_for(secondary)
    assert primary_pills and secondary_pills
    _hide_live(cs)
    _place_on_canvas(cs, primary, primary_pills[0], x=24, y=24)
    _place_on_canvas(cs, secondary, secondary_pills[0], x=24, y=24)
    red = QColor("#ee0000")
    green = QColor("#00bb00")
    _install_chrome_colors(
        cs,
        {id(primary_pills[0]): red, id(secondary_pills[0]): green},
        monkeypatch,
    )

    captured = []
    cs.image_captured.connect(captured.append)
    cs._copy_card_image(cs._time_card)
    pix = captured[-1]
    img = pix.toImage()
    left = QRect(0, 0, int(pix.width() * 0.4), pix.height())
    right = QRect(int(pix.width() * 0.6), 0, int(pix.width() * 0.4), pix.height())
    assert _count_color(img, red, rect=left) > 0
    assert _count_color(img, green, rect=right) > 0
    assert _count_color(img, red, rect=right) == 0
    assert _count_color(img, green, rect=left) == 0


def test_analysis_combined_pins_stay_on_owner_half(qapp, qtbot, monkeypatch):
    cs = _make_stack(qtbot, qapp, width=1280, height=720)
    cs.set_mode("fft")
    page = cs.page_fft
    page.enter_split()
    qapp.processEvents()
    left_canvas = page.pane_canvas(0)
    right_canvas = page.pane_canvas(1)
    entries = _fft_entries()
    left_canvas.plot_spectra(
        entries, xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    right_canvas.plot_spectra(
        entries, xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    qapp.processEvents()
    _pin(cs, left_canvas, [10.0], domain="frequency", expand=True)
    _pin(cs, right_canvas, [100.0], domain="frequency", expand=True)
    left_pills = cs._pinned_cursors.pills_for(left_canvas)
    right_pills = cs._pinned_cursors.pills_for(right_canvas)
    assert left_pills and right_pills
    _hide_live(cs)
    _place_on_canvas(cs, left_canvas, left_pills[0], x=20, y=20)
    _place_on_canvas(cs, right_canvas, right_pills[0], x=20, y=20)
    magenta = QColor("#ff00aa")
    yellow = QColor("#ffe600")
    _install_chrome_colors(
        cs,
        {id(left_pills[0]): magenta, id(right_pills[0]): yellow},
        monkeypatch,
    )

    combined = page.grab_combined_pixmap(scale=1.0)
    assert combined is not None and not combined.isNull()
    img = combined.toImage()
    left = QRect(0, 0, int(combined.width() * 0.4), combined.height())
    right = QRect(
        int(combined.width() * 0.6), 0, int(combined.width() * 0.4),
        combined.height(),
    )
    assert _count_color(img, magenta, rect=left) > 0
    assert _count_color(img, yellow, rect=right) > 0
    assert _count_color(img, magenta, rect=right) == 0
    assert _count_color(img, yellow, rect=left) == 0


def test_hide_transient_overlays_keeps_pin_overlay_lines(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()
    records = _pin(cs, canvas, [0.42])
    overlay = canvas._pinned_overlay
    lines = list(overlay.iter_lines())
    assert lines
    for line in lines:
        assert line.isVisible() is True
    with hide_transient_overlays(canvas):
        for line in lines:
            assert line.isVisible() is True
        for item in canvas.iter_transient_overlay_items():
            if item in lines:
                pytest.fail("pin overlay line joined iter_transient_overlay_items")
    for line in lines:
        assert line.isVisible() is True
    assert records[0].record_id


def test_ultraview_digest_tracks_pins_not_hover(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()

    window, coord = _make_coord()
    window.chart_stack = cs
    state = window.view_manager.get(0)
    state.view_id = "view-a"
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    baseline = coord.current_digest_for(ref)

    records = _pin(cs, canvas, [0.3])
    added = coord.current_digest_for(ref)
    assert added != baseline
    collapsed = cs._pinned_cursors.capture_fingerprint_for(canvas)
    assert collapsed[0][7:9] == ("full", False)

    cs._pinned_cursors.toggle_record_panel(canvas, records[0].record_id)
    qapp.processEvents()
    expanded = coord.current_digest_for(ref)
    assert expanded != added
    assert cs._pinned_cursors.capture_fingerprint_for(canvas)[0][8] is True

    collection = cs.pinned_cursors_for_canvas(canvas)
    from dataclasses import replace
    mini = replace(collection.records[0], presentation="mini")
    cs.set_pinned_cursors_for_canvas(
        canvas, replace(collection, records=(mini,)),
    )
    qapp.processEvents()
    mini_digest = coord.current_digest_for(ref)
    assert mini_digest != expanded

    collection = cs.pinned_cursors_for_canvas(canvas)
    from mf4_analyzer.ui.pinned_cursor_state import PinnedCursorAnchor
    moved = replace(
        collection.records[0],
        anchor=PinnedCursorAnchor(h_edge="left", v_edge="top", nx=0.2, ny=0.4),
    )
    cs.set_pinned_cursors_for_canvas(
        canvas, replace(collection, records=(moved,)),
    )
    qapp.processEvents()
    moved_digest = coord.current_digest_for(ref)
    assert moved_digest != mini_digest

    committed = replace(moved, x=0.48)
    cs.set_pinned_cursors_for_canvas(
        canvas, replace(collection, records=(committed,)),
    )
    qapp.processEvents()
    committed_digest = coord.current_digest_for(ref)
    assert committed_digest != moved_digest

    cs._pinned_cursors.raise_record(canvas, records[0].record_id)
    qapp.processEvents()
    assert coord.current_digest_for(ref) == committed_digest

    coord.clear()
    coord.deleteLater()


def test_ultraview_digest_omits_axis_edit_preview(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()

    window, coord = _make_coord()
    window.chart_stack = cs
    window.view_manager.get(0).view_id = "view-a"
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    record = _pin(cs, canvas, [0.35])[0]
    before = coord.current_digest_for(ref)

    controller = cs._pinned_cursors
    overlay = canvas._pinned_overlay
    viewport = canvas._glw.viewport()
    start = overlay.bottom_axis_viewport_pos_for_physical(record.x)
    global_start = viewport.mapToGlobal(start)
    assert controller.begin_axis_edit(canvas, record.record_id, "x", global_start)
    controller.preview_axis_edit(
        canvas,
        record.record_id,
        "x",
        QPoint(global_start.x() + 24, global_start.y()),
        Qt.NoModifier,
    )
    qapp.processEvents()
    qapp.processEvents()

    assert controller.is_axis_edit_active(canvas)
    assert coord.current_digest_for(ref) == before

    controller.cancel_axis_edit(canvas, record.record_id, "x")
    qapp.processEvents()
    assert coord.current_digest_for(ref) == before
    coord.clear()
    coord.deleteLater()


def _image_fingerprint(pix):
    from PyQt5.QtGui import QImage
    import hashlib

    img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    bits = img.bits()
    bits.setsize(img.byteCount())
    return (img.width(), img.height(), hashlib.md5(bytes(bits)).hexdigest())


def test_copy_flush_layout_matches_settled_geometry_pixels(
    qapp, qtbot, monkeypatch,
):
    cs = _make_stack(qtbot, qapp, width=1100, height=640)
    canvas = cs.canvas_time
    cs.set_mode("time")
    _plot_time(canvas)
    qapp.processEvents()
    _pin(cs, canvas, [0.35], expand=True)
    _hide_live(cs)
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    _place_on_canvas(cs, canvas, pills[0])
    red = QColor("#dd1111")
    _install_chrome_colors(cs, {id(pills[0]): red}, monkeypatch)
    cs.resize(1000, 600)
    qapp.processEvents()
    cs._pinned_cursors.flush_layout()
    settled = []
    cs.image_captured.connect(settled.append)
    cs._copy_card_image(cs._time_card)
    oracle = settled[-1]
    oracle_size = pills[0].size()
    oracle_pill_key = _image_fingerprint(pills[0].grab())

    cs.resize(1100, 600)
    qapp.processEvents()
    cs._pinned_cursors.flush_layout()
    for width in (1060, 1020, 1000):
        cs.resize(width, 600)
    flushed = []
    cs.image_captured.connect(flushed.append)
    cs._copy_card_image(cs._time_card)
    assert pills[0].size() == oracle_size
    assert _image_fingerprint(pills[0].grab()) == oracle_pill_key
    img = flushed[-1].toImage()
    pill_rect = _mapped_rect(cs, canvas, pills[0], flushed[-1])
    assert _count_color(img, red, rect=pill_rect) > 0
    assert _count_color(oracle.toImage(), red, rect=_mapped_rect(cs, canvas, pills[0], oracle)) > 0
    assert not cs._pinned_cursors._projector._layout_timer.isActive()
