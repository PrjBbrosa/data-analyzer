"""W0 owner: WWT open → Board Fit / Smart Layout fixed-point integration.

Uses the synthetic U-Can fixture and the real UltraView projection seam.
Does not stub ``add_time_views_from_native_layout``. QSettings isolation is
the directory autouse fixture; policy is frozen explicitly where possible.
"""
from __future__ import annotations

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


def _hold_pending_settle(controller) -> None:
    """Stop quiet/deadline so wall-clock cannot flush pending during Fit/resize."""
    for name in ("_smart_layout_quiet_timer", "_smart_layout_deadline_timer"):
        timer = getattr(controller, name, None)
        if timer is not None:
            timer.stop()


class _ZoomFitCount:
    """Bound-method wrapper; do not connect Qt signals with a lambda."""

    def __init__(self, original) -> None:
        self._original = original
        self.calls = 0

    def zoom_fit(self):
        self.calls += 1
        return self._original()


def _open_ucan_board(mw, monkeypatch, tmp_path, qapp):
    _install_explicit_policy(monkeypatch)
    path = wwt.ucan_semantic_seven_windows(tmp_path / "ucan_semantic.wwt")
    asked = _load_wwt(mw, monkeypatch, path, accept=True)
    qapp.processEvents()
    board = mw._ultraview.board
    assert asked
    assert "同步到独立 Board" in asked[0][0]
    assert len(board.free_grid) == 7
    _hold_pending_settle(_controller(mw))
    return board


def test_wwt_open_then_board_fit_keeps_exact_placement_digest(
    qapp, tmp_path, monkeypatch,
):
    """UFP-02: zoom_fit is camera-only; digest / history / revision stay put."""
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        page = _page(mw)
        revision = controller._current_layout_revision(board.board_id)
        before = _placement_digest(board, revision)
        undo_before = list(_history_undo(mw, board.board_id))
        dirty_before = mw._ultraview.workspace.opaque_payload
        pending_before = getattr(controller, "pending_smart_layout_group", None)
        pending_was_active = bool(
            pending_before is not None
            and getattr(pending_before, "active", False)
        )
        for _ in range(3):
            page.zoom_fit()
            qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == before
        assert list(_history_undo(mw, board.board_id)) == undo_before
        assert after_revision == revision
        assert mw._ultraview.workspace.opaque_payload == dirty_before
        pending_after = getattr(controller, "pending_smart_layout_group", None)
        if pending_was_active:
            assert pending_after is not None
            assert getattr(pending_after, "active", False) is True
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()


def test_wwt_open_then_smart_layout_is_already_a_fixed_point(
    qapp, tmp_path, monkeypatch,
):
    """Import geometry is already the Smart Layout fixed point (UFP-05)."""
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    qapp.processEvents()
    try:
        board = _open_ucan_board(mw, monkeypatch, tmp_path, qapp)
        controller = _controller(mw)
        page = _page(mw)
        revision = controller._current_layout_revision(board.board_id)
        before = _placement_digest(board, revision)
        page.auto_arrange_requested.emit()
        qapp.processEvents()
        after_revision = controller._current_layout_revision(board.board_id)
        assert _placement_digest(board, after_revision) == before
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
        board = _open_ucan_board(mw, monkeypatch, tmp_path, qapp)
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
        board = _open_ucan_board(mw, monkeypatch, tmp_path, qapp)
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
