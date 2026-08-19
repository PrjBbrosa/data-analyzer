"""UltraView R1: FreeGrid move/resize coalescer, fingerprint, and ghost contract."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QImage, QMouseEvent, QPainter
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    HANDLE_NAMES,
    LAYOUT_RESIZE,
    avoidance_preferred_delta,
    grid_metrics,
    plan_layout,
    snapped_resize_rect,
)
from mf4_analyzer.ui.chart_stack.ultraview.gesture import FreeGridGesture
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    CardViewModel,
    FreeGridBoard,
)
from mf4_analyzer.ui.ultraview_state import (
    GRID_RESOLUTION,
    FreeGridPlacement,
    GridRect as _GridRect,
    make_ref,
)


def GridRect(column: int, row: int, column_span: int, row_span: int) -> _GridRect:
    """Lift schema-4 fixtures into the schema-5 micro-grid, matching free_grid tests."""
    return _GridRect(
        column * GRID_RESOLUTION,
        row * GRID_RESOLUTION,
        column_span * GRID_RESOLUTION,
        row_span * GRID_RESOLUTION,
    )


def _placement(view_id: str, rect: _GridRect) -> FreeGridPlacement:
    return FreeGridPlacement(make_ref("time", view_id), rect)


def _model(view_id: str, *, image: QImage | None = None, selected: bool = False) -> CardViewModel:
    return CardViewModel(
        slot_id=view_id,
        section="time",
        view_id=view_id,
        image=image,
        selected=selected,
    )


def _preview_image() -> QImage:
    image = QImage(48, 32, QImage.Format_ARGB32)
    image.fill(Qt.blue)
    return image


def _prepare_board(qtbot, *view_ids: str) -> FreeGridBoard:
    board = FreeGridBoard()
    qtbot.addWidget(board)
    placements = []
    models = {}
    column = 0
    for view_id in view_ids:
        rect = GridRect(column, 0, 4, 3)
        placements.append(_placement(view_id, rect))
        models[make_ref("time", view_id)] = _model(view_id, image=_preview_image())
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


def test_first_live_frame_hides_card_then_presents_overlay_once(qtbot, monkeypatch):
    board = _prepare_board(qtbot, "flash-0")
    card = board.card_for("time", "flash-0")
    assert card is not None
    present_calls = _wrap_present(board.ghost_overlay())
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    QApplication.processEvents()
    assert card._drag_shell_only is True
    assert board.ghost_overlay().is_showing()
    assert len(present_calls) == 1
    _release(card, QPoint(start.x() + unit * 2, start.y()))


def test_same_snapped_candidate_plans_and_presents_once(qtbot, monkeypatch):
    board = _prepare_board(qtbot, "same-0")
    card = board.card_for("time", "same-0")
    assert card is not None
    plan_targets = _wrap_plan_layout(monkeypatch)
    present_calls = _wrap_present(board.ghost_overlay())

    start = QPoint(16, 16)
    _press(card, start)
    QApplication.processEvents()
    present_calls = _wrap_present(board.ghost_overlay())
    for index in range(20):
        _send_move(card, QPoint(start.x() + 24 + (index % 3), start.y()))
        QApplication.processEvents()

    assert board.gesture().is_active()
    assert len(plan_targets) == 1
    assert len(present_calls) == 1
    _release(card, QPoint(start.x() + 24, start.y()))


def test_drag_shows_snap_overlay_without_waiting_for_the_timer(qtbot):
    board = _prepare_board(qtbot, "live-0")
    card = board.card_for("time", "live-0")
    assert card is not None
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    overlay = board.ghost_overlay()
    assert board.gesture().is_active()
    assert overlay.is_showing()
    assert overlay._highlights
    assert card._drag_shell_only is True
    _release(card, QPoint(start.x() + unit * 2, start.y()))


def test_resize_drag_shows_handle_badge_before_event_pump(qtbot):
    board = _prepare_board(qtbot, "live-resize-0")
    card = board.card_for("time", "live-resize-0")
    assert card is not None
    board.select_only("time", "live-resize-0")
    handle = QPoint(card.width() - 2, card.height() // 2)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, handle)
    _send_move(card, QPoint(handle.x() + unit * 2, handle.y()))
    overlay = board.ghost_overlay()
    assert board.gesture().is_active()
    session = board.gesture().session()
    assert session is not None and session.handle is not None
    assert overlay.is_showing()
    assert overlay._highlights
    assert overlay._badge
    _release(card, QPoint(handle.x() + unit * 2, handle.y()))


def test_relayout_while_armed_does_not_clear_live_ghosts(qtbot):
    board = _prepare_board(qtbot, "armed-0")
    card = board.card_for("time", "armed-0")
    assert card is not None
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    overlay = board.ghost_overlay()
    assert overlay._highlights
    board._relayout()
    board._sync_selection_handles()
    assert overlay.is_showing()
    assert overlay._highlights
    _release(card, QPoint(start.x() + unit * 2, start.y()))


def test_resize_event_during_drag_does_not_drop_the_overlay(qtbot):
    board = _prepare_board(qtbot, "resize-evt-0")
    card = board.card_for("time", "resize-evt-0")
    assert card is not None
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    overlay = board.ghost_overlay()
    assert overlay.is_showing()
    board.resize(board.width() + 8, board.height() + 8)
    assert board.gesture().is_active()
    assert overlay.is_showing()
    assert overlay._highlights
    _release(card, QPoint(start.x() + unit * 2, start.y()))


def test_resize_release_emits_geometry_once(qtbot):
    # History lives on the coordinator; this board-level gate asserts one
    # geometry_requested emit on release (one undo entry once wired).
    board = _prepare_board(qtbot, "resize-0")
    card = board.card_for("time", "resize-0")
    assert card is not None
    board.select_only("time", "resize-0")
    emits: list[tuple] = []
    board.geometry_requested.connect(lambda *args: emits.append(args))

    handle = QPoint(card.width() - 2, card.height() // 2)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    end = QPoint(handle.x() + unit * 2, handle.y())
    _press(card, handle)
    _send_move(card, end)
    QApplication.processEvents()
    _release(card, end)
    QApplication.processEvents()

    assert len(emits) == 1
    assert emits[0][0] == "time"
    assert emits[0][1] == "resize-0"
    assert emits[0][6] == "drag-resize"


def test_cancel_clears_overlay_timer_placeholder_and_cursor(qtbot):
    board = _prepare_board(qtbot, "cancel-0")
    card = board.card_for("time", "cancel-0")
    assert card is not None
    emits: list[tuple] = []
    board.geometry_requested.connect(lambda *args: emits.append(args))
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit, start.y()))
    QApplication.processEvents()
    assert board.gesture().is_active()
    board.setCursor(Qt.ForbiddenCursor)

    assert board.cancel_gesture() is True
    assert emits == []
    assert board.gesture().is_armed() is False
    assert board.ghost_overlay()._ghost_rect is None
    assert board.ghost_overlay()._highlights == ()
    assert board._latest_pointer_sample is None
    assert board._pointer_coalesce_timer.isActive() is False
    assert board._dimmed_refs == set()
    assert card._drag_shell_only is False
    assert card.graphicsEffect() is None
    assert board.cursor().shape() != Qt.ForbiddenCursor


def test_displaced_preview_does_not_leak_opacity_effects(qtbot):
    board = _prepare_board(qtbot, "dim-0", "dim-1")
    card = board.card_for("time", "dim-0")
    other = board.card_for("time", "dim-1")
    assert card is not None and other is not None
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    over = QPoint(start.x() + unit * 4, start.y())

    _press(card, start)
    _send_move(card, over)
    QApplication.processEvents()
    session = board.gesture().session()
    assert session is not None and session.plan is not None
    displaced = [ref for ref, _rect in session.plan.preview_rects() if ref != session.ref]
    assert displaced
    assert other.graphicsEffect() is None
    assert card.graphicsEffect() is None
    assert card._drag_shell_only is True
    assert other._drag_shell_only is False

    _send_move(card, start)
    QApplication.processEvents()
    session = board.gesture().session()
    assert session is not None and session.plan is not None
    assert [ref for ref, _rect in session.plan.preview_rects()] == [make_ref("time", "dim-0")]
    assert other.graphicsEffect() is None
    assert other._drag_shell_only is False

    _release(card, start)
    QApplication.processEvents()
    assert board._dimmed_refs == set()
    assert card._drag_shell_only is False
    assert other._drag_shell_only is False
    assert card.graphicsEffect() is None
    assert other.graphicsEffect() is None


def test_move_and_resize_both_publish_a_size_badge(qtbot):
    board = _prepare_board(qtbot, "badge-0")
    card = board.card_for("time", "badge-0")
    assert card is not None
    start = QPoint(16, 16)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(card, start)
    _send_move(card, QPoint(start.x() + unit * 2, start.y()))
    overlay = board.ghost_overlay()
    session = board.gesture().session()
    assert session is not None
    assert overlay._badge == (
        f"{session.candidate.column_span}×{session.candidate.row_span}"
    )
    _release(card, QPoint(start.x() + unit * 2, start.y()))


def test_session_hits_safety_only_when_the_mover_left_the_board(qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
        LAYOUT_RESIZE,
        LayoutPlan,
        LayoutRejectReason,
    )
    from mf4_analyzer.ui.ultraview_state import SAFETY_COLUMN_MAX

    board = _prepare_board(qtbot, "safe-0")
    origin = GridRect(0, 0, 4, 3)
    in_bounds = GridRect(0, 0, 8, 3)
    oob = GridRect(SAFETY_COLUMN_MAX - 2, 0, 8, 3)
    plan = LayoutPlan(
        accepted=False,
        reason=LayoutRejectReason.OUT_OF_BOUNDS,
        mover_before=origin,
        mover_after=in_bounds,
        displaced_before_after=(),
        operation=LAYOUT_RESIZE,
        based_on_layout_revision=0,
        mover_ref=make_ref("time", "safe-0"),
    )

    class _Session:
        legal = False
        candidate = in_bounds

        def is_group_move(self):
            return False

    session = _Session()
    session.plan = plan
    assert board._session_hits_safety(session) is False
    session.candidate = oob
    assert board._session_hits_safety(session) is True


def test_resize_toward_neighbor_shows_size_and_collision_or_displace(qtbot):
    board = _prepare_board(qtbot, "hit-0", "hit-1")
    left = board.card_for("time", "hit-0")
    assert left is not None
    board.select_only("time", "hit-0")
    handle = QPoint(left.width() - 2, left.height() // 2)
    metrics = board.metrics()
    unit = metrics.column_width + metrics.gutter
    _press(left, handle)
    _send_move(left, QPoint(handle.x() + unit * 4, handle.y()))
    overlay = board.ghost_overlay()
    session = board.gesture().session()
    assert session is not None
    assert overlay.is_showing()
    assert overlay._badge
    assert overlay._highlights
    if session.legal:
        assert len(overlay._highlights) >= 1
    else:
        assert overlay._safety_wall is False
        assert overlay._reject_mark is True
        assert overlay._legal is False
    _release(left, QPoint(handle.x() + unit * 4, handle.y()))


def test_illegal_preview_keeps_attempted_rect_and_size_badge(qtbot):
    board = _prepare_board(qtbot, "reject-0")
    overlay = board.ghost_overlay()
    attempted = (20, 20, 200, 120)
    overlay.set_move_previews(
        ((None, attempted),),
        (attempted,),
        legal=False,
        badge="12×6",
        handles=True,
    )
    assert overlay._legal is False
    assert overlay._reject_mark is True
    assert overlay._safety_wall is False
    assert overlay._badge == "12×6"
    assert overlay._highlights
    assert overlay._highlights[0].width() == 200


def test_shift_aspect_and_handles_match_snapped_resize_plan():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 6, 3)
    placements = [_placement("a", origin)]
    unit = metrics.column_width + metrics.gutter
    deltas = ((unit * 2, 0), (0, unit * 2), (unit * 2, unit))
    for handle in HANDLE_NAMES:
        for keep_aspect in (False, True):
            for dx, dy in deltas:
                gesture = FreeGridGesture()
                gesture.press_resize(
                    make_ref("time", "a"), origin, handle, (100, 50), (4, 50)
                )
                session = gesture.update(
                    (100 + dx, 50 + dy),
                    metrics,
                    placements,
                    start_drag_distance=1,
                    keep_aspect=keep_aspect,
                )
                assert session is not None
                expected = snapped_resize_rect(
                    origin, (dx, dy), metrics, handle, keep_aspect=keep_aspect
                )
                planned = plan_layout(
                    placements,
                    make_ref("time", "a"),
                    expected,
                    LAYOUT_RESIZE,
                    preferred=avoidance_preferred_delta(origin, expected),
                    incoming={make_ref("time", "a"): expected},
                )
                if planned.accepted and planned.mover_after is not None:
                    expected = planned.mover_after
                assert session.candidate == expected
                assert session.legal is planned.accepted
                if planned.accepted:
                    assert session.plan is not None
                    assert session.plan.mover_after == planned.mover_after


def test_pointer_coalesce_timer_is_single_shot_zero_ms(qtbot):
    board = _prepare_board(qtbot, "timer-0")
    timer = board._pointer_coalesce_timer
    assert timer.isSingleShot()
    assert timer.interval() == 0
    assert timer.parent() is board


def test_drag_paint_disables_smooth_pixmap_transform(qtbot, monkeypatch):
    board = _prepare_board(qtbot, "smooth-0")
    overlay = board.ghost_overlay()
    hints: list[bool] = []
    real_set = QPainter.setRenderHint

    def wrapped(self, hint, on=True):
        if hint == QPainter.SmoothPixmapTransform:
            hints.append(bool(on))
        return real_set(self, hint, on)

    monkeypatch.setattr(QPainter, "setRenderHint", wrapped)
    card = board.card_for("time", "smooth-0")
    assert card is not None
    start = QPoint(16, 16)
    _press(card, start)
    _send_move(card, QPoint(start.x() + 20, start.y()))
    QApplication.processEvents()
    hints.clear()
    overlay.repaint()
    assert hints
    assert all(enabled is False for enabled in hints)
    _release(card, QPoint(start.x() + 20, start.y()))
