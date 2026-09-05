"""Mode-switch full rebuild must not paint an empty viewport.

T0 Cocoa evidence: TimeCard 分屏/叠加 → plot_channels clear →
``_update_compute_progress(..., process_events=True)`` only repaints the
status bar, but the just-cleared viewport still paints ``n_axes=0``. The
first nonempty paint already has target geometry; there is no second
contraction. Independent ``canvas.plot_channels`` does not flash empty.

Offscreen does not always couple the status-bar repaint to the viewport, so
these tests issue a layout-neutral ``repaint()`` in the same progress
callback. That probe must not be able to draw a visible empty-axis frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _three_channel_csv(path):
    t = np.linspace(0.0, 1.0, 1000)
    pd.DataFrame(
        {
            "time": t,
            "torque": np.sin(2 * np.pi * 5 * t),
            "angle": np.cos(2 * np.pi * 3 * t),
            "speed": 1000.0 + 50.0 * np.sin(2 * np.pi * 2 * t),
        }
    ).to_csv(path, index=False)
    return str(path)


def _make_window(qtbot, qapp, csv_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    qtbot.waitExposed(window)
    window.load_file(csv_path)
    qapp.processEvents()
    fid = next(iter(window.files))
    window.navigator.set_checked_channels(
        [(fid, "torque"), (fid, "angle"), (fid, "speed")]
    )
    qapp.processEvents()
    return window, fid


def _time_card(window):
    return window.chart_stack._time_card


def _click_mode(window, mode):
    card = _time_card(window)
    button = card.btn_overlay if mode == "overlay" else card.btn_subplot
    button.click()


def _composite_keys(canvas):
    return [
        ck for ck, _name, _value in canvas._channel_lines.composite_items()
    ]


def _bottom_axis_heights(canvas):
    heights = []
    for handle in list(canvas.axes_list):
        plot_item = getattr(handle, "plot_item", None)
        if plot_item is None:
            continue
        try:
            axis = plot_item.getAxis("bottom")
        except Exception:
            axis = None
        if axis is None:
            continue
        try:
            heights.append(float(axis.height()))
        except Exception:
            continue
    return tuple(heights)


def _viewbox_union(canvas):
    lefts, tops, rights, bottoms = [], [], [], []
    for handle in list(canvas.axes_list):
        view_box = getattr(handle, "view_box", None)
        if view_box is None:
            continue
        try:
            rect = view_box.sceneBoundingRect()
        except Exception:
            continue
        lefts.append(float(rect.left()))
        tops.append(float(rect.top()))
        rights.append(float(rect.right()))
        bottoms.append(float(rect.bottom()))
    if not lefts:
        return None
    return (min(lefts), min(tops), max(rights), max(bottoms))


def _snapshot_geometry(canvas):
    return {
        "n_axes": len(canvas.axes_list),
        "heights": _bottom_axis_heights(canvas),
        "vb_union": _viewbox_union(canvas),
    }


def _probe_layout_neutral_paint(canvas):
    """Synchronous paint that must not change layout.

    Stands in for Cocoa painting the dirty viewport when the progress
    widget ``repaint()``s. Not a flush/grab, not ``processEvents``, not a
    zero-ms timer.
    """
    if canvas is None or sip.isdeleted(canvas):
        return
    targets = [canvas]
    glw = getattr(canvas, "_glw", None)
    if glw is not None and not sip.isdeleted(glw):
        targets.append(glw)
        viewport = glw.viewport()
        if viewport is not None and not sip.isdeleted(viewport):
            targets.append(viewport)
    for widget in targets:
        widget.repaint()


class _ViewportPaintLog(QObject):
    """Record Paint events; never consume them and never pump Qt."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.frames = []
        self._watched = []
        for widget in (canvas, canvas._glw, canvas._glw.viewport()):
            if widget is None:
                continue
            widget.installEventFilter(self)
            self._watched.append(widget)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            snapshot = _snapshot_geometry(self.canvas)
            snapshot["empty"] = snapshot["n_axes"] == 0
            snapshot["widget"] = type(obj).__name__
            self.frames.append(snapshot)
        return False

    def detach(self):
        for widget in self._watched:
            if widget is not None and not sip.isdeleted(widget):
                widget.removeEventFilter(self)
        self._watched = []


def _install_progress_paint_probe(window, canvas):
    real = window._update_compute_progress

    def wrapped(
        current,
        total,
        label=None,
        token=None,
        *,
        process_events=False,
        flush_events=False,
    ):
        real(
            current,
            total,
            label,
            token,
            process_events=process_events,
            flush_events=flush_events,
        )
        if process_events:
            _probe_layout_neutral_paint(canvas)

    window._update_compute_progress = wrapped
    return real


def _physical_drift(first, last, dpr):
    if first is None or last is None:
        return 0.0
    return max(abs(a - b) for a, b in zip(first, last)) * float(dpr)


def _assert_first_nonempty_stable(frames, canvas):
    nonempty = [frame for frame in frames if not frame["empty"]]
    assert nonempty, "mode switch never painted a nonempty viewport"
    first = nonempty[0]
    last = nonempty[-1]
    assert first["n_axes"] == last["n_axes"] == len(canvas.axes_list)
    dpr = float(canvas.devicePixelRatioF() or 1.0)
    # Bottom-axis heights and vertical ViewBox extent are the B/G3
    # contraction contract. Overlay left/right gutters can still move on
    # the first painted tick-textWidth refresh (offscreen); that is not
    # the empty-frame flash and must not drive a speculative overlay
    # geometry rewrite.
    assert _physical_drift(first["heights"], last["heights"], dpr) <= 1.0 + 1e-6
    first_union = first["vb_union"]
    last_union = last["vb_union"]
    assert first_union is not None and last_union is not None
    top_bottom_first = (first_union[1], first_union[3])
    top_bottom_last = (last_union[1], last_union[3])
    assert _physical_drift(top_bottom_first, top_bottom_last, dpr) <= 1.0 + 1e-6


def _assert_no_empty_visible_frame(frames):
    empty = [frame for frame in frames if frame["empty"]]
    assert not empty, (
        "full rebuild painted a visible empty-axis frame: "
        f"{empty[0]!r}"
    )


def _shared_legend_member_names(canvas):
    names = []
    for item in getattr(canvas, "_inside_label_items", ()) or ():
        text = item.toPlainText()
        for line in text.splitlines():
            stripped = line.lstrip("● ").strip()
            if stripped:
                names.append(stripped.split(" (")[0])
    return names


@pytest.fixture
def mode_switch_window(qtbot, qapp, tmp_path):
    window, fid = _make_window(qtbot, qapp, _three_channel_csv(tmp_path / "eps.csv"))
    window.chart_stack.set_plot_mode("subplot")
    window.plot_time()
    qapp.processEvents()
    yield window, fid
    canvas = window.canvas_time
    if canvas is not None and not sip.isdeleted(canvas):
        canvas.close()
    if not sip.isdeleted(window):
        window.close()


def test_subplot_to_overlay_button_does_not_paint_empty_viewport(
    mode_switch_window, qapp,
):
    window, _fid = mode_switch_window
    canvas = window.canvas_time
    assert window.chart_stack.plot_mode() == "subplot"
    assert len(canvas.axes_list) == 3

    saved_xlim = canvas.get_visible_xlim()
    saved_keys = _composite_keys(canvas)
    idle_before = canvas._quality.timer.interval()
    settle_calls = []
    xlim_flushes = []
    real_settle = canvas.settle_view_restore
    real_xlim = canvas.restore_visible_xlim

    def spy_settle():
        settle_calls.append("settle")
        return real_settle()

    def spy_xlim(xlim, *, flush=True):
        xlim_flushes.append(bool(flush))
        return real_xlim(xlim, flush=flush)

    canvas.settle_view_restore = spy_settle
    canvas.restore_visible_xlim = spy_xlim
    observer = _ViewportPaintLog(canvas)
    previous_progress = _install_progress_paint_probe(window, canvas)
    try:
        _click_mode(window, "overlay")
        qapp.processEvents()
        _probe_layout_neutral_paint(canvas)
    finally:
        window._update_compute_progress = previous_progress
        canvas.settle_view_restore = real_settle
        canvas.restore_visible_xlim = real_xlim
        observer.detach()

    _assert_no_empty_visible_frame(observer.frames)
    _assert_first_nonempty_stable(observer.frames, canvas)
    assert window.chart_stack.plot_mode() == "overlay"
    assert len(canvas.axes_list) == 3
    assert canvas.get_visible_xlim() == pytest.approx(saved_xlim)
    assert _composite_keys(canvas) == saved_keys
    assert settle_calls == ["settle"]
    assert xlim_flushes and all(flush is False for flush in xlim_flushes)
    assert canvas._quality.timer.interval() == idle_before == 150


def test_overlay_to_subplot_button_does_not_paint_empty_viewport(
    mode_switch_window, qapp,
):
    window, _fid = mode_switch_window
    canvas = window.canvas_time
    _click_mode(window, "overlay")
    qapp.processEvents()
    assert window.chart_stack.plot_mode() == "overlay"
    saved_xlim = canvas.get_visible_xlim()
    saved_keys = _composite_keys(canvas)

    observer = _ViewportPaintLog(canvas)
    previous_progress = _install_progress_paint_probe(window, canvas)
    try:
        _click_mode(window, "subplot")
        qapp.processEvents()
        _probe_layout_neutral_paint(canvas)
    finally:
        window._update_compute_progress = previous_progress
        observer.detach()

    _assert_no_empty_visible_frame(observer.frames)
    _assert_first_nonempty_stable(observer.frames, canvas)
    assert window.chart_stack.plot_mode() == "subplot"
    assert len(canvas.axes_list) == 3
    heights = _bottom_axis_heights(canvas)
    assert len(heights) == 3
    assert heights[0] < 8.0
    assert heights[1] < 8.0
    assert heights[2] > 20.0
    assert canvas.get_visible_xlim() == pytest.approx(saved_xlim)
    assert _composite_keys(canvas) == saved_keys


def test_plot_time_full_rebuild_does_not_paint_empty_viewport(
    mode_switch_window, qapp, monkeypatch,
):
    window, _fid = mode_switch_window
    canvas = window.canvas_time
    monkeypatch.setattr(
        canvas,
        "try_apply_selection_delta",
        lambda *args, **kwargs: {
            "applied": False,
            "reason": "forced-full-rebuild",
        },
    )
    observer = _ViewportPaintLog(canvas)
    previous_progress = _install_progress_paint_probe(window, canvas)
    try:
        window.plot_time()
        qapp.processEvents()
        _probe_layout_neutral_paint(canvas)
    finally:
        window._update_compute_progress = previous_progress
        observer.detach()

    _assert_no_empty_visible_frame(observer.frames)
    assert len(canvas.axes_list) == 3
    assert canvas.updatesEnabled() is True


def test_mode_switch_keeps_shared_legend_members(mode_switch_window, qapp):
    window, fid = mode_switch_window
    canvas = window.canvas_time
    window.channel_list.merge_axis_group([(fid, "torque"), (fid, "angle")])
    window.plot_time()
    qapp.processEvents()
    before = " ".join(_shared_legend_member_names(canvas))
    assert "torque" in before and "angle" in before

    _click_mode(window, "overlay")
    qapp.processEvents()
    _click_mode(window, "subplot")
    qapp.processEvents()

    after = " ".join(_shared_legend_member_names(canvas))
    assert "torque" in after and "angle" in after
    key_blob = " ".join(str(key) for key in _composite_keys(canvas))
    assert "torque" in key_blob and "angle" in key_blob and "speed" in key_blob


def test_display_update_suppression_is_nested_and_restores_on_exception(qapp):
    canvas = TimeDomainCanvasPG()
    canvas.resize(320, 240)
    canvas.show()
    try:
        assert canvas.updatesEnabled() is True
        with canvas.suppress_display_updates():
            assert canvas.updatesEnabled() is False
            with canvas.suppress_display_updates():
                assert canvas.updatesEnabled() is False
            assert canvas.updatesEnabled() is False
        assert canvas.updatesEnabled() is True

        canvas.setUpdatesEnabled(False)
        with canvas.suppress_display_updates():
            assert canvas.updatesEnabled() is False
        assert canvas.updatesEnabled() is False
        canvas.setUpdatesEnabled(True)

        with pytest.raises(RuntimeError, match="rebuild failed"):
            with canvas.suppress_display_updates():
                assert canvas.updatesEnabled() is False
                raise RuntimeError("rebuild failed")
        assert canvas.updatesEnabled() is True

        with pytest.raises(RuntimeError, match="inner failed"):
            with canvas.suppress_display_updates():
                with canvas.suppress_display_updates():
                    raise RuntimeError("inner failed")
        assert canvas.updatesEnabled() is True
    finally:
        canvas.close()


def test_mode_switch_exception_restores_updates(mode_switch_window, monkeypatch):
    window, _fid = mode_switch_window
    canvas = window.canvas_time

    def boom(*args, **kwargs):
        raise RuntimeError("plot_channels failed")

    monkeypatch.setattr(
        canvas,
        "try_apply_selection_delta",
        lambda *args, **kwargs: {
            "applied": False,
            "reason": "forced-full-rebuild",
        },
    )
    monkeypatch.setattr(canvas, "plot_channels", boom)
    with pytest.raises(RuntimeError, match="plot_channels failed"):
        window.plot_time()
    assert not sip.isdeleted(canvas)
    assert canvas.updatesEnabled() is True

    def boom_settle():
        raise RuntimeError("settle failed")

    monkeypatch.setattr(canvas, "plot_channels", lambda *args, **kwargs: None)
    monkeypatch.setattr(canvas, "settle_view_restore", boom_settle)
    with pytest.raises(RuntimeError, match="settle failed"):
        window._render_view_onto_canvas(0, canvas, update_primary_ui=True)
    assert canvas.updatesEnabled() is True


def test_hidden_canvas_suppression_restores_original_flag(qapp):
    canvas = TimeDomainCanvasPG()
    canvas.resize(320, 240)
    canvas.show()
    try:
        canvas.hide()
        original = canvas.updatesEnabled()
        with canvas.suppress_display_updates():
            pass
        assert canvas.updatesEnabled() is original
    finally:
        canvas.close()


def test_rapid_mode_toggles_leave_updates_enabled(mode_switch_window, qapp):
    window, _fid = mode_switch_window
    canvas = window.canvas_time
    _click_mode(window, "overlay")
    _click_mode(window, "subplot")
    _click_mode(window, "overlay")
    qapp.processEvents()
    assert canvas.updatesEnabled() is True
    assert len(canvas.axes_list) == 3
    assert isinstance(canvas, QWidget)
