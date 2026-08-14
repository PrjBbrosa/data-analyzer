"""UltraView P3-2 viewport: zoom-at-cursor math and board zoom/pan channels."""
from __future__ import annotations

import math

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QCursor, QImage, QMouseEvent, QNativeGestureEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import grid_metrics
from mf4_analyzer.ui.chart_stack.ultraview.viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    SMOOTH_DELAY_MS,
    ZOOM_MAX,
    ZOOM_MIN,
    BoardViewport,
    clamp_zoom,
    fit_zoom,
    focus_grab_scale,
    lod_level,
    needs_focus_recapture,
    scale_grid_metrics,
    wheel_event_delta_y,
    wheel_zoom_factor,
    zoom_at_cursor,
    zoom_percent,
    zoom_to_rect,
    zoomed_viewport_size,
    FOCUS_PREVIEW_RATIO,
    LOD_FULL,
    LOD_NO_FOOTER,
    LOD_TITLE_ONLY,
    normalize_viewport_payload,
)
from mf4_analyzer.ui.ultraview_state import (
    FreeGridPlacement,
    GridRect,
    board_to_payload,
    default_board,
    make_ref,
    normalize_board_payload,
    set_layout,
)
from mf4_analyzer.ui_kit import load_stylesheet

from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid, _send_mouse_move


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
    origin = (78.0, 64.0)
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
    assert fit_zoom((400, 200), (800, 800)) == 2.0
    assert wheel_zoom_factor(120) == pytest.approx(1.1)
    assert wheel_zoom_factor(-120) == pytest.approx(1.1 ** -1)
    assert wheel_event_delta_y(0, 120) == 120
    assert wheel_zoom_factor(0, 120) == pytest.approx(1.1)
    assert wheel_zoom_factor(0, 0) == 1.0


def test_board_viewport_owns_zoom_quality_and_pan_delta():
    viewport = BoardViewport()
    assert viewport.zoom() == 1.0
    assert viewport.quality() == QUALITY_SMOOTH
    assert viewport.set_zoom(3.0) == ZOOM_MAX
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
    assert toolbar.zoom_label().text() == "100%"


def test_page_zoom_clamps_and_scales_free_grid(qtbot):
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    base = free.metrics()
    width_1x = cards[0].width()
    harness.page.set_board_zoom(2.0)
    assert harness.page.board_zoom() == ZOOM_MAX
    assert free.metrics().column_width == base.column_width * 2
    assert free.metrics().row_height == base.row_height * 2
    assert cards[0].width() == pytest.approx(width_1x * 2, rel=0.08)
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
    _wheel(card, 120, pos=local, global_pos=QPoint(0, 0))
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > 1.0
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
    _wheel(card, 120, pos=QPoint(0, 0), global_pos=QPoint(0, 0))
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > 1.0
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
    assert harness.page.board_zoom() > 1.0
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
    _wheel(card, 120, pos=img_local, global_pos=img_global)
    logical_after = _viewport_logical(harness.page, cursor)
    assert harness.page.board_zoom() > 1.0
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


def test_fit_and_zoom_to_card_end_state(qtbot):
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a", "b")
    harness.page.zoom_fit()
    viewport = harness.page.board_scroll_area().viewport()
    size = free.unzoomed_size()
    fit = harness.page._content_fit_rect()
    assert harness.page.board_zoom() == pytest.approx(
        fit_zoom((size.width(), size.height()), (float(fit.width), float(fit.height)))
    )
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

    harness.page.set_board_zoom(1.5)
    qtbot.wait(10)
    zoomed_top = card.mapTo(host, QPoint(0, 0)).y()
    assert zoomed_top < island_bottom


def test_lod_hides_footer_below_sixty_percent(qtbot):
    harness = _Harness(qtbot)
    _free, cards = _prepare_free_grid(harness, qtbot, "a")
    card = cards[0]
    assert card.footer_height() == 24 or card._footer.isVisible()
    harness.page.set_board_zoom(0.5)
    assert not card._footer.isVisible()
    harness.page.set_board_zoom(1.0)
    assert card._footer.isVisible()


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
    assert harness.page.board_zoom() == pytest.approx(1.0)
    harness.page.set_board(first)
    assert harness.page.board_zoom() == pytest.approx(1.5)


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
