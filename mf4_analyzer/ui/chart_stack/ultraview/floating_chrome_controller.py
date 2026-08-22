"""Apply UltraView floating chrome. Page remains the composition root.

Geometry policy stays in ``floating_layout.py`` (``calculate_floating_layout``,
``place_minimap``, ``overlay_anchor_facts``). This controller only collects
public facts, calls that policy, and writes widget geometry / stacking.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtWidgets import QWidget

from .author_chrome import SelectionToolbar
from .author_geometry import HANDLE_HIT_PX as AUTHOR_HANDLE_HIT_PX
from .canvas_host import CanvasHost
from .chrome_popovers import BoardPopover
from .free_grid import HANDLE_HIT_PX as CARD_HANDLE_HIT_PX
from .floating_layout import (
    DEFAULT_MINIMAP_SIZE,
    OVERLAY_GAP,
    RAIL_WIDTH_COMPACT,
    SAFE_MARGIN,
    MinimapPlacementFacts,
    Rect as FloatingRect,
    is_compact_stage,
    minimap_placement_fingerprint,
    place_minimap,
)
from .tool_rail import PANEL_BOARDS, PANEL_LIBRARY, ToolRail


def _qrect(rect: FloatingRect) -> QRect:
    return QRect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))


class FloatingChromeController:
    """Own floating chrome apply, minimap fingerprint, and stacking."""

    def __init__(
        self,
        *,
        canvas_host: CanvasHost,
        board_scroll: QWidget,
        tool_rail: ToolRail,
        board_island: QWidget,
        global_island: QWidget,
        status_island: QWidget,
        navigation_island: QWidget,
        overview: QWidget,
        minimap: QWidget,
        selection_toolbar: SelectionToolbar,
        empty_board_hint: QWidget,
        card_context: QWidget,
        format_picker: QWidget,
        board_popover: BoardPopover,
        author_flyouts: Sequence[QWidget],
        text_editor: QWidget,
        sticky_editor: QWidget,
        layout_for: Callable[..., Any],
        active_panel: Callable[[], str | None],
        board_popover_rect: Callable[[], QRect],
        minimap_should_show: Callable[[], bool],
        drag_active: Callable[[], bool],
        interaction_facts: Callable[[], Mapping[str, bool]],
        page_geometry_active: Callable[[], bool],
        selection_bounds: Callable[[], QRect | None],
        selection_capabilities: Callable[[], Any],
        close_format_picker: Callable[[], None],
        is_presentation: Callable[[], bool],
        page_size: Callable[[], tuple[int, int]],
        draft_active: Callable[[], bool],
        sync_empty_board_cue: Callable[[], None],
        sync_feedback_surface: Callable[[], None],
        position_card_context: Callable[[], None],
    ) -> None:
        self._canvas_host = canvas_host
        self._board_scroll = board_scroll
        self._tool_rail = tool_rail
        self._board_island = board_island
        self._global_island = global_island
        self._status_island = status_island
        self._navigation_island = navigation_island
        self._overview = overview
        self._minimap = minimap
        self._selection_toolbar = selection_toolbar
        self._empty_board_hint = empty_board_hint
        self._card_context = card_context
        self._format_picker = format_picker
        self._board_popover = board_popover
        self._author_flyouts = tuple(author_flyouts)
        self._text_editor = text_editor
        self._sticky_editor = sticky_editor
        self._layout_for = layout_for
        self._active_panel = active_panel
        self._board_popover_rect = board_popover_rect
        self._minimap_should_show = minimap_should_show
        self._drag_active = drag_active
        self._interaction_facts = interaction_facts
        self._page_geometry_active = page_geometry_active
        self._selection_bounds = selection_bounds
        self._selection_capabilities = selection_capabilities
        self._close_format_picker = close_format_picker
        self._is_presentation = is_presentation
        self._page_size = page_size
        self._draft_active = draft_active
        self._sync_empty_board_cue = sync_empty_board_cue
        self._sync_feedback_surface = sync_feedback_surface
        self._position_card_context = position_card_context
        self._minimap_placement_key: tuple | None = None

    def apply(self, layout=None) -> None:
        """Place the scroll viewport and all fixed chrome without reflow."""
        layout = self._layout_for() if layout is None else layout
        self._tool_rail.set_compact(layout.rail.width <= RAIL_WIDTH_COMPACT)
        self._board_scroll.setGeometry(_qrect(layout.board))
        self._tool_rail.setGeometry(_qrect(layout.rail))
        self._board_island.setGeometry(_qrect(layout.board_island))
        self._global_island.setGeometry(_qrect(layout.global_island))
        self._status_island.setGeometry(_qrect(layout.status_island))
        self._navigation_island.setGeometry(_qrect(layout.navigation_island))
        self._sync_empty_board_cue()
        panel = self._active_panel()
        if panel == PANEL_BOARDS:
            self._canvas_host.set_overlay_geometry(PANEL_BOARDS, self._board_popover_rect())
            self._board_popover.relayout()
        elif panel is not None and layout.overlay is not None:
            self._canvas_host.set_overlay_geometry(panel, _qrect(layout.overlay))
        if self._overview.isVisible():
            self._overview.setGeometry(self._board_scroll.geometry())
            self._card_context.hide()
        self._sync_feedback_surface()
        self.sync_minimap_placement(layout)
        if not self._overview.isVisible():
            self._position_card_context()
            self.refresh_author_toolbar()
        self.reassert_stacking()

    def reassert_stacking(self) -> None:
        extra = (
            self._tool_rail,
            self._board_island,
            self._global_island,
            self._status_island,
            self._navigation_island,
            self._empty_board_hint,
            self._overview,
            self._minimap,
            self._selection_toolbar,
            self._card_context,
        )
        self._canvas_host.reassert_stacking(extra)

    def position_empty_board_hint(self) -> None:
        button = self._tool_rail.panel_button(PANEL_LIBRARY)
        hint = self._empty_board_hint
        if button is None:
            return
        hint.adjustSize()
        center = button.mapTo(self._canvas_host, button.rect().center())
        x = self._tool_rail.geometry().right() + 14
        y = center.y() - hint.height() // 2
        hint.move(x, max(0, y))
        self.reassert_stacking()

    def refresh_author_toolbar(self) -> None:
        toolbar = self._selection_toolbar

        def hide_toolbar() -> None:
            self._close_format_picker()
            toolbar.hide()
            self.sync_minimap_placement()

        if self._is_presentation() or self._overview.isVisible():
            hide_toolbar()
            return
        facts = self._interaction_facts()
        if self._drag_active() or facts["gesture_active"]:
            hide_toolbar()
            return
        if self._draft_active():
            hide_toolbar()
            return
        if self._page_geometry_active() or facts["author_geometry_active"]:
            hide_toolbar()
            return
        caps = self._selection_capabilities()
        if caps.kind in {"empty", "", "card", "card_author"}:
            hide_toolbar()
            return
        bounds = self._selection_bounds()
        if bounds is None or bounds.isNull():
            hide_toolbar()
            return
        toolbar.apply_capabilities(caps)
        width, height = self._page_size()
        toolbar.set_compact(width < 900 or is_compact_stage((width, height)))
        toolbar.prepare_layout()
        hint = toolbar.sizeHint()
        host = self._canvas_host.contentsRect()
        safe = host.adjusted(SAFE_MARGIN, SAFE_MARGIN, -SAFE_MARGIN, -SAFE_MARGIN)
        rail_right = self._tool_rail.geometry().right()
        safe.setLeft(max(safe.left(), rail_right + OVERLAY_GAP))
        bar_h = max(48, hint.height())
        gap = 8
        bar_width = min(max(hint.width(), 1), max(1, safe.width()))
        bar_h = min(bar_h, max(1, safe.height()))
        above = bounds.y() - gap - bar_h
        below = bounds.bottom() + gap
        if above >= safe.top():
            top = above
        elif below + bar_h <= safe.bottom():
            top = below
        else:
            top = min(max(safe.top(), bounds.center().y() - bar_h // 2), safe.bottom() - bar_h)
        left = bounds.center().x() - bar_width // 2
        left = min(max(safe.left(), left), safe.right() - bar_width)
        top = min(max(safe.top(), top), safe.bottom() - bar_h)
        toolbar.setGeometry(left, top, bar_width, bar_h)
        toolbar.show()
        self.reassert_stacking()
        self.sync_minimap_placement()

    def minimap_geometry_gesture_active(self) -> bool:
        if self._drag_active():
            return True
        facts = self._interaction_facts()
        if (
            facts["gesture_armed"]
            or facts["gesture_active"]
            or facts["marquee_active"]
            or facts["author_geometry_active"]
        ):
            return True
        return bool(self._page_geometry_active())

    def hide_minimap(self) -> None:
        self._minimap_placement_key = None
        self._minimap.hide()

    def hide(self) -> None:
        self.hide_minimap()

    def reset(self) -> None:
        self.hide_minimap()

    def sync_minimap_placement(self, floating=None) -> None:
        if not self._minimap_should_show():
            self.hide_minimap()
            return
        facts = self._minimap_placement_facts(floating)
        key = minimap_placement_fingerprint(facts)
        if key == self._minimap_placement_key:
            return
        self._minimap_placement_key = key
        placed = place_minimap(facts)
        if placed is None:
            self._minimap.hide()
            return
        viewport = self._board_scroll.viewport()
        global_point = self._canvas_host.mapToGlobal(QPoint(placed.x, placed.y))
        local_point = viewport.mapFromGlobal(global_point)
        self._minimap.move(local_point)
        self._minimap.show()
        self.reassert_stacking()

    def position_minimap(self, floating=None) -> None:
        self.sync_minimap_placement(floating)

    def _widget_rect_in_host(self, widget: QWidget | None) -> FloatingRect | None:
        if widget is None:
            return None
        try:
            if widget.isHidden() or widget.width() <= 0 or widget.height() <= 0:
                return None
            top_left = widget.mapTo(self._canvas_host, QPoint(0, 0))
        except RuntimeError:
            return None
        return FloatingRect(top_left.x(), top_left.y(), widget.width(), widget.height())

    def _minimap_avoid_rects(self) -> tuple[FloatingRect, ...]:
        avoid: list[FloatingRect] = []
        bounds = self._selection_bounds()
        if bounds is not None and not bounds.isNull():
            margin = max(AUTHOR_HANDLE_HIT_PX, CARD_HANDLE_HIT_PX)
            inflated = bounds.adjusted(-margin, -margin, margin, margin)
            avoid.append(
                FloatingRect(
                    inflated.x(), inflated.y(), inflated.width(), inflated.height()
                )
            )
        for widget in (
            self._selection_toolbar,
            self._format_picker,
            *self._author_flyouts,
        ):
            rect = self._widget_rect_in_host(widget)
            if rect is not None:
                avoid.append(rect)
        for widget in (self._text_editor, self._sticky_editor):
            if not widget.is_editing():
                continue
            rect = self._widget_rect_in_host(widget)
            if rect is not None:
                avoid.append(rect)
        return tuple(avoid)

    def _minimap_placement_facts(self, floating=None) -> MinimapPlacementFacts:
        layout = floating if floating is not None else self._layout_for()
        size: tuple[int, int] | None = None
        if self._minimap_should_show():
            width = int(self._minimap.width()) or DEFAULT_MINIMAP_SIZE[0]
            height = int(self._minimap.height()) or DEFAULT_MINIMAP_SIZE[1]
            size = (width, height)
        return MinimapPlacementFacts(
            stage=layout.stage,
            board_island=layout.board_island,
            global_island=layout.global_island,
            status_island=layout.status_island,
            navigation_island=layout.navigation_island,
            rail=layout.rail,
            avoid=self._minimap_avoid_rects(),
            gesture_active=self.minimap_geometry_gesture_active(),
            size=size,
        )
