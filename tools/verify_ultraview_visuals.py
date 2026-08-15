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

from PyQt5.QtCore import QRect, Qt
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
    "library_overview_stale_1280",
    "library_overview_1280",
    "layout_1280",
    "filter_1280",
    "unplaced_1280",
    "display_1280",
    "export_1280",
    "card_context_1280",
    "presentation_1280",
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
    host = page.canvas_host()
    rail = page.tool_rail()
    board_island = page.board_island()
    status_island = page.status_island()
    global_island = page.global_island()
    navigation_island = page.navigation_island()
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


def _layout_picker_facts(page) -> dict[str, Any]:
    from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import ISLAND_GAP

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
    if overlay is not None and trigger is not None:
        mapped = trigger.mapTo(host, trigger.rect().center())
        trigger_center = {"x": int(mapped.x()), "y": int(mapped.y())}
        geo = overlay.geometry()
        overlay_center = {"x": int(geo.center().x()), "y": int(geo.center().y())}
        center_error_y = abs(overlay_center["y"] - trigger_center["y"])
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
        "thumbs": thumbs,
        "checked": [layout_id for layout_id, button in picker._buttons.items() if button.isChecked()],
        "history_buttons": history,
        "intro": picker.intro_label().text(),
        "thumb_count": len(picker._buttons),
    }


#: Target geometry constants from the View-library plan §4. They are read by
#: name instead of by literal so a retune stays a one-line edit in ``widgets``;
#: a name that is absent is recorded as ``None`` and turned into an explicit
#: ``assert_geometry`` failure, never silently substituted with a number.
_LIBRARY_CONSTANT_NAMES = (
    "LIBRARY_OVERLAY_HEIGHT",
    "LIBRARY_OVERLAY_MIN_HEIGHT",
    "LIBRARY_HEAD_HEIGHT",
    "LIBRARY_SECTION_HEAD_HEIGHT",
    "LIBRARY_ROW_HEIGHT",
    "LIBRARY_CATALOG_HEIGHT",
    "LIBRARY_ROW_ACTION_SIZE",
    "LIBRARY_MODE_GROUPS",
    "LIBRARY_MODE_COMPACT",
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


def _library_mode_tabs(page) -> tuple[QWidget | None, QWidget | None]:
    """The 展开 / 概览 segmented control, looked up by objectName.

    objectName is the stable handle here: QSS targets it and the selector
    liveness test keeps it wired, whereas the panel exposes no public accessor
    for these two buttons.
    """
    from PyQt5.QtWidgets import QToolButton

    panel = page.library_panel()
    return (
        panel.findChild(QToolButton, "ultraViewLibraryModeGroups"),
        panel.findChild(QToolButton, "ultraViewLibraryModeCompact"),
    )


def _library_facts(page) -> dict[str, Any]:
    """Record the View-library geometry the anti-jump contract is made of.

    Three failure shapes live in these numbers: the panel rect changing when
    only panel *content* changed (the jump), a section frame rendered shorter
    than its own minimum hint (the clipped group card), and catalog cards
    stretched past their row height by a body layout with no trailing stretch
    (the ballooned overview — visible only while the frame is still stale, see
    the shot recipe in ``generate``). All three are facts about widget
    geometry, so they are read off the widgets rather than sampled from
    screenshot pixels.
    """
    panel = page.library_panel()
    sections = {
        section: {
            "height": int(frame.height()),
            "min_hint": int(frame.minimumSizeHint().height()),
            "visible": bool(frame.isVisible()),
        }
        for section, frame in panel.section_widgets().items()
    }
    catalog = {
        section: int(card.height()) for section, card in panel.catalog_cards().items()
    }
    row_heights = [int(widget.height()) for widget in panel.row_widgets()]
    groups_tab, compact_tab = _library_mode_tabs(page)
    tabs = {
        "groups": _rect(groups_tab) if groups_tab is not None else None,
        "compact": _rect(compact_tab) if compact_tab is not None else None,
    }
    return {
        "panel": _rect(panel),
        "browse_mode": panel.browse_mode(),
        "size_hint_h": int(panel.sizeHint().height()),
        "min_size_hint_h": int(panel.minimumSizeHint().height()),
        "sections": sections,
        "section_heights": sorted({fact["height"] for fact in sections.values()}),
        "row_heights": sorted(set(row_heights)),
        "catalog_cards": catalog,
        "catalog_heights": sorted(set(catalog.values())),
        "mode_tabs": tabs,
        "mode_tab_widths": [
            None if tabs[key] is None else int(tabs[key]["w"])
            for key in ("groups", "compact")
        ],
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

        # Three library shots covering the two halves of the same defect. In the
        # product a mode switch does NOT call ``_apply_floating_layout``: the
        # frame keeps the height it had, and the content-driven size hint only
        # lands later, at the next resize / reopen / set_board. The click and
        # the jump are therefore separated in time, which is why the two states
        # need different shots and MUST NOT share a shooting recipe:
        #
        #   *_stale*  — mode switched, layout deliberately NOT re-applied. The
        #               frame is still the taller groups-mode one while the
        #               content already shrank, so a body layout with no
        #               trailing stretch hands the spare height to the catalog
        #               cards and they balloon. This is the user-visible frame.
        #   *_groups* / *_overview* — layout forced after the switch so the two
        #               rects sit in a directly comparable state; that is the
        #               only way to compare frames, but note it also zeroes the
        #               spare height and thereby hides the ballooning above.
        #
        # Do not "tidy" this by re-applying the layout before the stale shot:
        # that is exactly the mistake that made this harness report a healthy
        # 40px card on a build that rendered 100px ones.
        groups_tab, compact_tab = _library_mode_tabs(page)
        if groups_tab is not None:
            groups_tab.click()
        page._apply_floating_layout()
        _pump(app, page)
        snap("library_groups_1280", page, _page_snapshot(page))
        if compact_tab is not None:
            compact_tab.click()
        _pump(app, page)
        snap("library_overview_stale_1280", page, _page_snapshot(page))
        page._apply_floating_layout()
        _pump(app, page)
        snap("library_overview_1280", page, _page_snapshot(page))
        if groups_tab is not None:
            groups_tab.click()
        page._apply_floating_layout()
        _pump(app, page)

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
    """View-library geometry contract (plan §6.3).

    The load-bearing one is the first: the panel rect must be byte-identical
    across the two browse modes. Panel height used to be a function of panel
    content, and the trigger-centred anchor put that height in the numerator of
    the top edge, so every fold / mode switch / keystroke moved the frame. A
    rect that survives a mode switch is the machine-checkable form of "it does
    not jump"; a height cap would only narrow the jump.
    """
    errors: list[str] = []
    geometry = manifest.get("geometry") or {}
    constants = manifest.get("library_constants") or {}
    missing = sorted(name for name, value in constants.items() if value is None)
    if missing:
        errors.append(
            "library geometry constants absent from ultraview.widgets: "
            + ", ".join(missing)
        )

    facts = {}
    for name, wanted_mode_key in (
        ("library_groups_1280", "LIBRARY_MODE_GROUPS"),
        ("library_overview_stale_1280", "LIBRARY_MODE_COMPACT"),
        ("library_overview_1280", "LIBRARY_MODE_COMPACT"),
    ):
        fact = (geometry.get(name) or {}).get("library") or {}
        facts[name] = fact
        if not fact:
            errors.append(f"{name} recorded no library facts")
            continue
        if not (fact.get("panel") or {}).get("visible"):
            errors.append(f"{name} did not leave the library panel visible")
        wanted_mode = constants.get(wanted_mode_key)
        if wanted_mode is not None and fact.get("browse_mode") != wanted_mode:
            errors.append(
                f"{name} browse mode is {fact.get('browse_mode')!r}, expected {wanted_mode!r}"
            )

    groups = facts.get("library_groups_1280") or {}
    overview = facts.get("library_overview_1280") or {}
    groups_panel = groups.get("panel")
    overview_panel = overview.get("panel")
    if groups_panel and overview_panel and groups_panel != overview_panel:
        errors.append(
            "library panel rect changed with panel content: "
            f"groups={groups_panel} overview={overview_panel}"
        )

    for section, fact in sorted((groups.get("sections") or {}).items()):
        if not fact.get("visible"):
            continue
        height = int(fact.get("height") or 0)
        min_hint = int(fact.get("min_hint") or 0)
        if height < min_hint:
            errors.append(
                f"library section {section!r} is clipped: height={height} < minHint={min_hint}"
            )

    # Catalog cards are checked on BOTH overview shots, and the stale one is the
    # load-bearing half: it is the only state where the frame still carries the
    # taller mode's height, so it is the only state where a missing trailing
    # stretch has spare pixels to hand out. Checking just the re-laid-out shot
    # passes on a build whose cards render at 100px.
    catalog_height = constants.get("LIBRARY_CATALOG_HEIGHT")
    if catalog_height is not None:
        for name in ("library_overview_stale_1280", "library_overview_1280"):
            cards = (facts.get(name) or {}).get("catalog_cards") or {}
            if not cards:
                errors.append(f"{name} recorded no catalog cards")
            for section, height in sorted(cards.items()):
                if int(height) != int(catalog_height):
                    errors.append(
                        f"{name} catalog card {section!r} height={height}, "
                        f"expected {catalog_height}"
                    )
    return errors


def assert_geometry(manifest: dict[str, Any]) -> None:
    """Raise GeometryError if the harness contract is broken."""
    errors: list[str] = []
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
        if int(rail.get("height") or 0) != int(rail.get("preferred_height") or 0):
            errors.append(f"{name} rail is stretched instead of content-height: {rail}")

    base_board = (narrow_1280.get("board_scroll") or {})
    for name in (
        "library_1280",
        "library_groups_1280",
        "library_overview_stale_1280",
        "library_overview_1280",
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
    if not (context.get("card_context") or {}).get("visible"):
        errors.append("card_context_1280 missing selected-card actions")

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
    error_y = layout_facts.get("center_error_y")
    budget = int(layout_facts.get("anchor_budget_px") or 44)
    if error_y is None or int(error_y) > budget:
        errors.append(f"layout_1280 overlay not anchored to trigger: error={error_y} budget={budget}")
    overlay = layout_facts.get("overlay") or {}
    nav = (geometry.get("layout_1280") or {}).get("navigation_island") or {}
    if overlay.get("visible") and nav.get("visible"):
        overlay_rect = QRect(int(overlay.get("x") or 0), int(overlay.get("y") or 0), int(overlay.get("w") or 0), int(overlay.get("h") or 0))
        nav_rect = QRect(int(nav.get("x") or 0), int(nav.get("y") or 0), int(nav.get("w") or 0), int(nav.get("h") or 0))
        if overlay_rect.intersects(nav_rect):
            errors.append("layout_1280 overlay covers the navigation island")

    errors.extend(_library_errors(manifest))

    if errors:
        raise GeometryError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
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
