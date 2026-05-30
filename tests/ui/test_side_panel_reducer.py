# tests/ui/test_side_panel_reducer.py
"""Pure (no-Qt) tests for the side-panel HIDDEN/PEEK/PINNED reducer."""
from mf4_analyzer.ui.side_panels import (
    PanelState, Ev, Effect, reduce_panel, strip_visible_for,
)


def test_hidden_hover_enters_peek():
    state, effects = reduce_panel(PanelState.HIDDEN, Ev.HOVER)
    assert state == PanelState.PEEK
    assert effects == (Effect.ENTER_PEEK,)


def test_hidden_click_pins():
    state, effects = reduce_panel(PanelState.HIDDEN, Ev.CLICK)
    assert state == PanelState.PINNED
    assert effects == (Effect.DOCK,)


def test_peek_click_stops_timer_then_docks():
    state, effects = reduce_panel(PanelState.PEEK, Ev.CLICK)
    assert state == PanelState.PINNED
    assert effects == (Effect.STOP_TIMER, Effect.DOCK)


def test_peek_mouse_left_starts_collapse_timer():
    state, effects = reduce_panel(PanelState.PEEK, Ev.OVERLAY_LEFT)
    assert state == PanelState.PEEK
    assert effects == (Effect.START_TIMER,)


def test_peek_mouse_reentered_cancels_collapse():
    state, effects = reduce_panel(PanelState.PEEK, Ev.OVERLAY_ENTERED)
    assert state == PanelState.PEEK
    assert effects == (Effect.STOP_TIMER,)


def test_peek_timeout_collapses_to_hidden():
    state, effects = reduce_panel(PanelState.PEEK, Ev.COLLAPSE_TIMEOUT)
    assert state == PanelState.HIDDEN
    assert effects == (Effect.EXIT_PEEK,)


def test_pinned_drag_collapse_hides():
    state, effects = reduce_panel(PanelState.PINNED, Ev.DRAG_COLLAPSED)
    assert state == PanelState.HIDDEN
    assert effects == (Effect.COLLAPSE_PINNED,)


def test_irrelevant_events_are_noops():
    assert reduce_panel(PanelState.PEEK, Ev.HOVER) == (PanelState.PEEK, ())
    assert reduce_panel(PanelState.PINNED, Ev.HOVER) == (PanelState.PINNED, ())
    assert reduce_panel(PanelState.HIDDEN, Ev.COLLAPSE_TIMEOUT) == (PanelState.HIDDEN, ())


def test_strip_visible_in_hidden_and_peek_only():
    assert strip_visible_for(PanelState.HIDDEN) is True
    assert strip_visible_for(PanelState.PEEK) is True
    assert strip_visible_for(PanelState.PINNED) is False
