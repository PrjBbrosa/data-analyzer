"""Owner-level WWT → UltraView Board projection and delayed Card Fit."""
from __future__ import annotations

from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ultraview_core.board_ops import (
    add_ref,
    board_is_empty,
    create_board,
    nearest_unoccupied_origin,
    unique_board_name,
)
from mf4_analyzer.ultraview_core.model import (
    DEFAULT_BOARD_NAME,
    GridRect,
    MAX_UI_BOARDS,
    UltraViewRef,
    default_workspace,
)
from mf4_analyzer.ultraview_core.native_layout import NativeLayoutRect
from mf4_analyzer.ui.ultraview_state import PreviewMeta
from mf4_analyzer.ui.view_state import default_view_tab_color
from tests._helpers import wwt_factory as wwt


def _board_fingerprint(workspace):
    return tuple(
        (
            board.board_id,
            board.name,
            tuple((item.ref, item.rect) for item in board.free_grid),
            tuple(board.unplaced),
            tuple((item.slot_id, item.ref) for item in board.placements),
            tuple(getattr(item, "object_id", id(item)) for item in board.author_objects),
        )
        for board in workspace.boards
    )


def _stub_plot(mw, monkeypatch, *, accept=True):
    asked = []

    def fake_ask(body, informative=""):
        asked.append((body, informative))
        return accept

    monkeypatch.setattr(mw._wwt_import, "_ask_layout", fake_ask)
    monkeypatch.setattr(mw, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(mw, "_apply_active_view", lambda *a, **k: None)
    return asked


def _load_wwt(mw, monkeypatch, path, *, accept=True):
    asked = _stub_plot(mw, monkeypatch, accept=accept)
    mw._load_one(str(path))
    return asked


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


def _placed_map(board):
    return {item.ref: item.rect for item in board.free_grid}


def test_board_is_empty_and_unique_name_ignore_self():
    workspace = default_workspace()
    first = workspace.boards[0]
    assert board_is_empty(first)
    assert unique_board_name(workspace, "demo") == "demo"
    first.name = "demo"
    assert unique_board_name(workspace, "demo") == "demo (2)"
    assert unique_board_name(
        workspace, "demo", ignore_board_id=first.board_id
    ) == "demo"
    created = create_board(workspace, name="demo (2)")
    assert created is not None
    assert unique_board_name(workspace, "demo") == "demo (3)"


def test_nearest_unoccupied_origin_manhattan_and_row_column_tiebreak():
    occupied = (GridRect(0, 0, 8, 6),)
    origin = GridRect(0, 0, 8, 6)
    found = nearest_unoccupied_origin(occupied, (8, 6), origin)
    # Dist 6 to (0, -6) and (0, 6); smaller row wins. Sideways is dist 8.
    assert found == GridRect(0, -6, 8, 6)


def test_single_created_view_does_not_touch_board(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    before = _board_fingerprint(mw._ultraview.workspace)
    path = wwt.channel_xy_with_auxiliaries(tmp_path / "single.wwt")
    asked = _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        assert asked
        assert "仅生成时域 View" in asked[0][0]
        assert "同步到独立 Board" not in asked[0][0]
        assert len(mw.view_manager.views) == 1
        assert mw.view_manager.views[0].name.startswith("WinWert")
        assert _board_fingerprint(mw._ultraview.workspace) == before
        assert mw._ultraview.board.name == DEFAULT_BOARD_NAME
        assert mw._ultraview.board.free_grid == []
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_first_multi_view_reuses_empty_board_named_for_stem(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    path = wwt.two_window_non_overlap(tmp_path / "rack.wwt")
    board_id = mw._ultraview.board.board_id
    asked = _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        assert asked
        assert "同步到独立 Board" in asked[0][0]
        uv = mw._ultraview
        assert len(uv.workspace.boards) == 1
        assert uv.board.board_id == board_id
        assert uv.board.name == "rack"
        assert uv.board.layout_mode == "free_grid"
        assert len(uv.board.free_grid) == 2
        assert uv.workspace.active_board_id == board_id
        history = uv._workspace_controller.grid_histories[board_id]
        assert len(history.undo) == 1
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_second_multi_view_creates_new_active_board(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    first = wwt.two_window_non_overlap(tmp_path / "alpha.wwt")
    second = wwt.two_window_non_overlap(tmp_path / "beta.wwt")
    _load_wwt(mw, monkeypatch, first, accept=True)
    qapp.processEvents()
    uv = mw._ultraview
    first_board = uv.board
    first_fp = _board_fingerprint(uv.workspace)
    _load_wwt(mw, monkeypatch, second, accept=True)
    qapp.processEvents()
    try:
        assert len(uv.workspace.boards) == 2
        assert uv.workspace.boards[0].board_id == first_board.board_id
        assert uv.workspace.boards[0].name == "alpha"
        assert _board_fingerprint(uv.workspace)[0] == first_fp[0]
        assert uv.board.board_id != first_board.board_id
        assert uv.board.name == "beta"
        assert uv.workspace.active_board_id == uv.board.board_id
        assert len(uv.board.free_grid) == 2
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_reject_dialog_creates_no_views_and_leaves_board(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    before_views = [(v.view_id, v.name) for v in mw.view_manager.views]
    before_board = _board_fingerprint(mw._ultraview.workspace)
    path = wwt.two_window_non_overlap(tmp_path / "reject.wwt")
    _load_wwt(mw, monkeypatch, path, accept=False)
    qapp.processEvents()
    try:
        assert [(v.view_id, v.name) for v in mw.view_manager.views] == before_views
        assert _board_fingerprint(mw._ultraview.workspace) == before_board
        assert mw.files
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_duplicate_stem_gets_numbered_board_name(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = wwt.two_window_non_overlap(first_dir / "torque.wwt")
    second = wwt.two_window_non_overlap(second_dir / "torque.wwt")
    mw = MainWindow()
    qapp.processEvents()
    _load_wwt(mw, monkeypatch, first, accept=True)
    _load_wwt(mw, monkeypatch, second, accept=True)
    qapp.processEvents()
    try:
        names = [board.name for board in mw._ultraview.workspace.boards]
        assert names == ["torque", "torque (2)"]
        assert mw._ultraview.board.name == "torque (2)"
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_time_domain_cap_truncated_to_one_view_skips_dedicated_board(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    mw.view_manager.max_views = 2
    mw.view_manager.views[0].checked = [("keep", "ch")]
    before = _board_fingerprint(mw._ultraview.workspace)
    path = wwt.multi_window_overlap_and_formula(tmp_path / "capped.wwt")
    asked = _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        assert "仅生成时域 View" in asked[0][0]
        assert "同步到独立 Board" not in asked[0][0]
        assert len(mw.view_manager.views) == 2
        assert mw.view_manager.views[1].name.startswith("WinWert")
        assert _board_fingerprint(mw._ultraview.workspace) == before
        assert mw._ultraview.board.free_grid == []
        assert mw._ultraview.board.unplaced == []
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_board_cap_keeps_views_and_does_not_mutate_existing_boards(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    toasts = []
    uv = mw._ultraview
    monkeypatch.setattr(
        uv._workspace_controller,
        "_toast_impl",
        lambda msg, level="info": toasts.append((msg, level)),
    )
    ws = uv.workspace
    while len(ws.boards) < MAX_UI_BOARDS:
        created = create_board(ws, name=f"filled-{len(ws.boards) + 1}")
        assert created is not None
    for board in ws.boards:
        if board_is_empty(board):
            add_ref(board, UltraViewRef("time", f"seed-{board.board_id[:8]}"))
    before = _board_fingerprint(ws)
    path = wwt.two_window_non_overlap(tmp_path / "full.wwt")
    returns = []
    real = uv.add_time_views_from_native_layout

    def _capture(items, **kwargs):
        result = real(items, **kwargs)
        returns.append(result)
        return result

    monkeypatch.setattr(uv, "add_time_views_from_native_layout", _capture)
    _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        assert len(mw.view_manager.views) >= 2
        assert any(view.name.startswith("WinWert") for view in mw.view_manager.views)
        assert returns
        _placed, warnings = returns[0]
        assert "board_limit" in warnings
        assert _board_fingerprint(ws) == before
        assert any("Board 已达 20" in str(msg) for msg, _level in toasts)
        assert any("未加入 UltraView" in str(msg) for msg, _level in toasts)
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_wwt_views_use_slot_palette_and_keep_winwert_curve_colors(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    keep = mw.view_manager.views[0]
    keep.name = "KeepMe"
    keep.tab_color = "#abcdef"
    keep.checked = [("keep", "ch")]
    path = wwt.two_window_non_overlap(tmp_path / "color.wwt")
    _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        views = mw.view_manager.views
        assert views[0].tab_color == "#abcdef"
        wwt_views = [view for view in views if view.name.startswith("WinWert")]
        assert len(wwt_views) == 2
        colors = [view.tab_color for view in wwt_views]
        assert colors == [
            default_view_tab_color(1),
            default_view_tab_color(2),
        ]
        assert colors != ["#2d7ff9", "#2d7ff9"]
        winwert = wwt.palette_hex(wwt.CHAN_Y_COLOR)
        assert winwert in wwt_views[0].colors.values()
        assert wwt_views[0].colors != {}
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_exact_overlap_relocated_on_dedicated_board(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    path = wwt.multi_window_overlap_and_formula(tmp_path / "overlap.wwt")
    _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        board = mw._ultraview.board
        assert board.name == "overlap"
        assert len(board.free_grid) == wwt.MULTI_WINDOW_COUNT
        assert board.unplaced == []
        rects = [(item.ref, item.rect) for item in board.free_grid]
        for index, left in enumerate(rects):
            for right in rects[index + 1 :]:
                a, b = left[1], right[1]
                overlap = not (
                    a.column + a.column_span <= b.column
                    or b.column + b.column_span <= a.column
                    or a.row + a.row_span <= b.row
                    or b.row + b.row_span <= a.row
                )
                assert not overlap, (left, right)
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_add_time_views_items_only_still_writes_active_board(qapp):
    host = QWidget()
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    coordinator = UltraViewCoordinator(host, parent=host)
    board = coordinator.board
    try:
        placed, warnings = coordinator.add_time_views_from_native_layout(
            (
                ("view-left", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
                ("view-right", NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
            )
        )
        assert warnings == () or "board_limit" not in warnings
        assert placed == ("view-left", "view-right")
        assert coordinator.board is board
        assert board.name == DEFAULT_BOARD_NAME
        assert len(board.free_grid) == 2
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def _native_pair_items():
    return (
        ("fit-left", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        ("fit-right", NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
    )


def _native_stacked_items():
    return (
        ("fit-top", NativeLayoutRect(0.0, 70.0, 100.0, 60.0)),
        ("fit-bottom", NativeLayoutRect(0.0, 200.0, 100.0, 60.0)),
    )


def test_fit_after_preview_reflows_whole_group(qapp):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    try:
        coordinator.add_time_views_from_native_layout(
            _native_stacked_items(),
            dedicated_board=True,
            board_name="fit-demo",
        )
        board = coordinator.board
        assert board.name == "fit-demo"
        tokens = [
            token
            for token in controller.pending_auto_aspect.values()
            if token.kind == "native_card_fit"
        ]
        assert len(tokens) == 2
        inserted = {token.ref: token.inserted_rect for token in tokens}
        top = UltraViewRef("time", "fit-top")
        bottom = UltraViewRef("time", "fit-bottom")
        _publish(coordinator, top, 1600, 400)
        _publish(coordinator, bottom, 1600, 400)
        coordinator._maybe_apply_pending_auto_aspect(top)
        after = _placed_map(board)
        assert after[bottom].row == after[top].row + after[top].row_span
        assert after[bottom].row < inserted[bottom].row
        overlap = (
            after[top].column < after[bottom].column + after[bottom].column_span
            and after[bottom].column < after[top].column + after[top].column_span
            and after[top].row < after[bottom].row + after[bottom].row_span
            and after[bottom].row < after[top].row + after[top].row_span
        )
        assert not overlap
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
        assert controller.pending_auto_aspect == {}
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_fit_after_preview_dpr_uses_logical_size(qapp, monkeypatch):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    monkeypatch.setattr(coordinator, "_preview_fit_device_pixel_ratio", lambda: 2.0)
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="dpr",
        )
        left = UltraViewRef("time", "fit-left")
        right = UltraViewRef("time", "fit-right")
        before = _placed_map(coordinator.board)
        _publish(coordinator, left, 800, 200)
        _publish(coordinator, right, 800, 200)
        assert coordinator._preview_fit_image_size(left) == (400, 100)
        coordinator._maybe_apply_pending_auto_aspect(left)
        placed = _placed_map(coordinator.board)
        assert placed[left].column_span == before[left].column_span
        assert placed[right].column_span == before[right].column_span
        assert placed[left].row_span <= before[left].row_span
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_delayed_preview_tokens_survive_until_preview_or_user_mutation(qapp):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )
    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="delay",
        )
        left = UltraViewRef("time", "fit-left")
        right = UltraViewRef("time", "fit-right")
        assert (coordinator.board.board_id, left) in controller.pending_auto_aspect
        token = controller.pending_auto_aspect[(coordinator.board.board_id, left)]
        assert token.kind == "native_card_fit"
        native = _placed_map(coordinator.board)[left]
        coordinator._maybe_apply_pending_auto_aspect(left)
        assert (coordinator.board.board_id, left) in controller.pending_auto_aspect
        assert _placed_map(coordinator.board)[left] == native

        moved = GridRect(
            native.column,
            native.row + native.row_span,
            native.column_span,
            native.row_span,
        )
        coordinator._on_free_grid_geometry(
            left.section,
            left.view_id,
            moved.column,
            moved.row,
            moved.column_span,
            moved.row_span,
            "drag-move",
        )
        assert (coordinator.board.board_id, left) not in controller.pending_auto_aspect
        assert (coordinator.board.board_id, right) not in controller.pending_auto_aspect
        _publish(coordinator, left, 1600, 400)
        coordinator._maybe_apply_pending_auto_aspect(left)
        assert _placed_map(coordinator.board)[left] == moved

        right_native = _placed_map(coordinator.board)[right]
        _publish(coordinator, right, 1600, 400)
        coordinator._maybe_apply_pending_auto_aspect(right)
        assert (coordinator.board.board_id, right) not in controller.pending_auto_aspect
        assert _placed_map(coordinator.board)[right] == right_native
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_import_and_delayed_fit_share_one_undo_step(qapp):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="undo",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
        left = UltraViewRef("time", "fit-left")
        right = UltraViewRef("time", "fit-right")
        _publish(coordinator, left, 1600, 400)
        _publish(coordinator, right, 1600, 400)
        coordinator._maybe_apply_pending_auto_aspect(left)
        assert len(history.undo) == 1
        assert board.free_grid
        coordinator._on_free_grid_undo()
        assert board.free_grid == []
        assert board.unplaced == []
        assert history.undo == []
        assert history.redo
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()
