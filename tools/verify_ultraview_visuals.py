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
    "hero_1280",
    "hero_1600",
    "grid_6_1600",
    "tray_1600",
    "four_status_1600",
    "show_flags_1600",
    "focus_1600",
    "presentation_1600",
    "toolbar_1100",
    "toolbar_1600",
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
    page.set_library_visible(True)
    return board


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
        toolbar.btn_mode_ultraview,
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
        page.resize(1600, 900)
        _reset_board(page, "hero_left_4")
        for index, (section, color) in enumerate(
            (("time", "#2d7ff9"), ("fft", "#e0883c"), ("order", "#9b6bd0"), ("frf", "#168f91"))
        ):
            _add_preview(page, section, f"{section}-1", color=color, digest=f"d{index}")
        page.set_board(page.board())
        _pump(app, page)
        snap("hero_1600", page, _page_snapshot(page))

        page.resize(1280, 800)
        _pump(app, page)
        snap("hero_1280", page, _page_snapshot(page))

        page.resize(1600, 900)
        _reset_board(page, "grid_3x2")
        colors = ("#2d7ff9", "#e0883c", "#6a8f4f", "#9b6bd0", "#168f91", "#5b6775")
        sections = ("time", "fft", "fft_time", "order", "frf", "time")
        for index, (section, color) in enumerate(zip(sections, colors)):
            _add_preview(
                page, section, f"g{index}", color=color, digest=f"g{index}"
            )
        page.set_board(page.board())
        _pump(app, page)
        snap("grid_6_1600", page, _page_snapshot(page))

        _reset_board(page, "grid_2x2")
        for index in range(6):
            _add_preview(
                page, "time", f"tray-{index}", color="#3f7fc4", digest=f"t{index}"
            )
        page.set_board(page.board())
        _pump(app, page)
        snap("tray_1600", page, _page_snapshot(page))

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
        snap("four_status_1600", page, _page_snapshot(page))

        page.board().show_titles = False
        page.board().show_sources = False
        page.set_board(page.board())
        _pump(app, page)
        snap("show_flags_1600", page, _page_snapshot(page))

        page.board().show_titles = True
        page.board().show_sources = True
        page.set_board(page.board())
        first = page.board().placements[0].ref
        page.show_focus(first.section, first.view_id)
        _pump(app, page)
        snap("focus_1600", page, _page_snapshot(page))
        page.focus_layer().close_layer()

        page.set_presentation_active(True)
        _pump(app, page)
        snap("presentation_1600", page, _page_snapshot(page))
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

    compact = geometry.get("toolbar_1100") or {}
    if compact.get("compact") is not True:
        errors.append("toolbar_1100 is not icon-only compact")
    if compact.get("overlap_pairs"):
        errors.append(f"toolbar_1100 overlaps: {compact['overlap_pairs']}")
    if compact.get("clipped"):
        errors.append(f"toolbar_1100 clipped: {compact['clipped']}")
    if any(compact.get("labels") or ["x"]):
        errors.append("toolbar_1100 still shows labels")

    wide = geometry.get("toolbar_1600") or {}
    if wide.get("compact") is not False:
        errors.append("toolbar_1600 stayed compact")
    if wide.get("labels") != ["时域", "频谱", "时频", "阶次", "频响", "总览"]:
        errors.append(f"toolbar_1600 labels={wide.get('labels')}")

    hero = geometry.get("hero_1600") or {}
    filled = [c for c in hero.get("cards") or [] if not c.get("empty")]
    if len(filled) < 4:
        errors.append(f"hero_1600 expected 4 cards, got {len(filled)}")
    if hero.get("library_visible") is not True:
        errors.append("hero_1600 library hidden")

    grid = geometry.get("grid_6_1600") or {}
    filled6 = [c for c in grid.get("cards") or [] if not c.get("empty")]
    if len(filled6) != 6:
        errors.append(f"grid_6_1600 expected 6 cards, got {len(filled6)}")

    tray = geometry.get("tray_1600") or {}
    if int(tray.get("unplaced") or 0) < 1:
        errors.append("tray_1600 has no overflow")
    if tray.get("tray_body_visible") is not True:
        errors.append("tray_1600 body not visible")

    statuses = {
        card.get("status")
        for card in (geometry.get("four_status_1600") or {}).get("cards") or []
        if not card.get("empty")
    }
    wanted = {"fresh", "stale", "missing", "orphaned"}
    if not wanted <= statuses:
        errors.append(f"four_status missing {wanted - statuses}")

    flags = geometry.get("show_flags_1600") or {}
    if flags.get("show_titles") or flags.get("show_sources"):
        errors.append("show_flags_1600 did not hide titles/sources")
    for card in flags.get("cards") or []:
        if card.get("empty"):
            continue
        if card.get("title_visible"):
            errors.append("show_flags left a visible title")
        if int(card.get("footer_h") or 0) != 0:
            errors.append("show_flags left a source footer band")
        break

    if (geometry.get("focus_1600") or {}).get("focus_visible") is not True:
        errors.append("focus layer not visible")
    presentation = geometry.get("presentation_1600") or {}
    if presentation.get("presentation") is not True:
        errors.append("presentation flag off")
    if presentation.get("library_visible") is True:
        errors.append("presentation still shows library")

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
