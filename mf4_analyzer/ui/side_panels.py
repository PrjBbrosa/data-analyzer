# mf4_analyzer/ui/side_panels.py
"""Collapsible side panels: HIDDEN/PEEK/PINNED state machine + widgets.

The reducer (``reduce_panel``) is intentionally Qt-free so the transition
logic is unit-testable without an event loop. ``SidePanelController`` (added
in a later task) executes the emitted effects against real Qt widgets.
"""
from enum import Enum, auto


class PanelState(Enum):
    HIDDEN = auto()   # splitter slot 0, panel invisible, strip visible
    PEEK = auto()     # panel reparented into a floating overlay, strip visible
    PINNED = auto()   # panel docked in splitter, pushes canvas, strip hidden


class Side(Enum):
    LEFT = auto()
    RIGHT = auto()


class Ev(Enum):
    HOVER = auto()            # mouse entered strip (after open debounce)
    CLICK = auto()            # strip left-clicked
    OVERLAY_LEFT = auto()     # mouse left (overlay ∪ strip)
    OVERLAY_ENTERED = auto()  # mouse re-entered (overlay ∪ strip)
    COLLAPSE_TIMEOUT = auto() # auto-hide timer fired
    DRAG_COLLAPSED = auto()   # splitter dragged to <= threshold while pinned


class Effect(Enum):
    ENTER_PEEK = auto()       # reparent panel -> overlay, size+position, show, raise
    EXIT_PEEK = auto()        # reparent panel -> splitter slot 0, setVisible(False)
    DOCK = auto()             # reparent -> splitter, restore width, show; (strip hidden via state)
    COLLAPSE_PINNED = auto()  # setVisible(False), slot -> 0 (panel already in splitter)
    START_TIMER = auto()
    STOP_TIMER = auto()


# (current_state, event) -> (next_state, effects tuple). Missing keys are no-ops.
_TRANSITIONS = {
    (PanelState.HIDDEN, Ev.HOVER): (PanelState.PEEK, (Effect.ENTER_PEEK,)),
    (PanelState.HIDDEN, Ev.CLICK): (PanelState.PINNED, (Effect.DOCK,)),
    (PanelState.PEEK, Ev.CLICK): (PanelState.PINNED, (Effect.STOP_TIMER, Effect.DOCK)),
    (PanelState.PEEK, Ev.OVERLAY_LEFT): (PanelState.PEEK, (Effect.START_TIMER,)),
    (PanelState.PEEK, Ev.OVERLAY_ENTERED): (PanelState.PEEK, (Effect.STOP_TIMER,)),
    (PanelState.PEEK, Ev.COLLAPSE_TIMEOUT): (PanelState.HIDDEN, (Effect.EXIT_PEEK,)),
    (PanelState.PINNED, Ev.DRAG_COLLAPSED): (PanelState.HIDDEN, (Effect.COLLAPSE_PINNED,)),
}


def reduce_panel(state, event):
    """Pure transition: returns ``(next_state, effects)``; no-op stays put."""
    return _TRANSITIONS.get((state, event), (state, ()))


def strip_visible_for(state):
    """Edge strip is shown only while the panel is HIDDEN or PEEK."""
    return state in (PanelState.HIDDEN, PanelState.PEEK)
