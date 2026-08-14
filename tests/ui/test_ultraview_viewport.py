"""UltraView P3-2 viewport: zoom-at-cursor math and board zoom/pan channels."""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QImage, QMouseEvent, QWheelEvent
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
    lod_level,
    needs_focus_recapture,
    scale_grid_metrics,
    wheel_zoom_factor,
    zoom_at_cursor,
    zoom_percent,
    zoom_to_rect,
    zoomed_viewport_size,
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
)

from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid, _send_mouse_move


def _logical_under_cursor(zoom, cursor, scroll):
    return (
        (scroll[0] + cursor[0]) / zoom,
        (scroll[1] + cursor[1]) / zoom,
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


def _wheel(widget, delta_y, modifiers=Qt.ControlModifier):
    pos = QPoint(widget.width() // 2, widget.height() // 2)
    event = QWheelEvent(
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.NoButton,
        modifiers,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return event


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
    assert harness.page.board_zoom() == pytest.approx(
        fit_zoom((size.width(), size.height()), (viewport.width(), viewport.height()))
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
