"""WWT ordinary Views → manual UltraView → Smart Layout fixed-point coverage.

WWT import must not alter a Board.  The cards below enter through the same
source-tab entry point that the ``加入总览`` command uses; no test writes Board
state or calls the retired WWT native-layout projection.  QSettings isolation
is the directory autouse fixture; policy is frozen explicitly where possible.
"""
from __future__ import annotations

import pytest

from mf4_analyzer.ultraview_core.smart_layout import SmartLayoutPolicy
from tests._helpers import wwt_factory as wwt


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


def _frozen_balanced_policy(*, target_viewport=(1200, 750), settings=None):
    return SmartLayoutPolicy(
        mode="balanced",
        density="auto",
        target_viewport=tuple(target_viewport),
        preserve_locked=True,
    )


def _install_explicit_policy(monkeypatch) -> None:
    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window.ultraview_workspace_controller.load_smart_layout_policy",
        _frozen_balanced_policy,
    )


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


def _controller(mw):
    return mw._ultraview._workspace_controller


def _history_undo(mw, board_id):
    histories = _controller(mw)._grid_histories
    history = histories.get(board_id)
    if history is None:
        history = histories.get(str(board_id))
    assert history is not None
    return history.undo


def _page(mw):
    page = mw._ultraview.page()
    assert page is not None, "MainWindow chart stack must host UltraViewPage"
    return page


class _ZoomFitCount:
    """Bound-method wrapper; do not connect Qt signals with a lambda."""

    def __init__(self, original) -> None:
        self._original = original
        self.calls = 0

    def zoom_fit(self):
        self.calls += 1
        return self._original()


class _StubSmartLayoutPlan:
    """Accepted plan double that exposes the solver diagnostics to the controller."""

    accepted = True
    reason = None
    search_visits = 4096
    used_fallback = False
    solver_reason = None

    def __init__(self, update, diagnostics: tuple[str, ...]) -> None:
        self._update = update
        self.diagnostics = diagnostics

    def committed_updates(self):
        return (self._update,)


def _open_ucan_views_then_add_to_board(mw, monkeypatch, tmp_path, qapp):
    _install_explicit_policy(monkeypatch)
    path = wwt.ucan_semantic_seven_windows(tmp_path / "ucan_semantic.wwt")
    asked = _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    board = mw._ultraview.board
    assert asked
    assert "创建 7 个时域 View" in asked[0][0]
    assert "UltraView" not in asked[0][0]
    view_ids = tuple(str(state.view_id) for state in mw.view_manager.views)
    assert len(view_ids) == wwt.UCAN_SEMANTIC_WINDOW_COUNT
    assert board.free_grid == []
    assert board.unplaced == []

    # This is the signal emitted by the View-tab ``加入总览`` command.  Do not
    # seed ``board.free_grid`` directly here: import and this user action have
    # intentionally different ownership.
    for view_id in view_ids:
        mw.chart_stack.add_to_ultraview_requested.emit("time", view_id)
        qapp.processEvents()

    assert {item.ref.view_id for item in board.free_grid} == set(view_ids)
    assert len(board.free_grid) == wwt.UCAN_SEMANTIC_WINDOW_COUNT
    assert board.unplaced == []
    return board


def test_wwt_import_then_manual_board_fit_keeps_exact_placement_digest(
    qapp, tmp_path, monkeypatch,
):
    """UFP-02: zoom_fit is camera-only; digest / history / revision stay put."""
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_views_then_add_to_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        page = _page(mw)
        revision = controller._current_layout_revision(board.board_id)
        before = _placement_digest(board, revision)
        undo_before = list(_history_undo(mw, board.board_id))
        dirty_before = mw._ultraview.workspace.opaque_payload
        for _ in range(3):
            page.zoom_fit()
            qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == before
        assert list(_history_undo(mw, board.board_id)) == undo_before
        assert after_revision == revision
        assert mw._ultraview.workspace.opaque_payload == dirty_before
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_manual_smart_layout_reaches_a_fixed_point(
    qapp, tmp_path, monkeypatch,
):
    """One manual Smart Layout makes a subsequent command a strict no-op."""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window import ultraview_workspace_controller

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_views_then_add_to_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        page = _page(mw)
        plans = []
        original_plan = ultraview_workspace_controller.plan_smart_layout

        def record_plan(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            plans.append(plan)
            return plan

        monkeypatch.setattr(
            ultraview_workspace_controller,
            "plan_smart_layout",
            record_plan,
        )
        page.auto_arrange_requested.emit()
        qapp.processEvents()
        assert plans
        assert plans[-1].accepted and plans[-1].committed_updates()
        revision = controller._current_layout_revision(board.board_id)
        after_first = _placement_digest(board, revision)
        page.auto_arrange_requested.emit()
        qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == after_first
        assert after_revision == revision
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    ("diagnostics", "expected"),
    (
        ((), "已排版"),
        (("search_budget_exhausted",), "搜索预算耗尽，已用已完成候选完成排版"),
        (("search_budget_exhausted", "equal_grid_fallback"), "已使用等大网格完成降级排版"),
    ),
    ids=("normal", "budget-exhausted", "equal-grid"),
)
def test_manual_smart_layout_toast_distinguishes_solver_diagnostics(
    qapp, tmp_path, monkeypatch, diagnostics, expected,
):
    """B3: controller feedback must project the solver's exact fallback state."""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window import ultraview_workspace_controller

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_views_then_add_to_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        first = board.free_grid[0]
        plan = _StubSmartLayoutPlan((first.ref, first.rect), diagnostics)
        notices = []
        monkeypatch.setattr(
            ultraview_workspace_controller,
            "plan_smart_layout",
            lambda *args, **kwargs: plan,
        )
        monkeypatch.setattr(
            controller,
            "_toast",
            lambda message, level: notices.append((message, level)),
        )

        controller._on_auto_arrange_free_grid()

        assert notices[-1] == (expected, "info")
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_second_manual_smart_layout_is_zero_mutation_zero_history(
    qapp, tmp_path, monkeypatch,
):
    """After one explicit Smart Layout, a second call is a strict no-op."""
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_views_then_add_to_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        page = _page(mw)
        counter = _ZoomFitCount(page.zoom_fit)
        monkeypatch.setattr(page, "zoom_fit", counter.zoom_fit)
        page.auto_arrange_requested.emit()
        qapp.processEvents()
        revision = controller._current_layout_revision(board.board_id)
        after_first = _placement_digest(board, revision)
        undo_after_first = list(_history_undo(mw, board.board_id))
        fits_after_first = counter.calls
        page.auto_arrange_requested.emit()
        qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == after_first
        assert list(_history_undo(mw, board.board_id)) == undo_after_first
        assert counter.calls == fits_after_first
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_window_resize_does_not_relayout_until_explicit_command(
    qapp, tmp_path, monkeypatch,
):
    """UFP-08: resize is not a layout command; geometry waits for Smart Layout."""
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_views_then_add_to_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        page = _page(mw)
        revision = controller._current_layout_revision(board.board_id)
        before = _placement_digest(board, revision)
        mw.resize(640, 480)
        page.resize(400, 300)
        qapp.processEvents()
        mw.resize(1600, 1000)
        page.resize(1400, 800)
        qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == before
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()
