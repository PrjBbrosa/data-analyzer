"""Relative lifecycle/performance ratchets for UltraView composition.

Thresholds are measured from the current stable implementation, not invented
absolute budgets. They catch unexplained reconnects, leftover timers, and
projection storms after reset/shutdown.
"""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.chart_stack.ultraview.preview_store import (
    RESIDENCY_TIER_INACTIVE_PLACED,
    PreviewStore,
    ResidencyRequest,
)
from mf4_analyzer.ui.ultraview_state import default_board, make_ref, add_ref


# Measured on the Wave-2 composition snapshot (offscreen). Widen only with
# a spec change and a new measurement.
_MAX_SET_BOARD_PROJECTION_REFRESHES = 4
_MAX_CONNECT_SIGNAL_GROWTH = 0


def _owned_timers(page: UltraViewPage) -> list[QTimer]:
    timers = []
    viewport = page._viewport_ctrl
    if viewport is not None:
        timers.extend([viewport.smooth_timer(), viewport.edge_pan_timer()])
    return [timer for timer in timers if timer is not None]


def test_page_connect_is_idempotent(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    rail = page.tool_rail()
    before = rail.receivers(rail.tool_requested)
    page._author_ui.connect()
    page._author_ui.connect()
    after = rail.receivers(rail.tool_requested)
    assert after - before <= _MAX_CONNECT_SIGNAL_GROWTH
    assert after == before


@pytest.mark.parametrize("ref_count", [12, 24])
def test_set_board_projection_refresh_stays_bounded(qtbot, monkeypatch, ref_count):
    page = UltraViewPage()
    qtbot.addWidget(page)
    calls = {"n": 0}
    original = page._refresh_projection

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(page, "_refresh_projection", wrapped)
    board = default_board()
    for index in range(ref_count):
        section = "time" if index % 2 == 0 else "fft"
        add_ref(board, make_ref(section, f"ratchet-{index}"))
    page.set_board(board)
    first = calls["n"]
    page.set_board(board)
    second = calls["n"] - first
    assert first <= _MAX_SET_BOARD_PROJECTION_REFRESHES, first
    assert second <= _MAX_SET_BOARD_PROJECTION_REFRESHES, second


def test_preview_residency_deduplicates_60_refs_across_20_boards(qapp):
    store = PreviewStore()
    refs = [make_ref("time", f"scale-{index}") for index in range(60)]
    requests = [
        ResidencyRequest(
            ref,
            tier=RESIDENCY_TIER_INACTIVE_PLACED,
            target_size=(200, 100),
        )
        for _board in range(20)
        for ref in refs
    ]
    store.set_residency_requests(requests)
    assert store.stats().residency_refs == 60
    store.deleteLater()


def test_shutdown_stops_viewport_timers_and_does_not_leave_active_hooks(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    page.zoom_in()
    qtbot.wait(20)
    page.shutdown()
    QApplication.processEvents()
    for timer in _owned_timers(page):
        assert not timer.isActive(), timer
    assert page._author_ui._connected is False
    assert page._floating_chrome._connected is False
    assert page._board_context._connected is False


def test_reset_sheet_session_clears_selection_and_open_author_transient(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    page._author_ui.show_pointer_popover()
    qtbot.wait(20)
    page.reset_sheet_session(emit_presentation=False)
    QApplication.processEvents()
    assert page._author_ui.active_transient_facts() is None
    assert not page.pointer_popover().isVisible()
    assert page.interaction().selection() == frozenset()
