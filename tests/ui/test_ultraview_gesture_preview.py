"""UltraView drag preview: pixels, coalescing, re-entry, and commit parity.

Field-only overlay checks (_legal, _highlights) missed empty neighbour
ghosts and dropped extent refreshes. These tests render the overlay.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPainter
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    HANDLE_NAMES,
    LAYOUT_MOVE,
    LayoutPlan,
    LayoutRejectReason,
    rect_to_pixels,
)
from mf4_analyzer.ui.chart_stack.ultraview.ghost_overlay import (
    GhostOverlay,
    ILLEGAL_PEN,
    PREVIEW_COLLISION_REJECT,
    PREVIEW_DISPLACED_WARNING,
    PREVIEW_MOVER_VALID,
)
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    CardViewModel,
    FreeGridBoard,
)
from mf4_analyzer.ui.ultraview_state import (
    GRID_RESOLUTION,
    FreeGridPlacement,
    GridBounds,
    GridRect as _GridRect,
    make_ref,
)


def GridRect(column: int, row: int, column_span: int, row_span: int) -> _GridRect:
    return _GridRect(
        column * GRID_RESOLUTION,
        row * GRID_RESOLUTION,
        column_span * GRID_RESOLUTION,
        row_span * GRID_RESOLUTION,
    )


def _placement(view_id: str, rect: _GridRect) -> FreeGridPlacement:
    return FreeGridPlacement(make_ref("time", view_id), rect)


def _solid_image(color: QColor, width: int = 48, height: int = 32) -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(color)
    return image


def _model(view_id: str, *, color: QColor, selected: bool = False) -> CardViewModel:
    return CardViewModel(
        slot_id=view_id,
        section="time",
        view_id=view_id,
        image=_solid_image(color),
        selected=selected,
    )


def _prepare_colored_board(qtbot, *cards: tuple[str, QColor]) -> FreeGridBoard:
    board = FreeGridBoard()
    qtbot.addWidget(board)
    placements = []
    models = {}
    column = 0
    for view_id, color in cards:
        rect = GridRect(column, 0, 4, 3)
        placements.append(_placement(view_id, rect))
        models[make_ref("time", view_id)] = _model(view_id, color=color)
        column += 4
    board.set_free_grid(placements, models)
    board.resize(board.minimumSize())
    board.show()
    qtbot.waitExposed(board)
    QApplication.processEvents()
    return board


def _send_move(widget, pos: QPoint, *, modifiers=Qt.NoModifier) -> None:
    event = QMouseEvent(
        QEvent.MouseMove,
        pos,
        widget.mapToGlobal(pos),
        Qt.NoButton,
        Qt.LeftButton,
        modifiers,
    )
    QApplication.sendEvent(widget, event)


def _press(card, pos: QPoint, *, modifiers=Qt.NoModifier) -> None:
    from PyQt5.QtTest import QTest

    QTest.mousePress(card, Qt.LeftButton, modifiers, pos)


def _release(card, pos: QPoint, *, modifiers=Qt.NoModifier) -> None:
    from PyQt5.QtTest import QTest

    QTest.mouseRelease(card, Qt.LeftButton, modifiers, pos)


def _wrap_plan_layout(monkeypatch):
    import mf4_analyzer.ui.chart_stack.ultraview.gesture as gesture_mod

    calls: list[_GridRect] = []
    real = gesture_mod.plan_layout

    def wrapped(*args, **kwargs):
        target = args[2] if len(args) > 2 else kwargs.get("target")
        calls.append(target)
        return real(*args, **kwargs)

    monkeypatch.setattr(gesture_mod, "plan_layout", wrapped)
    return calls


def _wrap_present(overlay):
    calls: list[object] = []
    real = overlay._present

    def wrapped(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("dirty"))
        return real(*args, **kwargs)

    overlay._present = wrapped
    return calls


def _overlay_image(overlay) -> QImage:
    overlay.repaint()
    size = overlay.size()
    image = QImage(max(1, size.width()), max(1, size.height()), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    overlay.render(painter)
    painter.end()
    return image


def _count_matching(image: QImage, box: QRect, predicate, *, step: int = 2) -> int:
    hits = 0
    x0 = max(0, int(box.x()))
    y0 = max(0, int(box.y()))
    x1 = min(image.width(), int(box.x() + box.width()))
    y1 = min(image.height(), int(box.y() + box.height()))
    for y in range(y0, max(y0 + 1, y1), step):
        for x in range(x0, max(x0 + 1, x1), step):
            if predicate(image.pixelColor(x, y)):
                hits += 1
    return hits


def _is_mover_fill(color: QColor) -> bool:
    return color.alpha() > 40 and color.blue() > 180 and color.red() < 80 and color.green() < 80


def _is_neighbor_fill(color: QColor) -> bool:
    return color.alpha() > 40 and color.green() > 180 and color.red() < 80 and color.blue() < 80


def _is_legal_stroke(color: QColor) -> bool:
    return color.alpha() > 40 and color.blue() > 180 and color.red() < 100


def _is_illegal_stroke(color: QColor) -> bool:
    return color.alpha() > 40 and color.red() > 180 and color.green() < 100


def _border_strip(box: QRect, *, depth: int = 4) -> QRect:
    return QRect(box.x(), box.y(), box.width(), depth)


MOVER_BLUE = QColor(Qt.blue)
NEIGHBOR_GREEN = QColor(Qt.green)


def test_click_select_does_not_whiteout_the_card(qtbot):
    """Idle selection chrome must not punch the canvas through the cards."""
    from PyQt5.QtTest import QTest

    board = _prepare_colored_board(qtbot, ("sel-white", MOVER_BLUE))
    card = board.card_for("time", "sel-white")
    assert card is not None
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(16, 16))
    QApplication.processEvents()
    overlay = board.ghost_overlay()
    assert overlay._selection_rects or overlay._handles_rect is not None
    assert card._image.pixmap() is not None and not card._image.pixmap().isNull()
    overlay_shot = _overlay_image(overlay)
    assert overlay_shot.pixelColor(2, 2).alpha() == 0
    composed = QImage(max(1, board.width()), max(1, board.height()), QImage.Format_ARGB32)
    composed.fill(Qt.white)
    painter = QPainter(composed)
    board.render(painter)
    painter.end()
    center = card.geometry().center()
    pixel = composed.pixelColor(center.x(), center.y())
    assert pixel.blue() > 80, pixel.name()


def test_legal_avoidance_paints_mover_and_displaced_images(qtbot):
    board = _prepare_colored_board(
        qtbot, ("pix-0", MOVER_BLUE), ("pix-1", NEIGHBOR_GREEN)
    )
    card = board.card_for("time", "pix-0")
    other = board.card_for("time", "pix-1")
    assert card is not None and other is not None
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    over = QPoint(start.x() + unit * 4, start.y())
    _press(card, start)
    _send_move(card, over)
    QApplication.processEvents()
    overlay = board.ghost_overlay()
    session = board.gesture().session()
    assert session is not None and session.plan is not None
    assert session.legal is True
    displaced = [ref for ref, _rect in session.plan.preview_rects() if ref != session.ref]
    assert displaced
    images = overlay.ghost_images()
    assert len(images) >= 2
    assert all(image is not None for image in images)
    assert overlay.preview_roles()[0] == PREVIEW_MOVER_VALID
    assert PREVIEW_DISPLACED_WARNING in overlay.preview_roles()
    assert overlay._displace_copy == "让位 1 张"
    assert card._drag_shell_only is False
    assert other._drag_shell_only is False
    assert other._image.pixmap() is not None and not other._image.pixmap().isNull()

    rendered = _overlay_image(overlay)
    mover_box = overlay._highlights[0]
    displaced_box = overlay._highlights[1]
    assert _count_matching(rendered, mover_box.adjusted(8, 8, -8, -8), _is_mover_fill) >= 8
    assert _count_matching(
        rendered, displaced_box.adjusted(8, 8, -8, -8), _is_neighbor_fill
    ) >= 8
    assert _count_matching(rendered, _border_strip(mover_box), _is_legal_stroke) >= 4
    assert _count_matching(rendered, _border_strip(displaced_box), _is_illegal_stroke) >= 4
    _release(card, over)


def test_plain_move_ghost_has_preview_image(qtbot):
    board = _prepare_colored_board(qtbot, ("move-pix", MOVER_BLUE))
    card = board.card_for("time", "move-pix")
    assert card is not None
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    end = QPoint(start.x() + unit * 2, start.y())
    _press(card, start)
    _send_move(card, end)
    QApplication.processEvents()
    overlay = board.ghost_overlay()
    assert overlay.preview_roles() == (PREVIEW_MOVER_VALID,)
    assert overlay.ghost_images()[0] is not None
    rendered = _overlay_image(overlay)
    assert _count_matching(
        rendered, overlay._highlights[0].adjusted(8, 8, -8, -8), _is_mover_fill
    ) >= 8
    _release(card, end)


def _handle_pos(card, handle: str) -> QPoint:
    width, height = card.width(), card.height()
    x = 2 if "w" in handle else (width - 2 if "e" in handle else width // 2)
    y = 2 if "n" in handle else (height - 2 if "s" in handle else height // 2)
    return QPoint(x, y)


def _handle_delta(handle: str, unit: int) -> QPoint:
    dx = -unit if "w" in handle else (unit * 2 if "e" in handle else 0)
    dy = -unit if "n" in handle else (unit * 2 if "s" in handle else 0)
    return QPoint(dx, dy)


def test_eight_handle_resize_keeps_mover_image(qtbot):
    board = _prepare_colored_board(qtbot, ("resize-pix", MOVER_BLUE))
    card = board.card_for("time", "resize-pix")
    assert card is not None
    board.select_only("time", "resize-pix")
    unit = board.metrics().column_width + board.metrics().gutter
    for handle in HANDLE_NAMES:
        pos = _handle_pos(card, handle)
        delta = _handle_delta(handle, unit)
        _press(card, pos)
        _send_move(card, pos + delta)
        QApplication.processEvents()
        overlay = board.ghost_overlay()
        session = board.gesture().session()
        assert session is not None and session.handle == handle
        assert overlay.is_showing()
        assert overlay.ghost_images()
        assert overlay.ghost_images()[0] is not None
        _release(card, pos + delta)
        QApplication.processEvents()


def test_unsolvable_collision_paints_red_reject_and_blocks_commit(qtbot, monkeypatch):
    import mf4_analyzer.ui.chart_stack.ultraview.gesture as gesture_mod

    board = _prepare_colored_board(qtbot, ("rej-0", MOVER_BLUE), ("rej-1", NEIGHBOR_GREEN))
    card = board.card_for("time", "rej-0")
    assert card is not None
    emits: list[object] = []
    board.geometry_requested.connect(lambda *args: emits.append(args))
    board.group_geometry_requested.connect(lambda payload: emits.append(payload))

    def rejected(*args, **kwargs):
        ref = args[1] if len(args) > 1 else kwargs.get("mover_ref")
        target = args[2] if len(args) > 2 else kwargs.get("target")
        return LayoutPlan(
            accepted=False,
            reason=LayoutRejectReason.NO_LEGAL_LAYOUT,
            mover_before=target,
            mover_after=target,
            displaced_before_after=(),
            operation=LAYOUT_MOVE,
            based_on_layout_revision=board._layout_revision,
            mover_ref=ref,
        )

    monkeypatch.setattr(gesture_mod, "plan_layout", rejected)
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    over = QPoint(start.x() + unit * 4, start.y())
    _press(card, start)
    _send_move(card, over)
    QApplication.processEvents()
    overlay = board.ghost_overlay()
    assert overlay._legal is False
    assert overlay._reject_mark is True
    assert overlay._safety_wall is False
    assert PREVIEW_COLLISION_REJECT in overlay.preview_roles()
    rendered = _overlay_image(overlay)
    assert overlay._highlights
    assert _count_matching(
        rendered, _border_strip(overlay._highlights[0]), _is_illegal_stroke
    ) >= 4
    _release(card, over)
    QApplication.processEvents()
    assert emits == []


def test_origin_shift_reprojects_ghost_to_rect_to_pixels(qtbot):
    board = _prepare_colored_board(qtbot, ("origin-0", MOVER_BLUE))
    card = board.card_for("time", "origin-0")
    assert card is not None
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    end = QPoint(start.x() + unit * 2, start.y())
    _press(card, start)
    _send_move(card, end)
    QApplication.processEvents()
    session = board.gesture().session()
    assert session is not None
    board.set_workspace_extent(GridBounds(-8, 0, 48, 24))
    QApplication.processEvents()
    sample = board._last_pointer_sample
    assert sample is not None
    expected = board._workspace_pixel_rect(
        session.ghost_pixels(board.metrics(), sample[0])
    )
    ghost = board.ghost_overlay()._ghost_rect
    assert ghost is not None
    assert (ghost.x(), ghost.y(), ghost.width(), ghost.height()) == expected
    _release(card, end)


def test_reentrant_present_keeps_pending_sample(qtbot):
    board = _prepare_colored_board(qtbot, ("pend-0", MOVER_BLUE))
    card = board.card_for("time", "pend-0")
    assert card is not None
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    first = QPoint(start.x() + unit * 2, start.y())
    later = QPoint(start.x() + unit * 6, start.y())
    _press(card, start)
    _send_move(card, first)
    QApplication.processEvents()
    board._gesture_presenting = True
    board._ingest_pointer_sample(
        board._logical_board_pos((later.x(), later.y())),
        global_pos=card.mapToGlobal(later),
    )
    assert board._latest_pointer_sample is not None
    board._gesture_presenting = False
    board._flush_pointer_sample()
    session = board.gesture().session()
    assert session is not None
    expected = board._workspace_pixel_rect(
        session.ghost_pixels(board.metrics(), board._logical_board_pos((later.x(), later.y())))
    )
    ghost = board.ghost_overlay()._ghost_rect
    assert ghost is not None
    assert (ghost.x(), ghost.y(), ghost.width(), ghost.height()) == expected
    _release(card, later)


def test_avoidance_preview_rects_match_commit_and_one_undo(qtbot):
    board = _prepare_colored_board(
        qtbot, ("txn-0", MOVER_BLUE), ("txn-1", NEIGHBOR_GREEN)
    )
    card = board.card_for("time", "txn-0")
    assert card is not None
    emits: list[object] = []
    board.geometry_requested.connect(lambda *args: emits.append(args))
    board.group_geometry_requested.connect(lambda payload: emits.append(payload))
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    over = QPoint(start.x() + unit * 4, start.y())
    _press(card, start)
    _send_move(card, over)
    QApplication.processEvents()
    session = board.gesture().session()
    assert session is not None and session.plan is not None
    overlay_rects = [
        (item.x(), item.y(), item.width(), item.height())
        for item in board.ghost_overlay()._highlights
    ]
    preview_pixels = [
        board._workspace_pixel_rect(rect_to_pixels(rect, board.metrics()))
        for _ref, rect in session.plan.preview_rects()
    ]
    assert overlay_rects == list(preview_pixels)
    _release(card, over)
    QApplication.processEvents()
    assert len(emits) == 1
    payload = emits[0]
    if isinstance(payload[0], tuple):
        committed = [
            (section, view_id, column, row, column_span, row_span)
            for section, view_id, column, row, column_span, row_span in payload
        ]
    else:
        committed = [payload[:6]]
    planned_updates = [
        (ref.section, ref.view_id, rect.column, rect.row, rect.column_span, rect.row_span)
        for ref, rect in session.plan.committed_updates()
    ]
    assert committed == planned_updates or set(committed) == set(planned_updates)


def test_later_pointer_events_coalesce_to_latest_sample(qtbot, monkeypatch):
    board = _prepare_colored_board(qtbot, ("coal-0", MOVER_BLUE))
    card = board.card_for("time", "coal-0")
    assert card is not None
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit, start.y()))
    QApplication.processEvents()
    plan_targets = _wrap_plan_layout(monkeypatch)
    present_calls = _wrap_present(board.ghost_overlay())
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    _send_move(card, QPoint(start.x() + unit * 4, start.y()))
    _send_move(card, QPoint(start.x() + unit * 6, start.y()))
    assert board._latest_pointer_sample is not None
    assert plan_targets == []
    assert present_calls == []
    QApplication.processEvents()
    assert len(plan_targets) == 1
    assert len(present_calls) == 1
    _release(card, QPoint(start.x() + unit * 6, start.y()))


def test_same_candidate_keeps_overlay_after_it_is_hidden(qtbot):
    """A blanked translucent overlay must come back on the next sample."""
    board = _prepare_colored_board(qtbot, ("keep-0", MOVER_BLUE))
    card = board.card_for("time", "keep-0")
    assert card is not None
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    end = QPoint(start.x() + unit * 2, start.y())
    _press(card, start)
    _send_move(card, end)
    QApplication.processEvents()
    overlay = board.ghost_overlay()
    assert overlay.is_showing()
    overlay.hide()
    assert overlay.is_showing() is False
    _send_move(card, end)
    QApplication.processEvents()
    assert overlay.is_showing()
    assert overlay._highlights
    assert overlay.ghost_images()
    _release(card, end)


def test_live_overlay_repaints_the_full_widget(qtbot):
    board = _prepare_colored_board(qtbot, ("full-0", MOVER_BLUE))
    card = board.card_for("time", "full-0")
    assert card is not None
    overlay = board.ghost_overlay()
    calls: list[tuple] = []
    real_update = overlay.update

    def wrapped(*args, **kwargs):
        calls.append(args)
        return real_update(*args, **kwargs)

    overlay.update = wrapped
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    QApplication.processEvents()
    assert calls
    assert all(len(args) == 0 for args in calls)
    _release(card, QPoint(start.x() + unit * 2, start.y()))


def test_drag_does_not_freeze_or_clear_card_pixels(qtbot, monkeypatch):
    board = _prepare_colored_board(
        qtbot, ("freeze-0", MOVER_BLUE), ("freeze-1", NEIGHBOR_GREEN)
    )
    card = board.card_for("time", "freeze-0")
    other = board.card_for("time", "freeze-1")
    assert card is not None and other is not None
    frozen: list[tuple[QWidget, bool]] = []
    real = QWidget.setUpdatesEnabled

    def wrapped(self, enabled):
        if self in (card, other):
            frozen.append((self, bool(enabled)))
        return real(self, enabled)

    monkeypatch.setattr(QWidget, "setUpdatesEnabled", wrapped)
    start = QPoint(16, 16)
    unit = board.metrics().column_width + board.metrics().gutter
    over = QPoint(start.x() + unit * 4, start.y())
    _press(card, start)
    _send_move(card, over)
    QApplication.processEvents()
    assert frozen == []
    assert card._drag_shell_only is False
    assert other._drag_shell_only is False
    assert card._image.pixmap() is not None and not card._image.pixmap().isNull()
    assert other._image.pixmap() is not None and not other._image.pixmap().isNull()
    _release(card, over)


def test_illegal_overlay_roles_do_not_use_global_legal_for_neighbors(qtbot):
    overlay = GhostOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(400, 200)
    overlay.show()
    mover = (20, 20, 120, 80)
    neighbor = (160, 20, 120, 80)
    overlay.set_move_previews(
        (
            (_solid_image(MOVER_BLUE), mover, PREVIEW_MOVER_VALID),
            (_solid_image(NEIGHBOR_GREEN), neighbor, PREVIEW_DISPLACED_WARNING),
        ),
        (mover, neighbor),
        legal=True,
        badge="8×6",
        displace_copy="让位 1 张",
    )
    assert overlay._legal is True
    assert overlay._reject_mark is False
    assert overlay.preview_roles() == (
        PREVIEW_MOVER_VALID,
        PREVIEW_DISPLACED_WARNING,
    )
    rendered = _overlay_image(overlay)
    assert _count_matching(rendered, _border_strip(QRect(*neighbor)), _is_illegal_stroke) >= 4
    assert ILLEGAL_PEN.red() > 200
