"""Cross-section chart-toolbar contract for focus, mode, history, and export.

These nodes describe the intended behavior from the 2026-09-26 remediation
plan. They build real ChartStack cards and canvases with synthetic data and
only replace file dialogs and clear-confirm prompts.
"""
from __future__ import annotations

import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QMenu, QToolButton, QWidgetAction

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.pg_canvas import context_menu as context_menu_module

import numpy as np

SECTIONS = ("time", "fft", "fft_time", "order", "frf")
HEATMAP_SECTIONS = ("fft_time", "order")


@pytest.fixture
def stack(qtbot):
    chart_stack = ChartStack()
    qtbot.addWidget(chart_stack)
    chart_stack.resize(1000, 650)
    chart_stack.show()
    qtbot.waitExposed(chart_stack)
    return chart_stack


def _split(chart_stack, mode):
    chart_stack.set_mode(mode)
    if mode == "time":
        chart_stack.enter_split()
        return [chart_stack._time_card, chart_stack._secondary_card]
    page = chart_stack.page_for_mode[mode]
    page.enter_split()
    return list(page._cards)


def _focus(chart_stack, mode, index):
    if mode == "time":
        card = chart_stack._time_card if index == 0 else chart_stack._secondary_card
        chart_stack.set_focused_card(card)
        return
    chart_stack.page_for_mode[mode].set_focused_index(index)


def _annotation_on(card, mode):
    canvas = card.canvas
    if mode == "time":
        return bool(canvas._annotations.enabled)
    return bool(canvas._remark_enabled)


def _shared_annotation_checked(cards):
    return bool(cards[0]._annotation_btn.isChecked())


def _viewbox_modes(card):
    return [box.state["mouseMode"] for box in card.toolbar._view_boxes()]


def _zoom_highlighted(card):
    button = card.toolbar.widgetForAction(card.toolbar._actions_by_key["zoom"])
    return button.property("navActive") is True


def _context_zoom_button(toolbar):
    menu = QMenu()
    menu.addAction(
        context_menu_module._make_inline_context_panel_action(menu, None, toolbar)
    )
    for action in menu.actions():
        if not isinstance(action, QWidgetAction):
            continue
        widget = action.defaultWidget()
        if widget is not None and widget.objectName() == "pgContextInlinePanel":
            return widget.findChild(QToolButton, "pgContextZoomButton")
    return None


def _plot_heatmap(card):
    card.canvas.plot_or_update_heatmap(
        matrix=np.arange(80, dtype=float).reshape(8, 10),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode="amplitude",
        z_auto=True,
    )


def _emit_time_pan(canvas, lo, hi):
    primary = canvas._primary_xaxis_ax
    primary.set_xlim(lo, hi)
    box = primary.view_box
    box.sigRangeChangedManually.emit(box.state["mouseEnabled"])


@pytest.mark.parametrize("mode", SECTIONS)
def test_shared_annotation_follows_the_focused_pane(qapp, stack, mode):
    cards = _split(stack, mode)
    _focus(stack, mode, 1)

    cards[0]._annotation_btn.click()
    qapp.processEvents()

    assert _annotation_on(cards[0], mode) is False
    assert _annotation_on(cards[1], mode) is True
    assert _shared_annotation_checked(cards) is True

    _focus(stack, mode, 0)
    qapp.processEvents()
    assert _shared_annotation_checked(cards) is False

    cards[1].set_annotation_enabled(False)
    assert _annotation_on(cards[1], mode) is False
    assert _shared_annotation_checked(cards) is False


@pytest.mark.parametrize("mode", HEATMAP_SECTIONS)
def test_shared_clear_removes_only_the_focused_remarks(qapp, stack, mode):
    cards = _split(stack, mode)
    for card in cards:
        _plot_heatmap(card)
        card.canvas.set_remark_enabled(True)
        card.canvas.add_remark_at(5.0, 4.0)
    assert [card.canvas.remark_count() for card in cards] == [1, 1]
    _focus(stack, mode, 1)
    cards[0]._confirm_clear_annotations = lambda count: True

    cards[0]._clear_annotation_btn.click()
    qapp.processEvents()

    assert [card.canvas.remark_count() for card in cards] == [1, 0]


def test_clear_confirmation_cancels_when_the_view_changes(qapp, stack):
    cards = _split(stack, "fft_time")
    page = stack.page_for_mode["fft_time"]
    for card in cards:
        _plot_heatmap(card)
        card.canvas.set_remark_enabled(True)
        card.canvas.add_remark_at(5.0, 4.0)
    _focus(stack, "fft_time", 1)
    other = page.manager.new_view(activate=False)

    def _confirm(_count):
        page.manager.set_active(other)
        return True

    cards[0]._confirm_clear_annotations = _confirm
    cards[0]._clear_annotation_btn.click()
    qapp.processEvents()

    assert [card.canvas.remark_count() for card in cards] == [1, 1]


def test_clear_confirmation_can_be_cancelled(qapp, stack):
    cards = _split(stack, "order")
    _plot_heatmap(cards[1])
    cards[1].canvas.set_remark_enabled(True)
    cards[1].canvas.add_remark_at(5.0, 4.0)
    _focus(stack, "order", 1)
    cards[0]._confirm_clear_annotations = lambda count: False

    cards[0]._clear_annotation_btn.click()
    qapp.processEvents()

    assert cards[1].canvas.remark_count() == 1


def test_fft_annotation_api_targets_the_focused_pane(qapp, stack):
    cards = _split(stack, "fft")
    _focus(stack, "fft", 1)

    stack.set_annotation_enabled("fft", True)
    qapp.processEvents()

    assert _annotation_on(cards[0], "fft") is False
    assert _annotation_on(cards[1], "fft") is True
    assert _shared_annotation_checked(cards) is True


@pytest.mark.parametrize("mode", SECTIONS)
def test_split_mouse_mode_syncs_from_either_pane(qapp, stack, mode):
    cards = _split(stack, mode)
    if mode == "time":
        t = np.linspace(0.0, 1.0, 32)
        for card in cards:
            card.canvas.plot_channels(
                [("speed", True, t, np.sin(t), "#1769e0", "rpm", "file-a")],
            )
        qapp.processEvents()
    _focus(stack, mode, 1)
    for card in cards:
        card.toolbar.set_pan_mode()
    zoom_button = _context_zoom_button(cards[1].toolbar)
    assert zoom_button is not None

    zoom_button.click()
    qapp.processEvents()

    assert [card.toolbar.mode for card in cards] == ["zoom", "zoom"]
    assert _viewbox_modes(cards[0])
    assert all(mode_id == pg.ViewBox.RectMode for mode_id in _viewbox_modes(cards[0]))
    assert all(mode_id == pg.ViewBox.RectMode for mode_id in _viewbox_modes(cards[1]))
    assert _zoom_highlighted(cards[0]) is True

    cards[0].toolbar._actions_by_key["pan"].trigger()
    qapp.processEvents()
    assert [card.toolbar.mode for card in cards] == ["pan", "pan"]
    assert all(mode_id == pg.ViewBox.PanMode for mode_id in _viewbox_modes(cards[1]))


def test_mouse_mode_broadcast_does_not_recurse_or_touch_another_section(qapp, stack):
    fft_cards = _split(stack, "fft")
    order_cards = _split(stack, "order")
    stack.set_mode("fft")
    for card in fft_cards:
        card.toolbar.set_pan_mode()
    calls = []
    original = order_cards[0].toolbar.set_mouse_mode_broadcast

    def _forbidden(mode):
        calls.append(mode)
        return original(mode)

    order_cards[0].toolbar.set_mouse_mode_broadcast = _forbidden
    peer_calls = []
    fft_cards[0].toolbar.set_mouse_mode_broadcast = (
        lambda mode: peer_calls.append(mode)
    )

    fft_cards[1].toolbar.set_mouse_mode_broadcast("zoom")

    assert fft_cards[1].toolbar.mode == "zoom"
    assert fft_cards[0].toolbar.mode == "zoom"
    assert peer_calls == []
    assert calls == []
    assert order_cards[1].toolbar.mode != "zoom"


def test_new_split_pane_inherits_mouse_mode_without_duplicate_connections(qapp, stack):
    stack.set_mode("frf")
    page = stack.page_for_mode["frf"]
    page._cards[0].toolbar.set_zoom_mode()
    calls = []

    def _record(*_args):
        calls.append(1)

    page._sync_shared_nav_highlight = _record
    page.enter_split()
    page._configure_shared_toolbar()
    page._configure_shared_toolbar()
    right = page._cards[1].toolbar

    assert right.mode == "zoom"
    assert _viewbox_modes(page._cards[1])
    assert all(mode_id == pg.ViewBox.RectMode for mode_id in _viewbox_modes(page._cards[1]))
    calls.clear()
    right.set_pan_mode()
    assert calls == [1]

    page.exit_split()
    page.enter_split()
    assert page._cards[1].toolbar.mode == page._toolbar.mode


def test_duplicate_source_labels_keep_independent_y_history(qapp, stack):
    stack.set_mode("time")
    canvas = stack.canvas_time
    toolbar = stack._time_toolbar
    t = np.linspace(0.0, 10.0, 200)
    canvas.plot_channels(
        [
            ("same", True, t, np.sin(t), "#1769e0", "rpm", "file-a"),
            ("same", True, t, 100 * np.cos(t), "#ef4444", "rpm", "file-b"),
        ],
        mode="subplot",
    )
    qapp.processEvents()
    pairs = list(canvas._channel_lines.composite_items())
    assert len(pairs) == 2
    snap = toolbar._snapshot_view()
    assert len(snap) == len(pairs)
    original = [tuple(pair[0].get_ylim()) for _key, _label, pair in pairs]
    for _key, _label, pair in pairs:
        pair[0].set_ylim(1000, 2000)

    toolbar._restore_view(snap)

    restored = [tuple(pair[0].get_ylim()) for _key, _label, pair in pairs]
    assert restored == pytest.approx(original)
    assert restored[0] != pytest.approx((1000, 2000))


def test_ambiguous_display_name_snapshot_does_not_guess(qapp, stack):
    stack.set_mode("time")
    canvas = stack.canvas_time
    toolbar = stack._time_toolbar
    t = np.linspace(0.0, 4.0, 40)
    canvas.plot_channels(
        [
            ("same", True, t, np.sin(t), "#1769e0", "rpm", "file-a"),
            ("same", True, t, np.cos(t) * 20, "#ef4444", "rpm", "file-b"),
        ],
        mode="subplot",
    )
    qapp.processEvents()
    pairs = list(canvas._channel_lines.composite_items())
    for _key, _label, pair in pairs:
        pair[0].set_ylim(-3, 3)
    before = [tuple(pair[0].get_ylim()) for _key, _label, pair in pairs]

    toolbar._restore_view({"same": ((0.0, 1.0), (50.0, 80.0))})

    after = [tuple(pair[0].get_ylim()) for _key, _label, pair in pairs]
    assert after == pytest.approx(before)


def test_pending_gesture_can_go_back_immediately(qapp, stack):
    stack.set_mode("time")
    canvas = stack.canvas_time
    toolbar = stack._time_toolbar
    t = np.linspace(0.0, 10.0, 200)
    canvas.plot_channels(
        [("speed", True, t, np.sin(t), "#1769e0", "rpm", "file-a")],
    )
    qapp.processEvents()
    baseline = canvas._primary_xaxis_ax.get_xlim()
    toolbar._history_timer.stop()
    _emit_time_pan(canvas, 2.0, 4.0)
    assert toolbar._history_timer.isActive()
    assert toolbar._history_timer.interval() == 180
    assert toolbar._actions_by_key["back"].isEnabled()

    toolbar._actions_by_key["back"].trigger()
    qapp.processEvents()

    assert canvas._primary_xaxis_ax.get_xlim() == pytest.approx(baseline)
    assert toolbar._history_timer.isActive() is False
    depth = len(toolbar._view_stack)
    toolbar._on_history_timeout()
    assert len(toolbar._view_stack) == depth


def test_home_commits_pending_range_then_the_home_range(qapp, stack):
    stack.set_mode("time")
    canvas = stack.canvas_time
    toolbar = stack._time_toolbar
    t = np.linspace(0.0, 10.0, 200)
    canvas.plot_channels(
        [("speed", True, t, np.sin(t), "#1769e0", "rpm", "file-a")],
    )
    qapp.processEvents()
    _emit_time_pan(canvas, 2.0, 4.0)
    toolbar.home()
    qapp.processEvents()
    assert canvas._primary_xaxis_ax.get_xlim() != pytest.approx((2.0, 4.0))

    toolbar.back()
    qapp.processEvents()
    assert canvas._primary_xaxis_ax.get_xlim() == pytest.approx((2.0, 4.0))


def test_replot_discards_pending_history_before_replacing_curves(qapp, stack):
    stack.set_mode("time")
    canvas = stack.canvas_time
    toolbar = stack._time_toolbar
    t = np.linspace(0.0, 10.0, 80)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "rpm", "file-a")]
    canvas.plot_channels(rows)
    qapp.processEvents()
    _emit_time_pan(canvas, 1.0, 2.0)
    assert toolbar._history_commit_armed is True
    before = len(toolbar._view_stack)
    import mf4_analyzer.ui.pg_canvas._shared as shared

    seen = {}
    real_notify = shared.notify_content_replacement

    def _spy(obj):
        seen["xlim"] = tuple(obj._primary_xaxis_ax.get_xlim())
        seen["armed"] = toolbar._history_commit_armed
        real_notify(obj)

    shared.notify_content_replacement = _spy
    try:
        canvas.plot_channels(rows)
        qapp.processEvents()
    finally:
        shared.notify_content_replacement = real_notify

    assert seen["armed"] is True
    assert seen["xlim"] == pytest.approx((1.0, 2.0))
    assert toolbar._history_commit_armed is False
    assert toolbar._history_timer.isActive() is False
    assert len(toolbar._view_stack) == before


def test_heatmap_wheel_gesture_restores_main_range_and_enables_back(qapp, stack):
    stack.set_mode("fft_time")
    canvas = stack.canvas_fft_time
    toolbar = stack.page_for_mode["fft_time"]._cards[0].toolbar
    assert toolbar._actions_by_key["back"].isEnabled() is False
    _plot_heatmap(stack.page_for_mode["fft_time"]._cards[0])
    qapp.processEvents()
    baseline = canvas.capture_xy_viewport()
    assert baseline is not None
    assert toolbar._view_stack

    canvas._handle_wheel_dispatch(
        delta=120,
        modifiers=Qt.ShiftModifier,
        x_pos=5.0,
        y_pos=4.0,
        view_box=canvas._plot.vb,
    )
    qapp.processEvents()
    zoomed = canvas.capture_xy_viewport()
    assert zoomed[1] != pytest.approx(baseline[1])
    assert toolbar._actions_by_key["back"].isEnabled() is True
    assert canvas._slice_plot.vb.viewRange()[0] == pytest.approx(zoomed[1])

    toolbar.back()
    qapp.processEvents()

    restored = canvas.capture_xy_viewport()
    assert restored[0] == pytest.approx(baseline[0])
    assert restored[1] == pytest.approx(baseline[1])
    assert canvas._slice_plot.vb.viewRange()[0] == pytest.approx(restored[1])


def test_heatmap_history_restore_does_not_restack(qapp, stack):
    stack.set_mode("order")
    card = stack.page_for_mode["order"]._cards[0]
    canvas = card.canvas
    toolbar = card.toolbar
    _plot_heatmap(card)
    qapp.processEvents()
    canvas._plot.vb.setXRange(2.0, 4.0, padding=0)
    canvas._plot.vb.sigRangeChangedManually.emit([True, False])
    qapp.processEvents()
    depth_before = len(toolbar._view_stack)
    toolbar.back()
    toolbar._on_history_timeout()
    qapp.processEvents()
    assert len(toolbar._view_stack) == depth_before + 1


def test_save_and_copy_share_the_live_readout(qapp, stack, monkeypatch, tmp_path):
    stack.set_mode("time")
    canvas = stack.canvas_time
    t = np.linspace(0.0, 10.0, 80)
    canvas.plot_channels(
        [("same", True, t, np.sin(t), "#1769e0", "rpm", "file-a")],
    )
    qapp.processEvents()
    stack.set_cursor_mode("single")
    stack._pill.setStyleSheet(
        "background-color: rgb(250, 1, 200); color: rgb(250, 1, 200);"
    )
    stack._pill.set_primary("READOUT 12345")
    stack._pill.resize(180, 36)
    stack._pill.show()
    stack._pill.move(canvas.mapTo(stack.stack, QPoint(80, 70)))
    qapp.processEvents()

    copied = []
    stack.image_captured.connect(copied.append)
    stack._time_card._copy_btn.click()
    qapp.processEvents()
    assert copied
    destination = tmp_path / "saved.png"
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), "PNG (*.png)"),
    )
    stack._time_toolbar._actions_by_key["save"].trigger()
    qapp.processEvents()

    saved = QImage(str(destination))
    copied_image = copied[-1].toImage()
    marker = QColor(250, 1, 200)
    saved_hits = _count_color(saved, marker)
    raw_hits = _count_color(canvas.grab_pixmap().toImage(), marker)
    assert saved.size() == copied_image.size()
    assert saved == copied_image
    assert saved_hits > raw_hits
    assert saved_hits > 0


def test_configured_save_provider_failure_does_not_write_a_fallback(qapp, stack, monkeypatch, tmp_path):
    destination = tmp_path / "missing.png"
    warnings = []
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), "PNG (*.png)"),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.toolbar.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    stack._time_toolbar._save_pixmap_provider = lambda: None
    stack._time_toolbar.save_figure()
    assert warnings
    assert destination.exists() is False


def test_save_dialog_cancel_does_not_grab(qapp, stack, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    stack._time_toolbar._save_pixmap_provider = lambda: calls.append("grab") or None
    stack._time_toolbar.save_figure()
    assert calls == []


def _count_color(image, color):
    hits = 0
    target = (color.red(), color.green(), color.blue())
    step_x = max(1, image.width() // 80)
    step_y = max(1, image.height() // 80)
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            pixel = image.pixelColor(x, y)
            if (pixel.red(), pixel.green(), pixel.blue()) == target:
                hits += 1
    return hits
