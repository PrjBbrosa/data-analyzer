"""UltraView P3-2 viewport: zoom-at-cursor math and board zoom/pan channels."""
from __future__ import annotations

import math
from dataclasses import replace

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PyQt5.QtGui import QColor, QCursor, QImage, QMouseEvent, QNativeGestureEvent, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    grid_metrics,
    screen_grid_metrics,
)
from mf4_analyzer.ui.chart_stack.ultraview import widgets as uv_widgets
from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    RAIL_TO_CANVAS_GAP,
    RAIL_WIDTH,
    SAFE_MARGIN,
)
from mf4_analyzer.ui.chart_stack.ultraview.viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    SMOOTH_DELAY_MS,
    ZOOM_MAX,
    ZOOM_MIN,
    BoardViewport,
    board_fit_zoom,
    clamp_zoom,
    default_board_zoom,
    fit_zoom,
    focus_grab_scale,
    initial_viewport,
    lod_level,
    lod_visibility,
    needs_focus_recapture,
    scale_grid_metrics,
    two_card_working_frame,
    wheel_event_delta_y,
    wheel_zoom_factor,
    zoom_at_cursor,
    zoom_percent,
    zoom_to_rect,
    zoomed_viewport_size,
    FOCUS_PREVIEW_RATIO,
    FIT_CONTENT_MARGIN,
    NEW_BOARD_ZOOM_MAX,
    BOARD_FIT_ZOOM_MAX,
    LOD_FOOTER_HIDE,
    LOD_FULL,
    LOD_HYSTERESIS,
    LOD_NO_FOOTER,
    LOD_TITLE_ONLY,
    LOD_TITLE_ONLY_ZOOM,
    normalize_viewport_payload,
)
from mf4_analyzer.ui.ultraview_state import (
    FreeGridPlacement,
    GridRect,
    LAYOUT_MODE_FREE_GRID,
    STATUS_STALE,
    add_ref,
    board_to_payload,
    default_board,
    make_ref,
    normalize_board_payload,
    set_layout,
)
from mf4_analyzer.ui_kit import load_stylesheet

from tests.ui.test_ultraview_page import (
    FakePreview,
    _Harness,
    _image,
    _prepare_free_grid,
    _send_mouse_move,
)


def _logical_under_cursor(zoom, cursor, scroll, origin=(0.0, 0.0)):
    return (
        (scroll[0] + cursor[0] - origin[0]) / zoom,
        (scroll[1] + cursor[1] - origin[1]) / zoom,
    )


def test_clamp_zoom_and_percent_cover_the_product_range():
    assert clamp_zoom(0.1) == ZOOM_MIN
    assert clamp_zoom(8) == ZOOM_MAX
    assert clamp_zoom(float("nan")) == 1.0
    assert clamp_zoom("nope") == 1.0
    assert zoom_percent(1.0) == 100
    assert zoom_percent(0.25) == 25
    assert zoom_percent(2.0) == 200


def test_zoom_clamps_at_three_hundred_percent():
    assert ZOOM_MAX == 3.0
    assert clamp_zoom(5.0) == ZOOM_MAX
    assert zoom_percent(ZOOM_MAX) == 300


def test_zoom_at_cursor_keeps_the_logical_point_fixed():
    cursor = (400.0, 220.0)
    scroll = (80.0, 40.0)
    before, after = 1.0, 2.0
    logical = _logical_under_cursor(before, cursor, scroll)
    new_scroll = zoom_at_cursor(before, after, cursor, scroll)
    restored = _logical_under_cursor(after, cursor, new_scroll)
    assert restored == pytest.approx(logical)
    back = zoom_at_cursor(after, before, cursor, new_scroll)
    assert _logical_under_cursor(before, cursor, back) == pytest.approx(logical)


def test_zoom_at_cursor_accounts_for_fit_origin_offset():
    origin = (float(SAFE_MARGIN + RAIL_WIDTH + RAIL_TO_CANVAS_GAP), 64.0)
    cursor = (400.0, 220.0)
    scroll = (0.0, 0.0)
    before, after = 1.0, 1.1
    logical = _logical_under_cursor(before, cursor, scroll, origin)
    new_scroll = zoom_at_cursor(before, after, cursor, scroll, origin)
    restored = _logical_under_cursor(after, cursor, new_scroll, origin)
    assert restored == pytest.approx(logical)


def test_scale_grid_metrics_is_identity_at_1x_and_uniform_at_2x():
    placements = [
        FreeGridPlacement(make_ref("time", "a"), GridRect(0, 0, 4, 3)),
    ]
    base = grid_metrics((1280, 800), placements)
    same = scale_grid_metrics(base, 1.0)
    assert same == base
    doubled = scale_grid_metrics(base, 2.0)
    assert doubled.board_width == base.board_width * 2
    assert doubled.board_height == base.board_height * 2
    assert doubled.column_width == base.column_width * 2
    assert doubled.row_height == base.row_height * 2
    assert doubled.gutter == base.gutter * 2
    assert doubled.padding == base.padding * 2


def test_zoomed_viewport_and_fit_zoom_clamp_to_product_range():
    assert zoomed_viewport_size((800, 400), 2.0) == (1600, 800)
    assert fit_zoom((2000, 1000), (500, 400)) == ZOOM_MIN
    assert fit_zoom((400, 200), (800, 800)) == BOARD_FIT_ZOOM_MAX
    assert wheel_zoom_factor(120) == pytest.approx(1.1)
    assert wheel_zoom_factor(-120) == pytest.approx(1.1 ** -1)
    assert wheel_event_delta_y(0, 120) == 120
    assert wheel_zoom_factor(0, 120) == pytest.approx(1.1)
    assert wheel_zoom_factor(0, 0) == 1.0


def test_two_card_working_frame_uses_cell_pitch_not_full_canvas():
    metrics = screen_grid_metrics(())
    frame = two_card_working_frame(metrics)
    assert frame[0] < float(metrics.board_width)
    assert frame[1] < float(metrics.board_height)
    columns = 8
    rows = 3
    expected_w = (
        2.0 * metrics.padding
        + columns * metrics.column_width
        + (columns - 1) * metrics.gutter
    )
    expected_h = (
        2.0 * metrics.padding
        + rows * metrics.row_height
        + (rows - 1) * metrics.gutter
    )
    assert frame == pytest.approx((expected_w, expected_h))


def test_board_fit_zoom_never_exceeds_100_percent():
    tiny_card = (80.0, 60.0)
    huge_view = (2560.0, 1440.0)
    assert board_fit_zoom(tiny_card, huge_view) == pytest.approx(BOARD_FIT_ZOOM_MAX)
    assert board_fit_zoom(tiny_card, huge_view) <= 1.0
    metrics = screen_grid_metrics(())
    frame = two_card_working_frame(metrics)
    assert board_fit_zoom(frame, huge_view) == pytest.approx(1.0)
    cramped = board_fit_zoom((2000.0, 1200.0), (800.0, 500.0))
    assert ZOOM_MIN <= cramped < 1.0


def test_new_board_default_zoom_never_exceeds_66_percent():
    metrics = screen_grid_metrics(())
    frame = two_card_working_frame(metrics)
    huge_view = (2560.0, 1440.0)
    zoom = default_board_zoom(huge_view, frame)
    unconstrained = board_fit_zoom(frame, huge_view)
    assert unconstrained > NEW_BOARD_ZOOM_MAX
    assert zoom == pytest.approx(NEW_BOARD_ZOOM_MAX)
    assert zoom <= 0.66
    payload = initial_viewport(huge_view, frame)
    assert payload["zoom"] == pytest.approx(NEW_BOARD_ZOOM_MAX)
    assert payload["center_x"] == pytest.approx(frame[0] / 2.0)
    assert payload["center_y"] == pytest.approx(frame[1] / 2.0)
    small_view = (200.0, 140.0)
    fitted = default_board_zoom(small_view, frame)
    assert fitted == pytest.approx(board_fit_zoom(frame, small_view))
    assert fitted < NEW_BOARD_ZOOM_MAX


def test_empty_board_fit_caps_at_100_new_board_caps_at_66():
    metrics = screen_grid_metrics(())
    frame = two_card_working_frame(metrics)
    huge_view = (4000.0, 3000.0)
    assert board_fit_zoom(frame, huge_view) == pytest.approx(1.0)
    assert default_board_zoom(huge_view, frame) == pytest.approx(NEW_BOARD_ZOOM_MAX)


def test_focus_zoom_to_rect_can_still_reach_300_percent():
    zoom, center = zoom_to_rect((10.0, 20.0, 40.0, 30.0), (2000.0, 1500.0))
    assert zoom == ZOOM_MAX
    assert center == pytest.approx((30.0, 35.0))


def test_board_viewport_owns_zoom_quality_and_pan_delta():
    viewport = BoardViewport()
    assert viewport.zoom() == 1.0
    assert viewport.quality() == QUALITY_SMOOTH
    assert viewport.set_zoom(5.0) == ZOOM_MAX
    viewport.set_quality(QUALITY_FAST)
    assert viewport.quality() == QUALITY_FAST
    viewport.begin_pan((10.0, 20.0))
    assert viewport.is_panning()
    assert viewport.update_pan((6.0, 12.0)) == pytest.approx((4.0, 8.0))
    viewport.end_pan()
    assert not viewport.is_panning()


def _wheel(
    widget,
    delta_y,
    modifiers=Qt.ControlModifier,
    *,
    pos=None,
    global_pos=None,
    pixel_delta_y=0,
    angle_delta_y=None,
):
    if pos is None:
        pos = QPoint(widget.width() // 2, widget.height() // 2)
    if global_pos is None:
        global_pos = widget.mapToGlobal(pos)
    if angle_delta_y is None:
        angle_delta_y = delta_y
    event = QWheelEvent(
        QPointF(pos),
        QPointF(global_pos),
        QPoint(0, pixel_delta_y),
        QPoint(0, angle_delta_y),
        Qt.NoButton,
        modifiers,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return pos


def _viewport_cursor(page, widget, local_pos):
    mapped = page.board_scroll_area().viewport().mapFromGlobal(
        widget.mapToGlobal(local_pos)
    )
    return (float(mapped.x()), float(mapped.y()))


def _viewport_logical(page, cursor):
    scroll = page.board_scroll_area()
    origin = page._board_content_origin()
    return _logical_under_cursor(
        page.board_zoom(),
        cursor,
        (
            float(scroll.horizontalScrollBar().value()),
            float(scroll.verticalScrollBar().value()),
        ),
        origin,
    )


def test_toolbar_exposes_zoom_cluster(qtbot):
    harness = _Harness(qtbot)
    toolbar = harness.page.board_toolbar()
    assert toolbar.findChild(QToolButton, "ultraViewZoomOutButton") is not None
    assert toolbar.findChild(QLabel, "ultraViewZoomLabel") is not None
    assert toolbar.findChild(QToolButton, "ultraViewZoomInButton") is not None
    assert toolbar.findChild(QToolButton, "ultraViewZoomFitButton") is not None
    assert toolbar.findChild(QToolButton, "ultraViewZoomResetButton") is not None
    harness.page.zoom_reset()
    assert toolbar.zoom_label().text() == "100%"


def test_page_zoom_clamps_and_scales_free_grid(qtbot):
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    harness.page.zoom_reset()
    qtbot.wait(10)
    base = free.metrics()
    width_1x = cards[0].width()
    harness.page.set_board_zoom(5.0)
    assert harness.page.board_zoom() == ZOOM_MAX
    assert free.metrics().column_width == max(1, round(base.column_width * ZOOM_MAX))
    assert free.metrics().row_height == max(1, round(base.row_height * ZOOM_MAX))
    assert cards[0].width() == pytest.approx(width_1x * ZOOM_MAX, rel=0.08)
    harness.page.set_board_zoom(0.1)
    assert harness.page.board_zoom() == ZOOM_MIN
    assert harness.page.board_toolbar().zoom_label().text() == "25%"
    harness.page.zoom_reset()
    assert harness.page.board_zoom() == 1.0
    assert harness.page.board_toolbar().zoom_label().text() == "100%"


def test_ctrl_wheel_zooms_plain_wheel_does_not(qtbot):
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a")
    before = harness.page.board_zoom()
    _wheel(cards[0], 120, modifiers=Qt.NoModifier)
    assert harness.page.board_zoom() == before
    _wheel(cards[0], 120, modifiers=Qt.ControlModifier)
    assert harness.page.board_zoom() > before


def test_ctrl_wheel_keeps_the_logical_point_under_the_cursor(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    local = QPoint(max(24, card.width() * 2 // 3), max(24, card.height() * 2 // 3))
    cursor = _viewport_cursor(harness.page, card, local)
    assert cursor[0] > 20 and cursor[1] > 20
    before_zoom = harness.page.board_zoom()
    logical_before = _viewport_logical(harness.page, cursor)
    _wheel(card, 120, pos=local)
    assert harness.page.board_zoom() > before_zoom
    logical_after = _viewport_logical(harness.page, cursor)
    assert logical_after == pytest.approx(logical_before, abs=4.0)
    scroll = harness.page.board_scroll_area()
    assert (
        scroll.horizontalScrollBar().value() != 0
        or scroll.verticalScrollBar().value() != 0
    )


def test_ctrl_wheel_anchors_when_global_position_is_zero(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    local = QPoint(max(24, card.width() * 2 // 3), max(24, card.height() * 2 // 3))
    cursor = _viewport_cursor(harness.page, card, local)
    logical_before = _viewport_logical(harness.page, cursor)
    before = harness.page.board_zoom()
    _wheel(card, 120, pos=local, global_pos=QPoint(0, 0))
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > before
    assert logical_after == pytest.approx(logical_before, abs=4.0)
    scroll = harness.page.board_scroll_area()
    assert (
        scroll.horizontalScrollBar().value() != 0
        or scroll.verticalScrollBar().value() != 0
    )


def test_ctrl_wheel_anchors_when_local_and_global_are_zero(qtbot):
    """Cocoa pinch-as-wheel often reports both local and global as (0, 0)."""
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    local = QPoint(max(24, card.width() * 2 // 3), max(24, card.height() * 2 // 3))
    QCursor.setPos(card.mapToGlobal(local))
    cursor = _viewport_cursor(harness.page, card, local)
    logical_before = _viewport_logical(harness.page, cursor)
    before = harness.page.board_zoom()
    _wheel(card, 120, pos=QPoint(0, 0), global_pos=QPoint(0, 0))
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > before
    assert logical_after == pytest.approx(logical_before, abs=4.0)
    scroll = harness.page.board_scroll_area()
    assert (
        scroll.horizontalScrollBar().value() != 0
        or scroll.verticalScrollBar().value() != 0
    )


def test_pinch_anchors_when_native_gesture_positions_are_zero(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    local = QPoint(max(24, card.width() * 2 // 3), max(24, card.height() * 2 // 3))
    QCursor.setPos(card.mapToGlobal(local))
    cursor = _viewport_cursor(harness.page, card, local)
    logical_before = _viewport_logical(harness.page, cursor)
    before = harness.page.board_zoom()
    event = QNativeGestureEvent(
        Qt.ZoomNativeGesture,
        QPointF(0, 0),
        QPointF(0, 0),
        QPointF(0, 0),
        0.1,
        0,
        0,
    )
    QApplication.sendEvent(card, event)
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > before
    assert logical_after == pytest.approx(logical_before, abs=4.0)
    scroll = harness.page.board_scroll_area()
    assert (
        scroll.horizontalScrollBar().value() != 0
        or scroll.verticalScrollBar().value() != 0
    )


def test_ctrl_wheel_prefers_global_when_local_is_from_a_child(qtbot):
    """Qt does not remap pos() when an ignored child wheel bubbles to the card."""
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    image = card._image
    img_local = QPoint(
        max(24, image.width() * 2 // 3),
        max(24, image.height() * 2 // 3),
    )
    img_global = image.mapToGlobal(img_local)
    mapped = harness.page.board_scroll_area().viewport().mapFromGlobal(img_global)
    cursor = (float(mapped.x()), float(mapped.y()))
    logical_before = _viewport_logical(harness.page, cursor)
    before = harness.page.board_zoom()
    _wheel(card, 120, pos=img_local, global_pos=img_global)
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > before
    assert logical_after == pytest.approx(logical_before, abs=4.0)


def test_ctrl_wheel_zooms_from_pixel_delta_when_angle_delta_is_zero(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    before = harness.page.board_zoom()
    _wheel(cards[0], 0, pixel_delta_y=120, angle_delta_y=0)
    assert harness.page.board_zoom() > before


def test_space_drag_and_middle_button_pan_the_scroll(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "a")
    harness.page.set_board_zoom(2.0)
    scroll = harness.page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    horizontal.setValue(40)
    start_value = horizontal.value()
    start = QPoint(80, 40)
    harness.page.note_space(True)
    QTest_mouse = QMouseEvent(
        QEvent.MouseButtonPress,
        start,
        free.mapToGlobal(start),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(free, QTest_mouse)
    _send_mouse_move(free, QPoint(40, 40), buttons=Qt.LeftButton)
    release = QMouseEvent(
        QEvent.MouseButtonRelease,
        QPoint(40, 40),
        free.mapToGlobal(QPoint(40, 40)),
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(free, release)
    harness.page.note_space(False)
    assert horizontal.value() != start_value

    start_value = horizontal.value()
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        start,
        free.mapToGlobal(start),
        Qt.MiddleButton,
        Qt.MiddleButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(free, press)
    _send_mouse_move(free, QPoint(20, 40), buttons=Qt.MiddleButton)
    mid_release = QMouseEvent(
        QEvent.MouseButtonRelease,
        QPoint(20, 40),
        free.mapToGlobal(QPoint(20, 40)),
        Qt.MiddleButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(free, mid_release)
    assert horizontal.value() != start_value


def test_zoom_uses_fast_transform_then_smooth_after_300ms(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "a")
    harness.page.set_board_zoom(1.2)
    assert harness.page.preview_quality() == QUALITY_FAST
    timer = harness.page.smooth_preview_timer()
    assert timer.isSingleShot()
    assert timer.interval() == SMOOTH_DELAY_MS
    timer.timeout.emit()
    assert harness.page.preview_quality() == QUALITY_SMOOTH


def test_zoom_does_not_compose_a_full_board_image(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "a")
    calls = []

    def _forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("zoom must not allocate a full-board compose")

    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.ultraview.widgets.compose_board",
        _forbidden,
    )
    harness.page.set_board_zoom(1.4)
    harness.page.set_board_zoom(1.8)
    assert calls == []


def test_card_reuses_scaled_preview_buffer_when_size_is_unchanged(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    card = cards[0]
    image = QImage(64, 48, QImage.Format_ARGB32)
    image.fill(Qt.blue)
    card._raw_image = image
    card.set_preview_quality(QUALITY_FAST)
    card._fit_card_image()
    first = card.scale_buffer()
    assert first is not None
    card._fit_card_image()
    assert card.scale_buffer() is first


def test_card_preview_buffer_uses_physical_target_and_dpr_metadata(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "retina")
    card = cards[0]
    image = QImage(2000, 1500, QImage.Format_ARGB32)
    image.fill(Qt.blue)
    monkeypatch.setattr(uv_widgets, "_effective_device_pixel_ratio", lambda _widget: 2.0)

    card._raw_image = image
    card._source_pixmap = None
    card._scale_buffer = None
    card._scale_key = None
    card._fit_card_image()

    pixmap = card.scale_buffer()
    assert pixmap is not None
    logical_box = card._preview_fit_size()
    physical_box = QSize(logical_box.width() * 2, logical_box.height() * 2)
    expected = image.size()
    expected.scale(physical_box, Qt.KeepAspectRatio)
    assert pixmap.size() == expected
    assert pixmap.devicePixelRatioF() == pytest.approx(2.0)
    assert pixmap.width() / pixmap.devicePixelRatioF() == pytest.approx(expected.width() / 2.0)
    assert pixmap.height() / pixmap.devicePixelRatioF() == pytest.approx(expected.height() / 2.0)


def test_title_only_lod_skips_pixmap_scaling_until_preview_returns(qtbot, monkeypatch):
    """§4.3: TITLE_ONLY hides the preview label, so a new image arriving on
    that tier must not pay for a scale nobody can see — even before layout
    has collapsed the (invisible) preview label's geometry — and growing
    back to a preview-showing tier must produce a correctly sized pixmap,
    not a stale/missing one.
    """
    from mf4_analyzer.ui.chart_stack.ultraview.widgets import UltraViewCard

    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    card = cards[0]
    card.resize(300, 220)

    card.apply_lod(LOD_TITLE_ONLY, show_title=True, show_source=False)
    assert not lod_visibility(LOD_TITLE_ONLY).preview
    assert not card._image.isVisible()

    calls = []
    original = UltraViewCard._fit_card_image

    def _spy(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(UltraViewCard, "_fit_card_image", _spy)

    fresh = QImage(400, 300, QImage.Format_ARGB32)
    fresh.fill(Qt.blue)
    card.apply_model(replace(card.model(), image=fresh))

    # apply_model must not even attempt a scale nobody can see, regardless
    # of whether the hidden label's geometry has already collapsed.
    assert card._raw_image is not None
    assert calls == []

    card.apply_lod(LOD_FULL, show_title=True, show_source=True)
    assert card._image.isVisible()
    assert calls == [card]
    assert card._scale_buffer is not None
    pixmap = card._image.pixmap()
    assert pixmap is not None and not pixmap.isNull()


def test_card_preview_keeps_top_pixels_inside_qss_padding(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    card = cards[0]
    image = QImage(400, 300, QImage.Format_ARGB32)
    image.fill(QColor("#1e293b"))
    for y in range(3):
        for x in range(400):
            image.setPixelColor(x, y, QColor("#ff00ff"))
    card._raw_image = image
    card._source_pixmap = None
    card._scale_buffer = None
    card._scale_key = None
    card._fit_card_image()
    qapp.processEvents()
    contents = card._image.contentsRect()
    assert contents.top() > 0
    assert contents.left() > 0
    grab = card._image.grab().toImage()
    found = False
    for y in range(contents.top(), min(contents.top() + 16, contents.bottom())):
        for x in range(contents.left(), contents.right(), 8):
            pixel = QColor(grab.pixel(x, y))
            if pixel.red() > 200 and pixel.blue() > 200 and pixel.green() < 80:
                found = True
                break
        if found:
            break
    assert found, "top plot pixels must remain visible inside the padded image label"


def test_lod_hysteresis_does_not_chatter_at_the_threshold():
    assert lod_level(1.0) == LOD_FULL
    assert lod_level(0.50, LOD_FULL) == LOD_NO_FOOTER
    assert lod_level(0.58, LOD_NO_FOOTER) == LOD_NO_FOOTER
    assert lod_level(0.66, LOD_NO_FOOTER) == LOD_FULL
    assert lod_level(0.35, LOD_NO_FOOTER) == LOD_TITLE_ONLY
    assert lod_level(0.42, LOD_TITLE_ONLY) == LOD_TITLE_ONLY


_LOD_ORDER = (LOD_TITLE_ONLY, LOD_NO_FOOTER, LOD_FULL)
# Boundary between two neighbouring bands, keyed by the pair of band names.
_LOD_BOUNDARY = {
    frozenset((LOD_TITLE_ONLY, LOD_NO_FOOTER)): LOD_TITLE_ONLY_ZOOM,
    frozenset((LOD_NO_FOOTER, LOD_FULL)): LOD_FOOTER_HIDE,
}


def _static_lod_band(zoom: float) -> str:
    """The single threshold table, spelled out once for the invariant."""
    if zoom < LOD_TITLE_ONLY_ZOOM:
        return LOD_TITLE_ONLY
    if zoom < LOD_FOOTER_HIDE:
        return LOD_NO_FOOTER
    return LOD_FULL


def _lod_sweep() -> tuple[float, ...]:
    steps = tuple(round(ZOOM_MIN + index * 0.005, 3) for index in range(0, 351))
    edges = (0.355, 0.359, 0.36, 0.37, 0.375, 0.399, 0.401, 0.435, 0.441, 0.559, 0.639)
    return tuple(sorted(set(steps + edges)))


@pytest.mark.parametrize("previous", (None, LOD_FULL, LOD_NO_FOOTER, LOD_TITLE_ONLY))
def test_lod_state_boundaries_use_the_single_threshold_table(previous):
    """Any start band × any target zoom lands in the static band or a *neighbouring*
    sticky band — never a third band.  Hysteresis is not a second table and it may
    only widen the boundary adjacent to the current band (review 2026-08-15 P1-3:
    ``lod_level(0.37, FULL)`` returned ``no_footer``, skipping ``title_only``)."""
    for zoom in _lod_sweep():
        result = lod_level(zoom, previous)
        static = _static_lod_band(zoom)
        if previous is None:
            assert result == static, f"zoom={zoom} previous={previous}"
            continue
        assert result in {static, previous}, (
            f"zoom={zoom} previous={previous} landed on {result}, which is neither "
            f"the static band {static} nor the sticky start band"
        )
        if result == static:
            continue
        # Sticky only across ONE adjacent boundary, and only inside the hysteresis band.
        assert abs(_LOD_ORDER.index(result) - _LOD_ORDER.index(static)) == 1, (
            f"zoom={zoom} stayed on non-adjacent band {result} (static {static})"
        )
        boundary = _LOD_BOUNDARY[frozenset((result, static))]
        assert abs(zoom - boundary) <= LOD_HYSTERESIS + 1e-9, (
            f"zoom={zoom} stuck on {result} beyond the {boundary} ± "
            f"{LOD_HYSTERESIS} hysteresis band"
        )


@pytest.mark.parametrize("zoom", (0.36, 0.37, 0.38, 0.39, 0.399))
def test_full_lod_zoomed_far_out_lands_on_title_only(zoom):
    """Zooming 100% → 36-39.9% must reach ``title_only``; the pre-fix double-boundary
    hysteresis parked the whole band on ``no_footer`` and kept previews rendering."""
    assert lod_level(zoom, LOD_FULL) == LOD_TITLE_ONLY


def test_lod_static_bands_and_single_boundary_stickiness():
    assert lod_level(0.60) == LOD_FULL
    assert lod_level(0.59) == LOD_NO_FOOTER
    assert lod_level(0.40) == LOD_NO_FOOTER
    assert lod_level(0.39) == LOD_TITLE_ONLY
    assert lod_level(1.00) == LOD_FULL
    assert lod_level(0.55) == LOD_NO_FOOTER
    assert lod_level(0.35) == LOD_TITLE_ONLY
    # Crossing down from full still uses the same hide-footer constant ± hysteresis.
    assert lod_level(0.59, LOD_FULL) == LOD_FULL
    assert lod_level(0.55, LOD_FULL) == LOD_NO_FOOTER
    assert lod_level(0.40, LOD_TITLE_ONLY) == LOD_TITLE_ONLY
    assert lod_level(0.39, LOD_NO_FOOTER) == LOD_TITLE_ONLY
    # ...and the far boundary stays put, in both directions.
    assert lod_level(0.62, LOD_TITLE_ONLY) == LOD_FULL
    assert lod_level(0.37, LOD_FULL) == LOD_TITLE_ONLY


def test_lod_visibility_table_is_owned_by_viewport():
    full = lod_visibility(lod_level(1.0))
    compact = lod_visibility(lod_level(0.55))
    title = lod_visibility(lod_level(0.35))
    assert (full.title, full.type_chip, full.trust, full.preview, full.footer, full.body_actions) == (
        True,
        True,
        True,
        True,
        True,
        True,
    )
    assert (compact.title, compact.type_chip, compact.trust, compact.preview, compact.footer) == (
        True,
        True,
        True,
        True,
        False,
    )
    assert compact.body_actions is True
    assert (title.title, title.type_chip, title.trust) == (True, True, True)
    assert title.preview is False
    assert title.footer is False
    assert title.body_actions is False
    assert lod_visibility(LOD_NO_FOOTER) is lod_visibility(lod_level(0.55))
    assert lod_visibility(LOD_TITLE_ONLY) is lod_visibility(lod_level(0.35))


def test_fit_and_zoom_to_card_end_state(qtbot):
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    harness.page.zoom_fit()
    viewport = harness.page.board_scroll_area().viewport()
    content = free.content_rect_1x()
    fit = harness.page._content_fit_rect()
    expected_zoom = board_fit_zoom(
        (float(content[2]), float(content[3])),
        (float(fit.width), float(fit.height)),
    )
    assert harness.page.board_zoom() == pytest.approx(expected_zoom)
    card = cards[0]
    harness.page.zoom_to_card("time", "a", animate=False)
    zoomed = card.geometry()
    assert zoomed.width() <= viewport.width()
    assert zoomed.height() <= viewport.height()
    assert zoomed.width() >= viewport.width() * 0.7 or zoomed.height() >= viewport.height() * 0.7
    visible = viewport.rect().intersects(
        QRect(card.mapTo(viewport, QPoint(0, 0)), card.size())
    )
    assert visible


def test_canvas_is_full_bleed_and_fit_parks_cards_in_the_safe_zone(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(1280, 800)
    qtbot.wait(20)
    host = harness.page._canvas_host
    scroll = harness.page.board_scroll_area()
    assert scroll.x() == 0
    assert scroll.y() == 0
    assert scroll.width() >= host.width() - 2
    assert scroll.height() >= host.height() - 2

    _prepare_free_grid(harness, qtbot, "a")
    harness.page.zoom_fit()
    qtbot.wait(10)
    card = harness.page.card_widget("time", "a")
    assert card is not None
    top_left = card.mapTo(host, QPoint(0, 0))
    island_bottom = harness.page._board_island.geometry().bottom()
    rail_right = harness.page._tool_rail.geometry().right()
    assert top_left.y() >= island_bottom
    assert top_left.x() >= rail_right

    # Content-fit parks the card in the safe-zone center, so zooming at the
    # viewport center cannot push it under the island. Anchor at the bottom
    # of the full-bleed host: the card recedes upward under the chrome.
    viewport = scroll.viewport()
    harness.page.set_board_zoom(
        ZOOM_MAX, (viewport.width() / 2.0, max(8.0, viewport.height() - 8.0))
    )
    qtbot.wait(10)
    zoomed_top = card.mapTo(host, QPoint(0, 0)).y()
    assert zoomed_top < island_bottom


def _union_cards_in_host(page, cards):
    host = page._canvas_host
    left = []
    top = []
    right = []
    bottom = []
    for card in cards:
        origin = card.mapTo(host, QPoint(0, 0))
        left.append(origin.x())
        top.append(origin.y())
        right.append(origin.x() + card.width())
        bottom.append(origin.y() + card.height())
    return (min(left), min(top), max(right) - min(left), max(bottom) - min(top))


def test_zoom_fit_fills_the_safe_zone_with_content(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b", "c", "d")
    harness.page.zoom_fit()
    qtbot.wait(10)
    fit = harness.page._content_fit_rect()
    _x, _y, width, height = _union_cards_in_host(harness.page, cards)
    fill = max(width / max(1.0, float(fit.width)), height / max(1.0, float(fit.height)))
    assert fill >= 1.0 - 2.0 * FIT_CONTENT_MARGIN - 0.02


def test_zoom_fit_centers_content_in_the_safe_zone(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b", "c", "d")
    harness.page.zoom_fit()
    qtbot.wait(10)
    fit = harness.page._content_fit_rect()
    x, y, width, height = _union_cards_in_host(harness.page, cards)
    assert x + width / 2.0 == pytest.approx(float(fit.x) + float(fit.width) / 2.0, abs=2)
    assert y + height / 2.0 == pytest.approx(float(fit.y) + float(fit.height) / 2.0, abs=2)


def test_zoom_fit_on_an_empty_board_uses_two_card_working_frame(qtbot):
    harness = _Harness(qtbot)
    canvas = harness.page._free_grid
    assert canvas.content_rect_1x() is None
    fit = harness.page._content_fit_rect()
    frame = two_card_working_frame(screen_grid_metrics(()))
    harness.page.zoom_fit()
    expected = board_fit_zoom(frame, (float(fit.width), float(fit.height)))
    # page host extent: Task 2 remainder
    assert harness.page.board_zoom() == pytest.approx(expected)
    assert expected <= BOARD_FIT_ZOOM_MAX


def test_zoom_fit_single_card_does_not_exceed_100_percent(qtbot):
    harness = _Harness(qtbot)
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(make_ref("time", "tiny"), GridRect(0, 0, 2, 2))
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    harness.page.zoom_fit()
    # page host extent: Task 2 remainder
    assert harness.page.board_zoom() <= BOARD_FIT_ZOOM_MAX
    assert harness.page.board_zoom() != ZOOM_MAX


def test_zoom_fit_fills_and_centers_template_content(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_2x2")
    for view_id in ("a", "b", "c", "d"):
        add_ref(harness.board, make_ref("time", view_id))
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    cards = [harness.page.card_widget("time", view_id) for view_id in ("a", "b", "c", "d")]
    assert all(card is not None for card in cards)
    harness.page.zoom_fit()
    qtbot.wait(10)
    fit = harness.page._content_fit_rect()
    x, y, width, height = _union_cards_in_host(harness.page, cards)
    fill = max(width / max(1.0, float(fit.width)), height / max(1.0, float(fit.height)))
    assert fill >= 1.0 - 2.0 * FIT_CONTENT_MARGIN - 0.02
    assert x + width / 2.0 == pytest.approx(float(fit.x) + float(fit.width) / 2.0, abs=2)
    assert y + height / 2.0 == pytest.approx(float(fit.y) + float(fit.height) / 2.0, abs=2)


def test_lod_hides_footer_below_sixty_percent(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    card = cards[0]
    assert card.footer_height() == 24 or card._footer.isVisible()
    harness.page.set_board_zoom(0.5)
    assert not card._footer.isVisible()
    harness.page.set_board_zoom(1.0)
    assert card._footer.isVisible()


def _type_chip(card):
    return card.findChild(QToolButton, "ultraViewCardTypeChip")


def _prepare_generic_title_card(harness, qtbot, *, section="fft", view_id="view-1"):
    from mf4_analyzer.ui.chart_stack.ultraview.widgets import LibraryRow
    from mf4_analyzer.ui.ultraview_state import STATUS_MISSING, add_ref, template_to_free_grid

    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref(section, view_id))
    template_to_free_grid(harness.board)
    harness.page.set_library_rows(
        [
            LibraryRow(
                section=section,
                view_id=view_id,
                name="View 1",
                tab_color="#2d7ff9",
                status=STATUS_MISSING,
                on_board=True,
                source_summary=f"{section}-src",
            )
        ]
    )
    ref = make_ref(section, view_id)
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="View 1", captured_digest="digest-keep"),
    )
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    card = harness.page.card_widget(section, view_id)
    assert card is not None
    return card, ref


def test_compact_lod_hides_footer_but_keeps_preview_type_and_trust(qtbot):
    harness = _Harness(qtbot)
    card, ref = _prepare_generic_title_card(harness, qtbot)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    harness.page.set_board_zoom(0.55)
    qtbot.wait(10)
    chip = _type_chip(card)
    assert chip is not None and chip.isVisible()
    assert "频谱" in chip.text() or "频谱" in chip.toolTip()
    assert card._title.isVisible()
    assert card._title.full_text() == "View 1"
    assert card._image.isVisible()
    assert card._image.height() > 8
    assert not card._footer.isVisible()
    assert card._status.isVisible()
    assert card._status.objectName() == "ultraViewCardStatus"
    assert chip.objectName() != card._status.objectName()


def test_title_only_lod_hides_preview_body_and_empty_backing(qtbot):
    harness = _Harness(qtbot)
    card, ref = _prepare_generic_title_card(harness, qtbot)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    before_placement = [
        (item.ref.view_id, item.rect.column, item.rect.row, item.rect.column_span, item.rect.row_span)
        for item in harness.page.board().free_grid
    ]
    digest_before = harness.page._previews[ref].captured_digest
    payload_before = board_to_payload(harness.page.board())
    geom_at_zoom = None
    harness.page.set_board_zoom(0.35)
    qtbot.wait(10)
    geom_at_zoom = QRect(card.geometry())
    chip = _type_chip(card)
    assert chip is not None and chip.isVisible()
    assert "频谱" in (chip.text() + chip.toolTip() + chip.accessibleName())
    assert card._title.full_text() == "View 1"
    assert not card._image.isVisible() or card._image.height() == 0
    assert card._image.minimumHeight() == 0
    assert not card._footer.isVisible()
    assert card.action_bar().isVisible()
    assert not card._orphan_bar.isVisible()
    assert card.focusPolicy() == Qt.StrongFocus
    QTest.mouseClick(
        card,
        Qt.LeftButton,
        Qt.NoModifier,
        QPoint(max(4, card.width() // 2), max(4, card.height() // 2)),
    )
    assert harness.page.selected_ref() == ("fft", "view-1")
    free = harness.page._free_grid
    assert free.ghost_overlay()._handles_rect is not None or card.property("selected") == "true"
    assert card.geometry() == geom_at_zoom
    after_placement = [
        (item.ref.view_id, item.rect.column, item.rect.row, item.rect.column_span, item.rect.row_span)
        for item in harness.page.board().free_grid
    ]
    assert after_placement == before_placement
    payload_after = board_to_payload(harness.page.board())
    assert payload_after["board"]["free_grid"] == payload_before["board"]["free_grid"]
    assert harness.page._previews[ref].captured_digest == digest_before
    assert harness.synced == []


def test_switching_lod_does_not_rename_generic_titles_or_create_jobs(qtbot):
    harness = _Harness(qtbot)
    card, ref = _prepare_generic_title_card(harness, qtbot)
    assert card._title.full_text() == "View 1"
    for zoom in (1.0, 0.55, 0.35, 1.0):
        harness.page.set_board_zoom(zoom)
        qtbot.wait(10)
        assert card._title.full_text() == "View 1"
        chip = _type_chip(card)
        assert chip is not None and chip.isVisible()
        assert "频谱" in (chip.text() + chip.toolTip() + chip.accessibleName())
    assert harness.synced == []
    assert harness.opened == []
    assert harness.page._previews[ref].captured_digest == "digest-keep"


def test_overview_stays_available_when_fit_is_not_equivalent(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "a")
    harness.page.zoom_fit()
    assert harness.page.board_toolbar().findChild(QPushButton, "ultraViewBoardOverviewButton") is not None
    harness.page.show_overview()
    assert harness.page.board_overview().isVisible()
    harness.page.hide_overview()
    assert not harness.page.board_overview().isVisible()


def test_needs_focus_recapture_uses_preview_ratio():
    assert needs_focus_recapture((100, 80), (0, 0)) is True
    assert needs_focus_recapture((100, 80), (200, 160)) is False
    assert needs_focus_recapture((160, 80), (200, 160)) is True
    assert needs_focus_recapture((149, 80), (200, 160)) is False


def test_state_and_viewport_legalizers_agree_on_clamp():
    raw = {"zoom": 9, "center_x": "x", "center_y": float("nan")}
    legal, warnings = normalize_viewport_payload(raw)
    board, board_warnings = normalize_board_payload(
        {
            "schema": 3,
            "board": {
                **board_to_payload(default_board())["board"],
                "viewport": raw,
            },
        }
    )
    assert legal == board.viewport
    assert warnings == board_warnings


def test_zoom_persists_on_board_and_restores_when_switching(qtbot):
    harness = _Harness(qtbot)
    first = harness.board
    _prepare_free_grid(harness, qtbot, "a")
    harness.page.set_board_zoom(1.5)
    assert first.viewport["zoom"] == pytest.approx(1.5)
    second = default_board()
    second.name = "另一块板"
    harness.page.set_board(second)
    fit = harness.page._content_fit_rect()
    expected = default_board_zoom(
        (float(fit.width), float(fit.height)),
        two_card_working_frame(screen_grid_metrics(())),
    )
    actual = harness.page.board_zoom()
    harness.page.set_board(first)
    assert harness.page.board_zoom() == pytest.approx(1.5)
    # page host extent: Task 2 remainder
    assert actual == pytest.approx(expected)
    assert expected <= NEW_BOARD_ZOOM_MAX


def test_zoom_reset_preserves_the_current_workspace_center(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "a", "b")
    page = harness.page
    page.set_board_zoom(2.0)
    scroll = page.board_scroll_area()
    scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().maximum())
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    before = page._current_center()

    page.zoom_reset()

    assert page.board_zoom() == pytest.approx(1.0)
    assert page._current_center() == pytest.approx(before, abs=2.0)


def test_page_workspace_extent_is_runtime_only_and_retains_a_high_water_mark(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    free = page._free_grid
    initial = page.workspace_extent()
    assert initial is not None
    assert free.workspace_extent() == initial
    payload_before = board_to_payload(harness.board)

    scroll = page.board_scroll_area()
    scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().maximum())
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    assert page._refresh_workspace_extent()
    grown = page.workspace_extent()
    assert grown is not None
    assert grown.column <= initial.column
    assert grown.row <= initial.row
    assert grown.column_end >= initial.column_end
    assert grown.row_end >= initial.row_end
    assert free.workspace_extent() == grown
    # Extent/halo is a session projection: only viewport persistence is
    # allowed, never a Board placement or schema-side runtime field.
    payload_after = board_to_payload(harness.board)
    assert payload_after["board"]["free_grid"] == payload_before["board"]["free_grid"]
    assert "workspace_extent" not in payload_after["board"]


def test_page_edge_timer_is_owned_by_the_page_and_stops_on_gesture_end(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    free = page._free_grid
    viewport = page.board_scroll_area().viewport()
    pointer = viewport.mapToGlobal(QPoint(1, viewport.height() // 2))

    free.workspace_gesture_changed.emit(True, pointer)
    assert page._edge_pan_timer.isActive()
    assert page._edge_pan_active

    free.workspace_gesture_changed.emit(False, None)
    assert not page._edge_pan_timer.isActive()
    assert not page._edge_pan_active


def test_switching_boards_does_not_copy_viewport_via_scroll_clamp(qtbot):
    harness = _Harness(qtbot)
    first = harness.board
    _prepare_free_grid(harness, qtbot, "a")
    harness.page.set_board_zoom(1.5)
    scroll = harness.page.board_scroll_area()
    scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().maximum())
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    second = default_board()
    second.name = "另一块板"
    second.viewport = {"zoom": 0.5, "center_x": 12.0, "center_y": 8.0}
    harness.page.set_board(second)
    assert second.viewport["zoom"] == pytest.approx(0.5)
    assert harness.page.board_zoom() == pytest.approx(0.5)
    harness.page.set_board(first)
    assert first.viewport["zoom"] == pytest.approx(1.5)


def test_template_grid_3x3_shrinks_when_zooming_out(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_3x3")
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    grid = harness.page.board_grid()
    base = grid.size()
    harness.page.set_board_zoom(0.25)
    qtbot.wait(10)
    shrunk = grid.size()
    assert shrunk.height() < base.height()
    assert shrunk.width() < base.width()


def test_focus_grab_scale_covers_preview_ratio_in_one_shot():
    native = (100.0, 50.0)
    target = (800, 400)
    scale = focus_grab_scale(native, target, max_edge=4096)
    preview = (int(round(native[0] * scale)), int(round(native[1] * scale)))
    assert needs_focus_recapture(target, preview) is False
    assert scale >= math.ceil(target[0] / FOCUS_PREVIEW_RATIO - 1e-9) / native[0]


def test_update_board_pan_restarts_smooth_preview_timer(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "a")
    harness.page.set_board_zoom(2.0)
    start = QPoint(80, 40)
    harness.page.note_space(True)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseButtonPress,
            start,
            free.mapToGlobal(start),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert harness.page.is_board_panning()
    harness.page.smooth_preview_timer().stop()
    assert not harness.page.smooth_preview_timer().isActive()
    _send_mouse_move(free, QPoint(40, 40), buttons=Qt.LeftButton)
    assert harness.page.smooth_preview_timer().isActive()


@pytest.mark.parametrize(
    "fx,fy",
    [(0.12, 0.12), (0.88, 0.12), (0.12, 0.88), (0.88, 0.88), (0.5, 0.5)],
)
@pytest.mark.parametrize("delta", [120, -120])
def test_zoom_at_keeps_board_point_under_cursor_in_every_corner(qtbot, fx, fy, delta):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    local = QPoint(
        max(8, min(card.width() - 8, int(card.width() * fx))),
        max(8, min(card.height() - 8, int(card.height() * fy))),
    )
    cursor = _viewport_cursor(harness.page, card, local)
    logical_before = _viewport_logical(harness.page, cursor)
    _wheel(card, delta, pos=local)
    logical_after = _viewport_logical(harness.page, cursor)
    assert logical_after == pytest.approx(logical_before, abs=1.0)


def test_zoom_at_from_fit_does_not_collapse_onto_fit_origin(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    harness.page.zoom_fit()
    qtbot.wait(10)
    card = cards[0]
    local = QPoint(max(8, card.width() * 3 // 4), max(8, card.height() * 3 // 4))
    cursor = _viewport_cursor(harness.page, card, local)
    logical_before = _viewport_logical(harness.page, cursor)
    _wheel(card, 120, pos=local)
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > 0.25
    assert logical_after == pytest.approx(logical_before, abs=1.0)


def test_zoom_at_clamp_does_not_jump_scroll(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    card = cards[0]
    local = QPoint(max(24, card.width() * 2 // 3), max(24, card.height() * 2 // 3))
    harness.page.set_board_zoom(ZOOM_MAX, _viewport_cursor(harness.page, card, local))
    scroll = harness.page.board_scroll_area()
    before = (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value())
    _wheel(card, 120, pos=local)
    after = (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value())
    assert harness.page.board_zoom() == ZOOM_MAX
    assert after == before


def test_toolbar_zoom_anchors_viewport_center(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "a", "b")
    viewport = harness.page.board_scroll_area().viewport()
    cursor = (viewport.width() / 2.0, viewport.height() / 2.0)
    logical_before = _viewport_logical(harness.page, cursor)
    harness.page.zoom_in()
    logical_after = _viewport_logical(harness.page, cursor)
    assert logical_after == pytest.approx(logical_before, abs=1.0)
