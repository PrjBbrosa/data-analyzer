"""Canonical import path for UltraView ``PointerRouter``.

Implementation lives in ``board_pointer.py`` so existing relative imports keep
working. This module re-exports the composed router and installs the lost-release
guard on that class. It does not install a QApplication event filter.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QMouseEvent

from .author_tools import TOOL_CONNECTOR, TOOL_DRAW, TOOL_SHAPES, TOOL_TEXT
from .board_pointer import PointerHitFacts, PointerRouter

__all__ = [
    "PointerHitFacts",
    "PointerRouter",
    "pointer_button_is_down",
]


def pointer_button_is_down(buttons: int, button: int) -> bool:
    """True when *button* is still present in this event's button mask.

    A zero initiating button means the gesture did not record one, so the
    mask is not used to cancel it.
    """
    if int(button) == 0:
        return True
    return bool(int(buttons) & int(button))


def _draft_tracks_without_button(draft) -> bool:
    """Click-click connectors keep a draft after the first release."""
    return bool(getattr(draft, "awaiting_end", False))


def _pointer_gesture_open(router: PointerRouter) -> bool:
    draft = router._interaction.draft()
    if draft is not None and not _draft_tracks_without_button(draft):
        return True
    for tool in (TOOL_TEXT, TOOL_SHAPES, TOOL_CONNECTOR):
        if router._interaction.geometry_session(tool) is not None:
            return True
    return False


def _cancel_pointer_gesture(router: PointerRouter) -> None:
    """Drop an in-flight author pointer gesture without committing it."""
    if getattr(router, "_cancelling_lost_pointer", False):
        return
    router._cancelling_lost_pointer = True
    try:
        draft = router._interaction.draft()
        if draft is not None and not _draft_tracks_without_button(draft):
            tool = draft.tool
            router._interaction.cancel_draft()
            if tool == TOOL_DRAW:
                router.clear_draw_draft_paint()
            elif tool == TOOL_SHAPES:
                router.clear_shape_draft_paint()
            elif tool == TOOL_CONNECTOR:
                router.clear_connector_draft_paint()
        for tool in (TOOL_TEXT, TOOL_SHAPES, TOOL_CONNECTOR):
            if router._interaction.geometry_session(tool) is None:
                continue
            router._interaction.set_geometry_session(tool, None)
            if tool == TOOL_SHAPES:
                router.clear_shape_draft_paint()
            elif tool == TOOL_CONNECTOR:
                router.clear_connector_draft_paint()
        router._release_text_mouse()
        router._sync_tool_cursor()
    finally:
        router._cancelling_lost_pointer = False


def _event_buttons(event) -> int:
    if isinstance(event, QMouseEvent):
        return int(event.buttons())
    return 0


def _lost_release_event(event) -> bool:
    event_type = event.type()
    if event_type == QEvent.UngrabMouse:
        return True
    if event_type == QEvent.MouseButtonPress and hasattr(event, "button"):
        return event.button() == Qt.RightButton
    if event_type == QEvent.MouseMove:
        return not pointer_button_is_down(_event_buttons(event), int(Qt.LeftButton))
    return False


def _install_lost_release_guard() -> None:
    original = PointerRouter.handle_board_event
    if getattr(original, "_lost_release_guard", False):
        return

    def handle_board_event(self, watched, event):
        if _lost_release_event(event) and _pointer_gesture_open(self):
            _cancel_pointer_gesture(self)
            if event.type() != QEvent.UngrabMouse:
                event.accept()
                return True
            return False
        return original(self, watched, event)

    handle_board_event._lost_release_guard = True
    PointerRouter.handle_board_event = handle_board_event


_install_lost_release_guard()
