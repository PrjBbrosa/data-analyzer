"""UltraView one-shot auto-aspect and Board placement undo (Tasks 4 and 6)."""
from __future__ import annotations

from PyQt5.QtGui import QColor, QImage

from mf4_analyzer.ui.chart_stack.ultraview.feedback import (
    MEMBERSHIP_CAP,
    PLACED_CAP_TO_TRAY,
    REMOVED_FROM_BOARD,
    text_for_key,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    fit_rect_for_aspect,
    screen_grid_metrics,
)
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import (
    MAX_BOARD_MEMBERSHIP,
    MAX_PLACED_CARDS,
    PreviewMeta,
    UltraViewRef,
    add_ref,
    free_grid_placement_for,
    make_ref,
    membership_set,
    GridRect,
    GRID_RESOLUTION,
    free_grid_default_span,
    set_free_grid_rects,
)


def _image(width: int, height: int, color: str = "#336699") -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(color))
    return image


def _publish(uv, ref: UltraViewRef, width: int, height: int) -> None:
    uv.store.publish(
        ref,
        _image(width, height),
        digest=f"{ref.section}:{ref.view_id}:{width}x{height}",
        meta=PreviewMeta(ref=ref, title=ref.view_id),
    )


def _legacy_rect(
    column: int, row: int, column_span: int, row_span: int
) -> GridRect:
    """Express a pre-schema-5 fixture in the persisted micro-grid."""
    return GridRect(
        column * GRID_RESOLUTION,
        row * GRID_RESOLUTION,
        column_span * GRID_RESOLUTION,
        row_span * GRID_RESOLUTION,
    )


def _fitted_span(board, image_size: tuple[int, int]) -> tuple[int, int]:
    column_span, row_span = free_grid_default_span(board)
    wanted = fit_rect_for_aspect(
        GridRect(0, 0, column_span, row_span),
        image_size,
        screen_grid_metrics(board.free_grid),
    )
    return wanted.column_span, wanted.row_span


def test_add_with_preview_shrinks_on_first_insert(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    _publish(uv, ref, 800, 200)
    uv._apply_add_ref(ref)
    item = free_grid_placement_for(uv.board, ref)
    assert item is not None
    expected = _fitted_span(uv.board, (800, 200))
    assert (item.rect.column_span, item.rect.row_span) == expected
    assert (item.rect.column_span, item.rect.row_span) != (4, 3) or expected == (4, 3)
    assert uv._pending_auto_aspect == {}
    history = uv._grid_histories[uv.board.board_id]
    assert len(history.undo) == 1


def test_add_with_retina_preview_uses_logical_pixels_for_first_fit(
    qapp, qtbot, monkeypatch
):
    """A raw DPR=2 capture must not make the new card reserve 2× the space."""
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    monkeypatch.setattr(uv, "_preview_fit_device_pixel_ratio", lambda: 2.0)
    _publish(uv, ref, 800, 200)

    assert uv._preview_fit_image_size(ref) == (400, 100)
    uv._apply_add_ref(ref)

    item = free_grid_placement_for(uv.board, ref)
    assert item is not None
    expected = _fitted_span(uv.board, (400, 100))
    raw_pixel_expected = _fitted_span(uv.board, (800, 200))
    assert (item.rect.column_span, item.rect.row_span) == expected
    assert expected != raw_pixel_expected


def test_add_without_preview_applies_once_if_span_unchanged(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(ref)
    item = free_grid_placement_for(uv.board, ref)
    assert item is not None
    assert item.rect == _legacy_rect(0, 0, 4, 3)
    assert (uv.board.board_id, ref) in uv._pending_auto_aspect
    _publish(uv, ref, 800, 200)
    uv._push_preview(ref)
    item = free_grid_placement_for(uv.board, ref)
    expected = _fitted_span(uv.board, (800, 200))
    assert (item.rect.column_span, item.rect.row_span) == expected
    assert uv._pending_auto_aspect == {}
    _publish(uv, ref, 200, 800)
    uv._push_preview(ref)
    item = free_grid_placement_for(uv.board, ref)
    assert (item.rect.column_span, item.rect.row_span) == expected


def test_resize_and_preset_cancel_pending_but_move_does_not(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    moved = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(moved)
    uv._on_free_grid_geometry(
        moved.section, moved.view_id, 16, 0, 8, 6, "drag-move"
    )
    assert (uv.board.board_id, moved) in uv._pending_auto_aspect
    _publish(uv, moved, 800, 200)
    uv._push_preview(moved)
    item = free_grid_placement_for(uv.board, moved)
    expected = fit_rect_for_aspect(
        _legacy_rect(8, 0, 4, 3),
        (800, 200),
        screen_grid_metrics(uv.board.free_grid),
    )
    assert item.rect == expected

    resized = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    uv._apply_add_ref(resized)
    current = free_grid_placement_for(uv.board, resized)
    assert current is not None
    uv._on_free_grid_geometry(
        resized.section,
        resized.view_id,
        current.rect.column,
        current.rect.row,
        12,
        6,
        "drag-resize",
    )
    assert (uv.board.board_id, resized) not in uv._pending_auto_aspect
    resized_rect = free_grid_placement_for(uv.board, resized).rect
    _publish(uv, resized, 800, 200)
    uv._push_preview(resized)
    assert free_grid_placement_for(uv.board, resized).rect == resized_rect

    preset = UltraViewRef("frf", str(win.analysis_managers["frf"].get(0).view_id))
    uv._apply_add_ref(preset)
    uv._on_free_grid_preset(preset.section, preset.view_id, "wide")
    assert (uv.board.board_id, preset) not in uv._pending_auto_aspect
    before = free_grid_placement_for(uv.board, preset).rect
    _publish(uv, preset, 800, 200)
    uv._push_preview(preset)
    assert free_grid_placement_for(uv.board, preset).rect == before


def test_remove_undo_redo_restores_exact_membership_and_geometry(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    uv._apply_add_ref(time_ref)
    uv._apply_add_ref(fft_ref)
    uv._on_free_grid_geometry(fft_ref.section, fft_ref.view_id, 12, 8, 8, 6, "drag-move")
    parked = {item.ref: item.rect for item in uv.board.free_grid}
    uv._on_remove_ref(fft_ref.section, fft_ref.view_id)
    assert fft_ref not in membership_set(uv.board)
    assert (text_for_key(REMOVED_FROM_BOARD), "info") in toasts
    uv._on_free_grid_undo()
    restored = {item.ref: item.rect for item in uv.board.free_grid}
    assert restored == parked
    assert fft_ref in membership_set(uv.board)
    uv._on_free_grid_redo()
    assert fft_ref not in membership_set(uv.board)
    assert time_ref in membership_set(uv.board)


def test_add_then_auto_aspect_is_one_undo_step(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(ref)
    history = uv._grid_histories[uv.board.board_id]
    assert len(history.undo) == 1
    _publish(uv, ref, 800, 200)
    uv._push_preview(ref)
    assert len(history.undo) == 1
    fitted = free_grid_placement_for(uv.board, ref).rect
    uv._on_free_grid_undo()
    assert ref not in membership_set(uv.board)
    uv._on_free_grid_redo()
    assert free_grid_placement_for(uv.board, ref).rect == fitted


def test_membership_edits_do_not_wipe_prior_move_history(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    uv._apply_add_ref(time_ref)
    uv._on_free_grid_geometry(time_ref.section, time_ref.view_id, 0, 12, 8, 6, "drag-move")
    history = uv._grid_histories[uv.board.board_id]
    assert len(history.undo) == 2
    uv._apply_add_ref(fft_ref)
    assert len(history.undo) == 3
    uv._on_free_grid_undo()
    assert fft_ref not in membership_set(uv.board)
    moved = free_grid_placement_for(uv.board, time_ref)
    assert moved is not None
    assert moved.rect.row == 12
    uv._on_free_grid_undo()
    assert free_grid_placement_for(uv.board, time_ref).rect.row == 0


def test_restore_does_not_register_pending_or_auto_aspect(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(ref)
    assert uv._pending_auto_aspect
    payload = uv.to_project_payload()
    original = free_grid_placement_for(uv.board, ref).rect
    uv.restore_project_state(payload)
    assert uv._pending_auto_aspect == {}
    _publish(uv, ref, 800, 200)
    uv._push_preview(ref)
    assert free_grid_placement_for(uv.board, ref).rect == original
    assert uv._pending_auto_aspect == {}


def test_camera_settle_does_not_create_placement_history(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(ref)
    history = uv._grid_histories[uv.board.board_id]
    assert len(history.undo) == 1
    uv._on_camera_settled()
    assert len(history.undo) == 1


def test_membership_cap_and_placed_cap_use_feedback_copy(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    board = uv.board
    for index in range(MAX_PLACED_CARDS):
        add_ref(board, make_ref("time", f"placed-{index}"))
    extra = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    uv._apply_add_ref(extra)
    assert extra in board.unplaced
    assert (text_for_key(PLACED_CAP_TO_TRAY), "info") in toasts
    toasts.clear()
    for index in range(MAX_BOARD_MEMBERSHIP - len(membership_set(board))):
        add_ref(board, make_ref("order", f"tray-{index}"))
    blocked = UltraViewRef("frf", str(win.analysis_managers["frf"].get(0).view_id))
    uv._apply_add_ref(blocked)
    assert blocked not in membership_set(board)
    assert (text_for_key(MEMBERSHIP_CAP), "warning") in toasts


def test_tray_place_with_preview_uses_fitted_span(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(ref)
    uv._on_move_to_unplaced(ref.section, ref.view_id)
    _publish(uv, ref, 800, 200)
    uv._on_place_free_grid_from_unplaced(ref.section, ref.view_id)
    item = free_grid_placement_for(uv.board, ref)
    assert item is not None
    expected = _fitted_span(uv.board, (800, 200))
    assert (item.rect.column_span, item.rect.row_span) == expected
    assert uv._pending_auto_aspect == {}


def test_tray_place_without_preview_keeps_pending_auto_aspect(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    uv._apply_add_ref(ref)
    uv._on_move_to_unplaced(ref.section, ref.view_id)
    assert uv._pending_auto_aspect == {}
    uv._on_place_free_grid_from_unplaced(ref.section, ref.view_id)
    item = free_grid_placement_for(uv.board, ref)
    assert item is not None
    assert item.rect == _legacy_rect(0, 0, 4, 3)
    assert (uv.board.board_id, ref) in uv._pending_auto_aspect


def test_insert_ghost_span_matches_fitted_drop_span(qapp, qtbot):
    from PyQt5.QtCore import QPoint

    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("frf", str(win.analysis_managers["frf"].get(0).view_id))
    _publish(uv, ref, 800, 1400)
    page = uv.page()
    expected = uv._fitted_insert_span(uv.board, (800, 1400))
    assert expected != (4, 3)
    resolved = page._resolve_insert_span_for_drag(ref.section, ref.view_id)
    assert resolved == expected
    free = page._free_grid
    free._insert_drag_ref = (ref.section, ref.view_id)
    ghost = free._insertion_rect_at(QPoint(80, 80))
    assert ghost is not None
    assert (ghost.column_span, ghost.row_span) == expected
    uv._apply_add_ref(ref)
    item = free_grid_placement_for(uv.board, ref)
    assert item is not None
    assert (item.rect.column_span, item.rect.row_span) == expected


def test_auto_arrange_undo_redo_restores_every_rect(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    first = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    second = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    uv._apply_add_ref(first)
    uv._apply_add_ref(second)
    warnings = set_free_grid_rects(
        uv.board,
        (
            (first, _legacy_rect(8, 6, 4, 3)),
            (second, _legacy_rect(0, 14, 6, 3)),
        ),
    )
    assert warnings == []
    before = {item.ref: item.rect for item in uv.board.free_grid}
    uv._on_auto_arrange_free_grid()
    arranged = {item.ref: item.rect for item in uv.board.free_grid}
    assert arranged != before
    assert arranged[first].column_span == before[first].column_span
    assert arranged[second].row_span == before[second].row_span
    assert uv._can_undo_auto_arrange() is True
    uv._on_free_grid_undo()
    assert {item.ref: item.rect for item in uv.board.free_grid} == before
    assert uv._can_undo_auto_arrange() is False
    uv._on_free_grid_redo()
    assert {item.ref: item.rect for item in uv.board.free_grid} == arranged
    assert uv._can_undo_auto_arrange() is True
