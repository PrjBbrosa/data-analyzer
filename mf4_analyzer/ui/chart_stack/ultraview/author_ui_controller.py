"""Author ToolRail / flyout / format-picker UI bridge.

Session mutable state stays on ``BoardInteractionController``. This
controller only projects that session onto chrome and translates rail /
flyout signals back into ``_interaction.*`` calls.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt5.QtCore import QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import QWidget

from .author_selection import picker_presentation_role, swatch_role_for
from .author_style import STICKY_PALETTE_TOKENS
from .author_tools import (
    CLOSED_SHAPE_TYPES,
    CONNECTOR_STROKE_PALETTES,
    SHAPE_CORNERS,
    SHAPE_FILL_PALETTES,
    SHAPE_STROKE_PALETTES,
    SHAPE_STROKE_WIDTHS,
    TOOL_CONNECTOR,
    TOOL_DRAW,
    TOOL_SELECT,
    TOOL_SHAPES,
    TOOL_STICKY,
    TOOL_TEXT,
    BoardInteractionController,
    is_draw_ink_subtool,
)
from .canvas_host import CanvasHost
from .floating_layout import OVERLAY_GAP, SAFE_MARGIN
from .tool_rail import (
    OVERLAY_AUTHOR_CONNECTOR,
    OVERLAY_AUTHOR_DRAW,
    OVERLAY_AUTHOR_FORMAT,
    OVERLAY_AUTHOR_POINTER,
    OVERLAY_AUTHOR_SHAPES,
    OVERLAY_AUTHOR_STICKY,
    ToolRail,
)


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        return


AUTHOR_TRANSIENT_OVERLAYS = frozenset(
    {
        OVERLAY_AUTHOR_POINTER,
        OVERLAY_AUTHOR_STICKY,
        OVERLAY_AUTHOR_SHAPES,
        OVERLAY_AUTHOR_CONNECTOR,
        OVERLAY_AUTHOR_DRAW,
        OVERLAY_AUTHOR_FORMAT,
    }
)
_FLYOUT_TRIGGER_TOOLS = {
    OVERLAY_AUTHOR_POINTER: TOOL_SELECT,
    OVERLAY_AUTHOR_STICKY: TOOL_STICKY,
    OVERLAY_AUTHOR_SHAPES: TOOL_SHAPES,
    OVERLAY_AUTHOR_CONNECTOR: TOOL_CONNECTOR,
    OVERLAY_AUTHOR_DRAW: TOOL_DRAW,
}


@dataclass(frozen=True)
class ActiveTransientFacts:
    """Immutable facts for the currently open author flyout or format picker."""

    overlay_id: str
    kind: str
    visible: bool
    trigger_tool: str | None = None
    format_key: str = ""


FORMAT_PICKER_KEYS = frozenset(
    {
        "palette",
        "shape",
        "font_size",
        "font_role",
        "align",
        "list_style",
        "text_palette",
        "fill_palette",
        "fill",
        "stroke",
        "width",
        "dash",
        "color",
        "route",
        "start_head",
        "end_head",
        "tool",
        "corner",
    }
)


class AuthorUiController:
    """Project author session onto ToolRail / flyouts / format picker."""

    def __init__(
        self,
        *,
        interaction: BoardInteractionController,
        canvas_host: CanvasHost,
        tool_rail: ToolRail,
        pointer_popover: QWidget,
        sticky_popover: QWidget,
        shape_popover: QWidget,
        connector_popover: QWidget,
        draw_popover: QWidget,
        format_picker: QWidget,
        selection_toolbar: QWidget,
        navigation_island: QWidget,
        status_island: QWidget,
        sync_tool_cursor: Callable[[], None],
        sync_free_grid_cursor: Callable[[], None],
        refresh_author_toolbar: Callable[[], None],
        sync_minimap_placement: Callable[[], None],
        reassert_host_stacking: Callable[[], None],
        selection_capabilities: Callable[[], Any],
        selection_bounds: Callable[[], QRect | None],
        author_item: Callable[[str], Any],
        apply_format: Callable[[str, object], None],
        text_field_has_focus: Callable[[], bool],
        creation_allowed: Callable[[], bool],
    ) -> None:
        self._interaction = interaction
        self._canvas_host = canvas_host
        self._tool_rail = tool_rail
        self._pointer_popover = pointer_popover
        self._sticky_popover = sticky_popover
        self._shape_popover = shape_popover
        self._connector_popover = connector_popover
        self._draw_popover = draw_popover
        self._format_picker = format_picker
        self._selection_toolbar = selection_toolbar
        self._navigation_island = navigation_island
        self._status_island = status_island
        self._sync_tool_cursor = sync_tool_cursor
        self._sync_free_grid_cursor = sync_free_grid_cursor
        self._refresh_author_toolbar = refresh_author_toolbar
        self._sync_minimap_placement = sync_minimap_placement
        self._reassert_host_stacking = reassert_host_stacking
        self._selection_capabilities = selection_capabilities
        self._selection_bounds = selection_bounds
        self._author_item = author_item
        self._apply_format = apply_format
        self._text_field_has_focus = text_field_has_focus
        self._creation_allowed = creation_allowed
        self._format_picker_key = ""
        self._connected = False
        self._slots: list[tuple[Any, Any]] = []

    def connect(self) -> None:
        if self._connected:
            return
        pairs = (
            (self._tool_rail.tool_requested, self.on_author_tool_requested),
            (self._tool_rail.tool_pinned_changed, self.on_author_tool_pinned),
            (self._tool_rail.pointer_menu_requested, self.on_pointer_menu_requested),
            (self._pointer_popover.mode_selected, self.on_pointer_mode_requested),
            (self._sticky_popover.palette_selected, self.on_sticky_palette_selected),
            (self._sticky_popover.pin_requested, self.on_sticky_pin_requested),
            (self._sticky_popover.stack_requested, self.on_sticky_stack_requested),
            (self._shape_popover.shape_selected, self.on_shape_selected),
            (self._shape_popover.connector_selected, self.on_connector_selected),
            (self._shape_popover.pin_requested, self.on_shape_pin_requested),
            (self._connector_popover.connector_selected, self.on_connector_selected),
            (self._connector_popover.pin_requested, self.on_connector_pin_requested),
            (self._draw_popover.tool_selected, self.on_draw_tool_selected),
            (self._draw_popover.layoutChanged, self.relayout_draw_popover),
            (self._selection_toolbar.format_requested, self._apply_format),
            (self._format_picker.choice_selected, self.on_format_choice_selected),
            (self._selection_toolbar.schema_will_rebuild, self.close_format_picker),
        )
        for signal, slot in pairs:
            signal.connect(slot)
            self._slots.append((signal, slot))
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        for signal, slot in self._slots:
            _disconnect(signal, slot)
        self._slots.clear()
        self._connected = False

    def reset(self) -> None:
        self.close_author_flyouts()
        self.close_format_picker()

    def shutdown(self) -> None:
        self.reset()
        self.disconnect()

    def format_picker_key(self) -> str:
        return self._format_picker_key

    def set_format_picker_key(self, value: str) -> None:
        self._format_picker_key = str(value or "")

    def author_flyouts(self) -> tuple[QWidget, ...]:
        return (
            self._pointer_popover,
            self._sticky_popover,
            self._shape_popover,
            self._connector_popover,
            self._draw_popover,
        )

    def handle_overlay_closed(self, panel_id: str) -> bool:
        if panel_id == OVERLAY_AUTHOR_FORMAT:
            self._format_picker_key = ""
            self._sync_minimap_placement()
            return True
        if panel_id == OVERLAY_AUTHOR_POINTER:
            self._tool_rail.set_pointer_menu_open(False)
        return False

    def sync_tool_rail_from_controller(self) -> None:
        if not self._tool_rail.visible_author_tools():
            return
        tool = self._interaction.active_tool()
        rail_tool = TOOL_SHAPES if tool == TOOL_CONNECTOR else tool
        pinned = self._interaction.pinned_tool() == tool and tool != TOOL_SELECT
        try:
            self._tool_rail.set_draw_subtool(self._interaction.last_draw_subtool())
            self._tool_rail.set_pointer_mode(self._interaction.pointer_mode())
            self._tool_rail.set_active_tool(rail_tool, pinned=pinned)
        except ValueError:
            return

    def on_author_tool_requested(self, tool: str) -> None:
        flyout_tools = {TOOL_STICKY, TOOL_SHAPES, TOOL_DRAW}
        if tool in flyout_tools:
            already = self._interaction.active_tool() == tool
            if not already:
                self._interaction.set_active_tool(tool)
                self.sync_tool_rail_from_controller()
                self._sync_tool_cursor()
                self.show_tool_flyout(tool)
                return
            self.toggle_tool_flyout(tool)
            return
        self.close_author_flyouts()
        if tool == TOOL_SELECT:
            self.apply_pointer_mode(self._interaction.pointer_mode())
            return
        self._interaction.set_active_tool(tool)
        self.sync_tool_rail_from_controller()
        self._sync_tool_cursor()

    def on_pointer_menu_requested(self) -> None:
        if not self._creation_allowed():
            return
        if self._pointer_popover.isVisible():
            self._canvas_host.close_overlay(OVERLAY_AUTHOR_POINTER)
            self._tool_rail.set_pointer_menu_open(False)
            return
        self.show_pointer_popover()

    def on_pointer_mode_requested(self, mode: str) -> None:
        self.apply_pointer_mode(mode)
        if self._pointer_popover.isVisible():
            self._pointer_popover.close()

    def apply_pointer_mode(self, mode: str) -> None:
        self.close_author_flyouts(keep=self._pointer_popover)
        self._interaction.activate_pointer_mode(mode)
        self.sync_tool_rail_from_controller()
        self._sync_tool_cursor()
        self._refresh_author_toolbar()

    def show_pointer_popover(self) -> None:
        button = self._tool_rail.tool_button(TOOL_SELECT)
        if button is None:
            return
        self._pointer_popover.set_mode(self._interaction.pointer_mode(), emit=False)
        self.open_author_flyout(OVERLAY_AUTHOR_POINTER, self._pointer_popover, button)

    def on_author_tool_pinned(self, tool: str, pinned: bool) -> None:
        self._interaction.set_active_tool(tool, pinned=bool(pinned))
        self.sync_tool_rail_from_controller()
        self._sync_free_grid_cursor()

    def on_sticky_palette_selected(self, token: str) -> None:
        self._interaction.set_sticky_palette(token)
        if self._interaction.pinned_tool() == TOOL_STICKY:
            self.on_author_tool_pinned(TOOL_STICKY, False)
        if self._interaction.active_tool() != TOOL_STICKY:
            self._interaction.set_active_tool(TOOL_STICKY)
            self.sync_tool_rail_from_controller()
            self._sync_free_grid_cursor()

    def on_sticky_stack_requested(self, token: str) -> None:
        self._interaction.set_sticky_palette(token)
        self.on_author_tool_pinned(TOOL_STICKY, True)
        self.sync_tool_rail_from_controller()
        self._sync_free_grid_cursor()

    def show_sticky_popover(self) -> None:
        button = self._tool_rail.tool_button(TOOL_STICKY)
        if button is None:
            return
        self._sticky_popover.choose_palette(
            self._interaction.sticky_palette(), emit=False
        )
        self._sticky_popover.set_pinned(self._interaction.pinned_tool() == TOOL_STICKY)
        self.open_author_flyout(OVERLAY_AUTHOR_STICKY, self._sticky_popover, button)

    def on_sticky_pin_requested(self, pinned: bool) -> None:
        self.on_author_tool_pinned(TOOL_STICKY, bool(pinned))

    def on_shape_selected(self, shape: str) -> None:
        self._interaction.set_last_shape(shape)
        self._interaction.set_shape_format(shape=shape)
        if self._interaction.active_tool() != TOOL_SHAPES:
            self._interaction.set_active_tool(TOOL_SHAPES)
        self.sync_tool_rail_from_controller()
        self._sync_free_grid_cursor()

    def on_shape_pin_requested(self, pinned: bool) -> None:
        self.on_author_tool_pinned(TOOL_SHAPES, bool(pinned))

    def show_shape_popover(self) -> None:
        button = self._tool_rail.tool_button(TOOL_SHAPES)
        if button is None:
            return
        self._shape_popover.set_pinned(self._interaction.pinned_tool() == TOOL_SHAPES)
        self.open_author_flyout(OVERLAY_AUTHOR_SHAPES, self._shape_popover, button)

    def on_select_tool_shortcut(self) -> None:
        if self._text_field_has_focus() or not self._tool_rail.visible_author_tools():
            return
        self.apply_pointer_mode(self._interaction.pointer_mode())

    def on_sticky_tool_shortcut(self) -> None:
        if self._text_field_has_focus() or not self._creation_allowed():
            return
        self.on_author_tool_requested(TOOL_STICKY)

    def on_text_tool_shortcut(self) -> None:
        if self._text_field_has_focus() or not self._creation_allowed():
            return
        if TOOL_TEXT not in self._tool_rail.visible_author_tools():
            return
        self.on_author_tool_requested(TOOL_TEXT)

    def on_shape_tool_shortcut(self) -> None:
        if self._text_field_has_focus() or not self._creation_allowed():
            return
        if TOOL_SHAPES not in self._tool_rail.visible_author_tools():
            return
        self.on_author_tool_requested(TOOL_SHAPES)

    def on_connector_selected(self, kind: str) -> None:
        self._interaction.set_last_connector(kind)
        self._interaction.set_connector_format(connector_type=kind)
        if self._interaction.active_tool() != TOOL_CONNECTOR:
            self._interaction.set_active_tool(TOOL_CONNECTOR)
        self.sync_tool_rail_from_controller()
        self._sync_free_grid_cursor()

    def on_connector_pin_requested(self, pinned: bool) -> None:
        self.on_author_tool_pinned(TOOL_CONNECTOR, bool(pinned))

    def show_connector_popover(self) -> None:
        button = self._tool_rail.tool_button(TOOL_CONNECTOR)
        if button is None:
            return
        self._connector_popover.set_pinned(self._interaction.pinned_tool() == TOOL_CONNECTOR)
        self.open_author_flyout(OVERLAY_AUTHOR_CONNECTOR, self._connector_popover, button)

    def on_connector_tool_shortcut(self) -> None:
        if self._text_field_has_focus() or not self._creation_allowed():
            return
        self.close_author_flyouts()
        self._interaction.set_active_tool(TOOL_CONNECTOR)
        self.sync_tool_rail_from_controller()
        self._sync_tool_cursor()

    def on_draw_tool_selected(self, tool: str, preset_index: int) -> None:
        if not is_draw_ink_subtool(tool):
            self._interaction.set_draw_style(tool=tool, preset_index=0)
            if self._interaction.active_tool() != TOOL_DRAW:
                self._interaction.set_active_tool(TOOL_DRAW)
            self.sync_tool_rail_from_controller()
            self._sync_tool_cursor()
            return
        presets = self._draw_popover.presets(tool)
        if not 0 <= int(preset_index) < len(presets):
            return
        preset = presets[int(preset_index)]
        self._interaction.set_draw_style(
            tool=tool,
            palette=preset.palette,
            width_px_100=preset.width_px_100,
            preset_index=int(preset_index),
        )
        if self._interaction.active_tool() != TOOL_DRAW:
            self._interaction.set_active_tool(TOOL_DRAW)
        self.sync_tool_rail_from_controller()
        self._sync_tool_cursor()

    def show_draw_popover(self) -> None:
        button = self._tool_rail.tool_button(TOOL_DRAW)
        if button is None:
            return
        subtool = self._interaction.last_draw_subtool()
        preset = 0 if not is_draw_ink_subtool(subtool) else self._interaction.draw_preset_index()
        self._draw_popover.choose_tool(subtool, preset)
        self.open_author_flyout(OVERLAY_AUTHOR_DRAW, self._draw_popover, button)

    def relayout_draw_popover(self) -> None:
        if not self._draw_popover.isVisible():
            return
        self.reanchor_open_transient()

    def on_draw_tool_shortcut(self) -> None:
        if self._text_field_has_focus() or not self._creation_allowed():
            return
        if TOOL_DRAW not in self._tool_rail.visible_author_tools():
            return
        self.on_author_tool_requested(TOOL_DRAW)

    def active_transient_facts(self) -> ActiveTransientFacts | None:
        """Public snapshot of the live author overlay. No widget internals."""
        overlay_id = self._canvas_host.active_overlay()
        if overlay_id not in AUTHOR_TRANSIENT_OVERLAYS:
            return None
        widget = self._canvas_host.overlay(overlay_id)
        visible = bool(widget is not None and widget.isVisible())
        if not visible:
            return None
        if overlay_id == OVERLAY_AUTHOR_FORMAT:
            return ActiveTransientFacts(
                overlay_id=overlay_id,
                kind="format",
                visible=True,
                format_key=str(self._format_picker_key or ""),
            )
        return ActiveTransientFacts(
            overlay_id=overlay_id,
            kind="flyout",
            visible=True,
            trigger_tool=_FLYOUT_TRIGGER_TOOLS.get(overlay_id),
        )

    def reanchor_open_transient(self) -> None:
        """Recompute the open author overlay against the live trigger and safe area.

        Closed transients stay closed. Active tool, selection, pointer mode,
        and focus owner are not changed.
        """
        facts = self.active_transient_facts()
        if facts is None:
            return
        widget = self._canvas_host.overlay(facts.overlay_id)
        if widget is None or not widget.isVisible():
            return
        if facts.kind == "format":
            key = facts.format_key
            button = self._selection_toolbar.button(key) if key else None
            if button is None:
                return
            size = widget.content_size() if callable(getattr(widget, "content_size", None)) else widget.size()
            rect = self.format_picker_rect(button, size)
        else:
            button = self._live_flyout_trigger(facts.overlay_id)
            if button is None:
                return
            size = widget.content_size() if callable(getattr(widget, "content_size", None)) else widget.size()
            rect = self.author_flyout_rect(button, size)
        self._sync_transient_scroll(widget, rect.height())
        self._canvas_host.set_overlay_geometry(facts.overlay_id, rect)
        self._reassert_host_stacking()
        self._sync_minimap_placement()

    def _live_flyout_trigger(self, overlay_id: str) -> QWidget | None:
        tool = _FLYOUT_TRIGGER_TOOLS.get(overlay_id)
        if tool is not None:
            button = self._tool_rail.tool_button(tool)
            if button is not None:
                return button
        return self._canvas_host.overlay_trigger(overlay_id)

    @staticmethod
    def _sync_transient_scroll(widget: QWidget, available_height: int) -> None:
        sync = getattr(widget, "sync_vertical_scroll_for_height", None)
        if callable(sync):
            sync(available_height)

    def author_flyout_safe_rect(self) -> QRect:
        host = self._canvas_host.contentsRect()
        rect = host.adjusted(SAFE_MARGIN, SAFE_MARGIN, -SAFE_MARGIN, -SAFE_MARGIN)
        bottoms = []
        for island in (self._navigation_island, self._status_island):
            if island is not None and island.isVisible():
                bottoms.append(island.geometry().top() - OVERLAY_GAP)
        if bottoms:
            rect.setBottom(min(rect.bottom(), min(bottoms)))
        return rect

    def author_flyout_rect(self, button: QWidget | None, size: QSize) -> QRect:
        safe = self.author_flyout_safe_rect()
        width = min(max(1, size.width()), safe.width())
        height = min(max(1, size.height()), safe.height())
        rail = self._tool_rail.geometry()
        x = rail.right() + OVERLAY_GAP
        if x + width > safe.right():
            x = rail.left() - OVERLAY_GAP - width
        y = button.mapTo(self._canvas_host, QPoint(0, 0)).y() if button is not None else safe.top()
        if y + height > safe.bottom():
            y = safe.bottom() - height
        x = min(max(safe.left(), x), safe.right() - width)
        y = min(max(safe.top(), y), safe.bottom() - height)
        return QRect(x, y, width, height)

    def open_author_flyout(self, overlay_id: str, flyout, button: QWidget | None) -> None:
        # Tool and selection flyouts share CanvasHost: never leave a stale
        # format picker below a newly opened Shapes/Draw/Pointer surface.
        self.close_format_picker()
        size = flyout.content_size()
        rect = self.author_flyout_rect(button, size)
        self._sync_transient_scroll(flyout, rect.height())
        self._canvas_host.open_overlay(overlay_id, rect)
        self._tool_rail.set_pointer_menu_open(overlay_id == OVERLAY_AUTHOR_POINTER)
        self._reassert_host_stacking()
        self._sync_minimap_placement()

    def close_author_flyouts(self, keep=None) -> None:
        for flyout in self.author_flyouts():
            if flyout is keep:
                continue
            key = flyout.property("overlayId")
            if key and self._canvas_host.active_overlay() == str(key):
                self._canvas_host.close_overlay(str(key), restore_focus=False)
            elif flyout.isVisible():
                flyout.hide()
        if keep is not self._pointer_popover:
            opened = (
                self._canvas_host.active_overlay() == OVERLAY_AUTHOR_POINTER
                and self._pointer_popover.isVisible()
            )
            self._tool_rail.set_pointer_menu_open(opened)
        self._sync_minimap_placement()

    def show_tool_flyout(self, tool: str) -> None:
        if tool == TOOL_STICKY:
            self.close_author_flyouts(keep=self._sticky_popover)
            self.show_sticky_popover()
        elif tool == TOOL_SHAPES:
            self.close_author_flyouts(keep=self._shape_popover)
            self.show_shape_popover()
        elif tool == TOOL_DRAW:
            self.close_author_flyouts(keep=self._draw_popover)
            self.show_draw_popover()
        elif tool == TOOL_CONNECTOR:
            self.close_author_flyouts(keep=self._shape_popover)
            self.show_shape_popover()

    def toggle_tool_flyout(self, tool: str) -> None:
        mapping = {
            TOOL_STICKY: self._sticky_popover,
            TOOL_SHAPES: self._shape_popover,
            TOOL_DRAW: self._draw_popover,
        }
        flyout = mapping.get(tool)
        if flyout is None:
            return
        if flyout.isVisible():
            flyout.close()
            return
        self.show_tool_flyout(tool)

    def close_format_picker(self) -> None:
        if self._canvas_host.active_overlay() == OVERLAY_AUTHOR_FORMAT:
            self._canvas_host.close_overlay(OVERLAY_AUTHOR_FORMAT, restore_focus=False)
        elif self._format_picker.isVisible():
            self._format_picker.hide()
        self._format_picker_key = ""
        self._sync_minimap_placement()

    def format_picker_rect(self, button: QWidget, size: QSize) -> QRect:
        safe = self.author_flyout_safe_rect()
        width = min(max(1, size.width()), safe.width())
        height = min(max(1, size.height()), safe.height())
        origin = button.mapTo(self._canvas_host, QPoint(0, 0))
        x = origin.x()
        below = origin.y() + button.height() + 6
        above = origin.y() - 6
        below_room = safe.bottom() - below
        above_room = above - safe.top()
        if below_room >= height or below_room >= above_room:
            y = below
            height = min(height, max(1, below_room))
        else:
            height = min(height, max(1, above_room))
            y = above - height
        if x + width > safe.right():
            x = origin.x() + button.width() - width
        x = min(max(safe.left(), x), max(safe.left(), safe.right() - width))
        y = min(max(safe.top(), y), max(safe.top(), safe.bottom() - height))
        rect = QRect(x, y, width, height)
        # Keep a short format list usable without covering the object currently
        # being edited whenever there is room beside it.  This is especially
        # important for Shapes, whose outline otherwise looks like a clipping
        # or z-order fault under the dropdown.
        bounds = self._selection_bounds()
        if bounds is not None and rect.intersects(bounds):
            candidates = (
                QRect(bounds.right() + 7, rect.y(), width, height),
                QRect(bounds.left() - width - 7, rect.y(), width, height),
            )
            for candidate in candidates:
                if safe.contains(candidate) and not candidate.intersects(bounds):
                    return candidate
        return rect

    def on_format_choice_selected(self, value: object) -> None:
        key = self._format_picker_key
        if not key:
            return
        self.close_format_picker()
        self._apply_format(key, value)

    def popup_format_picker(self, key: str) -> None:
        caps = self._selection_capabilities()
        button = self._selection_toolbar.button(key)
        if button is None:
            return
        picker = self._format_picker
        if (
            self._format_picker_key == key
            and self._canvas_host.active_overlay() == OVERLAY_AUTHOR_FORMAT
            and picker.isVisible()
        ):
            self.close_format_picker()
            return
        # A formatting dropdown and a creation flyout must not coexist or
        # compete for the visual top layer.
        self.close_author_flyouts()
        self._format_picker_key = key
        ids = caps.author_ids
        item = self._author_item(ids[0]) if len(ids) == 1 else None
        presentation = picker_presentation_role(key)
        role = swatch_role_for(caps.kind, key)
        if caps.kind == "sticky" and key == "palette":
            picker.present_palette(
                STICKY_PALETTE_TOKENS,
                current=getattr(item, "palette", None),
                swatch_role=role or "sticky",
            )
        elif caps.kind == "sticky" and key == "font_size":
            picker.present_labels(
                tuple((size, str(size)) for size in ("auto", 12, 14, 18, 24)),
                current=getattr(item, "font_size", None),
                presentation=presentation,
            )
        elif caps.kind == "shape" and key == "shape":
            picker.present_shapes(CLOSED_SHAPE_TYPES, current=getattr(item, "shape", None))
        elif caps.kind == "shape" and key == "fill":
            picker.present_palette(
                SHAPE_FILL_PALETTES,
                current=getattr(item, "fill_palette", None),
                swatch_role=role or "fill",
            )
        elif key in {"stroke", "color"}:
            picker.present_palette(
                SHAPE_STROKE_PALETTES if caps.kind != "stroke" else CONNECTOR_STROKE_PALETTES,
                current=getattr(item, "stroke_palette", None) or getattr(item, "palette", None),
                swatch_role=role or ("ink" if caps.kind == "stroke" else "stroke"),
            )
        elif key == "width":
            widths = SHAPE_STROKE_WIDTHS if caps.kind != "stroke" else (2, 4, 8, 16)
            picker.present_labels(
                tuple((width, f"{width} px") for width in widths),
                current=getattr(item, "stroke_width", None) or getattr(item, "width_px_100", None),
                presentation=presentation,
            )
        elif key == "dash":
            picker.present_labels(
                (("solid", "实线"), ("dashed", "虚线")),
                current=getattr(item, "line_style", None),
                presentation=presentation,
            )
        elif key == "route":
            picker.present_labels(
                (("straight", "直线"), ("elbow", "折线")),
                current=getattr(item, "route", None),
                presentation=presentation,
            )
        elif key in {"start_head", "end_head"}:
            picker.present_labels(
                (("none", "无"), ("arrow", "箭头")),
                current=getattr(item, key, None),
                presentation=presentation,
            )
        elif key == "tool":
            picker.present_labels(
                (("pen", "钢笔"), ("highlighter", "荧光笔")),
                current=getattr(item, "tool", None),
                presentation=presentation,
            )
        elif key == "font_role":
            picker.present_labels(
                (("sans", "Sans"), ("serif", "Serif"), ("mono", "Mono")),
                current=getattr(item, "font_role", None),
                presentation=presentation,
            )
        elif key == "font_size" and caps.kind == "text":
            picker.present_labels(
                tuple((size, str(size)) for size in (8, 10, 12, 14, 18, 24, 32, 48, 72)),
                current=getattr(item, "font_size", None),
                presentation=presentation,
            )
        elif key == "align":
            picker.present_labels(
                (("left", "左"), ("center", "中"), ("right", "右")),
                current=getattr(item, "align", None),
                presentation=presentation,
            )
        elif key == "list_style":
            picker.present_labels(
                (("none", "无"), ("bullet", "项目符号"), ("number", "编号")),
                current=getattr(item, "list_style", None),
                presentation=presentation,
            )
        elif key == "text_palette":
            picker.present_palette(
                ("ink", "blue", "red", "green"),
                current=getattr(item, "text_palette", None),
                swatch_role=role or "text",
            )
        elif key == "fill_palette":
            picker.present_palette(
                (None, "yellow", "blue", "green"),
                current=getattr(item, "fill_palette", None),
                swatch_role=role or "fill",
            )
        elif key == "corner":
            picker.present_labels(
                tuple((value, str(value)) for value in SHAPE_CORNERS),
                current=getattr(item, "corner_radius", None),
                presentation=presentation,
            )
        else:
            self.close_format_picker()
            return
        live_trigger = self._selection_toolbar.button(key) or button
        size = picker.content_size()
        rect = self.format_picker_rect(live_trigger, size)
        self._sync_transient_scroll(picker, rect.height())
        self._canvas_host.open_overlay(OVERLAY_AUTHOR_FORMAT, rect)
        self._reassert_host_stacking()
        self._sync_minimap_placement()
