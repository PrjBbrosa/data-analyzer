"""Owner-level WWT → UltraView Board projection and group settle."""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QTimer
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


SMART_LAYOUT_QUIET_MS = 250
SMART_LAYOUT_DEADLINE_MS = 1200


class _ZoomFitProbe:
    """Bound-method page stub so settle can call zoom_fit without lambdas."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def zoom_fit(self) -> None:
        self.calls.append("fit")

    def select_ref(self, ref) -> None:
        return None

    def current_free_grid_insert_anchor(self):
        return None

    def page(self):
        return self


def _install_zoom_fit_probe(controller) -> _ZoomFitProbe:
    probe = _ZoomFitProbe()
    controller._page_impl = probe.page
    return probe


def _pending_smart_layout_group(controller):
    holder = getattr(controller, "pending_smart_layout_group", None)
    if holder is None:
        holder = getattr(controller, "_pending_smart_layout_group", None)
    assert holder is not None, (
        "UltraViewWorkspaceController must own pending_smart_layout_group "
        "(group settle, not per-card native_card_fit)"
    )
    return holder


def _smart_layout_timer(controller, name: str, interval_ms: int) -> QTimer:
    timer = getattr(controller, name, None)
    assert timer is not None, (
        f"UltraViewWorkspaceController must own {name} "
        f"(fake-clock/QTimer settle, interval {interval_ms} ms)"
    )
    assert isinstance(timer, QTimer)
    assert timer.interval() == interval_ms, (
        f"{name}.interval() must stay {interval_ms} "
        "(QTimer.start(int) rewrites interval permanently)"
    )
    return timer


def _quiet_timer(controller) -> QTimer:
    return _smart_layout_timer(
        controller, "_smart_layout_quiet_timer", SMART_LAYOUT_QUIET_MS
    )


def _deadline_timer(controller) -> QTimer:
    return _smart_layout_timer(
        controller, "_smart_layout_deadline_timer", SMART_LAYOUT_DEADLINE_MS
    )


def _record_preview(coordinator, ref: UltraViewRef, width: int, height: int) -> None:
    """Publish a preview and record it on the pending group settle holder."""
    _publish(coordinator, ref, width, height)
    controller = coordinator._workspace_controller
    recorder = getattr(controller, "record_smart_layout_aspect", None)
    assert callable(recorder), (
        "workspace controller must expose record_smart_layout_aspect "
        "so preview arrival updates group facts without reshaping per card"
    )
    recorder(ref)


def _emit_timer(timer: QTimer, qapp) -> None:
    timer.timeout.emit()
    qapp.processEvents()


def _native_fit_tokens(controller):
    pending = getattr(controller, "pending_auto_aspect", {}) or {}
    return [
        token
        for token in pending.values()
        if getattr(token, "kind", "") == "native_card_fit"
    ]


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


def test_three_exact_overlap_windows_place_all_without_arrow_warning(
    qapp, tmp_path, monkeypatch,
):
    import re

    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    toasts = []
    monkeypatch.setattr(
        mw, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    path = wwt.three_exact_overlap_windows(tmp_path / "triple.wwt")
    _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    try:
        board = mw._ultraview.board
        assert len(board.free_grid) == wwt.THREE_EXACT_OVERLAP_COUNT
        assert board.unplaced == []
        warn = " ".join(
            str(msg) for msg, level in toasts if level in {"warning", "warn"}
        )
        assert "exact_overlap_relocated" not in warn
        assert "→" not in warn
        assert re.search(r"\d+\s*->\s*\d+", warn) is None
        info = " ".join(msg for msg, level in toasts if level == "info")
        assert str(wwt.THREE_EXACT_OVERLAP_COUNT) in info or board.free_grid
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


def _stacked_refs():
    return (
        UltraViewRef("time", "fit-top"),
        UltraViewRef("time", "fit-bottom"),
    )


def _native_triple_items():
    return (
        ("a", NativeLayoutRect(0.0, 70.0, 50.0, 60.0)),
        ("b", NativeLayoutRect(60.0, 70.0, 50.0, 60.0)),
        ("c", NativeLayoutRect(0.0, 200.0, 50.0, 60.0)),
    )


def _triple_refs():
    return (
        UltraViewRef("time", "a"),
        UltraViewRef("time", "b"),
        UltraViewRef("time", "c"),
    )


def _assert_no_overlap_map(placed: dict) -> None:
    rects = list(placed.values())
    for index, left in enumerate(rects):
        for right in rects[index + 1 :]:
            overlap = not (
                left.column + left.column_span <= right.column
                or right.column + right.column_span <= left.column
                or left.row + left.row_span <= right.row
                or right.row + right.row_span <= left.row
            )
            assert not overlap, (left, right)


def _group_is_active(group) -> bool:
    if group is None or group in ({}, (), []):
        return False
    if getattr(group, "cancelled", None) is True:
        return False
    if getattr(group, "active", None) is False:
        return False
    return True


def _pending_group_or_none(controller):
    return getattr(controller, "pending_smart_layout_group", None) or getattr(
        controller, "_pending_smart_layout_group", None
    )


def test_import_commits_provisional_geometry_without_per_preview_reflow(qapp):
    """D7: import commits membership + stable provisional layout, not a reshape per preview."""
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
        assert len(board.free_grid) == 2
        group = _pending_smart_layout_group(controller)
        assert group is not None
        assert _native_fit_tokens(controller) == []
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
        revision = controller._current_layout_revision(board.board_id)
        provisional = _placed_map(board)
        top, _bottom = _stacked_refs()
        _publish(coordinator, top, 1600, 400)
        coordinator._maybe_apply_pending_auto_aspect(top)
        qapp.processEvents()
        assert _placed_map(board) == provisional
        assert len(history.undo) == 1
        assert controller._current_layout_revision(board.board_id) == revision
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("order", ((0, 1, 2), (2, 1, 0), (1, 2, 0)))
def test_group_settle_all_ready_is_one_history_and_one_zoom_fit(qapp, order):
    """D8: captured aspects never rewrite import geometry; one camera fit at import."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    refs = _triple_refs()
    sizes = ((1600, 400), (800, 800), (400, 1600))
    try:
        coordinator.add_time_views_from_native_layout(
            _native_triple_items(),
            dedicated_board=True,
            board_name="all-ready",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        imported = _placed_map(board)
        assert probe.calls == ["fit"]
        assert len(history.undo) == 1
        for index in order:
            _record_preview(coordinator, refs[index], *sizes[index])
            qapp.processEvents()
            assert _placed_map(board) == imported
            assert probe.calls == ["fit"]
            assert len(history.undo) == 1
        late_revision = controller._current_layout_revision(board.board_id)
        _record_preview(coordinator, refs[0], 1200, 300)
        qapp.processEvents()
        assert controller._current_layout_revision(board.board_id) == late_revision
        assert _placed_map(board) == imported
        assert probe.calls == ["fit"]
        assert len(history.undo) == 1
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_group_settle_quiet_timer_fires_once_with_partial_capture(qapp):
    """D8: 250ms quiet closes the aspect group without rewriting GridRect."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    top, bottom = _stacked_refs()
    try:
        coordinator.add_time_views_from_native_layout(
            _native_stacked_items(),
            dedicated_board=True,
            board_name="quiet",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        imported = _placed_map(board)
        assert probe.calls == ["fit"]
        _record_preview(coordinator, top, 1600, 400)
        qapp.processEvents()
        assert _placed_map(board) == imported
        _emit_timer(_quiet_timer(controller), qapp)
        assert len(history.undo) == 1
        assert probe.calls == ["fit"]
        assert _placed_map(board) == imported
        _emit_timer(_quiet_timer(controller), qapp)
        _record_preview(coordinator, bottom, 800, 800)
        qapp.processEvents()
        assert probe.calls == ["fit"]
        assert _placed_map(board) == imported
        assert len(history.undo) == 1
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_group_settle_deadline_fires_once_from_register(qapp):
    """D8: 1200ms deadline closes the group once and never rewrites GridRect."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    try:
        coordinator.add_time_views_from_native_layout(
            _native_stacked_items(),
            dedicated_board=True,
            board_name="deadline",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        imported = _placed_map(board)
        assert probe.calls == ["fit"]
        _emit_timer(_deadline_timer(controller), qapp)
        assert len(history.undo) == 1
        assert probe.calls == ["fit"]
        assert _placed_map(board) == imported
        _emit_timer(_deadline_timer(controller), qapp)
        assert probe.calls == ["fit"]
        assert _placed_map(board) == imported
        assert not _group_is_active(_pending_group_or_none(controller))
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

    def _dpr():
        return 2.0

    monkeypatch.setattr(coordinator, "_preview_fit_device_pixel_ratio", _dpr)
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="dpr",
        )
        left = UltraViewRef("time", "fit-left")
        right = UltraViewRef("time", "fit-right")
        _publish(coordinator, left, 800, 200)
        _publish(coordinator, right, 800, 200)
        assert coordinator._preview_fit_image_size(left) == (400, 100)
        assert coordinator._preview_fit_image_size(right) == (400, 100)
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_delayed_preview_group_survives_until_settle_or_user_mutation(qapp):
    """User mutation still cancels pending work; the holder is the group settle."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="delay",
        )
        left = UltraViewRef("time", "fit-left")
        right = UltraViewRef("time", "fit-right")
        group = _pending_smart_layout_group(controller)
        assert _group_is_active(group)
        assert _native_fit_tokens(controller) == []
        native = _placed_map(coordinator.board)[left]
        right_native = _placed_map(coordinator.board)[right]
        _publish(coordinator, left, 1600, 400)
        qapp.processEvents()
        assert _placed_map(coordinator.board)[left] == native
        assert _group_is_active(_pending_smart_layout_group(controller))

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
        assert not _group_is_active(_pending_group_or_none(controller))
        history = controller.grid_histories[coordinator.board.board_id]
        history_after_move = len(history.undo)
        revision_after_move = controller._current_layout_revision(
            coordinator.board.board_id
        )
        _record_preview(coordinator, left, 1600, 400)
        _record_preview(coordinator, right, 1600, 400)
        qapp.processEvents()
        assert _placed_map(coordinator.board)[left] == moved
        assert _placed_map(coordinator.board)[right] == right_native
        assert len(history.undo) == history_after_move
        assert (
            controller._current_layout_revision(coordinator.board.board_id)
            == revision_after_move
        )
        assert probe.calls == ["fit"]
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("gesture", ("move", "resize", "lock"))
def test_user_gesture_before_settle_cancels_auto_submit(qapp, gesture):
    """D9/D12: move/resize/lock before settle cancels auto-submit; user rect kept."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    left, right = (
        UltraViewRef("time", "fit-left"),
        UltraViewRef("time", "fit-right"),
    )
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="touch",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        native = _placed_map(board)[left]
        _record_preview(coordinator, left, 1600, 400)
        qapp.processEvents()
        if gesture == "lock":
            lock = getattr(controller, "_on_free_grid_lock", None)
            assert callable(lock), (
                "explicit card lock must cancel pending group settle"
            )
            lock(left.section, left.view_id)
            kept = native
            assert controller._free_grid_ref_is_locked(board.board_id, left)
        elif gesture == "move":
            kept = GridRect(
                native.column,
                native.row + native.row_span,
                native.column_span,
                native.row_span,
            )
            coordinator._on_free_grid_geometry(
                left.section,
                left.view_id,
                kept.column,
                kept.row,
                kept.column_span,
                kept.row_span,
                "drag-move",
            )
        else:
            kept = GridRect(
                native.column,
                native.row,
                native.column_span,
                native.row_span + 2,
            )
            coordinator._on_free_grid_geometry(
                left.section,
                left.view_id,
                kept.column,
                kept.row,
                kept.column_span,
                kept.row_span,
                "drag-resize",
            )
        assert not _group_is_active(_pending_group_or_none(controller))
        history_after = len(history.undo)
        revision_after = controller._current_layout_revision(board.board_id)
        zoom_after = list(probe.calls)
        _record_preview(coordinator, right, 800, 800)
        qapp.processEvents()
        assert _placed_map(board)[left] == kept
        assert len(history.undo) == history_after
        assert controller._current_layout_revision(board.board_id) == revision_after
        assert probe.calls == zoom_after
        if gesture != "lock":
            assert not controller._free_grid_ref_is_locked(board.board_id, left)
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_settle_reject_stale_deleted_or_switched_is_zero_mutation(qapp, monkeypatch):
    """Solver reject / stale token / Board deleted / workspace switched → zero mutation."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    top, bottom = _stacked_refs()
    try:
        coordinator.add_time_views_from_native_layout(
            _native_stacked_items(),
            dedicated_board=True,
            board_name="reject",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        fingerprint = tuple((item.ref, item.rect) for item in board.free_grid)
        history_count = len(history.undo)
        revision = controller._current_layout_revision(board.board_id)

        class _Reject:
            accepted = False
            placements = ()
            reason = "no_legal_layout"
            diagnostics = ("locked",)
            search_visits = 0
            used_fallback = False

        def _reject(*args, **kwargs):
            return _Reject()

        monkeypatch.setattr(
            "mf4_analyzer.ultraview_core.smart_layout.solve_smart_layout",
            _reject,
        )
        _record_preview(coordinator, top, 1600, 400)
        _record_preview(coordinator, bottom, 800, 800)
        qapp.processEvents()
        assert tuple((item.ref, item.rect) for item in board.free_grid) == fingerprint
        assert len(history.undo) == history_count
        assert controller._current_layout_revision(board.board_id) == revision
        assert probe.calls == ["fit"]

        controller._bump_layout_revision(board.board_id)
        stale_revision = controller._current_layout_revision(board.board_id)
        _emit_timer(_deadline_timer(controller), qapp)
        assert controller._current_layout_revision(board.board_id) == stale_revision
        assert tuple((item.ref, item.rect) for item in board.free_grid) == fingerprint
        assert probe.calls == ["fit"]

        created = create_board(controller.workspace, name="other")
        assert created is not None
        other_fp = tuple((item.ref, item.rect) for item in created.free_grid)
        controller._on_select_board(created.board_id)
        _emit_timer(_quiet_timer(controller), qapp)
        assert tuple((item.ref, item.rect) for item in board.free_grid) == fingerprint
        assert tuple((item.ref, item.rect) for item in created.free_grid) == other_fp
        assert probe.calls == ["fit"]

        controller._on_select_board(board.board_id)
        controller._on_delete_board(board.board_id)
        _emit_timer(_deadline_timer(controller), qapp)
        remaining = [
            item for item in controller.workspace.boards if item.board_id == board.board_id
        ]
        assert remaining == []
        assert probe.calls == ["fit"]
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_import_and_group_settle_share_one_undo_step(qapp):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
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
        _record_preview(coordinator, left, 1600, 400)
        _record_preview(coordinator, right, 1600, 400)
        qapp.processEvents()
        assert len(history.undo) == 1
        assert probe.calls == ["fit"]
        assert board.free_grid
        coordinator._on_free_grid_undo()
        assert board.free_grid == []
        assert board.unplaced == []
        assert history.undo == []
        assert history.redo
        assert probe.calls == ["fit"]
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_user_move_before_settle_seals_import_history(qapp):
    """Spec §15: user edit between provisional and settle seals import Undo."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    left, right = (
        UltraViewRef("time", "fit-left"),
        UltraViewRef("time", "fit-right"),
    )
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="seal",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
        import_before = history.undo[-1].before
        import_after = history.undo[-1].after
        native = _placed_map(board)[left]
        kept = GridRect(
            native.column,
            native.row + native.row_span,
            native.column_span,
            native.row_span,
        )
        coordinator._on_free_grid_geometry(
            left.section,
            left.view_id,
            kept.column,
            kept.row,
            kept.column_span,
            kept.row_span,
            "drag-move",
        )
        assert not _group_is_active(_pending_group_or_none(controller))
        assert len(history.undo) == 2
        assert history.undo[0].before == import_before
        assert history.undo[0].after == import_after
        zoom_after = list(probe.calls)
        _record_preview(coordinator, left, 1600, 400)
        _record_preview(coordinator, right, 800, 800)
        _emit_timer(_quiet_timer(controller), qapp)
        _emit_timer(_deadline_timer(controller), qapp)
        qapp.processEvents()
        assert len(history.undo) == 2
        assert history.undo[0].before == import_before
        assert history.undo[0].after == import_after
        assert _placed_map(board)[left] == kept
        assert probe.calls == zoom_after
        coordinator._on_free_grid_undo()
        assert _placed_map(board)[left] == native
        coordinator._on_free_grid_undo()
        assert board.free_grid == []
        assert probe.calls == zoom_after
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_wwt_undo_redo_does_not_rerun_solver(qapp, monkeypatch):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    left = UltraViewRef("time", "fit-left")
    right = UltraViewRef("time", "fit-right")
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="undo-resolve",
        )
        board = coordinator.board
        _record_preview(coordinator, left, 1600, 400)
        _record_preview(coordinator, right, 1600, 400)
        qapp.processEvents()
        settled = _placed_map(board)
        zoom_after_settle = list(probe.calls)

        def boom(*_args, **_kwargs):
            raise AssertionError("Undo/Redo must not re-run Smart Layout")

        monkeypatch.setattr(
            "mf4_analyzer.ultraview_core.smart_layout.solve_smart_layout",
            boom,
        )
        monkeypatch.setattr(
            "mf4_analyzer.ui.main_window.ultraview_workspace_controller.plan_smart_layout",
            boom,
        )
        coordinator._on_free_grid_undo()
        coordinator._on_free_grid_redo()
        assert _placed_map(board) == settled
        assert probe.calls == zoom_after_settle
        assert not _group_is_active(_pending_group_or_none(controller))
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_delete_board_and_shutdown_drop_lock_map(qapp):
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    left = UltraViewRef("time", "fit-left")
    try:
        coordinator.add_time_views_from_native_layout(
            _native_pair_items(),
            dedicated_board=True,
            board_name="locks",
        )
        board_id = coordinator.board.board_id
        controller._on_free_grid_lock(left.section, left.view_id)
        assert controller._free_grid_ref_is_locked(board_id, left)
        controller._on_create_board()
        controller._on_delete_board(board_id)
        assert board_id not in controller._locked_free_grid_refs
        coordinator.shutdown()
        assert controller._locked_free_grid_refs == {}
    finally:
        if not getattr(coordinator, "_shutdown", False):
            coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def _placement_digest(board, layout_revision):
    rects = tuple(
        sorted(
            (
                item.ref.section,
                item.ref.view_id,
                int(item.rect.column),
                int(item.rect.row),
                int(item.rect.column_span),
                int(item.rect.row_span),
            )
            for item in board.free_grid
        )
    )
    return (board.board_id, int(layout_revision), rects)


class _SettleCount:
    """Bound-method wrapper around pending settle; no Qt-signal lambdas."""

    def __init__(self, original) -> None:
        self._original = original
        self.calls = 0

    def settle(self) -> None:
        self.calls += 1
        return self._original()


def test_late_capture_and_resolution_recapture_never_change_geometry(qapp):
    """UFP-08: late preview / recapture update images only, never GridRects."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    top, bottom = _stacked_refs()
    try:
        coordinator.add_time_views_from_native_layout(
            _native_stacked_items(),
            dedicated_board=True,
            board_name="late-capture",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        revision = controller._current_layout_revision(board.board_id)
        before_map = _placed_map(board)
        before_digest = _placement_digest(board, revision)
        undo_before = list(history.undo)
        _record_preview(coordinator, top, 1600, 400)
        _record_preview(coordinator, bottom, 800, 800)
        qapp.processEvents()
        _publish(coordinator, top, 3200, 800)
        controller.record_smart_layout_aspect(top)
        coordinator.store.mark_resolution_stale(top, True)
        recapture = getattr(
            coordinator._capture, "_recapture_resolution_stale_refs", None,
        )
        if callable(recapture):
            recapture()
        qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placed_map(board) == before_map
        assert _placement_digest(board, after_revision) == before_digest
        assert after_revision == revision
        assert list(history.undo) == undo_before
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_fit_during_pending_capture_is_camera_only(qapp, monkeypatch):
    """UFP-02: Fit during pending capture does not flush or commit layout."""
    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    probe = _install_zoom_fit_probe(controller)
    settle = _SettleCount(controller._settle_pending_smart_layout)
    monkeypatch.setattr(controller, "_settle_pending_smart_layout", settle.settle)
    try:
        coordinator.add_time_views_from_native_layout(
            _native_stacked_items(),
            dedicated_board=True,
            board_name="fit-pending",
        )
        board = coordinator.board
        history = controller.grid_histories[board.board_id]
        revision = controller._current_layout_revision(board.board_id)
        before = _placement_digest(board, revision)
        undo_before = list(history.undo)
        group = _pending_smart_layout_group(controller)
        assert _group_is_active(group)
        quiet = getattr(controller, "_smart_layout_quiet_timer", None)
        deadline = getattr(controller, "_smart_layout_deadline_timer", None)
        if quiet is not None:
            quiet.stop()
        if deadline is not None:
            deadline.stop()
        settle_before = settle.calls
        probe.zoom_fit()
        qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == before
        assert _group_is_active(_pending_group_or_none(controller))
        assert list(history.undo) == undo_before
        assert after_revision == revision
        assert settle.calls == settle_before
        kinds_after = tuple(getattr(entry, "kind", "") for entry in history.undo)
        kinds_before = tuple(getattr(entry, "kind", "") for entry in undo_before)
        assert kinds_after == kinds_before
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()
