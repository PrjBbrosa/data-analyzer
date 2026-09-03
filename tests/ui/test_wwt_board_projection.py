"""WWT import keeps its generated TimeDomain Views out of UltraView."""
from __future__ import annotations

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
        )
        for board in workspace.boards
    )


def _load_wwt(window, monkeypatch, path, *, accept=True):
    asked = []

    def ask(body, informative=""):
        asked.append((body, informative))
        return accept

    monkeypatch.setattr(window._wwt_import, "_ask_layout", ask)
    monkeypatch.setattr(window, "plot_time", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_apply_active_view", lambda *args, **kwargs: None)
    window._load_one(str(path))
    return asked


def test_board_is_empty_and_unique_name_ignore_self():
    workspace = default_workspace()
    first = workspace.boards[0]
    assert board_is_empty(first)
    first.name = "demo"
    assert unique_board_name(workspace, "demo") == "demo (2)"
    assert unique_board_name(workspace, "demo", ignore_board_id=first.board_id) == "demo"


def test_nearest_unoccupied_origin_manhattan_and_row_column_tiebreak():
    rect = GridRect(0, 0, 8, 6)
    assert nearest_unoccupied_origin((rect,), (8, 6), rect) == GridRect(0, -6, 8, 6)


def test_single_created_view_does_not_touch_board(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    before = _board_fingerprint(window._ultraview.workspace)
    asked = _load_wwt(
        window,
        monkeypatch,
        wwt.channel_xy_with_auxiliaries(tmp_path / "single.wwt"),
    )
    try:
        assert "创建 1 个时域 View 并绘图" in asked[0][0]
        assert len(window.view_manager.views) == 1
        assert _board_fingerprint(window._ultraview.workspace) == before
        assert window._ultraview.board.name == DEFAULT_BOARD_NAME
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_multi_view_import_creates_views_without_board_side_effects(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    before = _board_fingerprint(window._ultraview.workspace)
    active_id = window._ultraview.workspace.active_board_id
    asked = _load_wwt(
        window, monkeypatch, wwt.two_window_non_overlap(tmp_path / "rack.wwt")
    )
    try:
        assert "创建 2 个时域 View 并绘图" in asked[0][0]
        assert len(window.view_manager.views) == 2
        assert _board_fingerprint(window._ultraview.workspace) == before
        assert window._ultraview.workspace.active_board_id == active_id
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_second_multi_view_import_keeps_existing_board_selection(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    first = wwt.two_window_non_overlap(tmp_path / "alpha.wwt")
    second = wwt.two_window_non_overlap(tmp_path / "beta.wwt")
    _load_wwt(window, monkeypatch, first)
    before = _board_fingerprint(window._ultraview.workspace)
    active_id = window._ultraview.workspace.active_board_id
    _load_wwt(window, monkeypatch, second)
    try:
        assert len(window.view_manager.views) == 4
        assert _board_fingerprint(window._ultraview.workspace) == before
        assert window._ultraview.workspace.active_board_id == active_id
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_reject_dialog_creates_no_views_and_leaves_board(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    before_views = [(view.view_id, view.name) for view in window.view_manager.views]
    before_board = _board_fingerprint(window._ultraview.workspace)
    _load_wwt(
        window,
        monkeypatch,
        wwt.two_window_non_overlap(tmp_path / "reject.wwt"),
        accept=False,
    )
    try:
        assert [(view.view_id, view.name) for view in window.view_manager.views] == before_views
        assert _board_fingerprint(window._ultraview.workspace) == before_board
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_time_domain_cap_truncated_to_one_view_leaves_board_untouched(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    window.view_manager.max_views = 2
    window.view_manager.views[0].checked = [("keep", "ch")]
    before = _board_fingerprint(window._ultraview.workspace)
    asked = _load_wwt(
        window,
        monkeypatch,
        wwt.multi_window_overlap_and_formula(tmp_path / "capped.wwt"),
    )
    try:
        assert "创建 1 个时域 View 并绘图" in asked[0][0]
        assert len(window.view_manager.views) == 2
        assert _board_fingerprint(window._ultraview.workspace) == before
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_full_existing_board_set_does_not_affect_wwt_view_import(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    workspace = window._ultraview.workspace
    while len(workspace.boards) < MAX_UI_BOARDS:
        assert create_board(workspace, name=f"filled-{len(workspace.boards) + 1}")
    for board in workspace.boards:
        if board_is_empty(board):
            add_ref(board, UltraViewRef("time", f"seed-{board.board_id[:8]}"))
    before = _board_fingerprint(workspace)
    _load_wwt(window, monkeypatch, wwt.two_window_non_overlap(tmp_path / "full.wwt"))
    try:
        assert len(window.view_manager.views) >= 2
        assert _board_fingerprint(workspace) == before
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_wwt_views_use_slot_palette_and_keep_winwert_curve_colors(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    keep = window.view_manager.views[0]
    keep.tab_color = "#abcdef"
    keep.checked = [("keep", "ch")]
    _load_wwt(window, monkeypatch, wwt.two_window_non_overlap(tmp_path / "color.wwt"))
    try:
        views = window.view_manager.views
        wwt_views = [view for view in views if view.name.startswith("WinWert")]
        assert views[0].tab_color == "#abcdef"
        assert [view.tab_color for view in wwt_views] == [
            default_view_tab_color(1),
            default_view_tab_color(2),
        ]
        assert wwt.palette_hex(wwt.CHAN_Y_COLOR) in wwt_views[0].colors.values()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_overlapping_wwt_windows_create_views_without_board_projection(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    before = _board_fingerprint(window._ultraview.workspace)
    _load_wwt(
        window,
        monkeypatch,
        wwt.multi_window_overlap_and_formula(tmp_path / "overlap.wwt"),
    )
    try:
        assert len(window.view_manager.views) == wwt.MULTI_WINDOW_COUNT
        assert _board_fingerprint(window._ultraview.workspace) == before
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
