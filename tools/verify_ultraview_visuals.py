"""Offscreen UltraView visual harness (geometry + contact sheet).

Generates named PNG shots, a JSON manifest with geometry facts, and a tiled
contact sheet under ``.state/ultraview-p0/`` by default. Screenshots are
verification evidence and are not committed.

Offscreen proves structure and pixel rules. Cocoa foreground and Windows
frozen executables are separate evidence classes.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".state" / "ultraview-p0"

REQUIRED_SHOTS = (
    "narrow_800",
    "narrow_1280",
    "narrow_1440",
    "library_1280",
    "library_groups_1280",
    "layout_1280",
    "filter_1280",
    "unplaced_1280",
    "display_1280",
    "export_1280",
    "boards_1280",
    "card_context_1280",
    "board_context_1280",
    "board_context_800",
    "arrange_before_1280",
    "arrange_after_1280",
    "presentation_1280",
    "pointer_popup_800",
    "pointer_popup_1280",
    "selected_bottom_right_with_minimap",
    "selected_shape_format_picker",
    "laser_cursor",
)

#: Fail-closed visual-facts schema. Missing or mismatched versions must not
#: validate as if chrome were proven on-stage.
MANIFEST_SCHEMA_VERSION = 2
HOST_COORD_SPACE = "host"
_SELECTION_CHROME_KEYS = (
    "stage",
    "target",
    "selection_bounds",
    "handles",
    "toolbar",
    "picker",
    "minimap",
)


@dataclass
class _Preview:
    ref: Any
    image: QImage | None = None
    captured_digest: str | None = None
    title: str = ""
    source_summary: str = ""
    tab_color: str = "#2d7ff9"
    axis_kind: str = "time"
    x_unit: str = "s"
    x_range: tuple[float, float] | None = (0.0, 10.0)


class GeometryError(AssertionError):
    """One or more visual geometry contracts failed."""


def _ensure_app() -> QApplication:
    from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    setup_chinese_font()
    load_stylesheet(app)
    return app


def _image(width: int = 96, height: int = 64, color: str = "#2d7ff9") -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(color))
    return image


def _pump(app: QApplication, widget: QWidget) -> None:
    from PyQt5.QtTest import QTest

    widget.show()
    for _ in range(4):
        app.processEvents()
    QTest.qWait(30)
    app.processEvents()


def _rect(widget: QWidget) -> dict[str, Any]:
    geo = widget.geometry()
    return {
        "x": int(geo.x()),
        "y": int(geo.y()),
        "w": int(geo.width()),
        "h": int(geo.height()),
        "visible": bool(widget.isVisible()),
    }


def _edge_rhythm(page) -> dict[str, Any]:
    """Record the persistent island axes without relying on screenshot pixels."""
    from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import ISLAND_GAP

    host = page.canvas_host()
    rail = page.tool_rail()
    board_island = page.board_island()
    status_island = page.status_island()
    global_island = page.global_island()
    navigation_island = page.navigation_island()
    band_top = board_island.y() + board_island.height() + ISLAND_GAP
    band_bottom = status_island.y() - ISLAND_GAP
    return {
        "stage": {"w": int(host.width()), "h": int(host.height())},
        "left_edges": {
            "rail": int(rail.x()),
            "board_island": int(board_island.x()),
            "status_island": int(status_island.x()),
        },
        "right_edges": {
            "global_island": int(global_island.x() + global_island.width()),
            "navigation_island": int(navigation_island.x() + navigation_island.width()),
        },
        "rail": {
            "height": int(rail.height()),
            "preferred_height": int(rail.sizeHint().height()),
            "center_error_px": int(2 * rail.y() + rail.height() - host.height()),
            "available_band_px": max(0, band_bottom - band_top),
            "band_top": int(band_top),
            "band_bottom": int(band_bottom),
        },
    }


def _card_facts(page) -> list[dict[str, Any]]:
    from mf4_analyzer.ui.ultraview_state import layout_slots, slot_occupant

    facts = []
    board = page.board()
    for slot_id in layout_slots(board.layout_id):
        ref = slot_occupant(board, slot_id)
        widget = page.slot_widget(slot_id)
        item: dict[str, Any] = {"slot": slot_id, "empty": ref is None}
        if widget is not None:
            item["geom"] = _rect(widget)
        if ref is None:
            facts.append(item)
            continue
        card = page.card_widget(ref.section, ref.view_id)
        item.update({"section": ref.section, "view_id": ref.view_id})
        if card is not None:
            item["status"] = card.model().status
            item["header_h"] = int(card.header_height())
            item["footer_h"] = int(card.footer_height())
            item["chrome_h"] = int(card.chrome_height())
            item["title_visible"] = bool(card._title.isVisible())
            action_bar = card.action_bar()
            item["actions_visible"] = bool(action_bar.isVisible())
            item["show_card_actions"] = bool(
                getattr(card.model(), "show_card_actions", False)
                or getattr(page, "_show_card_actions", False)
            )
            item["hovered"] = bool(getattr(card, "_card_hovered", False))
            item["has_focus"] = bool(card.hasFocus())
            item["visible_actions"] = [
                action
                for action in ("open", "focus", "fit", "remove", "more")
                if (button := card.action_button(action)) is not None and button.isVisible()
            ]
            item["geom"] = _rect(card)
        facts.append(item)
    return facts


def _grab(widget: QWidget, path: Path) -> dict[str, int]:
    pix = widget.grab()
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path))
    return {"w": int(pix.width()), "h": int(pix.height())}


def _library_rows():
    from mf4_analyzer.ui.chart_stack.ultraview.widgets import LibraryRow
    from mf4_analyzer.ui.ultraview_state import SOURCE_SECTIONS, STATUS_MISSING

    names = {
        "time": "道路输入",
        "fft": "共振检查",
        "fft_time": "瞬态频移",
        "frf": "基线 H1",
        "order": "2–8 阶总览",
    }
    rows = []
    for section in SOURCE_SECTIONS:
        rows.append(
            LibraryRow(
                section=section,
                view_id=f"{section}-1",
                name=names[section],
                tab_color="#2d7ff9",
                status=STATUS_MISSING,
                on_board=False,
                source_summary=f"{section}-src",
            )
        )
    return rows


def _add_preview(page, section: str, view_id: str, *, color: str, digest: str | None):
    from mf4_analyzer.ui.ultraview_state import add_ref, make_ref

    ref = make_ref(section, view_id)
    add_ref(page.board(), ref)
    page.set_preview(
        ref,
        _Preview(
            ref=ref,
            image=_image(color=color) if digest else None,
            captured_digest=digest,
            title=view_id,
            source_summary=f"{section}-src",
        ),
    )
    return ref


def _reset_board(page, layout_id: str = "hero_left_4"):
    from mf4_analyzer.ui.ultraview_state import default_board, set_layout

    board = default_board()
    set_layout(board, layout_id)
    page.set_library_rows(_library_rows())
    page.set_board(board)
    page.set_presentation_active(False)
    page.set_library_visible(False)
    return board


def _mean_icon_color(button) -> dict[str, int] | None:
    icon = button.icon()
    if icon is None or icon.isNull():
        return None
    image = icon.pixmap(18, 18).toImage()
    total = [0, 0, 0]
    count = 0
    for x in range(image.width()):
        for y in range(image.height()):
            pixel = QColor(image.pixel(x, y))
            if pixel.alpha() < 40:
                continue
            total[0] += pixel.red()
            total[1] += pixel.green()
            total[2] += pixel.blue()
            count += 1
    if count == 0:
        return None
    return {
        "r": total[0] // count,
        "g": total[1] // count,
        "b": total[2] // count,
        "samples": count,
    }


def _moonstone_facts(page) -> dict[str, Any]:
    """Sample canvas fill/dot and island material without relying on screenshots."""
    host = page.canvas_host()
    image = host.grab().toImage()
    width, height = image.width(), image.height()
    expected = QColor("#EDF2F5")
    candidates = (
        (2, 2),
        (min(width - 3, 92), min(height - 3, height // 2)),
        (min(width - 3, width // 2), min(height - 3, height - 6)),
        (min(width - 3, 70), 8),
    )
    best = None
    best_dist = 10**9
    sample_x = sample_y = 0
    for x, y in candidates:
        px = max(0, min(width - 1, int(x)))
        py = max(0, min(height - 1, int(y)))
        pixel = QColor(image.pixel(px, py))
        dist = (
            (pixel.red() - expected.red()) ** 2
            + (pixel.green() - expected.green()) ** 2
            + (pixel.blue() - expected.blue()) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best = pixel
            sample_x, sample_y = px, py
    fill = best or expected
    tile = getattr(host, "_dot_tile", None)
    dot_alpha = None
    if tile is not None and not tile.isNull():
        tile_image = tile.toImage()
        for x in range(tile_image.width()):
            for y in range(tile_image.height()):
                pixel = tile_image.pixelColor(x, y)
                if pixel.alpha() > 0:
                    if dot_alpha is None or pixel.alpha() > int(dot_alpha):
                        dot_alpha = pixel.alpha()
    layout_btn = page.tool_rail().panel_button("layout")
    free_btn = page.tool_rail().free_grid_button()
    return {
        "canvas_sample": {
            "x": sample_x,
            "y": sample_y,
            "hex": fill.name(),
            "r": fill.red(),
            "g": fill.green(),
            "b": fill.blue(),
        },
        "canvas_expected": expected.name(),
        "dot_alpha": dot_alpha,
        "dot_tile_key": list(host._dot_tile_key) if getattr(host, "_dot_tile_key", None) else None,
        "layout_icon": _mean_icon_color(layout_btn) if layout_btn is not None else None,
        "free_grid_icon": _mean_icon_color(free_btn),
        "layout_mode_active": layout_btn.property("modeActive") if layout_btn is not None else None,
        "free_grid_mode_active": free_btn.property("modeActive"),
    }


def _mapped_rect(widget: QWidget, host: QWidget) -> dict[str, Any]:
    origin = widget.mapTo(host, QPoint(0, 0))
    return {
        "x": int(origin.x()),
        "y": int(origin.y()),
        "w": int(widget.width()),
        "h": int(widget.height()),
        "visible": bool(widget.isVisible()),
        "space": HOST_COORD_SPACE,
    }


def _qrect_from_fact(data: dict[str, Any] | None) -> QRect:
    if not data:
        return QRect()
    return QRect(
        int(data.get("x") or 0),
        int(data.get("y") or 0),
        int(data.get("w") or 0),
        int(data.get("h") or 0),
    )


def _host_space_rect(rect: QRect | None, *, visible: bool) -> dict[str, Any] | None:
    if rect is None or not rect.isValid():
        return None
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "w": int(rect.width()),
        "h": int(rect.height()),
        "visible": bool(visible),
        "space": HOST_COORD_SPACE,
    }


def _hidden_host_rect() -> dict[str, Any]:
    return {
        "x": 0,
        "y": 0,
        "w": 0,
        "h": 0,
        "visible": False,
        "space": HOST_COORD_SPACE,
    }


def _stage_fact(host: QWidget) -> dict[str, Any]:
    rect = host.contentsRect()
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "w": int(rect.width()),
        "h": int(rect.height()),
        "visible": bool(host.isVisible()),
        "space": HOST_COORD_SPACE,
    }


def _fact_visible(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    return (
        bool(data.get("visible"))
        and int(data.get("w") or 0) > 0
        and int(data.get("h") or 0) > 0
    )


def _facts_intersect(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    left_rect = _qrect_from_fact(left)
    right_rect = _qrect_from_fact(right)
    return (
        not left_rect.isEmpty()
        and not right_rect.isEmpty()
        and left_rect.intersects(right_rect)
    )


def _fact_contained_by(
    child: dict[str, Any] | None, parent: dict[str, Any] | None
) -> bool:
    child_rect = _qrect_from_fact(child)
    parent_rect = _qrect_from_fact(parent)
    return (
        not child_rect.isEmpty()
        and not parent_rect.isEmpty()
        and parent_rect.contains(child_rect)
    )


def _widget_host_fact(widget: QWidget | None, host: QWidget) -> dict[str, Any]:
    if widget is None:
        return _hidden_host_rect()
    return _mapped_rect(widget, host)


def _rail_entry_facts(page) -> dict[str, Any]:
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import RELEASE_AUTHOR_TOOLS

    rail = page.tool_rail()
    rail_rect = QRect(0, 0, rail.width(), rail.height())
    entries: dict[str, Any] = {}
    for tool in RELEASE_AUTHOR_TOOLS:
        button = rail.tool_button(tool)
        if button is None:
            entries[tool] = None
            continue
        origin = button.mapTo(rail, QPoint(0, 0))
        hit = QRect(origin, button.size())
        entries[tool] = {
            "visible": bool(button.isVisible()),
            "enabled": bool(button.isEnabled()),
            "hit": {
                "x": int(hit.x()),
                "y": int(hit.y()),
                "w": int(hit.width()),
                "h": int(hit.height()),
            },
            "inside_rail": bool(rail_rect.contains(hit)),
        }
    visible = [item for item in entries.values() if item is not None]
    return {
        "compact": bool(rail.is_compact()),
        "entries": entries,
        "all_visible": bool(visible) and all(item["visible"] for item in visible),
        "all_inside": bool(visible) and all(item["inside_rail"] for item in visible),
        "missing": [tool for tool, item in entries.items() if item is None],
    }


def _layout_picker_facts(page) -> dict[str, Any]:
    from dataclasses import asdict

    from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
        ISLAND_GAP,
        Rect,
        overlay_anchor_facts,
    )

    host = page.canvas_host()
    overlay = host.overlay("layout")
    picker = page._layout_popover
    trigger = page.tool_rail().panel_button("layout")
    thumbs = {}
    for layout_id, button in picker._buttons.items():
        thumbs[layout_id] = {
            **_rect(button),
            "checked": bool(button.isChecked()),
            "text": button.text().replace("\n", " / "),
        }
    trigger_center = None
    overlay_center = None
    center_error_y = None
    anchor = None
    if overlay is not None and trigger is not None:
        mapped = trigger.mapTo(host, trigger.rect().center())
        trigger_center = {"x": int(mapped.x()), "y": int(mapped.y())}
        geo = overlay.geometry()
        overlay_center = {"x": int(geo.center().x()), "y": int(geo.center().y())}
        center_error_y = abs(overlay_center["y"] - trigger_center["y"])
        trigger_origin = trigger.mapTo(host, QPoint(0, 0))
        rail = page.tool_rail()
        requested = max(int(picker.sizeHint().height()), int(overlay.height()))
        facts = overlay_anchor_facts(
            Rect(geo.x(), geo.y(), geo.width(), geo.height()),
            Rect(trigger_origin.x(), trigger_origin.y(), trigger.width(), trigger.height()),
            Rect(rail.x(), rail.y(), rail.width(), rail.height()),
            requested_height=requested,
            board_island=Rect(
                page.board_island().x(),
                page.board_island().y(),
                page.board_island().width(),
                page.board_island().height(),
            ),
            navigation_island=Rect(
                page.navigation_island().x(),
                page.navigation_island().y(),
                page.navigation_island().width(),
                page.navigation_island().height(),
            ),
        )
        anchor = asdict(facts)
    history = [
        name
        for name in (
            "ultraViewLayoutPopoverOrganize",
            "ultraViewLayoutPopoverUndo",
            "ultraViewLayoutPopoverRedo",
        )
        if picker.findChild(QWidget, name) is not None
    ]
    return {
        "overlay": _rect(overlay) if overlay is not None else None,
        "trigger": _rect(trigger) if trigger is not None else None,
        "trigger_center": trigger_center,
        "overlay_center": overlay_center,
        "center_error_y": center_error_y,
        "anchor_budget_px": 32 + ISLAND_GAP,
        "anchor": anchor,
        "trigger_center_in_span": None if anchor is None else anchor["trigger_center_in_span"],
        "vertically_adjacent": None if anchor is None else anchor["vertically_adjacent"],
        "horizontally_right_of_rail": None if anchor is None else anchor["horizontally_right_of_rail"],
        "clamp_reason": None if anchor is None else anchor["clamp_reason"],
        "thumbs": thumbs,
        "checked": [layout_id for layout_id, button in picker._buttons.items() if button.isChecked()],
        "history_buttons": history,
        "intro": picker.intro_label().text(),
        "thumb_count": len(picker._buttons),
    }


def _pointer_popup_facts(page) -> dict[str, Any]:
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import OVERLAY_AUTHOR_POINTER

    host = page.canvas_host()
    overlay = host.overlay(OVERLAY_AUTHOR_POINTER)
    popover = page.pointer_popover()
    trigger = page.tool_rail().tool_button("select")
    return {
        "active_overlay": host.active_overlay(),
        "overlay": _rect(overlay) if overlay is not None else None,
        "popover_visible": bool(popover.isVisible()),
        "pointer_mode": page.interaction().pointer_mode(),
        "trigger": None if trigger is None else _mapped_rect(trigger, host),
        "rail_entries": _rail_entry_facts(page),
    }


def _selected_target_fact(page, host: QWidget) -> dict[str, Any] | None:
    """Selected card widget, or painted author bounds, in host coordinates."""
    caps = page._selection_capabilities()
    for ref in getattr(caps, "card_refs", ()) or ():
        card = page.card_widget(ref.section, ref.view_id)
        if card is None:
            continue
        return _mapped_rect(card, host)
    bounds = page._selection_bounds_in_host()
    if bounds is None or not bounds.isValid() or bounds.isEmpty():
        return None
    return _host_space_rect(bounds, visible=True)


def _selection_chrome_facts(page) -> dict[str, Any]:
    """Stage, target, and selection chrome in one host coordinate space."""
    host = page.canvas_host()
    bounds = page._selection_bounds_in_host()
    handles = bounds.adjusted(-18, -18, 18, 18) if bounds is not None else QRect()
    target = _selected_target_fact(page, host)
    toolbar = _widget_host_fact(page.selection_toolbar(), host)
    picker = _widget_host_fact(page.format_picker(), host)
    minimap = _widget_host_fact(page.free_grid_minimap(), host)
    selection_bounds = _host_space_rect(
        bounds,
        visible=bool(bounds is not None and bounds.isValid() and not bounds.isEmpty()),
    )
    handle_facts = _host_space_rect(handles, visible=bool(handles.isValid() and not handles.isEmpty()))
    return {
        "space": HOST_COORD_SPACE,
        "stage": _stage_fact(host),
        "target": target,
        "selection_bounds": selection_bounds,
        "handles": handle_facts,
        "toolbar": toolbar,
        "picker": picker,
        "minimap": minimap,
    }


def _minimap_selection_facts(page) -> dict[str, Any]:
    facts = _selection_chrome_facts(page)
    mini = facts.get("minimap")
    folded = not _fact_visible(mini)
    intersects_target = _fact_visible(mini) and _facts_intersect(mini, facts.get("target"))
    intersects_handles = _fact_visible(mini) and _facts_intersect(mini, facts.get("handles"))
    intersects_toolbar = (
        _fact_visible(mini)
        and _fact_visible(facts.get("toolbar"))
        and _facts_intersect(mini, facts.get("toolbar"))
    )
    intersects_picker = (
        _fact_visible(mini)
        and _fact_visible(facts.get("picker"))
        and _facts_intersect(mini, facts.get("picker"))
    )
    facts.update(
        {
            "folded": folded,
            "intersects_target": intersects_target,
            "intersects_handles": intersects_handles,
            "intersects_toolbar": intersects_toolbar,
            "intersects_picker": intersects_picker,
            "clear_of_selection_chrome": folded
            or not (
                intersects_target
                or intersects_handles
                or intersects_toolbar
                or intersects_picker
            ),
        }
    )
    return facts


def _format_picker_facts(page) -> dict[str, Any]:
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import OVERLAY_AUTHOR_FORMAT

    facts = _selection_chrome_facts(page)
    host = page.canvas_host()
    picker = facts.get("picker")
    picker_key = getattr(page, "_format_picker_key", "")
    trigger = page.selection_toolbar().button(picker_key) if picker_key else None
    facts.update(
        {
            "active_overlay": host.active_overlay(),
            "picker_visible": _fact_visible(picker),
            "picker_key": picker_key,
            "trigger": _widget_host_fact(trigger, host),
            "expected_overlay": OVERLAY_AUTHOR_FORMAT,
            "intersects_target": _fact_visible(picker)
            and _facts_intersect(picker, facts.get("target")),
            "intersects_handles": _fact_visible(picker)
            and _facts_intersect(picker, facts.get("handles")),
            "intersects_toolbar": _fact_visible(picker)
            and _fact_visible(facts.get("toolbar"))
            and _facts_intersect(picker, facts.get("toolbar")),
        }
    )
    return facts


def _ensure_widget_on_stage(page, widget: QWidget) -> None:
    """Scroll just enough that ``widget`` intersects the host stage.

    Do not jump to scrollbar maximum: that can hide a still-selected card
    that is not at the workspace far corner.
    """
    host = page.canvas_host()
    stage = host.contentsRect()
    if stage.isEmpty():
        stage = QRect(0, 0, max(1, host.width()), max(1, host.height()))
    safe = stage.adjusted(20, 20, -20, -20)
    mapped = QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())
    if safe.contains(mapped) and not mapped.isEmpty():
        return
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    vertical = scroll.verticalScrollBar()
    dx = mapped.left() - safe.left() if mapped.left() < safe.left() else 0
    if mapped.right() > safe.right():
        dx = mapped.right() - safe.right()
    dy = mapped.top() - safe.top() if mapped.top() < safe.top() else 0
    if mapped.bottom() > safe.bottom():
        dy = mapped.bottom() - safe.bottom()
    horizontal.setValue(int(horizontal.value() + dx))
    vertical.setValue(int(vertical.value() + dy))


def _scroll_target_off_stage(page) -> None:
    scroll = page.board_scroll_area()
    scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().maximum())
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())


def _reset_viewport(app: QApplication, page, *, zoom: float = 1.0) -> None:
    """Drop leftover camera from a previous harness scene."""
    page.set_board_zoom(zoom)
    scroll = page.board_scroll_area()
    scroll.horizontalScrollBar().setValue(0)
    scroll.verticalScrollBar().setValue(0)
    _pump(app, page)


def _ensure_selection_on_stage(page) -> None:
    host = page.canvas_host()
    stage = host.contentsRect()
    if stage.isEmpty():
        stage = QRect(0, 0, max(1, host.width()), max(1, host.height()))
    safe = stage.adjusted(20, 20, -20, -20)
    bounds = page._selection_bounds_in_host()
    if bounds is None or bounds.isEmpty() or safe.contains(bounds):
        return
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    vertical = scroll.verticalScrollBar()
    dx = bounds.left() - safe.left() if bounds.left() < safe.left() else 0
    if bounds.right() > safe.right():
        dx = bounds.right() - safe.right()
    dy = bounds.top() - safe.top() if bounds.top() < safe.top() else 0
    if bounds.bottom() > safe.bottom():
        dy = bounds.bottom() - safe.bottom()
    horizontal.setValue(int(horizontal.value() + dx))
    vertical.setValue(int(vertical.value() + dy))


def _to_free_grid(app: QApplication, page) -> None:
    from mf4_analyzer.ui.ultraview_state import template_to_free_grid

    template_to_free_grid(page.board())
    page.set_board(page.board())
    _pump(app, page)


def _setup_selected_bottom_right_scene(
    app: QApplication, page, *, scroll_off_stage: bool = False
):
    """Place a selected card; keep it on stage unless the negative path is requested."""
    from mf4_analyzer.ui.ultraview_state import GridRect, set_free_grid_rect

    page.resize(1600, 900)
    _reset_board(page, "grid_2x2")
    ref = _add_preview(page, "time", "mini-br", color="#2d7ff9", digest="minibr")
    _to_free_grid(app, page)
    set_free_grid_rect(page.board(), ref, GridRect(16, 12, 8, 6))
    page.set_board(page.board())
    page.set_board_zoom(1.6)
    _pump(app, page)
    card = page.card_widget(ref.section, ref.view_id)
    if scroll_off_stage:
        _scroll_target_off_stage(page)
    elif card is not None:
        _ensure_widget_on_stage(page, card)
    _pump(app, page)
    page._select_ref(ref)
    page._refresh_minimap()
    _pump(app, page)
    return ref


def _laser_cursor_facts(page) -> dict[str, Any]:
    from mf4_analyzer.ui.chart_stack.ultraview.laser_cursor import (
        LASER_CURSOR_HOTSPOT,
        LASER_CURSOR_LOGICAL_SIZE,
        laser_cursor_cache_key,
        laser_pointer_cursor,
    )

    free = page._free_grid
    cursor = free.cursor()
    pixmap = cursor.pixmap()
    dpr = float(free.devicePixelRatioF() or 1.0)
    expected = laser_pointer_cursor(dpr=dpr)
    return {
        "shape": int(cursor.shape()),
        "bitmap_cursor": cursor.shape() == Qt.BitmapCursor,
        "logical_size": [int(pixmap.width()), int(pixmap.height())],
        "hotspot": [int(cursor.hotSpot().x()), int(cursor.hotSpot().y())],
        "expected_hotspot": list(LASER_CURSOR_HOTSPOT),
        "design_size": LASER_CURSOR_LOGICAL_SIZE,
        "dpr": dpr,
        "cache_key": list(laser_cursor_cache_key(dpr=dpr)),
        "matches_cache": cursor.hotSpot() == expected.hotSpot(),
        "native_pixmap": False,
    }


#: Target geometry constants from the View-library plan §4. They are read by
#: name instead of by literal so a retune stays a one-line edit in ``widgets``;
#: a name that is absent is recorded as ``None`` and turned into an explicit
#: ``assert_geometry`` failure, never silently substituted with a number.
_LIBRARY_CONSTANT_NAMES = (
    "LIBRARY_DEFAULT_WIDTH",
    "LIBRARY_MAX_WIDTH",
    "LIBRARY_OVERLAY_HEIGHT",
    "LIBRARY_OVERLAY_MIN_HEIGHT",
    "LIBRARY_HEAD_HEIGHT",
    "LIBRARY_SECTION_HEAD_HEIGHT",
    "LIBRARY_ROW_HEIGHT",
    "LIBRARY_SELECTED_ROW_GUTTER",
    "LIBRARY_ROW_ACTION_SIZE",
    "LIBRARY_MODE_GROUPS",
)


def _library_constants() -> dict[str, int | str | None]:
    """Snapshot the plan §4 constants into the manifest.

    Carrying them in the manifest keeps ``assert_geometry`` free of product
    imports and makes an archived manifest self-describing: a later reader can
    tell whether a stored number matched the constant of its day.
    """
    from mf4_analyzer.ui.chart_stack.ultraview import widgets as library_widgets

    return {
        name: getattr(library_widgets, name, None) for name in _LIBRARY_CONSTANT_NAMES
    }


def _library_facts(page) -> dict[str, Any]:
    """Record the single-layer View-library geometry and visible controls."""
    from PyQt5.QtWidgets import QToolButton, QWidget

    panel = page.library_panel()
    sections = {
        section: {
            "height": int(frame.height()),
            "min_hint": int(frame.minimumSizeHint().height()),
            "visible": bool(frame.isVisible()),
        }
        for section, frame in panel.section_widgets().items()
    }
    row_heights = [int(widget.height()) for widget in panel.row_widgets()]
    return {
        "panel": _rect(panel),
        "browse_mode": panel.browse_mode(),
        "size_hint_h": int(panel.sizeHint().height()),
        "min_size_hint_h": int(panel.minimumSizeHint().height()),
        "sections": sections,
        "section_heights": sorted({fact["height"] for fact in sections.values()}),
        "row_heights": sorted(set(row_heights)),
        "section_order": list(panel.section_widgets()),
        "mode_controls_visible": bool(
            panel.findChild(QToolButton, "ultraViewLibraryModeGroups")
            or panel.findChild(QToolButton, "ultraViewLibraryModeCompact")
        ),
        "compact_host_visible": bool(panel.findChild(QWidget, "ultraViewLibraryCompactHost")),
    }


def _page_snapshot(page, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "size": {"w": int(page.width()), "h": int(page.height())},
        "library_visible": bool(page.library_panel().isVisible()),
        "presentation": bool(page.is_presentation_active()),
        "focus_visible": bool(page.focus_layer().isVisible()),
        "tray_expanded": bool(page.unplaced_tray().is_expanded()),
        "tray_body_visible": bool(page.unplaced_tray().body().isVisible()),
        "unplaced": len(page.board().unplaced),
        "show_titles": bool(page.board().show_titles),
        "show_sources": bool(page.board().show_sources),
        "layout_id": page.board().layout_id,
        "cards": _card_facts(page),
        "active_panel": page.active_panel(),
        "board_scroll": _rect(page.board_scroll_area()),
        "rail": _rect(page.tool_rail()),
        "board_island": _rect(page.board_island()),
        "global_island": _rect(page.global_island()),
        "navigation_island": _rect(page.navigation_island()),
        "status_island": _rect(page.status_island()),
        "card_context": _rect(page.card_context_island()),
        "edge_rhythm": _edge_rhythm(page),
        "moonstone": _moonstone_facts(page),
        "library": _library_facts(page),
        "rail_entries": _rail_entry_facts(page),
    }
    if extra:
        payload.update(extra)
    return payload


def _overlap(left: QRect, right: QRect) -> bool:
    return left.intersects(right)


def _toolbar_snapshot(toolbar) -> dict[str, Any]:
    buttons = [
        toolbar.btn_mode_time,
        toolbar.btn_mode_fft,
        toolbar.btn_mode_fft_time,
        toolbar.btn_mode_order,
        toolbar.btn_mode_frf,
    ]
    geoms = [button.geometry() for button in buttons]
    overlaps = []
    for index, (left, right) in enumerate(zip(geoms, geoms[1:])):
        if _overlap(left, right) or left.right() > right.left():
            overlaps.append(index)
    clipped = [
        button.objectName()
        for button in buttons
        if not toolbar.rect().contains(button.geometry())
    ]
    return {
        "compact": bool(toolbar.is_mode_compact()),
        "labels": [button.text() for button in buttons],
        "geoms": [_rect(button) for button in buttons],
        "overlap_pairs": overlaps,
        "clipped": clipped,
        "toolbar": _rect(toolbar),
    }


def _build_contact_sheet(shots: list[tuple[str, Path]], dest: Path) -> None:
    tiles = []
    for name, path in shots:
        pix = QPixmap(str(path))
        if pix.isNull():
            continue
        tiles.append((name, pix))
    if not tiles:
        raise GeometryError("contact sheet has no tiles")
    cols = 3
    cell_w, cell_h, label_h, gap = 420, 240, 28, 16
    rows = (len(tiles) + cols - 1) // cols
    sheet = QImage(
        cols * cell_w + (cols + 1) * gap,
        rows * (cell_h + label_h) + (rows + 1) * gap,
        QImage.Format_ARGB32,
    )
    sheet.fill(QColor("#f2f4f7"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    for index, (name, pix) in enumerate(tiles):
        col, row = index % cols, index // cols
        x = gap + col * (cell_w + gap)
        y = gap + row * (cell_h + label_h + gap)
        painter.setPen(QColor("#111827"))
        painter.drawText(x, y, cell_w, label_h, Qt.AlignLeft | Qt.AlignVCenter, name)
        scaled = pix.scaled(cell_w, cell_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ox = x + (cell_w - scaled.width()) // 2
        oy = y + label_h
        painter.fillRect(x, oy, cell_w, cell_h, QColor("#ffffff"))
        painter.drawPixmap(ox, oy, scaled)
    painter.end()
    sheet.save(str(dest))


def _close_transient_chrome(page, app: QApplication) -> None:
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import OVERLAY_AUTHOR_POINTER

    page._close_active_panel(restore_focus=False)
    host = page.canvas_host()
    if host.active_overlay() == OVERLAY_AUTHOR_POINTER:
        host.close_overlay(OVERLAY_AUTHOR_POINTER, restore_focus=False)
    elif page.pointer_popover().isVisible():
        page.pointer_popover().close()
    if page.format_picker().isVisible() or getattr(page, "_format_picker_key", ""):
        page._close_format_picker()
    _pump(app, page)


def _capture_wave3_shots(app: QApplication, page, snap) -> None:
    """Pointer, minimap collision, format picker, and Laser Qt-cursor facts."""
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
        POINTER_MODE_LASER,
        POINTER_MODE_MOUSE,
    )
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import AUTHOR_TOOL_SELECT
    from mf4_analyzer.ui.ultraview_state import (
        BoardBox,
        ShapeObject,
    )

    _close_transient_chrome(page, app)
    page.resize(1280, 800)
    _reset_board(page, "grid_2x2")
    _add_preview(page, "time", "ptr-1280", color="#2d7ff9", digest="ptr1280")
    _to_free_grid(app, page)
    pointer = page.tool_rail().tool_button(AUTHOR_TOOL_SELECT)
    if pointer is not None:
        pointer.click()
        _pump(app, page)
    snap(
        "pointer_popup_1280",
        page,
        _page_snapshot(page, {"pointer_popup": _pointer_popup_facts(page)}),
    )

    page.resize(800, 560)
    _pump(app, page)
    pointer = page.tool_rail().tool_button(AUTHOR_TOOL_SELECT)
    if pointer is not None and not page.pointer_popover().isVisible():
        pointer.click()
        _pump(app, page)
    snap(
        "pointer_popup_800",
        page,
        _page_snapshot(page, {"pointer_popup": _pointer_popup_facts(page)}),
    )
    _close_transient_chrome(page, app)

    _setup_selected_bottom_right_scene(app, page, scroll_off_stage=False)
    snap(
        "selected_bottom_right_with_minimap",
        page,
        _page_snapshot(page, {"minimap_selection": _minimap_selection_facts(page)}),
    )

    page.resize(1280, 800)
    _reset_board(page, "grid_2x2")
    _add_preview(page, "time", "shape-host", color="#6a8f4f", digest="shapehost")
    _to_free_grid(app, page)
    page.board().author_objects = [
        ShapeObject(
            "harness-shape",
            "shape",
            box=BoardBox(2.0, 2.0, 4.0, 3.0),
            shape="rectangle",
        )
    ]
    page.set_board(page.board())
    _reset_viewport(app, page, zoom=1.0)
    page.interaction().select_only_author("harness-shape")
    page._free_grid.sync_selection_projection()
    _ensure_selection_on_stage(page)
    page._refresh_author_toolbar()
    _pump(app, page)
    fill = page.selection_toolbar().button("fill")
    if fill is not None:
        QTest.mouseClick(fill, Qt.LeftButton)
        _pump(app, page)
    snap(
        "selected_shape_format_picker",
        page,
        _page_snapshot(page, {"format_picker": _format_picker_facts(page)}),
    )
    _close_transient_chrome(page, app)

    page._apply_pointer_mode(POINTER_MODE_LASER)
    _pump(app, page)
    facts = _laser_cursor_facts(page)
    pixmap = page._free_grid.cursor().pixmap()
    holder = QLabel()
    holder.setPixmap(pixmap)
    holder.setFixedSize(max(32, pixmap.width()), max(32, pixmap.height()))
    snap("laser_cursor", holder, facts)
    holder.close()
    page._apply_pointer_mode(POINTER_MODE_MOUSE)
    _pump(app, page)


def generate(output_dir: Path | None = None) -> dict[str, Any]:
    """Build shots + manifest. Returns the manifest dict."""
    from mf4_analyzer.ui.chart_stack.ultraview.layouts import MIN_CARD_CHROME_HEIGHT
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
    from mf4_analyzer.ui.toolbar import Toolbar
    from mf4_analyzer.ui.ultraview_state import (
        STATUS_FRESH,
        STATUS_MISSING,
        STATUS_ORPHANED,
        STATUS_STALE,
    )

    app = _ensure_app()
    dest = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT
    dest.mkdir(parents=True, exist_ok=True)
    shots_dir = dest / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    page = UltraViewPage()
    toolbar = Toolbar()
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(dest),
        "evidence_class": "offscreen",
        "shots": {},
        "geometry": {},
        "min_card_chrome_height": MIN_CARD_CHROME_HEIGHT,
        "library_constants": _library_constants(),
    }
    saved: list[tuple[str, Path]] = []

    def snap(name: str, widget: QWidget, geometry: dict[str, Any]) -> None:
        path = shots_dir / f"{name}.png"
        size = _grab(widget, path)
        manifest["shots"][name] = {
            "path": str(path.relative_to(dest)),
            "width": size["w"],
            "height": size["h"],
        }
        manifest["geometry"][name] = geometry
        saved.append((name, path))

    try:
        page.resize(1440, 900)
        _reset_board(page, "hero_left_4")
        for index, (section, color) in enumerate(
            (("time", "#2d7ff9"), ("fft", "#e0883c"), ("order", "#9b6bd0"), ("frf", "#168f91"))
        ):
            _add_preview(page, section, f"{section}-1", color=color, digest=f"d{index}")
        page.set_board(page.board())
        _pump(app, page)
        snap("narrow_1440", page, _page_snapshot(page))

        page.resize(1280, 800)
        _pump(app, page)
        snap("narrow_1280", page, _page_snapshot(page))

        page.resize(800, 560)
        _pump(app, page)
        snap("narrow_800", page, _page_snapshot(page))

        page.resize(1280, 800)
        _pump(app, page)
        page.tool_rail().panel_button("library").click()
        _pump(app, page)
        snap("library_1280", page, _page_snapshot(page))

        # The library has one direct, grouped browse path.  Re-placing it must
        # preserve the fixed frame while no hidden compact/catalog surface is
        # introduced by the visual harness itself.
        page._apply_floating_layout()
        _pump(app, page)
        snap("library_groups_1280", page, _page_snapshot(page))
        library_btn = page.tool_rail().panel_button("library")
        from PyQt5.QtTest import QTest

        QTest.mouseClick(page.canvas_host().canvas_widget(), Qt.LeftButton)
        _pump(app, page)
        manifest["geometry"]["library_groups_1280"]["trigger_rest"] = {
            "panelOpen": library_btn.property("panelOpen") if library_btn is not None else None,
            "hasFocus": bool(library_btn.hasFocus()) if library_btn is not None else None,
            "checked": bool(library_btn.isChecked()) if library_btn is not None else None,
        }

        page.board_island().menu_button().click()
        _pump(app, page)
        snap(
            "boards_1280",
            page,
            _page_snapshot(
                page,
                {
                    "board_popover": _rect(page.board_popover()),
                    "board_menu_button": _rect(page.board_island().menu_button()),
                },
            ),
        )
        page.tool_rail().panel_button("layout").click()
        _pump(app, page)
        snap("layout_1280", page, _page_snapshot(page, {"layout_picker": _layout_picker_facts(page)}))
        page.tool_rail().panel_button("filter").click()
        _pump(app, page)
        snap("filter_1280", page, _page_snapshot(page))
        page.global_island().display_button().click()
        _pump(app, page)
        snap("display_1280", page, _page_snapshot(page))
        page.global_island().export_button().click()
        _pump(app, page)
        snap("export_1280", page, _page_snapshot(page))
        page._close_active_panel()
        _pump(app, page)
        # Card actions are hover / focus / preference — never selection alone
        # (8d57ab0e). The harness records the persistent preference so the
        # selected-card shot still has a visible action bar.
        from mf4_analyzer.ui.ultraview_state import (
            UltraViewWorkspaceState,
            set_workspace_show_card_actions,
        )

        workspace = UltraViewWorkspaceState(
            active_board_id=page.board().board_id,
            boards=[page.board()],
        )
        set_workspace_show_card_actions(workspace, True)
        page.set_workspace(workspace)
        first = page.board().placements[0].ref
        page._select_ref(first)
        _pump(app, page)
        snap("card_context_1280", page, _page_snapshot(page))

        page.resize(1440, 900)
        _reset_board(page, "grid_3x2")
        colors = ("#2d7ff9", "#e0883c", "#6a8f4f", "#9b6bd0", "#168f91", "#5b6775")
        sections = ("time", "fft", "fft_time", "order", "frf", "time")
        for index, (section, color) in enumerate(zip(sections, colors)):
            _add_preview(
                page, section, f"g{index}", color=color, digest=f"g{index}"
            )
        page.set_board(page.board())
        _pump(app, page)
        snap("grid_6_1440", page, _page_snapshot(page))

        page.resize(1280, 800)
        _pump(app, page)
        _reset_board(page, "grid_2x2")
        for index in range(6):
            _add_preview(
                page, "time", f"tray-{index}", color="#3f7fc4", digest=f"t{index}"
            )
        page.set_board(page.board())
        _pump(app, page)
        page.tool_rail().panel_button("unplaced").click()
        _pump(app, page)
        snap("unplaced_1280", page, _page_snapshot(page))

        _reset_board(page, "grid_2x2")
        specs = (
            ("time", "fresh-1", STATUS_FRESH, "#2d7ff9", "fresh", True),
            ("fft", "stale-1", STATUS_STALE, "#e0883c", "stale", True),
            ("order", "missing-1", STATUS_MISSING, "#9b6bd0", None, True),
            ("frf", "orphan-1", STATUS_ORPHANED, "#168f91", "old", False),
        )
        for section, view_id, status, color, digest, exists in specs:
            ref = _add_preview(
                page, section, view_id, color=color, digest=digest
            )
            page.set_ref_status(ref, status, exists)
        page.set_board(page.board())
        _pump(app, page)
        snap("four_status_1440", page, _page_snapshot(page))

        page.board().show_titles = False
        page.board().show_sources = False
        page.set_board(page.board())
        _pump(app, page)
        snap("show_flags_1440", page, _page_snapshot(page))

        page.board().show_titles = True
        page.board().show_sources = True
        page.set_board(page.board())
        first = page.board().placements[0].ref
        page.show_focus(first.section, first.view_id)
        _pump(app, page)
        snap("focus_1440", page, _page_snapshot(page))
        page.focus_layer().close_layer()

        page.set_presentation_active(True)
        _pump(app, page)
        snap("presentation_1280", page, _page_snapshot(page))
        page.set_presentation_active(False)

        from mf4_analyzer.ui.chart_stack.ultraview.free_grid import plan_auto_arrange
        from mf4_analyzer.ui.chart_stack.ultraview.page import (
            BOARD_MENU_ARRANGE,
            BOARD_MENU_FIT,
            BOARD_MENU_OBJECT_NAME,
        )
        from mf4_analyzer.ui.ultraview_state import (
            GridRect,
            set_free_grid_rects,
            template_to_free_grid,
        )

        page.resize(1280, 800)
        template_to_free_grid(page.board())
        board = page.board()
        if len(board.free_grid) >= 2:
            first, second = board.free_grid[0], board.free_grid[1]
            set_free_grid_rects(
                board,
                (
                    (
                        first.ref,
                        GridRect(16, 12, first.rect.column_span, first.rect.row_span),
                    ),
                    (
                        second.ref,
                        GridRect(0, 28, second.rect.column_span, second.rect.row_span),
                    ),
                ),
            )
        page.set_board(page.board())
        _pump(app, page)

        def _rect_facts():
            return [
                {
                    "view_id": item.ref.view_id,
                    "column": item.rect.column,
                    "row": item.rect.row,
                    "column_span": item.rect.column_span,
                    "row_span": item.rect.row_span,
                }
                for item in page.board().free_grid
            ]

        snap(
            "arrange_before_1280",
            page,
            _page_snapshot(page, {"free_grid": _rect_facts()}),
        )
        plan = plan_auto_arrange(tuple(page.board().free_grid))
        if plan.accepted and plan.committed_updates():
            set_free_grid_rects(page.board(), plan.committed_updates())
            page.set_board(page.board())
            _pump(app, page)
        snap(
            "arrange_after_1280",
            page,
            _page_snapshot(page, {"free_grid": _rect_facts()}),
        )
        menu = page.make_board_context_menu()
        menu.popup(page.mapToGlobal(QPoint(420, 260)))
        _pump(app, page)
        board_actions = [action.text() for action in menu.actions() if action.text()]
        snap(
            "board_context_1280",
            menu if menu.width() > 10 else page,
            {
                "object_name": menu.objectName(),
                "actions": board_actions,
            },
        )
        menu.close()
        page.resize(800, 560)
        _pump(app, page)
        menu_800 = page.make_board_context_menu()
        menu_800.popup(page.mapToGlobal(QPoint(240, 180)))
        _pump(app, page)
        snap(
            "board_context_800",
            menu_800 if menu_800.width() > 10 else page,
            {
                "object_name": menu_800.objectName(),
                "actions": [action.text() for action in menu_800.actions() if action.text()],
            },
        )
        menu_800.close()
        card = None
        if page.board().free_grid:
            ref = page.board().free_grid[0].ref
            card = page.card_widget(ref.section, ref.view_id)
        card_actions = []
        if card is not None:
            card_menu = card.make_context_menu()

            def _flatten_menu(menu) -> list[str]:
                labels: list[str] = []
                for action in menu.actions():
                    text = action.text()
                    if text:
                        labels.append(text)
                    submenu = action.menu()
                    if submenu is not None:
                        labels.extend(_flatten_menu(submenu))
                return labels

            card_actions = _flatten_menu(card_menu)
            card_menu.close()
        manifest["geometry"]["board_context_1280"]["card_actions"] = card_actions
        manifest["geometry"]["board_context_1280"]["wanted_fit"] = BOARD_MENU_FIT
        manifest["geometry"]["board_context_1280"]["wanted_arrange"] = BOARD_MENU_ARRANGE
        manifest["geometry"]["board_context_1280"]["wanted_name"] = BOARD_MENU_OBJECT_NAME

        _capture_wave3_shots(app, page, snap)

        toolbar.resize(1100, 44)
        _pump(app, toolbar)
        snap("toolbar_1100", toolbar, _toolbar_snapshot(toolbar))
        toolbar.resize(1600, 44)
        _pump(app, toolbar)
        snap("toolbar_1600", toolbar, _toolbar_snapshot(toolbar))

        contact = dest / "contact-sheet.png"
        _build_contact_sheet(saved, contact)
        manifest["contact_sheet"] = str(contact.relative_to(dest))
        (dest / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert_geometry(manifest)
        return manifest
    finally:
        page.close()
        toolbar.close()
        app.processEvents()


def _library_errors(manifest: dict[str, Any]) -> list[str]:
    """View-library contract: one grouped path, stable frame, usable sections."""
    errors: list[str] = []
    geometry = manifest.get("geometry") or {}
    constants = manifest.get("library_constants") or {}
    missing = sorted(name for name, value in constants.items() if value is None)
    if missing:
        errors.append(
            "library geometry constants absent from ultraview.widgets: "
            + ", ".join(missing)
        )

    groups = (geometry.get("library_groups_1280") or {}).get("library") or {}
    if not groups:
        return errors + ["library_groups_1280 recorded no library facts"]
    if not (groups.get("panel") or {}).get("visible"):
        errors.append("library_groups_1280 did not leave the library panel visible")
    wanted_mode = constants.get("LIBRARY_MODE_GROUPS")
    if wanted_mode is not None and groups.get("browse_mode") != wanted_mode:
        errors.append(
            f"library browse mode is {groups.get('browse_mode')!r}, expected {wanted_mode!r}"
        )
    panel = groups.get("panel") or {}
    if int(panel.get("w") or 0) != int(constants.get("LIBRARY_DEFAULT_WIDTH") or 0):
        errors.append(
            f"library width={panel.get('w')}, expected {constants.get('LIBRARY_DEFAULT_WIDTH')}"
        )
    if groups.get("mode_controls_visible"):
        errors.append("library still exposes a browse-mode control")
    if groups.get("compact_host_visible"):
        errors.append("library still exposes a compact catalog host")

    for section, fact in sorted((groups.get("sections") or {}).items()):
        if not fact.get("visible"):
            continue
        height = int(fact.get("height") or 0)
        min_hint = int(fact.get("min_hint") or 0)
        if height < min_hint:
            errors.append(
                f"library section {section!r} is clipped: height={height} < minHint={min_hint}"
            )

    return errors


def _coord_space_errors(name: str, facts: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if facts.get("space") != HOST_COORD_SPACE:
        errors.append(
            f"{name} coordinate space is {facts.get('space')!r}, expected {HOST_COORD_SPACE!r}"
        )
    for key in _SELECTION_CHROME_KEYS:
        if key not in facts:
            errors.append(f"{name} missing {key} facts")
            continue
        item = facts.get(key)
        if item is None:
            if key in {"stage", "target"}:
                errors.append(f"{name} missing {key} facts")
            continue
        if not isinstance(item, dict):
            errors.append(f"{name} {key} is not a host-space rect")
            continue
        if item.get("space") != HOST_COORD_SPACE:
            errors.append(f"{name} {key} is not in host coordinates")
    trigger = facts.get("trigger")
    if trigger is not None and (
        not isinstance(trigger, dict) or trigger.get("space") != HOST_COORD_SPACE
    ):
        errors.append(f"{name} trigger is not in host coordinates")
    return errors


def _selection_chrome_errors(
    name: str,
    facts: dict[str, Any] | None,
    *,
    require_minimap: bool = False,
    require_picker: bool = False,
    require_toolbar: bool = False,
) -> list[str]:
    """Fail closed: target on stage first, then chrome containment/overlap."""
    if not isinstance(facts, dict) or not facts:
        return [f"{name} missing selection chrome facts"]
    errors = _coord_space_errors(name, facts)
    stage = facts.get("stage")
    target = facts.get("target")
    if not _fact_visible(target):
        errors.append(f"{name} target is not visible: {target}")
        return errors
    if not _facts_intersect(target, stage):
        errors.append(
            f"{name} target does not intersect stage: target={target} stage={stage}"
        )
        return errors

    handles = facts.get("handles")
    if not _fact_visible(handles):
        errors.append(f"{name} selection handles are not visible")
    elif not _fact_contained_by(handles, stage):
        errors.append(f"{name} selection handles are not contained by stage")

    toolbar = facts.get("toolbar")
    picker = facts.get("picker")
    minimap = facts.get("minimap")
    if require_toolbar and not _fact_visible(toolbar):
        errors.append(f"{name} selection toolbar is not visible")
    elif require_toolbar and not _fact_contained_by(toolbar, stage):
        errors.append(f"{name} selection toolbar is not contained by stage")
    if require_picker:
        trigger = facts.get("trigger")
        if not _fact_visible(picker):
            errors.append(f"{name} format picker is not visible")
        else:
            if not _fact_contained_by(picker, stage):
                errors.append(f"{name} format picker is not contained by stage")
            if _facts_intersect(picker, target) or _facts_intersect(picker, handles):
                errors.append(
                    f"{name} format picker overlaps selected object or handles"
                )
        if not _fact_visible(trigger):
            errors.append(f"{name} format picker trigger is not visible")
        else:
            if not _fact_contained_by(trigger, stage):
                errors.append(f"{name} format picker trigger is not contained by stage")
            picker_rect = _qrect_from_fact(picker)
            trigger_rect = _qrect_from_fact(trigger)
            below_gap = picker_rect.top() - trigger_rect.bottom()
            above_gap = trigger_rect.top() - picker_rect.bottom()
            if not (0 <= below_gap <= 12 or 0 <= above_gap <= 12):
                errors.append(
                    f"{name} format picker is not anchored to its trigger"
                )
    if require_minimap:
        if not _fact_visible(minimap):
            errors.append(f"{name} minimap is not visible")
        else:
            if not _fact_contained_by(minimap, stage):
                errors.append(f"{name} minimap is not contained by stage")
            overlaps = []
            if _facts_intersect(minimap, target):
                overlaps.append("target")
            if _facts_intersect(minimap, handles):
                overlaps.append("handles")
            if _fact_visible(toolbar) and _facts_intersect(minimap, toolbar):
                overlaps.append("toolbar")
            if _fact_visible(picker) and _facts_intersect(minimap, picker):
                overlaps.append("picker")
            if overlaps:
                errors.append(
                    f"{name} minimap overlaps selection chrome: {', '.join(overlaps)}"
                )
    return errors


def assert_geometry(manifest: dict[str, Any]) -> None:
    """Raise GeometryError if the harness contract is broken."""
    errors: list[str] = []
    version = manifest.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"manifest schema_version={version!r}, expected {MANIFEST_SCHEMA_VERSION}"
        )
    shots = manifest.get("shots") or {}
    geometry = manifest.get("geometry") or {}
    for name in REQUIRED_SHOTS:
        if name not in shots:
            errors.append(f"missing shot {name}")
            continue
        info = shots[name]
        if int(info.get("width") or 0) < 10 or int(info.get("height") or 0) < 10:
            errors.append(f"degenerate shot {name}")
    if not manifest.get("contact_sheet"):
        errors.append("missing contact sheet")

    def board_size(name: str) -> tuple[int, int]:
        fact = geometry.get(name) or {}
        rect = fact.get("board_scroll") or {}
        return int(rect.get("w") or 0), int(rect.get("h") or 0)

    narrow_1280 = geometry.get("narrow_1280") or {}
    width, height = board_size("narrow_1280")
    if width < 1190 or height < 700:
        errors.append(f"narrow_1280 board={width}x{height}, expected >=1190x700")
    narrow_800 = geometry.get("narrow_800") or {}
    width, height = board_size("narrow_800")
    if width < 710 or height < 470:
        errors.append(f"narrow_800 board={width}x{height}, expected >=710x470")
    if narrow_1280.get("library_visible"):
        errors.append("narrow_1280 library should default closed")

    for name in ("narrow_1280", "narrow_800"):
        rhythm = (geometry.get(name) or {}).get("edge_rhythm") or {}
        left_edges = rhythm.get("left_edges") or {}
        if len(set(left_edges.values())) != 1:
            errors.append(f"{name} left chrome axes drifted: {left_edges}")
        right_edges = rhythm.get("right_edges") or {}
        if len(set(right_edges.values())) != 1:
            errors.append(f"{name} right chrome axes drifted: {right_edges}")
        rail = rhythm.get("rail") or {}
        if abs(int(rail.get("center_error_px") or 0)) > 1:
            errors.append(f"{name} rail is not vertically centred: {rail}")
        height = int(rail.get("height") or 0)
        preferred = int(rail.get("preferred_height") or 0)
        available = int(rail.get("available_band_px") or 0)
        if available and height > available:
            errors.append(f"{name} rail exceeds available band: {rail}")
        if preferred and available and preferred <= available and height > preferred + 8:
            errors.append(f"{name} rail is stretched instead of content-height: {rail}")

    base_board = (narrow_1280.get("board_scroll") or {})
    for name in (
        "library_1280",
        "library_groups_1280",
        "layout_1280",
        "filter_1280",
        "display_1280",
        "export_1280",
    ):
        fact = geometry.get(name) or {}
        if fact.get("board_scroll") != base_board:
            errors.append(f"{name} changed BoardScrollArea geometry")
        if fact.get("active_panel") is None:
            errors.append(f"{name} did not expose its popover")

    context = geometry.get("card_context_1280") or {}
    selected_actions = [
        card
        for card in context.get("cards") or []
        if {"open", "focus", "remove", "more"} <= set(card.get("visible_actions") or [])
        and (
            card.get("show_card_actions")
            or card.get("hovered")
            or card.get("has_focus")
        )
    ]
    if not selected_actions:
        errors.append(
            "card_context_1280 missing card actions "
            "(need hover, focus, or persistent show_card_actions)"
        )

    grid = geometry.get("grid_6_1440") or {}
    filled6 = [c for c in grid.get("cards") or [] if not c.get("empty")]
    if len(filled6) != 6:
        errors.append(f"grid_6_1440 expected 6 cards, got {len(filled6)}")

    tray = geometry.get("unplaced_1280") or {}
    if int(tray.get("unplaced") or 0) < 1:
        errors.append("unplaced_1280 has no overflow")
    if tray.get("active_panel") != "unplaced":
        errors.append("unplaced_1280 did not open the rail tray panel")

    statuses = {
        card.get("status")
        for card in (geometry.get("four_status_1440") or {}).get("cards") or []
        if not card.get("empty")
    }
    wanted = {"fresh", "stale", "missing", "orphaned"}
    if not wanted <= statuses:
        errors.append(f"four_status missing {wanted - statuses}")

    flags = geometry.get("show_flags_1440") or {}
    if flags.get("show_titles") or flags.get("show_sources"):
        errors.append("show_flags_1440 did not hide titles/sources")
    for card in flags.get("cards") or []:
        if card.get("empty"):
            continue
        if card.get("title_visible"):
            errors.append("show_flags left a visible title")
        if int(card.get("footer_h") or 0) != 0:
            errors.append("show_flags left a source footer band")
        break

    if (geometry.get("focus_1440") or {}).get("focus_visible") is not True:
        errors.append("focus layer not visible")
    presentation = geometry.get("presentation_1280") or {}
    if presentation.get("presentation") is not True:
        errors.append("presentation flag off")
    if presentation.get("library_visible") is True:
        errors.append("presentation still shows library")

    board_menu = geometry.get("board_context_1280") or {}
    if board_menu.get("object_name") != "ultraViewBoardContextMenu":
        errors.append("board_context_1280 objectName mismatch")
    actions = board_menu.get("actions") or []
    if "适应内容" not in actions:
        errors.append("board_context_1280 missing 适应内容")
    if "自动排版" not in actions:
        errors.append("board_context_1280 missing 自动排版")
    card_actions = board_menu.get("card_actions") or []
    if "自动排版" in card_actions:
        errors.append("card context leaked board auto-arrange")
    if "打开原 View" in card_actions:
        errors.append("card context still lists 打开原 View")
    if "临时放大" in card_actions:
        errors.append("card context still lists 临时放大")
    if any("移除" in text for text in card_actions):
        errors.append("card context still lists remove")
    if "按原图比例" in card_actions:
        errors.append("card context still lists 按原图比例")
    if "复制本卡图像" not in card_actions:
        errors.append("card context missing 复制本卡图像")
    before = (geometry.get("arrange_before_1280") or {}).get("free_grid") or []
    after = (geometry.get("arrange_after_1280") or {}).get("free_grid") or []
    if len(before) >= 2 and before == after:
        errors.append("auto-arrange did not change scattered placements")

    moon = (narrow_1280.get("moonstone") or {})
    sample = moon.get("canvas_sample") or {}
    if abs(int(sample.get("r") or 0) - 0xED) > 28 or abs(int(sample.get("b") or 0) - 0xF5) > 28:
        errors.append(f"narrow_1280 canvas sample drifted from moonstone: {sample}")
    if int(moon.get("dot_alpha") or 0) not in range(30, 45):
        errors.append(f"narrow_1280 dot alpha expected ~38, got {moon.get('dot_alpha')}")

    layout_facts = (geometry.get("layout_1280") or {}).get("layout_picker") or {}
    if int(layout_facts.get("thumb_count") or 0) != 8:
        errors.append(f"layout_1280 expected 8 thumbs, got {layout_facts.get('thumb_count')}")
    if layout_facts.get("history_buttons"):
        errors.append(f"layout_1280 still has history buttons: {layout_facts.get('history_buttons')}")
    thumbs = layout_facts.get("thumbs") or {}
    left = thumbs.get("split_horizontal") or {}
    right = thumbs.get("split_vertical") or {}
    below = thumbs.get("grid_2x2") or {}
    if int(right.get("x") or 0) <= int(left.get("x") or 0):
        errors.append("layout_1280 thumbs are not two columns")
    if int(below.get("y") or 0) <= int(left.get("y") or 0):
        errors.append("layout_1280 thumbs are not four rows")
    in_span = layout_facts.get("trigger_center_in_span")
    adjacent = layout_facts.get("vertically_adjacent")
    if not in_span and not adjacent:
        errors.append(
            "layout_1280 overlay is not vertically anchored to trigger: "
            f"in_span={in_span} adjacent={adjacent} "
            f"clamp={layout_facts.get('clamp_reason')} "
            f"center_error_y={layout_facts.get('center_error_y')}"
        )
    if layout_facts.get("horizontally_right_of_rail") is not True:
        errors.append("layout_1280 overlay is not to the right of the rail")
    current_layout = (geometry.get("layout_1280") or {}).get("layout_id")
    checked = layout_facts.get("checked") or []
    if current_layout and current_layout not in checked:
        errors.append(f"layout_1280 current layout {current_layout!r} is not checked: {checked}")
    overlay = layout_facts.get("overlay") or {}
    nav = (geometry.get("layout_1280") or {}).get("navigation_island") or {}
    if overlay.get("visible") and nav.get("visible"):
        overlay_rect = QRect(int(overlay.get("x") or 0), int(overlay.get("y") or 0), int(overlay.get("w") or 0), int(overlay.get("h") or 0))
        nav_rect = QRect(int(nav.get("x") or 0), int(nav.get("y") or 0), int(nav.get("w") or 0), int(nav.get("h") or 0))
        if overlay_rect.intersects(nav_rect):
            errors.append("layout_1280 overlay covers the navigation island")

    errors.extend(_library_errors(manifest))
    rest = (geometry.get("library_groups_1280") or {}).get("trigger_rest")
    if not rest:
        errors.append("library_groups_1280 missing trigger_rest after canvas click")
    else:
        if rest.get("panelOpen") in ("true", True):
            errors.append("library trigger still panelOpen after canvas click")
        if rest.get("hasFocus"):
            errors.append("library trigger retained focus after canvas click")
        if rest.get("checked"):
            errors.append("library trigger still checked after canvas click")

    boards = geometry.get("boards_1280") or {}
    if boards.get("active_panel") != "boards":
        errors.append(f"boards_1280 active_panel={boards.get('active_panel')!r}, expected 'boards'")
    popover = boards.get("board_popover") or {}
    island = boards.get("board_island") or {}
    if not popover.get("visible"):
        errors.append("boards_1280 popover is not visible")
    if popover.get("visible") and island.get("visible"):
        island_bottom = int(island.get("y") or 0) + int(island.get("h") or 0)
        if int(popover.get("y") or 0) < island_bottom:
            errors.append("boards_1280 popover is not anchored below BoardIsland")

    rail_800 = (narrow_800.get("rail_entries") or {})
    if rail_800.get("missing"):
        errors.append(f"narrow_800 missing rail entries: {rail_800.get('missing')}")
    if rail_800.get("all_visible") is not True:
        errors.append("narrow_800 does not show every release rail entry including Pointer")
    if rail_800.get("all_inside") is not True:
        errors.append("narrow_800 rail entry hit rects are clipped")

    for name in ("pointer_popup_800", "pointer_popup_1280"):
        popup = (geometry.get(name) or {}).get("pointer_popup") or {}
        if popup.get("popover_visible") is not True:
            errors.append(f"{name} pointer popup is not visible")
        if popup.get("active_overlay") != "author_pointer":
            errors.append(f"{name} active overlay is {popup.get('active_overlay')!r}")
        entries = (popup.get("rail_entries") or {})
        select = (entries.get("entries") or {}).get("select") or {}
        if select.get("visible") is not True:
            errors.append(f"{name} Pointer tile is not visible")

    minimap = (geometry.get("selected_bottom_right_with_minimap") or {}).get(
        "minimap_selection"
    )
    errors.extend(
        _selection_chrome_errors(
            "selected_bottom_right_with_minimap",
            minimap,
            require_minimap=True,
        )
    )

    picker = (geometry.get("selected_shape_format_picker") or {}).get("format_picker")
    errors.extend(
        _selection_chrome_errors(
            "selected_shape_format_picker",
            picker,
            require_picker=True,
            require_toolbar=True,
        )
    )
    if isinstance(picker, dict):
        if picker.get("picker_visible") is not True and _fact_visible(picker.get("picker")):
            errors.append("selected_shape_format_picker picker_visible flag is false")
        expected_overlay = picker.get("expected_overlay")
        if expected_overlay and picker.get("active_overlay") != expected_overlay:
            errors.append(
                "selected_shape_format_picker active overlay is "
                f"{picker.get('active_overlay')!r}"
            )

    laser = geometry.get("laser_cursor") or {}
    if laser.get("bitmap_cursor") is not True:
        errors.append(f"laser_cursor is not a Qt bitmap cursor: {laser}")
    hotspot = laser.get("hotspot") or []
    expected_hotspot = laser.get("expected_hotspot") or [16, 16]
    if list(hotspot) != list(expected_hotspot):
        errors.append(f"laser_cursor hotspot {hotspot} != {expected_hotspot}")
    if laser.get("native_pixmap") is True:
        errors.append("laser_cursor must not pretend to be a native Cocoa screenshot")

    if errors:
        raise GeometryError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--platform", default=None)
    args = parser.parse_args()
    if args.platform:
        import os

        os.environ["QT_QPA_PLATFORM"] = args.platform
    try:
        manifest = generate(args.output)
    except GeometryError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {manifest['output_dir']}")
    print(f"contact sheet: {manifest.get('contact_sheet')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
