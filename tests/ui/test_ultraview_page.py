"""UltraView page harness: library, cards, tray, drag, focus (UV-A02/A06–A12)."""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QCoreApplication, QEvent, QMimeData, QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGraphicsDropShadowEffect,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui.chart_stack.ultraview.layouts import (
    BOARD_PADDING,
    MIN_CARD_CHROME_HEIGHT,
    SLOT_GUTTER,
    slot_rects,
)
from mf4_analyzer.ui.chart_stack.ultraview import widgets as uv_widgets
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    LAYOUT_MOVE,
    LayoutPlan,
    LayoutRejectReason,
    clamp_rect,
    legal_grid_rect,
    rect_to_pixels,
)
from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    BOARD_ISLAND_MAX_WIDTH,
    DEFAULT_NAVIGATION_ISLAND_SIZE,
    GLOBAL_ISLAND_WIDTH,
    ISLAND_HEIGHT,
    RAIL_CONTENT_HEIGHT,
    RAIL_WIDTH,
    STATUS_ISLAND_WIDTH,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import PANEL_FILTER, PANEL_LAYOUT, PANEL_LIBRARY, PANEL_UNPLACED, PANEL_BOARDS
from mf4_analyzer.ui.chart_stack.ultraview.feedback import format_rearranged
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    BoardSwitcher,
    FEEDBACK_NO_LEGAL_LAYOUT,
    FEEDBACK_OUT_OF_GRID,
    LIBRARY_DEFAULT_WIDTH,
    MISSING_CARD_COPY,
    LibraryRow,
    UltraViewCard,
    UnplacedTray,
    extract_ref_strings,
    make_ref_mime,
)
from mf4_analyzer.ui.ultraview_state import (
    MAX_UI_BOARDS,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    LAYOUT_SLOTS,
    SOURCE_SECTIONS,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    STATUS_FRESH,
    ULTRAVIEW_REF_MIME,
    FreeGridPlacement,
    GridRect,
    LAYOUT_MODE_FREE_GRID,
    LAYOUT_MODE_TEMPLATE,
    UltraViewRef,
    _legal_grid_rect,
    add_ref,
    board_to_payload,
    create_board,
    default_board,
    default_workspace,
    first_empty_slot,
    free_grid_placement_for,
    free_grid_to_template,
    make_ref,
    membership_set,
    move_to_unplaced,
    place_free_grid_from_unplaced,
    place_from_unplaced,
    rebind_ref,
    remove_ref,
    reorder_board,
    replace_slot,
    set_layout,
    set_board_viewport,
    slot_occupant,
    swap_slots,
    template_to_free_grid,
)
from mf4_analyzer.ui_kit import load_stylesheet

PAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)


@dataclass
class FakePreview:
    ref: UltraViewRef
    image: QImage | None = None
    captured_digest: str | None = None
    title: str = ""
    source_summary: str = ""
    tab_color: str = "#2d7ff9"
    axis_kind: str = "time"
    x_unit: str = "s"
    x_range: tuple[float, float] | None = (0.0, 10.0)


def _image(width=48, height=32, color="#2d7ff9") -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(color))
    return image


def _rows() -> list[LibraryRow]:
    rows = []
    names = {
        "time": "道路输入",
        "fft": "共振检查",
        "fft_time": "瞬态频移",
        "frf": "基线 H1",
        "order": "2–8 阶总览",
    }
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
        rows.append(
            LibraryRow(
                section=section,
                view_id=f"{section}-2",
                name=f"{names[section]} B",
                tab_color="#1098ad",
                status=STATUS_MISSING,
                on_board=False,
                source_summary=f"{section}-alt",
            )
        )
    return rows


def _mime(section: str, view_id: str) -> QMimeData:
    return make_ref_mime(section, view_id)


def _enter(mime: QMimeData, pos: QPoint | None = None) -> QDragEnterEvent:
    event = QDragEnterEvent(
        pos or QPoint(8, 8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    return event


def _drop(mime: QMimeData, pos: QPoint | None = None) -> QDropEvent:
    event = QDropEvent(
        pos or QPoint(8, 8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    return event


def _move(mime: QMimeData, pos: QPoint | None = None) -> QDragMoveEvent:
    event = QDragMoveEvent(
        pos or QPoint(8, 8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    return event


def _leave() -> QDragLeaveEvent:
    return QDragLeaveEvent()


def _is_drop_active(widget: QWidget) -> bool:
    return widget.property("dropActive") in (True, "true")


def _sample_pixel(widget: QWidget, x: int, y: int) -> QColor:
    image = widget.grab().toImage()
    return QColor(image.pixel(max(0, min(x, image.width() - 1)), max(0, min(y, image.height() - 1))))


def _centre_pixel(widget: QWidget) -> QColor:
    return _sample_pixel(widget, widget.width() // 2, widget.height() // 2)


def _chroma(color: QColor) -> float:
    """How loud a colour reads, as Qt-HSV ``S * V`` == ``(max - min) / 255`` of RGB.

    Saturation alone cannot express "calm": a dark forest green and a Tailwind alert
    green both sit near S 0.5-0.8, and the alert one is loud only because it is *also*
    bright. ``S * V`` separates them, and it is linear in RGB so antialiased blends
    between two calm colours stay calm (no overshoot).
    """
    return color.saturationF() * color.valueF()


def _loudest_pixel(widget: QWidget) -> QColor:
    """The most colourful pixel anywhere in ``widget`` — fill, border and ink alike."""
    image = widget.grab().toImage()
    worst = QColor(image.pixel(0, 0))
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = QColor(image.pixel(x, y))
            if _chroma(pixel) > _chroma(worst):
                worst = pixel
    return worst


def _hue_gap(left: QColor, right: QColor) -> float:
    """Shortest distance between two hues on the colour wheel, in degrees."""
    assert left.hue() >= 0, f"{left.name()} is achromatic, it has no hue to compare"
    assert right.hue() >= 0, f"{right.name()} is achromatic, it has no hue to compare"
    delta = abs(left.hue() - right.hue()) % 360
    return min(delta, 360 - delta)


def _dense_rows() -> list[LibraryRow]:
    """The shape from the plan's §1 probe: 4 time Views plus one of each other kind.

    Concentrating rows in one section is what exposed the clipping — a section card
    tall enough to be the one QVBoxLayout squeezes when the body minimum is too small.
    """
    meta = "Rte_TAS_mTorsionBarTorque_xds16, Rte_TLC_mSumLimMotorTorque_xds16"
    rows = [
        LibraryRow(
            section="time",
            view_id=f"t{index}",
            name=f"View {index + 1}",
            tab_color="#3B82F6",
            status=STATUS_MISSING,
            on_board=False,
            source_summary=meta,
        )
        for index in range(4)
    ]
    rows += [
        LibraryRow(
            section=section,
            view_id=f"{section}-only",
            name="View 1",
            tab_color="#3B82F6",
            status=STATUS_MISSING,
            on_board=False,
            source_summary="EPS_1_CRC",
        )
        for section in ("fft", "fft_time", "frf", "order")
    ]
    return rows


class _Harness:
    def __init__(self, qtbot):
        self.board = default_board()
        self.page = UltraViewPage()
        qtbot.addWidget(self.page)
        self.page.resize(1600, 900)
        self.page.show()
        self.added: list[tuple[str, str]] = []
        self.replaced: list[tuple[str, str, str]] = []
        self.swapped: list[tuple[str, str]] = []
        self.placed: list[tuple[str, str, str]] = []
        self.grid_replaced: list[tuple[str, str, str, str]] = []
        self.grid_inserted: list[tuple[str, str, object]] = []
        self.unplaced: list[tuple[str, str]] = []
        self.removed: list[tuple[str, str]] = []
        self.opened: list[tuple[str, str]] = []
        self.synced: list[tuple[str, str]] = []
        self.focused: list[tuple[str, str]] = []
        self.armed: list[tuple[str, str]] = []
        self.rebound: list[tuple[str, str, str, str]] = []
        self.located: list[tuple[str, str]] = []
        self.copied_cards: list[tuple[str, str]] = []
        self.copied_board = 0
        self.exports: list[int] = []
        self.filters: list[str] = []
        self.layouts: list[str] = []
        self.free_grid: list[bool] = []
        self.ratio_steps: list[int] = []
        self.presentation: list[bool] = []
        self.page.viewport_changed.connect(self._persist_viewport)
        self.page.add_ref_requested.connect(self._on_add)
        self.page.replace_slot_requested.connect(self._on_replace)
        self.page.swap_slots_requested.connect(self._on_swap)
        self.page.place_from_unplaced_requested.connect(self._on_place)
        self.page.free_grid_insert_requested.connect(self._on_grid_insert)
        self.page.free_grid_replace_requested.connect(self._on_grid_replace)
        self.page.move_to_unplaced_requested.connect(self._on_unplaced)
        self.page.remove_ref_requested.connect(self._on_remove)
        self.page.open_source_requested.connect(self._record_open)
        self.page.sync_requested.connect(self._record_sync)
        self.page.focus_requested.connect(self._record_focus)
        self.page.rebind_arm_requested.connect(self._record_arm)
        self.page.rebind_ref_requested.connect(self._on_rebind)
        self.page.locate_ref_requested.connect(self._record_locate)
        self.page.copy_card_image_requested.connect(self._record_copy_card)
        self.page.copy_board_requested.connect(self._record_copy_board)
        self.page.export_png_requested.connect(self._record_export)
        self.page.compare_filter_changed.connect(self._record_filter)
        self.page.layout_changed.connect(self._record_layout)
        self.page.free_grid_toggled.connect(self._record_free_grid)
        self.page.ratio_nudge_requested.connect(self._record_ratio)
        self.page.presentation_toggled.connect(self._record_presentation)
        self.page.set_library_rows(_rows())
        self.page.set_board(self.board)

    def _persist_viewport(self, board_id: str, payload: dict) -> None:
        if str(board_id) == self.board.board_id:
            set_board_viewport(self.board, payload)

    def _on_add(self, section: str, view_id: str) -> None:
        self.added.append((section, view_id))
        add_ref(self.board, make_ref(section, view_id))
        self.page.set_board(self.board)

    def _on_replace(self, slot_id: str, section: str, view_id: str) -> None:
        self.replaced.append((slot_id, section, view_id))
        replace_slot(self.board, slot_id, make_ref(section, view_id))
        self.page.set_board(self.board)

    def _on_swap(self, slot_a: str, slot_b: str) -> None:
        self.swapped.append((slot_a, slot_b))
        swap_slots(self.board, slot_a, slot_b)
        self.page.set_board(self.board)

    def _on_place(self, slot_id: str, section: str, view_id: str) -> None:
        self.placed.append((slot_id, section, view_id))
        place_from_unplaced(self.board, slot_id, make_ref(section, view_id))
        self.page.set_board(self.board)

    def _on_grid_insert(self, section: str, view_id: str, anchor: object) -> None:
        self.grid_inserted.append((section, view_id, anchor))
        ref = make_ref(section, view_id)
        if ref in self.board.unplaced:
            place_free_grid_from_unplaced(self.board, ref, preferred_anchor=anchor)
        else:
            add_ref(self.board, ref, preferred_anchor=anchor)
        self.page.set_board(self.board)

    def _on_grid_replace(
        self, target_section: str, target_view_id: str, source_section: str, source_view_id: str
    ) -> None:
        self.grid_replaced.append(
            (target_section, target_view_id, source_section, source_view_id)
        )

    def _on_unplaced(self, section: str, view_id: str) -> None:
        self.unplaced.append((section, view_id))
        move_to_unplaced(self.board, make_ref(section, view_id))
        self.page.set_board(self.board)

    def _on_remove(self, section: str, view_id: str) -> None:
        self.removed.append((section, view_id))
        remove_ref(self.board, make_ref(section, view_id))
        self.page.set_board(self.board)

    def _record_open(self, section: str, view_id: str) -> None:
        self.opened.append((section, view_id))

    def _record_sync(self, section: str, view_id: str) -> None:
        self.synced.append((section, view_id))

    def _record_focus(self, section: str, view_id: str) -> None:
        self.focused.append((section, view_id))

    def _record_arm(self, section: str, view_id: str) -> None:
        self.armed.append((section, view_id))

    def _on_rebind(
        self, old_section: str, old_view_id: str, new_section: str, new_view_id: str
    ) -> None:
        self.rebound.append((old_section, old_view_id, new_section, new_view_id))
        rebind_ref(
            self.board,
            make_ref(old_section, old_view_id),
            make_ref(new_section, new_view_id),
        )
        self.page.set_board(self.board)

    def _record_locate(self, section: str, view_id: str) -> None:
        self.located.append((section, view_id))

    def _record_copy_card(self, section: str, view_id: str) -> None:
        self.copied_cards.append((section, view_id))

    def _record_copy_board(self) -> None:
        self.copied_board += 1

    def _record_export(self, scale: int) -> None:
        self.exports.append(int(scale))

    def _record_filter(self, filter_id: str) -> None:
        self.filters.append(filter_id)

    def _record_layout(self, layout_id: str) -> None:
        self.layouts.append(layout_id)
        set_layout(self.board, layout_id)
        self.page.set_board(self.board)

    def _record_free_grid(self, enabled: bool) -> None:
        self.free_grid.append(bool(enabled))

    def _record_ratio(self, steps: int) -> None:
        self.ratio_steps.append(int(steps))

    def _record_presentation(self, on: bool) -> None:
        self.presentation.append(bool(on))

    def fill_board(self, count: int = 4) -> None:
        for index in range(count):
            add_ref(self.board, make_ref("time", f"fill-{index}"))
        self.page.set_board(self.board)


def test_chrome_size_fallbacks_track_floating_layout_constants(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    page = harness.page
    assert page._chrome_sizes() == {
        "board_island": (
            page._board_island.sizeHint().width(),
            page._board_island.sizeHint().height(),
        ),
        "global_island": (
            page._global_island.sizeHint().width(),
            page._global_island.sizeHint().height(),
        ),
        "status_island": (
            page._status_island.sizeHint().width(),
            page._status_island.sizeHint().height(),
        ),
        "navigation_island": (
            page._navigation_island.sizeHint().width(),
            page._navigation_island.sizeHint().height(),
        ),
        "rail": (
            page._tool_rail.sizeHint().width(),
            page._tool_rail.sizeHint().height(),
        ),
    }
    for widget in (
        page._board_island,
        page._global_island,
        page._status_island,
        page._navigation_island,
        page._tool_rail,
    ):
        monkeypatch.setattr(type(widget), "sizeHint", lambda _self: QSize(0, 0))

    assert page._chrome_sizes() == {
        "board_island": (BOARD_ISLAND_MAX_WIDTH, ISLAND_HEIGHT),
        "global_island": (GLOBAL_ISLAND_WIDTH, ISLAND_HEIGHT),
        "status_island": (STATUS_ISLAND_WIDTH, ISLAND_HEIGHT),
        "navigation_island": DEFAULT_NAVIGATION_ISLAND_SIZE,
        "rail": (RAIL_WIDTH, RAIL_CONTENT_HEIGHT),
    }


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.add(module.split(".")[0])
            for alias in node.names:
                names.add(alias.name)
    return names


def test_page_modules_do_not_import_main_window():
    for name in ("page.py", "widgets.py", "layouts.py", "gesture.py", "ghost_overlay.py"):
        imported = _imported_names(PAGE_DIR / name)
        assert "MainWindow" not in imported
        assert "main_window" not in imported
        source = (PAGE_DIR / name).read_text(encoding="utf-8")
        assert "QGraphicsScene" not in source
        assert "QGraphicsItem" not in source
        assert "QGraphicsProxyWidget" not in source


def test_library_grouped_by_five_sections_search_and_full_tooltip(qtbot):
    harness = _Harness(qtbot)
    library = harness.page.library_panel()
    assert tuple(library.section_widgets()) == SOURCE_SECTIONS
    assert library.pin_button().objectName() == "ultraViewLibraryPin"
    assert library.is_pinned() is False
    assert "钉住" in library.pin_button().toolTip()
    assert len(library.row_widgets()) == 10
    row = next(widget for widget in library.row_widgets() if widget.row().view_id == "time-1")
    tip = row.toolTip()
    assert "道路输入" in tip
    assert "time-src" in tip
    library.search_field().setText("共振")
    visible = library.visible_rows()
    assert {item.view_id for item in visible} == {"fft-1", "fft-2"}
    library.search_field().setText("FFT")
    assert any(item.section == "fft" for item in library.visible_rows())


def test_library_sections_collapse_expand_and_survive_rebuild(qtbot):
    harness = _Harness(qtbot)
    library = harness.page.library_panel()
    assert tuple(library.section_headers()) == SOURCE_SECTIONS
    header = library.section_headers()["time"]
    rows = [widget for widget in library.row_widgets() if widget.row().section == "time"]
    assert rows
    assert all(not widget.isHidden() for widget in rows)
    assert header.arrowType() == Qt.DownArrow
    header.click()
    assert library.is_section_expanded("time") is False
    assert header.arrowType() == Qt.RightArrow
    assert all(widget.isHidden() for widget in rows)

    header.click()
    assert library.is_section_expanded("time") is True
    assert all(not widget.isHidden() for widget in rows)

    header.click()
    library.set_rows(_rows())
    assert library.is_section_expanded("time") is False
    rows = [widget for widget in library.row_widgets() if widget.row().section == "time"]
    assert rows
    assert all(widget.isHidden() for widget in rows)

    add_ref(harness.board, make_ref("fft", "fft-1"))
    harness.page.set_board(harness.board)
    assert library.is_section_expanded("time") is False
    rows = [widget for widget in library.row_widgets() if widget.row().section == "time"]
    assert all(widget.isHidden() for widget in rows)


def test_library_empty_section_keeps_header_and_search_expands_matches(qtbot):
    harness = _Harness(qtbot)
    library = harness.page.library_panel()
    library.set_rows([row for row in _rows() if row.section == "time"])
    headers = library.section_headers()
    assert tuple(headers) == SOURCE_SECTIONS
    assert "  0" in headers["fft"].text()
    assert headers["fft"].findChild(QLabel, "ultraViewLibrarySectionTitle").text() == "频谱"
    assert headers["fft"].findChild(QLabel, "ultraViewLibrarySectionCount") is None
    assert headers["fft"].findChild(QLabel, "ultraViewLibrarySectionMeta") is None
    assert headers["fft"].isHidden() is False
    assert library.section_widgets()["fft"] is not None

    library.set_rows(_rows())
    fft_header = library.section_headers()["fft"]
    fft_header.click()
    assert library.is_section_expanded("fft") is False
    library.search_field().setText("共振")
    assert library.is_section_expanded("fft") is True
    fft_rows = [widget for widget in library.row_widgets() if widget.row().section == "fft"]
    assert fft_rows
    assert all(not widget.isHidden() for widget in fft_rows)


def test_library_has_one_grouped_browse_path_without_mode_or_catalog_controls(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    library = harness.page.library_panel()
    harness.page.set_library_visible(True)
    qapp.processEvents()
    assert library.findChild(QToolButton, "ultraViewLibraryModeGroups") is None
    assert library.findChild(QToolButton, "ultraViewLibraryModeCompact") is None
    assert library.findChild(QWidget, "ultraViewLibraryModeTree") is None
    assert library.findChild(QWidget, "ultraViewLibraryIntro") is None
    assert library.findChild(QToolButton, "ultraViewLibraryToggleAll") is None
    assert library.findChild(QWidget, "ultraViewLibraryCompactCaption") is None
    assert library.findChild(QWidget, "ultraViewLibraryCompactHost") is None
    assert library.browse_mode() == "groups"
    assert tuple(library.section_widgets()) == SOURCE_SECTIONS
    assert all(frame.isVisible() for frame in library.section_widgets().values())


def test_library_on_board_button_removes_instead_of_locating(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    qapp.processEvents()
    add_ref(harness.board, make_ref("frf", "frf-1"))
    harness.page.set_board(harness.board)
    qapp.processEvents()
    row = next(
        widget
        for widget in harness.page.library_panel().row_widgets()
        if widget.row().view_id == "frf-1"
    )
    button = row.findChild(QToolButton, "ultraViewLibraryAdd")
    assert button is not None
    assert button.text() == "−"
    assert button.property("action") == "remove"
    assert "移除" in button.toolTip()
    # Was `<= 20`, which pinned the size the code and the QSS used to disagree about
    # (setFixedSize(18) vs min-width 18px + 1px border). Plan §4 makes it a contract.
    assert button.width() == uv_widgets.LIBRARY_ROW_ACTION_SIZE
    assert button.height() == uv_widgets.LIBRARY_ROW_ACTION_SIZE
    assert button.height() < row.height()
    button.click()
    assert harness.removed == [("frf", "frf-1")]
    assert harness.located == []
    assert harness.added == []


def test_library_add_remove_and_selection_colors_are_distinct(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    library = harness.page.library_panel()
    library.set_selected("time", "time-1")
    library.resize(240, 640)
    qapp.processEvents()

    add_row = next(
        widget for widget in library.row_widgets() if widget.row().view_id == "fft-1"
    )
    remove_row = next(
        widget for widget in library.row_widgets() if widget.row().view_id == "time-1"
    )
    add_btn = add_row.findChild(QToolButton, "ultraViewLibraryAdd")
    remove_btn = remove_row.findChild(QToolButton, "ultraViewLibraryAdd")
    header = library.section_headers()["time"]
    assert add_btn.property("action") == "add"
    assert remove_btn.property("action") == "remove"
    assert add_btn.text() == "+"
    assert remove_btn.text() == "−"

    plus = _sample_pixel(add_btn, 2, 2)
    minus = _sample_pixel(remove_btn, 2, 2)
    # The old fixed channel deltas (+20/+8) were sized for the Tailwind palette that
    # plan §3.3 deliberately desaturates, so they measured loudness, not distinctness.
    # Direction plus hue separation says the same thing without pinning a hex string.
    assert plus.green() > plus.red()
    assert minus.red() > minus.green()
    assert _hue_gap(plus, minus) > 40

    selected_fill = _sample_pixel(remove_row, 8, remove_row.height() // 2)
    assert selected_fill.lightness() >= 247
    assert isinstance(remove_row.graphicsEffect(), QGraphicsDropShadowEffect)
    assert add_row.graphicsEffect() is None


def test_library_selection_is_single_elevated_projection_and_survives_rebuild(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)
    page.show()
    qtbot.waitExposed(page)
    page.set_library_visible(True)
    qapp.processEvents()
    library = page.library_panel()

    library.set_selected("time", "time-1")
    first = next(row for row in library.row_widgets() if row.row().view_id == "time-1")
    assert library.selected_ref() == ("time", "time-1")
    assert isinstance(first.graphicsEffect(), QGraphicsDropShadowEffect)
    assert [row.row().view_id for row in library.row_widgets() if row.property("selected") == "true"] == [
        "time-1"
    ]

    library.set_selected("time", "time-2")
    second = next(row for row in library.row_widgets() if row.row().view_id == "time-2")
    assert first.property("selected") == "false"
    assert first.graphicsEffect() is None
    assert second.property("selected") == "true"
    assert isinstance(second.graphicsEffect(), QGraphicsDropShadowEffect)

    library.set_rows(_rows())
    qapp.processEvents()
    rebuilt = next(row for row in library.row_widgets() if row.row().view_id == "time-2")
    assert rebuilt is not second
    assert library.selected_ref() == ("time", "time-2")
    assert rebuilt.property("selected") == "true"
    assert isinstance(rebuilt.graphicsEffect(), QGraphicsDropShadowEffect)
    assert sum(row.graphicsEffect() is not None for row in library.row_widgets()) == 1


def test_add_paths_share_one_intent(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    harness.page.set_board(harness.board)
    page = harness.page
    library = page.library_panel()
    library.set_selected("fft", "fft-1")
    page.request_add("fft", "fft-1")
    assert harness.added == [("fft", "fft-1")]

    harness.added.clear()
    library.set_selected("frf", "frf-1")
    add_btn = next(
        widget
        for widget in library.row_widgets()
        if widget.row().view_id == "frf-1"
    )
    add_btn.findChild(QWidget, "ultraViewLibraryAdd").click()
    assert harness.added == [("frf", "frf-1")]

    harness.added.clear()
    harness.replaced.clear()
    library.set_selected("order", "order-1")
    empty = page.slot_widget("aux_1")
    empty.add_clicked.emit("aux_1")
    assert harness.replaced == [("aux_1", "order", "order-1")]
    assert harness.added == []

    harness.added.clear()
    mime = _mime("fft_time", "fft_time-1")
    empty = page.slot_widget("aux_2")
    empty.dragEnterEvent(_enter(mime))
    empty.dropEvent(_drop(mime))
    assert harness.added == [("fft_time", "fft_time-1")]


def test_duplicate_add_locates_instead_of_adding(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.request_add("time", "time-1")
    assert harness.added == []
    assert harness.located == [("time", "time-1")]
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    assert card.property("selected") == "true"


def test_unplaced_badge_and_overlay_preserve_tray_actions(qtbot):
    harness = _Harness(qtbot)
    tray = harness.page.unplaced_tray()
    rail = harness.page.tool_rail()
    assert rail.badge_text(PANEL_UNPLACED) == "0"
    assert not tray.isVisible()
    set_layout(harness.board, "hero_left_4")
    harness.fill_board(4)
    add_ref(harness.board, make_ref("fft", "overflow-1"))
    harness.page.set_board(harness.board)
    assert [ref.view_id for ref in harness.board.unplaced] == ["overflow-1"]
    assert rail.badge_text(PANEL_UNPLACED) == "1"
    rail.panel_button(PANEL_UNPLACED).click()
    assert harness.page.active_panel() == PANEL_UNPLACED
    assert tray.isVisible()
    assert tray.body().isVisible()
    assert [item.ref() for item in tray.item_widgets()] == [("fft", "overflow-1")]
    restored = default_board()
    add_ref(restored, make_ref("time", "keep"))
    set_layout(restored, "split_horizontal")
    add_ref(restored, make_ref("fft", "a"))
    add_ref(restored, make_ref("fft", "b"))
    add_ref(restored, make_ref("order", "tray-restored"))
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.set_board(restored)
    assert page.tool_rail().badge_text(PANEL_UNPLACED) == str(len(restored.unplaced))
    assert not page.unplaced_tray().isVisible()
    assert ("order", "tray-restored") in [item.ref() for item in page.unplaced_tray().item_widgets()]


def test_tray_set_refs_skips_rebuild_when_signature_matches(qtbot):
    tray = UnplacedTray()
    qtbot.addWidget(tray)
    ref = make_ref("time", "tray-1")
    titles = {("time", "tray-1"): "道路输入"}
    tray.set_refs([ref], titles=titles, statuses={("time", "tray-1"): STATUS_STALE})
    first = tray.item_widgets()[0]
    tray.set_refs([ref], titles=titles, statuses={("time", "tray-1"): STATUS_STALE})
    assert tray.item_widgets()[0] is first
    tray.set_refs([ref], titles=titles, statuses={("time", "tray-1"): STATUS_ORPHANED})
    rebuilt = tray.item_widgets()[0]
    assert rebuilt is not first


def test_set_preview_and_status_noop_skips_projection(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    preview = FakePreview(ref=ref, image=_image(), title="道路输入")
    harness.page.set_preview(ref, preview)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    calls = []
    orig = harness.page._refresh_projection

    def counted():
        calls.append(1)
        orig()

    harness.page._refresh_projection = counted
    harness.page.set_preview(ref, preview)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    harness.page.apply_preview_and_status(ref, preview, STATUS_STALE, True)
    assert calls == []


def test_apply_preview_and_status_projects_once_when_changed(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    calls = []
    original = harness.page._refresh_free_grid_projection

    def counted():
        calls.append(1)
        original()

    harness.page._refresh_free_grid_projection = counted
    harness.page.apply_preview_and_status(
        ref,
        FakePreview(ref=ref, image=_image(), title="道路输入"),
        STATUS_STALE,
        True,
    )
    assert calls == [1]


def test_projection_batch_collapses_multiple_preview_updates(qtbot):
    harness = _Harness(qtbot)
    refs = [make_ref("time", f"time-{index}") for index in range(6)]
    for ref in refs:
        add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    calls = []
    original = harness.page._refresh_free_grid_projection

    def counted():
        calls.append(1)
        original()

    harness.page._refresh_free_grid_projection = counted
    with harness.page.projection_batch():
        with harness.page.projection_batch():
            for ref in refs:
                harness.page.apply_preview_and_status(
                    ref,
                    FakePreview(ref=ref, image=_image(), title=ref.view_id),
                    STATUS_STALE,
                    True,
                )
    assert calls == [1]


def test_projection_batch_delays_library_rows_until_exit(qtbot):
    harness = _Harness(qtbot)
    calls = []
    original = harness.page.library_panel().set_rows

    def counted(rows):
        calls.append(tuple(row.view_id for row in rows))
        original(rows)

    harness.page.library_panel().set_rows = counted
    with harness.page.projection_batch():
        harness.page.set_library_rows(_rows())
        assert calls == []
    assert calls == [tuple(row.view_id for row in _rows())]


def test_clear_runtime_caches_drops_preview_shadows(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    preview = FakePreview(ref=ref, image=_image(), title="道路输入")
    harness.page.set_preview(ref, preview)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    assert harness.page._previews
    harness.page.clear_runtime_caches()
    assert harness.page._previews == {}
    assert harness.page._statuses == {}
    assert harness.page._ref_exists == {}
    assert harness.page._status_for(ref) == STATUS_MISSING


def test_drop_event_copies_strings_before_mime_is_destroyed(qapp, qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    harness.page.set_board(harness.board)
    mime = _mime("time", "time-2")
    empty = harness.page.slot_widget("primary")
    event = _drop(mime)
    empty.dropEvent(event)
    assert harness.added == [("time", "time-2")]
    event._mime_ref = None
    del event
    sip.delete(mime)
    qapp.processEvents()
    assert harness.added == [("time", "time-2")]
    assert extract_ref_strings(make_ref_mime("fft", "x")) == ("fft", "x")
    bad = QMimeData()
    bad.setData(ULTRAVIEW_REF_MIME, QByteArray(b"not-json"))
    assert extract_ref_strings(bad) is None


def test_card_visual_properties_and_accessible_name(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    preview = FakePreview(
        ref=ref,
        image=_image(),
        title="道路输入",
        source_summary="A-Drive",
        axis_kind="time",
        captured_digest="abc",
    )
    harness.page.set_preview(ref, preview)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    card = harness.page.card_widget("time", "time-1")
    assert isinstance(card, UltraViewCard)
    card.selected.emit("time", "time-1")
    card = harness.page.card_widget("time", "time-1")
    assert card.property("selected") == "true"
    assert "源已变化" in card.accessibleName()
    assert "已选中" in card.accessibleName()
    assert "可同步" in card.accessibleName()
    sync_btn = card.findChild(QToolButton, "ultraViewCardSyncButton")
    assert sync_btn is not None
    assert sync_btn.isVisible()
    assert sync_btn.text() == "同步"

    harness.page.compare_rail()._buttons["frequency"].click()
    card = harness.page.card_widget("time", "time-1")
    assert card.property("dimmed") == "true"
    assert "已弱化" in card.accessibleName()
    effect = card.graphicsEffect()
    assert effect is not None
    assert effect.opacity() < 0.5

    harness.page.set_ref_status(ref, STATUS_ORPHANED, False)
    card = harness.page.card_widget("time", "time-1")
    assert card.property("orphaned") == "true"
    assert "源已删除" in card.accessibleName()
    assert card.findChild(QPushButton, "ultraViewCardRebindButton") is not None
    sync_btn = card.findChild(QToolButton, "ultraViewCardSyncButton")
    assert sync_btn is not None
    assert not sync_btn.isVisible()

    harness.page.arm_replacement("time", "time-1")
    card = harness.page.card_widget("time", "time-1")
    assert card.property("replacementArmed") == "true"
    assert "等待替换" in card.accessibleName()


def test_menu_double_click_and_keyboard_share_intents(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("fft", "fft-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="共振检查", axis_kind="frequency"),
    )
    card = harness.page.card_widget("fft", "fft-1")
    menu = card.make_context_menu()
    by_text = {action.text(): action for action in menu.actions()}
    by_text["打开原 View"].trigger()
    by_text["临时放大"].trigger()
    by_text["替换为…"].trigger()
    by_text["移到未放置"].trigger()
    by_text["复制本卡图像"].trigger()
    assert harness.opened == [("fft", "fft-1")]
    assert harness.focused == [("fft", "fft-1")]
    assert harness.armed == [("fft", "fft-1")]
    assert harness.unplaced == [("fft", "fft-1")]
    assert harness.copied_cards == [("fft", "fft-1")]
    harness.page.focus_layer().close_layer()
    harness.page.clear_replacement_arm()

    add_ref(harness.board, make_ref("frf", "frf-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("frf", "frf-1")
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QMouseEvent

    event = QMouseEvent(
        QEvent.MouseButtonDblClick,
        QPoint(8, 8),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    card.mouseDoubleClickEvent(event)
    assert ("frf", "frf-1") not in harness.focused
    assert harness.page.board_zoom() > 0.25

    card.mouseDoubleClickEvent(event)
    assert ("frf", "frf-1") in harness.focused
    assert harness.page.focus_layer().isVisible()
    card.mouseDoubleClickEvent(event)
    assert harness.page.focus_layer().isVisible()
    assert harness.focused[-1] == ("frf", "frf-1")

    card.setFocus()
    qtbot.keyClick(card, Qt.Key_Return)
    qtbot.keyClick(card, Qt.Key_O)
    qtbot.keyClick(card, Qt.Key_Delete)
    assert ("frf", "frf-1") in harness.opened
    assert ("frf", "frf-1") in harness.removed


def _dblclick(card) -> None:
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QMouseEvent

    event = QMouseEvent(
        QEvent.MouseButtonDblClick,
        QPoint(8, 8),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    card.mouseDoubleClickEvent(event)


def test_second_double_click_on_filled_card_opens_inspect_not_jitter(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "fill-0")
    del free
    _dblclick(card)
    assert harness.focused == []
    assert harness.page._filled_card == ("time", "fill-0")
    first_zoom = harness.page.board_zoom()
    _dblclick(card)
    assert harness.focused == [("time", "fill-0")]
    assert harness.page.focus_layer().isVisible()
    assert harness.page.board_zoom() == pytest.approx(first_zoom)
    _dblclick(card)
    assert harness.page.focus_layer().current_ref() == ("time", "fill-0")
    assert len(harness.focused) == 1


def test_filled_double_click_keeps_selection(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "sel-0")
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
    _dblclick(card)
    _dblclick(card)
    assert harness.page.selected_ref() == ("time", "sel-0")
    assert harness.page.focus_layer().isVisible()


def test_armed_replacement_blocks_inspect_on_filled_double_click(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "arm-0")
    _dblclick(card)
    harness.page.arm_replacement("time", "arm-0")
    _dblclick(card)
    assert harness.focused == []
    assert not harness.page.focus_layer().isVisible()
    assert harness.page.replacement_ref() == ("time", "arm-0")


def test_presentation_filled_double_click_opens_inspect(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "pres-0")
    harness.page.set_presentation_active(True)
    _dblclick(card)
    _dblclick(card)
    assert harness.page.is_presentation_active() is True
    assert harness.page.focus_layer().isVisible()
    assert harness.focused == [("time", "pres-0")]


def test_stale_card_sync_button_emits_page_intent(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="道路输入", captured_digest="old"),
    )
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    card = harness.page.card_widget("time", "time-1")
    assert isinstance(card, UltraViewCard)
    menu = card.make_context_menu()
    by_text = {action.text(): action for action in menu.actions()}
    assert "同步到最新" in by_text
    by_text["同步到最新"].trigger()
    assert harness.synced == [("time", "time-1")]
    sync_btn = card.findChild(QToolButton, "ultraViewCardSyncButton")
    assert sync_btn is not None and sync_btn.isVisible()
    QTest.mouseClick(sync_btn, Qt.LeftButton)
    assert harness.synced == [("time", "time-1"), ("time", "time-1")]
    harness.page.set_ref_status(ref, STATUS_MISSING, True)
    card = harness.page.card_widget("time", "time-1")
    menu = card.make_context_menu()
    assert "同步到最新" not in {action.text(): action for action in menu.actions()}
    sync_btn = card.findChild(QToolButton, "ultraViewCardSyncButton")
    assert sync_btn is not None
    assert not sync_btn.isVisible()


def test_sync_all_rail_emits_placed_and_unplaced_stale_refs(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "stale-a", "fresh-b")
    tray_ref = make_ref("time", "stale-tray")
    add_ref(harness.board, tray_ref)
    move_to_unplaced(harness.board, tray_ref)
    harness.page.set_board(harness.board)
    placed_stale = make_ref("time", "stale-a")
    placed_fresh = make_ref("time", "fresh-b")
    for ref, title in (
        (placed_stale, "过期甲"),
        (placed_fresh, "最新乙"),
        (tray_ref, "托盘过期"),
    ):
        harness.page.set_preview(
            ref,
            FakePreview(ref=ref, image=_image(), title=title, captured_digest="old"),
        )
    harness.page.set_ref_status(placed_stale, STATUS_STALE, True)
    harness.page.set_ref_status(placed_fresh, STATUS_FRESH, True)
    harness.page.set_ref_status(tray_ref, STATUS_STALE, True)

    rail = harness.page.tool_rail()
    button = rail.sync_all_button()
    assert rail.stale_count() == 2
    assert button.isEnabled()
    badge = rail.findChild(QLabel, "ultraViewRailSyncAllBadge")
    assert badge is not None and badge.isVisible()
    assert badge.text() == "2"
    QTest.mouseClick(button, Qt.LeftButton)
    assert harness.synced == [("time", "stale-a"), ("time", "stale-tray")]


def test_sync_all_rail_without_stale_emits_feedback(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "fresh-0")
    ref = make_ref("time", "fresh-0")
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="道路输入", captured_digest="now"),
    )
    harness.page.set_ref_status(ref, STATUS_FRESH, True)
    messages: list[str] = []
    harness.page.feedback_requested.connect(messages.append)
    rail = harness.page.tool_rail()
    assert rail.stale_count() == 0
    assert not rail.sync_all_button().isEnabled()
    harness.page._on_sync_all_requested()
    assert messages == ["没有需要更新的预览"]
    assert harness.synced == []


def test_focus_layer_caps_at_raw_100_percent_and_has_open_button(qtbot, qapp):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    preview = FakePreview(ref=ref, image=_image(24, 16), title="道路输入")
    harness.page.set_preview(ref, preview)
    harness.page._on_focus("time", "time-1")
    qapp.processEvents()
    layer = harness.page.focus_layer()
    assert layer.isVisible()
    button = layer.open_source_button()
    assert isinstance(button, QPushButton)
    assert button.text() == "打开原 View"
    shown = layer.displayed_pixmap_size()
    raw = layer.raw_image_size()
    assert shown.width() <= raw.width()
    assert shown.height() <= raw.height()
    assert shown.width() <= 24
    assert shown.height() <= 16
    button.click()
    assert harness.opened == [("time", "time-1")]
    qtbot.keyClick(layer, Qt.Key_Escape)
    assert not layer.isVisible()


def test_escape_clears_replacement_after_focus(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    harness.page.set_preview(ref, FakePreview(ref=ref, image=_image(), title="道路输入"))
    harness.page._on_focus("time", "time-1")
    harness.page.arm_replacement("time", "time-1")
    assert harness.page.focus_layer().isVisible()
    assert harness.page.replacement_slot() == "primary"
    harness.page.handle_escape()
    assert not harness.page.focus_layer().isVisible()
    assert harness.page.replacement_slot() == "primary"
    assert harness.page.active_panel() == PANEL_LIBRARY
    harness.page.handle_escape()
    assert harness.page.active_panel() is None
    assert harness.page.replacement_slot() == "primary"
    harness.page.handle_escape()
    assert harness.page.replacement_slot() is None


def test_escape_exits_presentation_after_focus_and_replacement(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    harness.page.set_preview(ref, FakePreview(ref=ref, image=_image(), title="道路输入"))
    harness.page._on_focus("time", "time-1")
    harness.page.arm_replacement("time", "time-1")
    harness.page.set_presentation_active(True)
    harness.page.handle_escape()
    assert not harness.page.focus_layer().isVisible()
    assert harness.page.is_presentation_active() is True
    harness.page.handle_escape()
    assert harness.page.replacement_slot() is None
    assert harness.page.is_presentation_active() is True
    harness.page.handle_escape()
    assert harness.page.is_presentation_active() is False
    assert harness.presentation == [False]


def test_compare_filter_and_axis_warnings_do_not_mutate_board(qtbot):
    harness = _Harness(qtbot)
    time_ref = make_ref("time", "time-1")
    fft_ref = make_ref("fft", "fft-1")
    add_ref(harness.board, time_ref)
    add_ref(harness.board, fft_ref)
    harness.page.set_board(harness.board)
    harness.page.set_preview(
        time_ref,
        FakePreview(ref=time_ref, image=_image(), axis_kind="time", x_unit="s", x_range=(0.0, 1.0)),
    )
    harness.page.set_preview(
        fft_ref,
        FakePreview(
            ref=fft_ref,
            image=_image(),
            axis_kind="frequency",
            x_unit="Hz",
            x_range=(0.0, 800.0),
        ),
    )
    before = board_to_payload(harness.board)
    harness.page.compare_rail()._buttons["frequency"].click()
    after = board_to_payload(harness.page.board())
    assert after == before
    assert harness.filters == ["frequency"]
    time_card = harness.page.card_widget("time", "time-1")
    fft_card = harness.page.card_widget("fft", "fft-1")
    assert time_card.property("dimmed") == "true"
    assert fft_card.property("dimmed") == "false"


def test_missing_copy_and_no_zero_jobs_badge(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("fft_time", "fft_time-1"))
    harness.page.set_board(harness.board)
    harness.page.set_ref_status(make_ref("fft_time", "fft_time-1"), STATUS_MISSING, True)
    card = harness.page.card_widget("fft_time", "fft_time-1")
    assert MISSING_CARD_COPY in card.findChild(QWidget, "ultraViewCardImage").text()
    texts = []
    for widget in harness.page.findChildren(QWidget):
        for attr in ("text", "accessibleName", "toolTip", "windowTitle"):
            getter = getattr(widget, attr, None)
            if callable(getter):
                texts.append(str(getter()))
    blob = "\n".join(texts)
    assert "0 JOBS" not in blob
    assert "0 jobs" not in blob.lower()
    assert "0 次计算" not in blob


def test_chrome_height_stays_readable_at_supported_window_sizes(qtbot, qapp):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.set_preview(
        make_ref("time", "time-1"),
        FakePreview(ref=make_ref("time", "time-1"), image=_image(), title="道路输入"),
    )
    heights = []
    for width, height in ((1600, 900), (1280, 800)):
        harness.page.resize(width, height)
        qapp.processEvents()
        card = harness.page.card_widget("time", "time-1")
        heights.append((card.header_height(), card.footer_height()))
        assert card.header_height() >= 24
        assert card.footer_height() >= 20
        assert card.header_height() + card.footer_height() >= MIN_CARD_CHROME_HEIGHT
    assert heights[0] == heights[1]


def test_hint_bar_exists_for_later_chart_stack_take(qtbot):
    harness = _Harness(qtbot)
    bar = harness.page.hint_bar()
    assert isinstance(bar, QWidget)
    assert bar.objectName() == "chartHintBar"
    assert bar.height() == 28
    assert "0 JOBS" not in bar.findChild(QWidget, "chartHintContext").text()


def test_replacement_armed_next_add_rebinds(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.arm_replacement("time", "time-1")
    harness.page.request_add("fft", "fft-1")
    assert harness.replaced == [("primary", "fft", "fft-1")]
    assert harness.page.replacement_slot() is None


def test_object_names_are_stable(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    assert page.objectName() == "ultraViewPage"
    assert page.library_panel().objectName() == "ultraViewLibrary"
    assert page.board_grid().objectName() == "ultraViewBoardGrid"
    assert page.board_scroll_area().objectName() == "ultraViewBoardScrollArea"
    assert page.board_switcher().objectName() == "ultraViewBoardSwitcher"
    assert page.board_overview().objectName() == "ultraViewBoardOverview"
    assert page.unplaced_tray().objectName() == "ultraViewUnplacedTray"
    assert page.compare_rail().objectName() == "ultraViewCompareRail"
    assert page.board_toolbar().objectName() == "ultraViewBoardToolbar"
    toolbar = page.board_toolbar()
    assert toolbar.findChild(QToolButton, "ultraViewDisplayButton") is not None
    assert toolbar.findChild(QPushButton, "ultraViewCopyBoardButton") is not None
    assert toolbar.findChild(QPushButton, "ultraViewBoardOverviewButton") is not None
    assert toolbar.findChild(QPushButton, "ultraViewAddButton") is None
    assert toolbar.findChild(QToolButton, "ultraViewRatioDown") is None
    assert toolbar.findChild(QToolButton, "ultraViewRatioUp") is None
    assert page.focus_layer().objectName() == "ultraViewFocusLayer"


def test_board_name_is_keyboard_editable(qtbot):
    harness = _Harness(qtbot)
    names = []
    harness.page.board_name_changed.connect(names.append)
    edit = harness.page.board_toolbar().board_name_edit()
    edit.setText("整车问题总览")
    edit.editingFinished.emit()
    assert names == ["整车问题总览"]


def test_show_titles_and_sources_hide_chrome_without_empty_band(qtbot, qapp):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.board.show_titles = False
    harness.board.show_sources = False
    harness.page.set_preview(
        make_ref("time", "time-1"),
        FakePreview(ref=make_ref("time", "time-1"), image=_image(), title="道路输入"),
    )
    harness.page.set_board(harness.board)
    qapp.processEvents()
    card = harness.page.card_widget("time", "time-1")
    assert card._title.isVisible() is False
    assert card.footer_height() == 0
    assert "道路输入" in card.accessibleName()


def test_board_toolbar_display_menu_emits_show_flags(qtbot):
    harness = _Harness(qtbot)
    titles = []
    sources = []
    harness.page.show_titles_toggled.connect(titles.append)
    harness.page.show_sources_toggled.connect(sources.append)
    toolbar = harness.page.board_toolbar()
    toolbar._act_titles.setChecked(False)
    toolbar._act_sources.setChecked(False)
    assert titles == [False]
    assert sources == [False]
    harness.board.show_titles = False
    harness.board.show_sources = True
    harness.page.set_board(harness.board)
    assert toolbar._act_titles.isChecked() is False
    assert toolbar._act_sources.isChecked() is True


def test_presentation_restores_visible_global_edit_controls(qtbot):
    harness = _Harness(qtbot)
    global_island = harness.page.global_island()
    rail = harness.page.tool_rail()
    assert global_island.display_button().isVisible() is True
    assert rail.isVisible() is True
    harness.page.set_presentation_active(True)
    assert global_island.display_button().isVisible() is False
    assert rail.isVisible() is False
    harness.page.set_presentation_active(False)
    assert global_island.display_button().isVisible() is True
    assert rail.isVisible() is True


def test_live_card_chrome_prefers_library_over_stale_preview(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="旧预览名", tab_color="#111111"),
    )
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card.model().title == "道路输入"
    assert card.model().tab_color == "#2d7ff9"


def test_orphaned_card_chrome_prefers_preview_record(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="孤儿旧名", tab_color="#abcdef"),
    )
    harness.page.set_ref_status(ref, STATUS_ORPHANED, False)
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card.model().title == "孤儿旧名"
    assert card.model().tab_color == "#abcdef"


def test_orphan_rebind_via_replacement_arm_removes_orphan_from_placed(qtbot):
    harness = _Harness(qtbot)
    orphan = make_ref("time", "time-1")
    add_ref(harness.board, orphan)
    harness.page.set_board(harness.board)
    harness.page.set_ref_status(orphan, STATUS_ORPHANED, False)
    harness.page.arm_replacement("time", "time-1")
    harness.page.request_add("fft", "fft-1")
    assert harness.rebound == [("time", "time-1", "fft", "fft-1")]
    assert harness.replaced == []
    assert orphan not in membership_set(harness.board)
    assert make_ref("fft", "fft-1") in membership_set(harness.board)
    assert harness.page.replacement_ref() is None


def test_orphan_rebind_from_tray_removes_old_ref(qtbot):
    harness = _Harness(qtbot)
    orphan = make_ref("time", "time-1")
    add_ref(harness.board, orphan)
    move_to_unplaced(harness.board, orphan)
    harness.page.set_board(harness.board)
    harness.page.set_ref_status(orphan, STATUS_ORPHANED, False)
    harness.page.arm_replacement("time", "time-1")
    assert harness.page.replacement_slot() is None
    assert harness.page.replacement_ref() == ("time", "time-1")
    harness.page.request_add("fft", "fft-1")
    assert harness.rebound == [("time", "time-1", "fft", "fft-1")]
    assert orphan not in membership_set(harness.board)
    assert make_ref("fft", "fft-1") in membership_set(harness.board)
    assert harness.replaced == []


def test_escape_cancels_rebind_arm_without_board_mutation(qtbot):
    harness = _Harness(qtbot)
    orphan = make_ref("time", "time-1")
    add_ref(harness.board, orphan)
    harness.page.set_board(harness.board)
    harness.page.set_ref_status(orphan, STATUS_ORPHANED, False)
    harness.page.arm_replacement("time", "time-1")
    assert harness.page.replacement_ref() == ("time", "time-1")
    members = set(membership_set(harness.board))
    harness.page.handle_escape()
    assert harness.page.active_panel() is None
    assert harness.page.replacement_ref() == ("time", "time-1")
    harness.page.handle_escape()
    assert harness.page.replacement_ref() is None
    assert harness.page.replacement_slot() is None
    assert membership_set(harness.board) == members
    assert harness.rebound == []
    assert harness.replaced == []


def _gutter_point(grid) -> QPoint:
    content = (
        BOARD_PADDING,
        BOARD_PADDING,
        max(0, grid.width() - 2 * BOARD_PADDING),
        max(0, grid.height() - 2 * BOARD_PADDING),
    )
    rects = slot_rects(grid.layout_id(), content, grid._ratio)
    first, second = list(rects.values())[:2]
    ax, ay, aw, ah = first
    bx, by, _bw, _bh = second
    if bx >= ax + aw:
        gx = ax + aw + max(1, (bx - ax - aw) // 2)
        gy = ay + max(1, ah // 2)
    else:
        gx = ax + max(1, aw // 2)
        gy = ay + ah + max(1, (by - ay - ah) // 2)
    return QPoint(int(gx), int(gy))


@pytest.mark.parametrize("layout_id", tuple(LAYOUT_SLOTS))
def test_empty_slot_click_places_into_clicked_slot(qtbot, layout_id):
    """UVL-A01: empty-slot click keeps slot X; first_empty_slot must not win."""
    harness = _Harness(qtbot)
    set_layout(harness.board, layout_id)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    slots = LAYOUT_SLOTS[layout_id]
    clicked = slots[-1]
    assert slot_occupant(harness.board, slots[0]) == make_ref("time", "time-1")
    if len(slots) > 2:
        assert first_empty_slot(harness.board) != clicked
    harness.page.library_panel().set_selected("fft", "fft-1")
    empty = harness.page.slot_widget(clicked)
    empty.add_clicked.emit(clicked)
    assert harness.replaced == [(clicked, "fft", "fft-1")]
    assert harness.added == []
    assert slot_occupant(harness.board, clicked) == make_ref("fft", "fft-1")
    assert slot_occupant(harness.board, slots[0]) == make_ref("time", "time-1")


def test_empty_slot_click_while_tray_armed_uses_clicked_slot(qtbot):
    """UVL-A01: tray-armed replacement has no slot; the clicked empty slot is the target."""
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    move_to_unplaced(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.arm_replacement("time", "time-1")
    assert harness.page.replacement_slot() is None
    assert harness.page.replacement_ref() == ("time", "time-1")
    harness.page.library_panel().set_selected("fft", "fft-1")
    harness.page._on_empty_slot("aux_1")
    assert harness.replaced == [("aux_1", "fft", "fft-1")]
    assert harness.added == []
    assert slot_occupant(harness.board, "aux_1") == make_ref("fft", "fft-1")
    assert harness.page.replacement_ref() is None
    assert harness.page.replacement_slot() is None


def test_empty_slot_click_while_board_armed_keeps_armed_slot(qtbot):
    """UVL-A01: a board-armed slot is not retargeted by clicking a different empty slot."""
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.arm_replacement("time", "time-1")
    assert harness.page.replacement_slot() == "primary"
    harness.page.library_panel().set_selected("fft", "fft-1")
    harness.page._on_empty_slot("aux_2")
    assert harness.replaced == [("primary", "fft", "fft-1")]
    assert slot_occupant(harness.board, "primary") == make_ref("fft", "fft-1")
    assert slot_occupant(harness.board, "aux_2") is None


def test_drop_on_board_padding_or_gutter_is_noop(qtbot, qapp):
    """UVL-A02: drop on BOARD_PADDING or slot gutter must not emit board intents."""
    harness = _Harness(qtbot)
    qapp.processEvents()
    grid = harness.page.board_grid()
    dropped = []

    def _capture_drop(slot, section, view_id):
        dropped.append((slot, section, view_id))

    grid.ref_dropped.connect(_capture_drop)
    padding = QPoint(1, 1)
    gutter = _gutter_point(grid)
    assert 0 <= padding.x() < BOARD_PADDING
    assert SLOT_GUTTER >= 1
    assert grid.slot_id_at(padding) is None
    assert grid.slot_id_at(gutter) is None
    mime = _mime("fft", "fft-1")
    grid.dropEvent(_drop(mime, padding))
    grid.dropEvent(_drop(mime, gutter))
    assert dropped == []
    assert harness.added == []
    assert harness.replaced == []
    assert harness.swapped == []
    assert harness.placed == []


def test_empty_slot_and_card_drop_active_until_leave_or_drop(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    harness.page.set_board(harness.board)
    empty = harness.page.slot_widget("aux_0")
    mime = _mime("fft", "fft-1")
    empty.dragEnterEvent(_enter(mime))
    assert _is_drop_active(empty) is True
    empty.dragLeaveEvent(_leave())
    assert _is_drop_active(empty) is False

    empty.dragEnterEvent(_enter(mime))
    assert _is_drop_active(empty) is True
    empty.dropEvent(_drop(mime))
    if not sip.isdeleted(empty):
        assert _is_drop_active(empty) is False

    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    replace_mime = _mime("order", "order-1")
    card.dragEnterEvent(_enter(replace_mime))
    assert _is_drop_active(card) is True
    card.dragLeaveEvent(_leave())
    assert _is_drop_active(card) is False
    card.dragEnterEvent(_enter(replace_mime))
    card.dropEvent(_drop(replace_mime))
    assert _is_drop_active(card) is False


def test_card_focus_button_fits_inside_rounded_chrome(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.resize(1600, 900)
    qapp.processEvents()
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    bar = card.action_bar()
    assert bar is not None and bar.isVisible()
    assert bar.objectName() == "ultraViewCardActionBar"
    mapped = QRect(bar.mapTo(card, QPoint(0, 0)), bar.size())
    assert card.rect().adjusted(1, 1, -1, -1).contains(mapped)
    assert mapped.top() >= 2
    assert mapped.right() <= card.width() - 4
    assert mapped.bottom() <= card.header_height()
    for action in ("open", "focus", "fit", "remove", "more"):
        button = card.action_button(action)
        assert button is not None
        assert button.isVisible()
        assert button.text() == ""
        assert button.toolTip()
        assert button.accessibleName()
        assert button.focusPolicy() == Qt.TabFocus
        assert not button.icon().isNull()
        assert button.width() == 22
        assert button.height() == 22
    assert harness.page.card_context_island().isHidden()


def test_card_swap_clears_replacement_arm_then_add_is_pure(qtbot):
    """UVL-A03: card-drag swap is not an armed completion; later add is a pure add."""
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    add_ref(harness.board, make_ref("fft", "fft-1"))
    harness.page.set_board(harness.board)
    harness.page.arm_replacement("time", "time-1")
    harness.page._drag_kind = "card"
    harness.page._on_ref_dropped("aux_0", "time", "time-1")
    assert harness.swapped == [("primary", "aux_0")]
    assert harness.page.replacement_slot() is None
    assert harness.page.replacement_ref() is None
    harness.page.request_add("order", "order-1")
    assert harness.added == [("order", "order-1")]
    assert harness.replaced == []
    assert slot_occupant(harness.board, "aux_1") == make_ref("order", "order-1")


def test_tray_place_drop_clears_replacement_arm_then_add_is_pure(qtbot):
    """UVL-A03: tray drop onto an empty slot clears arm; later add is a pure add."""
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    move_to_unplaced(harness.board, make_ref("time", "time-1"))
    add_ref(harness.board, make_ref("fft", "fft-1"))
    harness.page.set_board(harness.board)
    harness.page.arm_replacement("fft", "fft-1")
    harness.page._drag_kind = "tray"
    harness.page._on_ref_dropped("aux_0", "time", "time-1")
    assert harness.placed == [("aux_0", "time", "time-1")]
    assert harness.page.replacement_slot() is None
    assert harness.page.replacement_ref() is None
    harness.page.request_add("order", "order-1")
    assert harness.added == [("order", "order-1")]
    assert harness.replaced == []
    assert slot_occupant(harness.board, "primary") == make_ref("fft", "fft-1")
    assert slot_occupant(harness.board, "aux_1") == make_ref("order", "order-1")


def test_board_full_tray_place_emits_feedback(qtbot):
    """UVL-A04: tray place on a full board emits visible Board-full feedback."""
    harness = _Harness(qtbot)
    messages = []
    harness.page.feedback_requested.connect(messages.append)
    set_layout(harness.board, "hero_left_4")
    harness.fill_board(4)
    add_ref(harness.board, make_ref("fft", "overflow-1"))
    harness.page.set_board(harness.board)
    assert first_empty_slot(harness.board) is None
    harness.page._on_tray_place("fft", "overflow-1")
    assert harness.placed == []
    assert len(messages) == 1
    assert "已满" in messages[0]
    assert "换布局" in messages[0]
    assert "移除" in messages[0]


def test_add_without_library_selection_emits_feedback(qtbot):
    """UVL-A04: toolbar add / empty-slot click with no library selection asks to pick a View."""
    harness = _Harness(qtbot)
    messages = []
    harness.page.feedback_requested.connect(messages.append)
    assert harness.page.library_panel().selected_ref() is None
    harness.page._on_toolbar_add()
    harness.page._on_empty_slot("aux_0")
    assert harness.added == []
    assert harness.replaced == []
    assert messages == ["先打开 View 库并选择一个 View"] * 2


def test_large_grid_uses_logical_canvas_and_scrolls_without_misplacing_cards(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_4x3")
    for index in range(12):
        add_ref(harness.board, make_ref("time", f"large-{index}"))
    harness.page.set_board(harness.board)
    harness.page.resize(1000, 720)
    qtbot.wait(10)
    scroll = harness.page.board_scroll_area()
    grid = harness.page.board_grid()
    assert grid.width() > scroll.viewport().width()
    assert scroll.horizontalScrollBar().maximum() > 0
    card = harness.page.card_widget("time", "large-11")
    assert card is not None
    scroll.ensureWidgetVisible(card)
    assert scroll.horizontalScrollBar().value() > 0
    point = card.geometry().center()
    assert grid.slot_id_at(point) == "r2c3"


def test_free_grid_projects_cards_preserves_scroll_and_emits_keyboard_geometry(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_3x2")
    for index in range(6):
        add_ref(harness.board, make_ref("time", f"free-{index}"))
    template_to_free_grid(harness.board)
    harness.page.set_board(harness.board)
    harness.page.resize(1000, 720)
    qtbot.wait(10)
    free = harness.page._free_grid
    scroll = harness.page.board_scroll_area()
    assert free.width() > scroll.viewport().width()
    assert scroll.horizontalScrollBar().maximum() > 0
    assert harness.page.free_grid_minimap().isVisible()
    assert not harness.page.free_grid_minimap()._placements[0].ref.view_id == ""
    card = harness.page.card_widget("time", "free-0")
    assert card is not None
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    card.layout_key_requested.emit("time", "free-0", 0, 6, False)
    assert requested == [("time", "free-0", 0, 6, 4, 3, "keyboard-move")]
    harness.page.show_overview()
    overview = harness.page.board_overview()
    assert overview.isVisible()
    assert overview._free_metrics is not None
    harness.page._on_overview_ref("time", "free-5")
    assert not overview.isVisible()


def test_board_overview_click_returns_to_reading_slot(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_3x3")
    for index in range(9):
        add_ref(harness.board, make_ref("time", f"overview-{index}"))
    harness.page.set_board(harness.board)
    harness.page.resize(1000, 720)
    harness.page.show_overview()
    qtbot.wait(10)
    overview = harness.page.board_overview()
    assert overview.isVisible()
    slot = harness.page.slot_widget("r2c2")
    assert slot is not None
    harness.page._on_overview_slot("r2c2")
    assert not overview.isVisible()
    assert harness.page.board_scroll_area().horizontalScrollBar().value() > 0
    scroll = harness.page.board_scroll_area()
    assert scroll.viewport().rect().contains(
        slot.mapTo(scroll.viewport(), slot.rect().center())
    )


def test_board_switcher_projects_ids_and_emits_typed_intents(qtbot):
    one = default_board()
    one.board_id = "one"
    one.name = "第一条问题线"
    two = default_board()
    two.board_id = "two"
    two.name = "第二条问题线"
    switcher = BoardSwitcher()
    qtbot.addWidget(switcher)
    switcher.resize(320, 40)
    switcher.show()
    selected = []
    reordered = []
    created = []
    switcher.board_selected.connect(selected.append)
    switcher.reorder_requested.connect(lambda board_id, index: reordered.append((board_id, index)))
    switcher.create_requested.connect(lambda: created.append(True))
    switcher.set_boards([one, two], "one")
    assert switcher.board_ids() == ("one", "two")
    assert switcher.current_board_id() == "one"
    switcher.tab_bar().setCurrentIndex(1)
    assert selected == ["two"]
    switcher.tab_bar().moveTab(1, 0)
    assert reordered == [("two", 0)]
    qtbot.mouseClick(switcher.add_button(), Qt.LeftButton)
    assert created == [True]


def test_library_rebuild_is_deferred_until_drag_finishes(qtbot):
    """Drop refresh must not deleteLater the library row still inside QDrag.exec_."""
    harness = _Harness(qtbot)
    source = harness.page.library_panel().row_widgets()[0]
    assert not sip.isdeleted(source)
    harness.page._on_drag_started("library")
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_library_rows(_rows())
    harness.page.set_board(harness.board)
    assert not sip.isdeleted(source)
    assert source is harness.page.library_panel().row_widgets()[0]
    harness.page._on_drag_finished()
    qtbot.wait(20)
    rebuilt = harness.page.library_panel().row_widgets()
    assert source not in rebuilt
    assert sip.isdeleted(source)


def test_card_rebuild_is_deferred_until_drag_finishes(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    harness.page._on_drag_started("card")
    move_to_unplaced(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    assert not sip.isdeleted(card)
    assert harness.page.card_widget("time", "time-1") is card
    harness.page._on_drag_finished()
    qtbot.wait(20)
    assert harness.page.card_widget("time", "time-1") is None
    assert sip.isdeleted(card)


def test_free_grid_drop_clamps_span_inside_safety_bounds(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref("time", "time-1"))
    template_to_free_grid(harness.board)
    harness.page.set_board(harness.board)
    free = harness.page._free_grid
    span = harness.board.free_grid[0].rect
    pos = QPoint(max(0, free.width() - 2), 20)
    column, row = free._grid_at(pos, column_span=span.column_span, row_span=span.row_span)
    legal = legal_grid_rect(
        (pos.x(), pos.y()),
        free.metrics(),
        column_span=span.column_span,
        row_span=span.row_span,
    )
    assert (column, row) == (legal.column, legal.row)
    clamped = GridRect(column, row, span.column_span, span.row_span)
    assert clamp_rect(clamped) == clamped
    assert clamp_rect(clamped) == _legal_grid_rect(clamped)
    # The canonical 12×48 base frame is a scale reference, not a drag wall.
    # The widget can project its session extent well past it, but its resolver
    # still cannot emit a rect beyond the engineering guard.
    assert column + span.column_span <= SAFETY_COLUMN_MAX
    assert row + span.row_span <= SAFETY_ROW_MAX


def test_hidden_overview_defers_compose_until_shown(qtbot):
    harness = _Harness(qtbot)
    overview = harness.page.board_overview()
    assert not overview.isVisible()
    assert overview._image.isNull()
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    assert overview._image.isNull()
    harness.page.show_overview()
    assert overview.isVisible()
    assert not overview._image.isNull()


def test_clearing_preview_pixels_drops_card_raw_image(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    harness.page.set_board(harness.board)
    harness.page.set_preview(ref, FakePreview(ref, image=_image()))
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    assert card._raw_image is not None
    harness.page.set_preview(ref, FakePreview(ref, image=None))
    assert card._raw_image is None


def test_free_grid_alt_arrow_uses_real_key_event(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "key-0"))
    template_to_free_grid(harness.board)
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "key-0")
    assert card is not None
    card.setFocus(Qt.OtherFocusReason)
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    qtbot.keyClick(card, Qt.Key_Right, Qt.AltModifier)
    assert requested
    assert requested[0][0] == "time"
    assert requested[0][1] == "key-0"
    assert requested[0][6] == "keyboard-move"


def _prepare_free_grid(harness, qtbot, *view_ids):
    set_layout(harness.board, "grid_2x2")
    for view_id in view_ids:
        add_ref(harness.board, make_ref("time", view_id))
    template_to_free_grid(harness.board)
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    free = harness.page._free_grid
    cards = [harness.page.card_widget("time", view_id) for view_id in view_ids]
    assert all(card is not None and card.width() > 20 for card in cards)
    return free, cards


def _send_mouse_move(
    widget, pos: QPoint, buttons=Qt.LeftButton, modifiers=Qt.NoModifier
) -> None:
    # QTest.mouseMove() is cursor-based and a no-op on offscreen; send the same
    # QMouseEvent through the widget so press/move/release stay a real sequence.
    event = QMouseEvent(
        QEvent.MouseMove,
        pos,
        widget.mapToGlobal(pos),
        Qt.NoButton,
        buttons,
        modifiers,
    )
    QApplication.sendEvent(widget, event)


def _drag_card(
    card,
    start: QPoint,
    end: QPoint,
    *,
    release: bool = True,
    modifiers=Qt.NoModifier,
) -> None:
    QTest.mousePress(card, Qt.LeftButton, modifiers, start)
    QTest.mouseMove(card, end)
    _send_mouse_move(card, end, modifiers=modifiers)
    if release:
        QTest.mouseRelease(card, Qt.LeftButton, modifiers, end)


def _select_card(card) -> None:
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))


def _size_submenu(menu: QMenu) -> QMenu:
    for action in menu.actions():
        if action.text() == "自由网格尺寸" and action.menu() is not None:
            return action.menu()
    raise AssertionError("missing 自由网格尺寸 submenu")


def _assert_rounded_menu_shell(menu: QMenu) -> None:
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    flags = menu.windowFlags()
    assert bool(flags & Qt.NoDropShadowWindowHint)
    assert bool(flags & Qt.FramelessWindowHint)


def test_free_grid_size_context_submenu_uses_rounded_popup_shell(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "size-ctx")
    menu = card.make_context_menu()
    _assert_rounded_menu_shell(menu)
    _assert_rounded_menu_shell(_size_submenu(menu))


def test_free_grid_size_overflow_submenu_uses_rounded_popup_shell(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "size-more")
    captured: list[QMenu] = []

    def _fake_exec(self, *args, **kwargs):
        captured.append(self)
        return None

    monkeypatch.setattr(QMenu, "exec_", _fake_exec)
    harness.page._show_card_more_menu("time", "size-more")
    assert captured
    _assert_rounded_menu_shell(captured[0])
    _assert_rounded_menu_shell(_size_submenu(captured[0]))


def _east_handle_pos(card) -> QPoint:
    return QPoint(max(0, card.width() - 4), max(0, card.height() // 2))


def test_press_on_type_chip_still_arms_the_drag_gesture(qtbot):
    """§4.3: the header's type chip must not create a drag dead zone.

    Real mouse hit-testing resolves to whichever widget ``childAt`` finds at
    the click position; before the fix the chip (a ``QToolButton``) sat
    there and consumed the press without it ever reaching the card, so a
    press on the chip's strip of the header (left ~22-97px) could never arm
    a card drag.
    """
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "chip-0")
    chip = card._type_chip
    assert chip.isVisible()
    chip_center_global = chip.mapToGlobal(chip.rect().center())
    local_in_card = card.mapFromGlobal(chip_center_global)
    # This is exactly what real Qt hit-testing resolves to for a click at
    # the chip's on-screen position: skip it once WA_TransparentForMouseEvents
    # is set, land on it (swallowing the press) beforehand.
    target = card.childAt(local_in_card)
    assert target is not None
    local = target.mapFromGlobal(chip_center_global)

    QTest.mousePress(target, Qt.LeftButton, Qt.NoModifier, local)
    assert free.gesture().is_armed()
    QTest.mouseRelease(target, Qt.LeftButton, Qt.NoModifier, local)
    assert not free.gesture().is_armed()


def test_free_grid_click_within_threshold_does_not_move(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "click-0")
    requested = []
    selected = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    card.selected.connect(lambda section, view_id: selected.append((section, view_id)))
    start = QPoint(12, 12)
    stay = max(1, QApplication.startDragDistance() - 1)
    _drag_card(card, start, QPoint(start.x() + stay, start.y()))
    assert selected == [("time", "click-0")]
    assert requested == []
    assert not free.gesture().is_armed()
    assert free.ghost_overlay()._handles_rect is not None
    assert free.ghost_overlay()._ghost_rect is None


def test_free_grid_drag_past_threshold_shows_ghost_and_commits_legal_move(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "move-0")
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    mid = QPoint(start.x() + unit * 6, start.y())
    _drag_card(card, start, mid, release=False)
    assert free.gesture().is_active()
    assert free.ghost_overlay().is_showing()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, mid)
    assert requested == [("time", "move-0", 6, 0, 6, 3, "drag-move")]
    assert not free.gesture().is_armed()
    assert free.ghost_overlay()._ghost_rect is None
    assert free.ghost_overlay()._handles_rect is not None


def test_free_grid_overlap_drop_moves_blocker_without_modal(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card, other) = _prepare_free_grid(harness, qtbot, "block-0", "block-1")
    boxes = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: boxes.append(a) or QMessageBox.Yes
    )
    group = []
    requested = []
    toasts = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    mid = QPoint(16 + unit * 6, 16)
    _drag_card(card, start, mid, release=False)
    overlay = free.ghost_overlay()
    assert overlay.is_showing()
    assert overlay._legal is True
    assert overlay._reject_mark is False
    assert len(overlay._highlights) == 2
    ghost_geoms = [
        (item.x(), item.y(), item.width(), item.height()) for item in overlay._highlights
    ]
    session = free.gesture().session()
    assert session is not None and session.plan is not None
    planned = [
        (rect.column, rect.row, rect.column_span, rect.row_span)
        for _ref, rect in session.plan.preview_rects()
    ]
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, mid)
    assert boxes == []
    assert requested == []
    assert group == [
        (
            ("time", "block-0", 6, 0, 6, 3),
            ("time", "block-1", 12, 0, 6, 3),
        )
    ]
    assert toasts == [format_rearranged(2)]
    committed = [(6, 0, 6, 3), (12, 0, 6, 3)]
    assert planned == committed
    assert len(ghost_geoms) == 2


def test_drag_over_neighbour_and_back_leaves_no_dim_behind(qtbot):
    """Dragging across a neighbour and back to the original cell must not leave the
    neighbour at drag opacity: the dim set is recomputed every move, so it has to be
    undimmed incrementally and cleared unconditionally on release
    (review 2026-08-15 §4.3 dim 泄漏)."""
    harness = _Harness(qtbot)
    free, (card, other) = _prepare_free_grid(harness, qtbot, "dim-0", "dim-1")
    requested = []
    group = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    over = QPoint(start.x() + unit * 6, start.y())
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, start)
    _send_mouse_move(card, over)
    assert free.gesture().is_active()
    assert other.graphicsEffect() is not None, "the displaced neighbour is previewed"
    _send_mouse_move(card, start)
    session = free.gesture().session()
    assert session is not None and session.plan is not None
    assert [ref for ref, _rect in session.plan.preview_rects()] == [
        make_ref("time", "dim-0")
    ]
    assert other.graphicsEffect() is None, (
        "the neighbour left the plan, so its dim must be dropped on the same frame"
    )
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, start)
    assert requested == [] and group == []
    assert other.graphicsEffect() is None
    assert card.graphicsEffect() is None
    assert free._dimmed_refs == set()


def test_cancelled_drag_restores_every_dimmed_card(qtbot):
    """Esc is the path where nothing re-applies the model, so the board's own dim
    bookkeeping is the only thing that can undo it."""
    harness = _Harness(qtbot)
    free, (card, other) = _prepare_free_grid(harness, qtbot, "esc-dim-0", "esc-dim-1")
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, start)
    _send_mouse_move(card, QPoint(start.x() + unit * 6, start.y()))
    assert other.graphicsEffect() is not None
    assert free.cancel_gesture() is True
    assert other.graphicsEffect() is None
    assert card.graphicsEffect() is None
    assert free._dimmed_refs == set()


def test_free_grid_overlap_drop_does_not_construct_message_box(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card, _other) = _prepare_free_grid(harness, qtbot, "spy-0", "spy-1")
    seen = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: seen.append(("question", a)) or QMessageBox.Yes
    )
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: seen.append(("warning", a)) or QMessageBox.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: seen.append(("info", a)) or QMessageBox.Ok
    )
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    _drag_card(card, QPoint(16, 16), QPoint(16 + unit * 6, 16))
    assert seen == []


def test_free_grid_overlap_past_base_frame_rearranges_without_modal(qtbot):
    harness = _Harness(qtbot)
    ids = tuple(f"pack-{index}" for index in range(6))
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(make_ref("time", view_id), GridRect(0, index * 8, 12, 8))
        for index, view_id in enumerate(ids)
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    free = harness.page._free_grid
    card = harness.page.card_widget("time", "pack-0")
    assert card is not None and card.width() > 20
    group = []
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = free.metrics().row_height + free.metrics().gutter
    _drag_card(card, QPoint(16, 16), QPoint(16, 16 + unit))
    assert group == [
        (
            ("time", "pack-0", 0, 1, 12, 8),
            ("time", "pack-1", 0, 48, 12, 8),
        )
    ]
    assert toasts == [
        format_rearranged(2),
        uv_widgets.FEEDBACK_DISPLACED_OFFSCREEN,
    ]


def test_displacing_a_card_out_of_the_viewport_hints_and_logs(qtbot, caplog):
    """Blockers slide along the drag axis (spec D9.3, 2026-08-15 annotation), so a
    pushed card can land below everything on screen.  Scroll follow is out of
    scope; saying so is not (review 2026-08-15 §4.3 blocker 落点)."""
    harness = _Harness(qtbot)
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(make_ref("time", "far-0"), GridRect(0, 0, 12, 8)),
        FreeGridPlacement(make_ref("time", "far-1"), GridRect(0, 8, 12, 8)),
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    free = harness.page._free_grid
    visible = free._visible_board_rect()
    assert not visible.isEmpty()
    toasts = []
    harness.page.feedback_requested.connect(toasts.append)
    with caplog.at_level(logging.INFO, logger=uv_widgets.__name__):
        assert (
            free._request_geometry(
                make_ref("time", "far-0"), GridRect(0, 8, 12, 8), "keyboard-move"
            )
            is True
        )
    pushed = QRect(
        *rect_to_pixels(
            GridRect(0, 16, 12, 8),
            free.metrics(),
            free._workspace_origin_offset(),
        )
    )
    assert not visible.intersects(pushed)
    assert uv_widgets.FEEDBACK_DISPLACED_OFFSCREEN in toasts
    assert any(
        "outside the viewport" in record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.INFO
    )


def test_displacement_inside_the_viewport_stays_quiet(qtbot):
    harness = _Harness(qtbot)
    free, (card, _other) = _prepare_free_grid(harness, qtbot, "near-0", "near-1")
    toasts = []
    harness.page.feedback_requested.connect(toasts.append)
    assert (
        free._request_geometry(
            make_ref("time", "near-0"), GridRect(6, 0, 6, 3), "keyboard-move"
        )
        is True
    )
    assert toasts == [format_rearranged(2)]


def test_search_budget_reject_has_its_own_copy_and_a_warning_trace(qtbot, monkeypatch, caplog):
    """"The planner gave up" and "it does not fit" are different facts, and the
    give-up must leave a trace (review 2026-08-15 P1-4: both mapped to the same
    sentence and only ``logger.debug``)."""
    harness = _Harness(qtbot)
    free, (card, _other) = _prepare_free_grid(harness, qtbot, "cap-0", "cap-1")
    ref = make_ref("time", "cap-0")
    starved = LayoutPlan(
        accepted=False,
        reason=LayoutRejectReason.SEARCH_CAP,
        mover_before=free._placements[ref].rect,
        mover_after=free._placements[ref].rect,
        displaced_before_after=(),
        operation=LAYOUT_MOVE,
        based_on_layout_revision=free._layout_revision,
        mover_ref=ref,
        search_visits=768,
    )
    monkeypatch.setattr(uv_widgets, "plan_layout", lambda *args, **kwargs: starved)
    toasts = []
    requested = []
    harness.page.feedback_requested.connect(toasts.append)
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    monkeypatch.setattr(uv_widgets, "_PLANNER_LOG_MONO", 0.0, raising=False)
    with caplog.at_level(logging.DEBUG, logger=uv_widgets.__name__):
        assert (
            free._request_geometry(ref, GridRect(6, 6, 2, 2), "keyboard-move") is False
        )
    assert requested == []
    assert toasts == [uv_widgets.FEEDBACK_SEARCH_BUDGET]
    assert uv_widgets.FEEDBACK_SEARCH_BUDGET != FEEDBACK_NO_LEGAL_LAYOUT
    warnings = [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ]
    assert warnings, "a blown search budget must not be a debug-only event"
    assert "search_cap" in warnings[0].getMessage()


def test_reject_reasons_map_to_distinct_user_copy():
    assert uv_widgets._reject_feedback(LayoutRejectReason.OUT_OF_BOUNDS) == FEEDBACK_OUT_OF_GRID
    assert (
        uv_widgets._reject_feedback(LayoutRejectReason.NO_LEGAL_LAYOUT)
        == FEEDBACK_NO_LEGAL_LAYOUT
    )
    assert (
        uv_widgets._reject_feedback(LayoutRejectReason.SEARCH_CAP)
        == uv_widgets.FEEDBACK_SEARCH_BUDGET
    )
    assert uv_widgets._reject_feedback(None) == FEEDBACK_NO_LEGAL_LAYOUT


def test_free_grid_escape_cancels_active_move_without_commit(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "esc-0")
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    mid = QPoint(start.x() + unit * 6, start.y())
    _drag_card(card, start, mid, release=False)
    assert free.gesture().is_active()
    assert harness.page.handle_escape() is True
    assert requested == []
    assert not free.gesture().is_armed()
    assert free.ghost_overlay()._ghost_rect is None


def test_free_grid_selected_card_shows_handles_and_east_cursor(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "handle-0")
    _select_card(card)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "handle-0")
    assert card is not None
    assert card.model().selected
    overlay = free.ghost_overlay()
    assert overlay._handles_rect is not None
    _send_mouse_move(card, _east_handle_pos(card), buttons=Qt.NoButton)
    assert card.cursor().shape() == Qt.SizeHorCursor


def test_free_grid_resize_handle_snaps_shows_badge_and_commits(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "resize-0")
    _select_card(card)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "resize-0")
    assert card is not None
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = _east_handle_pos(card)
    end = QPoint(start.x() + unit * 2, start.y())
    _drag_card(card, start, end, release=False)
    session = free.gesture().session()
    assert session is not None and session.handle == "e"
    assert session.badge() == "8×3"
    assert free.ghost_overlay()._badge == "8×3"
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)
    assert requested == [("time", "resize-0", 0, 0, 8, 3, "drag-resize")]


def test_free_grid_shift_resize_keeps_aspect_ratio(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "ratio-0")
    _select_card(card)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "ratio-0")
    assert card is not None
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = _east_handle_pos(card)
    end = QPoint(start.x() + unit * 2, start.y())
    _drag_card(card, start, end, modifiers=Qt.ShiftModifier)
    assert requested == [("time", "ratio-0", 0, 0, 8, 4, "drag-resize")]


def test_free_grid_resize_span_clamps_to_grid_limits(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "clamp-0")
    _select_card(card)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "clamp-0")
    assert card is not None
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = _east_handle_pos(card)
    _drag_card(card, start, QPoint(start.x() + unit * 20, start.y()))
    assert requested == [("time", "clamp-0", 0, 0, 12, 3, "drag-resize")]
    _select_card(card)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "clamp-0")
    requested.clear()
    start = _east_handle_pos(card)
    _drag_card(card, start, QPoint(start.x() - unit * 20, start.y()))
    assert requested == [("time", "clamp-0", 0, 0, 2, 3, "drag-resize")]


def test_free_grid_overlap_resize_moves_blocker_without_modal(qtbot):
    harness = _Harness(qtbot)
    free, (card, _other) = _prepare_free_grid(harness, qtbot, "hit-0", "hit-1")
    _select_card(card)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "hit-0")
    assert card is not None
    group = []
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = _east_handle_pos(card)
    _drag_card(card, start, QPoint(start.x() + unit * 2, start.y()))
    assert toasts == [format_rearranged(2)]
    assert group == [
        (
            ("time", "hit-0", 0, 0, 8, 3),
            ("time", "hit-1", 8, 0, 6, 3),
        )
    ]


def test_free_grid_alt_shift_arrow_uses_keyboard_resize(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "key-1")
    card = harness.page.card_widget("time", "key-1")
    assert card is not None
    card.setFocus(Qt.OtherFocusReason)
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    qtbot.keyClick(card, Qt.Key_Right, Qt.AltModifier | Qt.ShiftModifier)
    assert requested == [("time", "key-1", 0, 0, 7, 3, "keyboard-resize")]


def _selection_view_ids(free) -> set[str]:
    return {ref.view_id for ref in free.gesture().selection()}


def _marquee(board, start: QPoint, end: QPoint, *, shift: bool = False) -> None:
    modifiers = Qt.ShiftModifier if shift else Qt.NoModifier
    QTest.mousePress(board, Qt.LeftButton, modifiers, start)
    _send_mouse_move(board, end, modifiers=modifiers)
    QTest.mouseRelease(board, Qt.LeftButton, modifiers, end)


def test_free_grid_marquee_selects_intersecting_cards(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "box-0", "box-1")
    start = QPoint(8, max(left.geometry().bottom(), right.geometry().bottom()) + 16)
    end = QPoint(
        max(left.geometry().right(), right.geometry().right()) - 8,
        min(left.geometry().top(), right.geometry().top()) + 8,
    )
    assert start.y() < free.height()
    _marquee(free, start, end)
    assert _selection_view_ids(free) == {"box-0", "box-1"}
    assert left.model().selected and right.model().selected
    assert free.ghost_overlay()._handles_rect is None
    assert len(free.ghost_overlay()._selection_rects) == 2


def test_free_grid_shift_click_toggles_selection(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "shift-0", "shift-1")
    _select_card(left)
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    assert _selection_view_ids(free) == {"shift-0", "shift-1"}
    QTest.mouseClick(left, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    assert _selection_view_ids(free) == {"shift-1"}
    assert not left.model().selected
    assert right.model().selected


def test_free_grid_group_move_commits_once_and_keeps_relative_layout(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "grp-0", "grp-1")
    _select_card(left)
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    requested = []
    group = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    metrics = free.metrics()
    unit = metrics.row_height + metrics.gutter
    _drag_card(left, QPoint(24, 24), QPoint(24, 24 + unit))
    assert requested == []
    assert group == [
        (
            ("time", "grp-0", 0, 1, 6, 3),
            ("time", "grp-1", 6, 1, 6, 3),
        )
    ]


def test_free_grid_group_move_past_base_frame_commits_without_warning(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "bad-0", "bad-1")
    _select_card(left)
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    group = []
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    _drag_card(left, QPoint(24, 24), QPoint(24 + unit, 24))
    assert group == [
        (
            ("time", "bad-0", 1, 0, 6, 3),
            ("time", "bad-1", 7, 0, 6, 3),
        )
    ]
    assert toasts == [format_rearranged(2)]


def test_free_grid_delete_and_backspace_apply_to_whole_selection(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "del-0", "del-1")
    _select_card(left)
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    left.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(left, Qt.Key_Backspace)
    assert set(harness.unplaced) == {("time", "del-0"), ("time", "del-1")}


def test_free_grid_escape_clears_selection(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "esc-sel")
    _select_card(card)
    island = harness.page.card_context_island()
    assert _selection_view_ids(free) == {"esc-sel"}
    assert harness.page.selected_ref() == ("time", "esc-sel")
    assert island.isHidden()
    assert card.action_bar().isVisible()
    assert harness.page.handle_escape() is True
    assert _selection_view_ids(free) == set()
    assert harness.page.selected_ref() is None
    assert island.isHidden()
    assert card.action_bar().isVisible()
    assert free.ghost_overlay()._handles_rect is None
    assert harness.page.handle_escape() is False
    assert not island.isVisible()


def test_template_escape_hides_card_context_island(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    _select_card(card)
    island = harness.page.card_context_island()
    assert harness.page.selected_ref() == ("time", "time-1")
    assert island.isHidden()
    assert card.action_bar().isVisible()
    assert card.model().selected
    assert harness.page.handle_escape() is True
    assert harness.page.selected_ref() is None
    assert island.isHidden()
    assert card.action_bar().isVisible()
    assert not card.model().selected
    assert harness.page.handle_escape() is False


def _blank_board_point(board) -> QPoint:
    for y in range(4, max(5, board.height() - 4), 8):
        for x in range(4, max(5, board.width() - 4), 8):
            pos = QPoint(x, y)
            if board._card_at(pos) is None:
                return pos
    raise AssertionError("free grid has no blank interior point")


def test_free_grid_empty_click_hides_card_context_island(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "empty-click")
    _select_card(card)
    island = harness.page.card_context_island()
    assert island.isHidden()
    assert card.action_bar().isVisible()
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, QPoint(4, 4))
    assert harness.page.selected_ref() is None
    assert _selection_view_ids(free) == set()
    assert island.isHidden()
    assert card.action_bar().isVisible()


def test_free_grid_blank_press_dismisses_the_library(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "lib-blank")
    harness.page.set_library_visible(True)
    assert harness.page.is_library_visible() is True
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    assert harness.page.is_library_visible() is False


def test_pinned_library_survives_a_blank_canvas_press(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "lib-pin")
    harness.page.set_library_visible(True)
    harness.page.library_panel().set_pinned(True)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    assert harness.page.is_library_visible() is True
    assert harness.page.active_panel() == PANEL_LIBRARY


def test_blank_press_during_drag_defers_the_dismiss(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "lib-drag")
    harness.page.set_library_visible(True)
    harness.page._on_drag_started("ref")
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    assert harness.page.is_library_visible() is True
    assert harness.page._deferred_panel_close is not None
    harness.page._on_drag_finished()
    assert harness.page.is_library_visible() is False


def test_card_press_does_not_dismiss_the_library(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "lib-card")
    harness.page.set_library_visible(True)
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    assert harness.page.is_library_visible() is True


def test_blank_press_still_clears_selection_and_starts_marquee(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "lib-marq")
    _select_card(card)
    pos = _blank_board_point(free)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, pos)
    assert _selection_view_ids(free) == set()
    assert harness.page.selected_ref() is None
    assert free.gesture().marquee() is not None


def test_template_blank_press_dismisses_the_library(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref("time", "time-1"))
    add_ref(harness.board, make_ref("time", "time-2"))
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    harness.page.set_library_visible(True)
    grid = harness.page.board_grid()
    QTest.mousePress(grid, Qt.LeftButton, Qt.NoModifier, _gutter_point(grid))
    assert harness.page.is_library_visible() is False


def test_template_gutter_click_hides_card_context_island(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref("time", "time-1"))
    add_ref(harness.board, make_ref("time", "time-2"))
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    _select_card(card)
    island = harness.page.card_context_island()
    assert island.isHidden()
    assert card.action_bar().isVisible()
    grid = harness.page.board_grid()
    QTest.mouseClick(grid, Qt.LeftButton, Qt.NoModifier, _gutter_point(grid))
    assert harness.page.selected_ref() is None
    assert island.isHidden()
    assert card.action_bar().isVisible()


def test_board_host_padding_click_hides_card_context_island(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "host-pad")
    card = harness.page.card_widget("time", "host-pad")
    assert card is not None
    _select_card(card)
    island = harness.page.card_context_island()
    assert island.isHidden()
    assert card.action_bar().isVisible()
    QTest.mouseClick(
        harness.page._board_host, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2)
    )
    assert harness.page.selected_ref() is None
    assert island.isHidden()
    assert card.action_bar().isVisible()


def test_make_layout_mime_has_no_product_references():
    forbidden = {"make_layout_mime", "ULTRAVIEW_LAYOUT_MIME", "extract_layout_strings"}
    hits = []
    product_root = Path(__file__).resolve().parents[2] / "mf4_analyzer"
    for path in product_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name in forbidden:
                hits.append(f"{path.name}:{name}")
    assert hits == []


def test_library_drop_on_occupied_card_requires_replace_ring(qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.ultraview.widgets.REPLACE_HOVER_MS", 1
    )
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    mime = _mime("order", "order-1")
    card.dragEnterEvent(_enter(mime))
    card.dropEvent(_drop(mime))
    assert harness.replaced == []
    card.dragEnterEvent(_enter(mime))
    qtbot.wait(30)
    overlay = harness.page.board_grid()._overlay
    assert overlay._ring_rect is not None
    card.dropEvent(_drop(mime))
    assert harness.replaced == [("primary", "order", "order-1")]


def test_library_drop_outside_replace_ring_cancels(qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.ultraview.widgets.REPLACE_HOVER_MS", 1
    )
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    mime = _mime("order", "order-1")
    card.dragEnterEvent(_enter(mime))
    qtbot.wait(30)
    card.dragLeaveEvent(_leave())
    card.dropEvent(_drop(mime))
    assert harness.replaced == []
    assert harness.added == []


def test_free_grid_library_drop_on_card_without_ring_does_not_replace(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "ring-0")
    mime = _mime("order", "order-1")
    pos = card.geometry().center()
    expected_anchor = free.grid_anchor_at(pos)
    free.dragEnterEvent(_enter(mime, pos))
    free.dragMoveEvent(_move(mime, pos))
    assert free.ghost_overlay()._ghost_rect is not None
    free.dropEvent(_drop(mime, pos))
    assert harness.grid_replaced == []
    assert harness.grid_inserted == [("order", "order-1", expected_anchor)]
    inserted = free_grid_placement_for(harness.board, make_ref("order", "order-1"))
    assert inserted is not None
    assert inserted.rect != GridRect(0, 0, 4, 3)


def test_free_grid_add_without_pointer_uses_current_scroll_viewport_center(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(1000, 720)
    qtbot.wait(10)
    expected_anchor = harness.page.current_free_grid_insert_anchor()
    assert expected_anchor is not None

    harness.page.request_add("order", "centered-1")

    assert harness.grid_inserted == [("order", "centered-1", expected_anchor)]
    placed = free_grid_placement_for(harness.board, make_ref("order", "centered-1"))
    assert placed is not None
    assert placed.rect != GridRect(0, 0, 4, 3)


def test_free_grid_library_drop_on_ring_replaces(qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.ultraview.widgets.REPLACE_HOVER_MS", 1
    )
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "ring-1")
    mime = _mime("order", "order-1")
    pos = card.geometry().center()
    free.dragEnterEvent(_enter(mime, pos))
    free.dragMoveEvent(_move(mime, pos))
    qtbot.wait(30)
    assert free.ghost_overlay()._ring_rect is not None
    free.dropEvent(_drop(mime, pos))
    assert harness.grid_replaced == [("time", "ring-1", "order", "order-1")]


def test_template_card_drag_to_empty_moves_and_to_occupied_swaps(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    source = harness.page.card_widget("time", "time-1")
    empty = harness.page.slot_widget("aux_0")
    assert source is not None and empty is not None
    grid = harness.page.board_grid()
    start = QPoint(20, 20)
    end = source.mapFrom(grid, empty.geometry().center())
    _drag_card(source, start, end)
    assert harness.swapped == [("primary", "aux_0")]

    add_ref(harness.board, make_ref("fft", "fft-1"))
    harness.page.set_board(harness.board)
    source = harness.page.card_widget("time", "time-1")
    other = harness.page.card_widget("fft", "fft-1")
    assert source is not None and other is not None
    harness.swapped.clear()
    end = source.mapFrom(grid, other.geometry().center())
    _drag_card(source, start, end)
    assert harness.swapped
    assert set(harness.swapped[0]) == {"aux_0", other.model().slot_id}


def test_overview_reuses_compositor_image_when_shown(qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.compositor import compose_board

    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.show_overview()
    overview = harness.page.board_overview()
    expected = compose_board(harness.board, {}, {}, scale=1, title=False)
    assert (overview._image.width(), overview._image.height()) == (
        expected.width(),
        expected.height(),
    )


def test_same_board_refresh_keeps_overview_visible(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    harness.page.show_overview()
    assert harness.page.board_overview().isVisible()
    harness.page.set_board(harness.board)
    assert harness.page.board_overview().isVisible()


def test_page_runtime_caches_shrink_after_remove_board_switch_and_reset(qtbot):
    harness = _Harness(qtbot)
    kept = make_ref("time", "time-1")
    dropped = make_ref("fft", "fft-1")
    add_ref(harness.board, kept)
    add_ref(harness.board, dropped)
    harness.page.set_board(harness.board)
    harness.page.set_preview(kept, FakePreview(kept, image=_image()))
    harness.page.set_preview(dropped, FakePreview(dropped, image=_image()))
    harness.page.set_ref_status(kept, STATUS_MISSING, True)
    harness.page.set_ref_status(dropped, STATUS_MISSING, True)
    assert set(harness.page._previews) == {kept, dropped}
    assert set(harness.page._statuses) == {kept, dropped}
    assert set(harness.page._ref_exists) == {kept, dropped}

    remove_ref(harness.board, dropped)
    harness.page.set_board(harness.board)
    assert set(harness.page._previews) == {kept}
    assert set(harness.page._statuses) == {kept}
    assert set(harness.page._ref_exists) == {kept}

    other = default_board()
    harness.page.set_board(other)
    assert harness.page._previews == {}
    assert harness.page._statuses == {}
    assert harness.page._ref_exists == {}

    harness.page.set_preview(kept, FakePreview(kept, image=_image()))
    harness.page.set_ref_status(kept, STATUS_MISSING, True)
    harness.page.clear_runtime_caches()
    assert harness.page._previews == {}
    assert harness.page._statuses == {}
    assert harness.page._ref_exists == {}


def test_board_switcher_does_not_rebuild_tabs_while_reordering(qtbot):
    switcher = BoardSwitcher()
    qtbot.addWidget(switcher)

    class _Board:
        def __init__(self, board_id: str, name: str) -> None:
            self.board_id = board_id
            self.name = name

    boards = [_Board("a", "A"), _Board("b", "B"), _Board("c", "C")]
    switcher.set_boards(boards, "a")
    tab = switcher.tab_bar()
    assert tab.count() == 3
    switcher._reordering = True
    switcher.set_boards(boards[:1], "a")
    assert tab.count() == 3
    assert switcher._pending_boards is not None
    QCoreApplication.processEvents()
    assert tab.count() == 1
    assert switcher._reordering is False
    assert switcher.board_ids() == ("a",)


def test_middle_pan_does_not_consume_left_release_during_card_drag(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "pan-0")
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    start = QPoint(16, 16)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    _drag_card(card, start, QPoint(start.x() + unit * 2, start.y()), release=False)
    assert free.gesture().is_active()
    mid_press = QMouseEvent(
        QEvent.MouseButtonPress,
        start,
        card.mapToGlobal(start),
        Qt.MiddleButton,
        Qt.MiddleButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(card, mid_press)
    assert harness.page.is_board_panning()
    assert not free.gesture().is_armed()
    left_release = QMouseEvent(
        QEvent.MouseButtonRelease,
        start,
        card.mapToGlobal(start),
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(card, left_release)
    assert harness.page.is_board_panning()
    assert requested == []
    mid_release = QMouseEvent(
        QEvent.MouseButtonRelease,
        start,
        card.mapToGlobal(start),
        Qt.MiddleButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(card, mid_release)
    assert not harness.page.is_board_panning()
    assert requested == []


def test_free_grid_drag_can_drop_on_unplaced_rail(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "tray-0")
    rail = harness.page.tool_rail()
    qtbot.wait(10)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    _drag_card(card, start, QPoint(start.x() + unit, start.y()), release=False)
    rail_pos = QPoint(max(8, rail.width() // 2), max(8, rail.height() // 2))
    global_pos = rail.mapToGlobal(rail_pos)
    local = free.mapFromGlobal(global_pos)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseButtonRelease,
            local,
            global_pos,
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    )
    assert harness.unplaced == [("time", "tray-0")]


def test_template_slot_drag_escape_cancels_without_swap(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref("time", "slot-a"))
    add_ref(harness.board, make_ref("time", "slot-b"))
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "slot-a")
    assert card is not None
    start = QPoint(20, 20)
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, start)
    _send_mouse_move(
        card, QPoint(start.x() + QApplication.startDragDistance() + 24, start.y())
    )
    assert harness.page.board_grid().is_slot_drag_armed()
    assert harness.page.handle_escape() is True
    assert not harness.page.board_grid().is_slot_drag_armed()
    assert harness.swapped == []


def test_free_grid_move_past_base_frame_commits_without_warning(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "oob-0")
    requested = []
    toasts = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.feedback_requested.connect(toasts.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    _drag_card(card, start, QPoint(start.x() - unit * 8, start.y()))
    assert requested == [("time", "oob-0", -8, 0, 6, 3, "drag-move")]
    assert toasts == []


def test_free_grid_edge_drop_rejects_without_shrinking_neighbors(qtbot):
    harness = _Harness(qtbot)
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(
            make_ref("time", "left-0"), GridRect(SAFETY_COLUMN_MIN, 0, 4, 3)
        ),
        FreeGridPlacement(
            make_ref("time", "left-1"), GridRect(SAFETY_COLUMN_MIN, 3, 4, 3)
        ),
        FreeGridPlacement(
            make_ref("time", "right-0"), GridRect(SAFETY_COLUMN_MIN + 4, 0, 8, 6)
        ),
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    free = harness.page._free_grid
    card = harness.page.card_widget("time", "right-0")
    assert card is not None and card.width() > 20
    origin = QRect(card.geometry())
    group = []
    requested = []
    toasts = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = free.metrics().column_width + free.metrics().gutter
    start = QPoint(24, 24)
    # The mover begins four cells inside the safety edge, so cross five cells
    # to reach the only real wall rather than the old 12-column base frame.
    mid = QPoint(24 - unit * 5, 24)
    _drag_card(card, start, mid, release=False)
    overlay = free.ghost_overlay()
    assert overlay.is_showing()
    assert overlay._legal is False
    assert overlay._reject_mark is True
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, mid)
    assert requested == []
    assert group == []
    assert toasts == [FEEDBACK_OUT_OF_GRID]
    assert card.geometry().topLeft() == origin.topLeft()


def test_free_grid_focus_loss_cancels_active_move_without_commit(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "blur-0")
    requested = []
    group = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    mid = QPoint(start.x() + unit * 6, start.y())
    _drag_card(card, start, mid, release=False)
    assert free.gesture().is_active()
    harness.page.changeEvent(QEvent(QEvent.WindowDeactivate))
    assert requested == []
    assert group == []
    assert not free.gesture().is_armed()
    assert free.ghost_overlay()._ghost_rect is None


def test_app_focus_changed_to_none_no_longer_cancels_active_move(qtbot):
    """§4.3: focusChanged(now=None) is a fragile cancel trigger.

    It also fires for transient reasons unrelated to real window
    deactivation (e.g. a popup hiding/destroying mid-interaction), so using
    it to cancel gestures risked killing an in-progress drag out from under
    the user.  Real window deactivation is already covered by
    changeEvent(WindowDeactivate) and hideEvent (both call
    _cancel_board_gestures() themselves — see
    test_free_grid_focus_loss_cancels_active_move_without_commit).
    """
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "blur-none-0")
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    start = QPoint(16, 16)
    mid = QPoint(start.x() + unit * 6, start.y())
    _drag_card(card, start, mid, release=False)
    assert free.gesture().is_active()

    harness.page._on_app_focus_changed(card, None)

    assert free.gesture().is_active()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, mid)


def test_free_grid_move_to_signed_empty_cell_without_toast(qtbot):
    harness = _Harness(qtbot)
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(make_ref("time", "clamp-1"), GridRect(2, 0, 4, 3)),
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    free = harness.page._free_grid
    card = harness.page.card_widget("time", "clamp-1")
    assert card is not None and card.width() > 20
    group = []
    requested = []
    toasts = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = free.metrics().column_width + free.metrics().gutter
    _drag_card(card, QPoint(16, 16), QPoint(16 - unit * 4, 16))
    assert toasts == []
    assert group == []
    assert requested == [("time", "clamp-1", -2, 0, 4, 3, "drag-move")]


def test_inactive_canvas_drops_stale_cards_when_mode_switches(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("time", "stale-0"))
    harness.page.set_board(harness.board)
    assert harness.page.board_grid().card_widgets()
    template_to_free_grid(harness.board)
    harness.page.set_board(harness.board)
    assert harness.page.board_grid().card_widgets() == []
    assert harness.page._free_grid.card_widgets()


def test_line_edit_focus_disables_board_shortcuts_and_clears_space_pan(qtbot):
    harness = _Harness(qtbot)
    search = harness.page.library_panel()._search
    harness.page.note_space(True)
    assert harness.page.board_viewport().space_down()
    harness.page._on_app_focus_changed(None, search)
    assert not harness.page.board_viewport().space_down()
    assert not harness.page._esc.isEnabled()
    assert not harness.page._grid_undo.isEnabled()
    harness.page._on_app_focus_changed(search, harness.page)
    assert harness.page._esc.isEnabled()


def test_arm_replacement_opens_library_search(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    assert harness.page.active_panel() is None
    harness.page.arm_replacement("time", "time-1")
    assert harness.page.active_panel() == PANEL_LIBRARY
    assert harness.page.library_panel().isVisible()
    assert harness.page.library_panel().search_field().isVisible()
    assert harness.armed == [("time", "time-1")]


def test_locate_unplaced_view_opens_tray_body(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "time-1"))
    move_to_unplaced(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    assert harness.page.active_panel() is None
    harness.page._on_locate("time", "time-1")
    assert harness.page.active_panel() == PANEL_UNPLACED
    tray = harness.page.unplaced_tray()
    assert tray.isVisible()
    assert tray.body().isVisible()
    assert tray.item_widgets()[0].ref() == ("time", "time-1")


def test_empty_slot_without_selection_opens_library(qtbot):
    harness = _Harness(qtbot)
    feedback = []
    harness.page.feedback_requested.connect(feedback.append)
    harness.page._on_empty_slot("primary")
    assert harness.page.active_panel() == PANEL_LIBRARY
    assert harness.page.library_panel().isVisible()
    assert feedback == ["先打开 View 库并选择一个 View"]
    assert harness.added == []


def test_layout_picker_exposes_template_thumbnails(qtbot):
    harness = _Harness(qtbot)
    picker = harness.page._layout_popover
    assert picker.thumb_button("hero_left_4") is not None
    assert picker.thumb_button("grid_4x3") is not None
    assert picker.findChild(QToolButton, "ultraViewLayoutPopoverFreeGrid") is None
    picker.thumb_button("grid_2x2").click()
    assert harness.layouts == ["grid_2x2"]


def test_display_and_export_overlays_anchor_under_global_island(qtbot):
    harness = _Harness(qtbot)
    qtbot.wait(20)
    host = harness.page.canvas_host()
    island = harness.page.global_island()
    rail = harness.page.tool_rail()

    QTest.mouseClick(island.display_button(), Qt.LeftButton)
    overlay = host.overlay("display")
    assert harness.page.active_panel() == "display"
    assert overlay is not None and overlay.isVisible()
    assert overlay.geometry().top() >= island.geometry().bottom()
    assert abs(overlay.geometry().right() - island.geometry().right()) <= 2
    assert overlay.geometry().left() > rail.geometry().right()
    assert overlay.height() <= overlay.sizeHint().height() + 24

    QTest.mouseClick(island.export_button(), Qt.LeftButton)
    overlay = host.overlay("export")
    assert harness.page.active_panel() == "export"
    assert overlay is not None and overlay.isVisible()
    assert overlay.geometry().top() >= island.geometry().bottom()
    assert abs(overlay.geometry().right() - island.geometry().right()) <= 2
    assert overlay.geometry().left() > rail.geometry().right()
    assert overlay.height() <= overlay.sizeHint().height() + 24
    assert overlay.height() < 170


@pytest.mark.parametrize("width,height", [(1280, 800), (800, 560)])
def test_floating_chrome_projects_edge_rhythm_and_compact_tool_rail(qtbot, width, height):
    """The page maps the pure layout to a content-height, centred ToolRail."""
    harness = _Harness(qtbot)
    harness.page.resize(width, height)
    qtbot.wait(20)

    host = harness.page.canvas_host()
    rail = harness.page.tool_rail()
    board_island = harness.page.board_island()
    status_island = harness.page.status_island()
    global_island = harness.page.global_island()
    navigation_island = harness.page.navigation_island()
    layout = harness.page._floating_layout()

    def geometry(widget):
        rect = widget.geometry()
        return (rect.x(), rect.y(), rect.width(), rect.height())

    assert geometry(rail) == (
        layout.rail.x,
        layout.rail.y,
        layout.rail.width,
        layout.rail.height,
    )
    assert rail.x() == board_island.x() == status_island.x()
    assert global_island.x() + global_island.width() == navigation_island.x() + navigation_island.width()
    assert rail.height() == rail.sizeHint().height()
    assert rail.height() < host.height()
    assert abs((2 * rail.y() + rail.height()) - host.height()) <= 1


def test_empty_board_library_cta_and_canvas_hint_retract_after_cards(qtbot):
    harness = _Harness(qtbot)
    qtbot.wait(20)
    page = harness.page
    library = page.tool_rail().panel_button(PANEL_LIBRARY)
    hint = page.canvas_host().findChild(QLabel, "ultraViewEmptyBoardHint")
    assert library is not None and hint is not None
    assert library.property("emptyCta") == "true"
    assert hint.isVisible()
    assert "View 库" in hint.text()

    QTest.mouseClick(library, Qt.LeftButton)
    qtbot.wait(20)
    assert page.active_panel() == PANEL_LIBRARY
    assert library.property("emptyCta") == "true"
    assert not hint.isVisible()

    QTest.mouseClick(library, Qt.LeftButton)
    qtbot.wait(20)
    assert page.active_panel() is None
    assert hint.isVisible()

    page.set_presentation_active(True)
    assert not hint.isVisible()
    page.set_presentation_active(False)
    qtbot.wait(20)
    assert hint.isVisible()
    assert library.property("emptyCta") == "true"

    add_ref(harness.board, make_ref("time", "time-1"))
    page.set_board(harness.board)
    assert library.property("emptyCta") != "true"
    assert not hint.isVisible()


def test_library_overlay_keeps_section_and_row_height(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    qtbot.wait(20)
    library = harness.page.library_panel()
    button = harness.page.tool_rail().panel_button(PANEL_LIBRARY)
    assert button is not None
    QTest.mouseClick(button, Qt.LeftButton)
    qapp.processEvents()
    assert harness.page.active_panel() == PANEL_LIBRARY
    assert library.isVisible()
    assert library.width() >= LIBRARY_DEFAULT_WIDTH
    assert library.height() >= 400
    headers = [library.section_headers()[section] for section in SOURCE_SECTIONS]
    assert len(headers) == 5
    header_y = []
    for header in headers:
        # Pinned, not bracketed: the old 22..40 window was wide enough to sit still
        # while the time card was being clipped by 51px. Section heads are a fixed
        # outer-box height now (plan §4).
        assert header.height() == uv_widgets.LIBRARY_SECTION_HEAD_HEIGHT
        title = header.findChild(QLabel, "ultraViewLibrarySectionTitle")
        assert title is not None
        assert "个 View" not in title.text()
        assert header.findChild(QLabel, "ultraViewLibrarySectionCount") is None
        assert header.text()
        header_y.append(header.mapTo(library, QPoint(0, 0)).y())
    for previous, current in zip(header_y, header_y[1:]):
        assert current >= previous + 22
    rows = [widget for widget in library.row_widgets() if widget.isVisible()]
    assert len(rows) >= 6
    for row in rows:
        assert row.height() == uv_widgets.LIBRARY_ROW_HEIGHT


def test_library_overlay_height_is_constant_across_content_changes(qtbot, qapp):
    """The panel's outer rect must not follow its own content (plan §1.1, R1 + R2).

    Recorded before the fix in
    ``docs/analyzer/verify/2026-08-15-ultraview-library-probes/baseline.txt``: the
    height walked 656 -> 356 -> 488 -> 530 as the content changed, and because the
    anchor centres the panel on the trigger button, that shrinkage came back out as
    an 83px slide of the *top edge*. Both mechanisms have to die for the jumping to
    stop, so this asserts the rect field-by-field rather than just the height.
    """
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)  # the plan's §3.2 reference size
    page.show()
    qtbot.waitExposed(page)
    page.set_library_rows(_dense_rows())
    qapp.processEvents()
    button = page.tool_rail().panel_button(PANEL_LIBRARY)
    assert button is not None
    QTest.mouseClick(button, Qt.LeftButton)
    qapp.processEvents()
    assert page.active_panel() == PANEL_LIBRARY
    library = page.library_panel()
    assert library.isVisible()

    def rect_now() -> tuple[int, int, int, int]:
        # The product only re-places the overlay on resize / reopen / set_board, so
        # the jump lands later than the operation that caused it. Forcing a re-place
        # after every step is what makes that delayed jump observable here.
        page._apply_floating_layout()
        qapp.processEvents()
        geometry = library.geometry()
        return (geometry.x(), geometry.y(), geometry.width(), geometry.height())

    opened = rect_now()
    # §3.2: at this window size nothing clamps, so the panel shows its design height.
    assert opened[3] == uv_widgets.LIBRARY_OVERLAY_HEIGHT

    library.section_headers()["time"].click()
    qapp.processEvents()
    assert library.is_section_expanded("time") is False
    assert rect_now() == opened, "折叠时域"

    library.section_headers()["time"].click()
    qapp.processEvents()
    assert library.is_section_expanded("time") is True
    assert rect_now() == opened, "展开时域"

    library.search_field().setText("View 1")
    qapp.processEvents()
    assert rect_now() == opened, "搜索 View 1"

    library.search_field().setText("")
    qapp.processEvents()
    assert rect_now() == opened, "清空搜索"


def test_library_section_frames_are_never_shorter_than_their_minimum(qtbot, qapp):
    """No section card may be squeezed below the height its own children need.

    Plan §1.2: the time card rendered at 164 against a minimumSizeHint of 215, so the
    fourth View row was sliced by the card's bottom border. The cause is a hand-written
    body-height formula that undercounts what Qt already knows (528 vs 579).
    """
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)
    page.show()
    qtbot.waitExposed(page)
    page.set_library_rows(_dense_rows())
    page.set_library_visible(True)
    qapp.processEvents()
    library = page.library_panel()
    assert library.browse_mode() == "groups"

    frames = library.section_widgets()
    assert tuple(frames) == SOURCE_SECTIONS
    clipped = {
        section: (frame.height(), frame.minimumSizeHint().height())
        for section, frame in frames.items()
        if frame.height() < frame.minimumSizeHint().height()
    }
    assert not clipped, f"section cards clipped below their own minimum: {clipped}"


def test_library_add_refresh_keeps_all_sections_scrollable_without_reopen(qtbot, qapp):
    """Adding a View must not squeeze five fresh section frames into one viewport.

    The add signal triggers the same membership refresh as the coordinator.  A
    rebuild cannot read a newly-created layout's temporary 22px minimum and
    overwrite the scroll body's last valid minimum before Qt has polished the
    new section widgets.  Reopening the Library used to repair that by chance.
    """
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)
    page.show()
    qtbot.waitExposed(page)
    rows = [
        LibraryRow(
            section=section,
            view_id=f"{section}-1",
            name="View 1",
            tab_color="#3B82F6",
            source_summary="Rte_TAS_mTorsionBarTorque_xds16",
        )
        for section in SOURCE_SECTIONS
    ]
    page.set_library_rows(rows)
    page.set_library_visible(True)
    qapp.processEvents()
    library = page.library_panel()
    time_row = next(row for row in library.row_widgets() if row.row().section == "time")
    add_button = time_row.findChild(QToolButton, "ultraViewLibraryAdd")
    assert add_button is not None
    QTest.mouseClick(add_button, Qt.LeftButton)
    assert harness.added == []
    assert [(section, view_id) for section, view_id, _anchor in harness.grid_inserted] == [
        ("time", "time-1")
    ]
    qtbot.wait(20)

    assert library._body.minimumHeight() > library._scroll.viewport().height()
    assert library._scroll.verticalScrollBar().maximum() > 0
    clipped = {
        section: (frame.height(), frame.minimumSizeHint().height())
        for section, frame in library.section_widgets().items()
        if frame.height() < frame.minimumSizeHint().height()
    }
    assert not clipped, f"add refresh squeezed library sections: {clipped}"


def test_library_width_contract_and_selected_row_gutter_have_no_crossing_rule(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)
    page.show()
    qtbot.waitExposed(page)
    page.set_library_visible(True)
    qapp.processEvents()
    library = page.library_panel()

    assert library.width() == uv_widgets.LIBRARY_DEFAULT_WIDTH == 360
    assert library.maximumWidth() == uv_widgets.LIBRARY_MAX_WIDTH == 400
    library.set_selected("time", "time-1")
    qapp.processEvents()
    section = library.section_widgets()["time"]
    rows = [row for row in library.row_widgets() if row.row().section == "time"]
    first, second = rows[:2]
    gutter = second.geometry().top() - first.geometry().bottom() - 1
    assert gutter >= uv_widgets.LIBRARY_SELECTED_ROW_GUTTER
    rule = section.findChild(QWidget, "ultraViewLibrarySectionRule")
    assert rule is not None
    assert rule.geometry().bottom() < first.geometry().top()

    # The only valid rule is between the section header and body.  The selected
    # row's lower gutter has no sibling separator to cut across its roundness.
    image = section.grab().toImage()
    y = first.geometry().bottom() + max(1, gutter // 2)
    pixels = [
        QColor(image.pixel(x, y))
        for x in range(16, max(17, section.width() - 16), max(1, section.width() // 9))
    ]
    spread = max(
        max(pixel.red() for pixel in pixels) - min(pixel.red() for pixel in pixels),
        max(pixel.green() for pixel in pixels) - min(pixel.green() for pixel in pixels),
        max(pixel.blue() for pixel in pixels) - min(pixel.blue() for pixel in pixels),
    )
    assert spread < 18, [pixel.name() for pixel in pixels]


def test_library_sections_use_selected_titanium_amber_category_materials(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)
    page.show()
    qtbot.waitExposed(page)
    page.set_library_visible(True)
    qapp.processEvents()
    library = page.library_panel()
    from mf4_analyzer.ui_kit.ultraview_style import ULTRAVIEW_TITANIUM

    expected_roles = {
        "time": "time_wash",
        "fft": "fft_wash",
        "fft_time": "fft_time_wash",
        "frf": "frf_wash",
        "order": "order_wash",
    }
    fills = []
    for section in SOURCE_SECTIONS:
        frame = library.section_widgets()[section]
        header = library.section_headers()[section]
        image = frame.grab().toImage()
        point = header.mapTo(frame, QPoint(header.width() - 34, header.height() // 2))
        fill = QColor(image.pixel(point))
        expected = QColor(ULTRAVIEW_TITANIUM[expected_roles[section]])
        assert max(
            abs(fill.red() - expected.red()),
            abs(fill.green() - expected.green()),
            abs(fill.blue() - expected.blue()),
        ) <= 8
        fills.append(fill)
    assert len({fill.name() for fill in fills}) == len(SOURCE_SECTIONS)
    assert all(fill.lightness() >= 230 for fill in fills)


def test_library_row_action_button_is_calm_and_square(qtbot, qapp):
    """The ＋/− affordance is square at the contract size and stays a quiet colour.

    Two defects in one place (plan §1.4 / §3.3): ``setFixedSize(18, 18)`` fought the
    QSS ``min-width: 18px`` plus a 1px border and settled at 20x20; and the palette was
    Tailwind alert green / red, the loudest thing in a 月白石蓝 panel.

    The colour assertion deliberately checks *tone and separability* rather than any
    hex string, so retuning the palette does not mean editing this test. Note it has to
    measure ``S * V``, not saturation alone — the plan's own target ink ``#3B7C5C`` is
    S 0.52, and it is calm because it is dark, not because it is grey.
    """
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("frf", "frf-1"))
    harness.page.set_board(harness.board)
    harness.page.resize(1280, 800)
    harness.page.show()
    qtbot.waitExposed(harness.page)
    harness.page.set_library_visible(True)
    qapp.processEvents()
    library = harness.page.library_panel()

    add_row = next(widget for widget in library.row_widgets() if widget.row().view_id == "fft-1")
    remove_row = next(widget for widget in library.row_widgets() if widget.row().view_id == "frf-1")
    add_button = add_row.findChild(QToolButton, "ultraViewLibraryAdd")
    remove_button = remove_row.findChild(QToolButton, "ultraViewLibraryAdd")
    assert add_button.property("action") == "add"
    assert remove_button.property("action") == "remove"

    size = uv_widgets.LIBRARY_ROW_ACTION_SIZE
    for button in (add_button, remove_button):
        assert (button.width(), button.height()) == (size, size), (
            button.property("action"), button.width(), button.height()
        )

    # Tone: nothing anywhere inside the button — fill, border or glyph — may shout.
    for button in (add_button, remove_button):
        loudest = _loudest_pixel(button)
        assert _chroma(loudest) < 0.35, (
            f"{button.property('action')} button has a loud pixel {loudest.name()} "
            f"(S*V={_chroma(loudest):.3f})"
        )

    # Separability: quiet must not mean indistinguishable.
    assert _hue_gap(_centre_pixel(add_button), _centre_pixel(remove_button)) > 40


def test_library_pin_keeps_overlay_open_on_canvas_click(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.resize(1600, 900)
    harness.page.show()
    qtbot.waitExposed(harness.page)
    harness.page.set_library_visible(True)
    qapp.processEvents()
    library = harness.page.library_panel()
    host = harness.page.canvas_host()
    assert library.isVisible()
    library.set_pinned(True)
    assert library.is_pinned() is True
    assert host.overlay_closes_on_canvas(PANEL_LIBRARY) is False
    QTest.mouseClick(host.canvas_widget(), Qt.LeftButton)
    qapp.processEvents()
    assert library.isVisible()
    assert harness.page.active_panel() == PANEL_LIBRARY
    harness.page.handle_escape()
    qapp.processEvents()
    assert library.isVisible() is False
    assert library.is_pinned() is True


def test_library_section_headers_keep_titanium_category_wash_not_gray_slab(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.set_library_visible(True)
    qapp.processEvents()
    library = harness.page.library_panel()
    header = library.section_headers()["time"]
    pos = header.mapTo(library, QPoint(max(12, header.width() - 8), header.height() // 2))
    image = library.grab().toImage()
    pixel = QColor(image.pixel(min(pos.x(), image.width() - 1), min(pos.y(), image.height() - 1)))
    from mf4_analyzer.ui_kit.ultraview_style import ULTRAVIEW_TITANIUM

    expected = QColor(ULTRAVIEW_TITANIUM["time_wash"])
    assert max(
        abs(pixel.red() - expected.red()),
        abs(pixel.green() - expected.green()),
        abs(pixel.blue() - expected.blue()),
    ) <= 8
    assert pixel.lightness() >= 235


def test_library_outer_corner_pixels_stay_with_the_overlay_shell(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    page.resize(1280, 800)
    page.show()
    qtbot.waitExposed(page)
    page.set_library_visible(True)
    qapp.processEvents()
    library = page.library_panel()
    image = page.grab().toImage()
    origin = library.mapTo(page, QPoint(0, 0))
    probes = (
        (origin.x(), origin.y(), origin.x() - 2, origin.y() - 2),
        (origin.x() + library.width() - 1, origin.y(), origin.x() + library.width() + 1, origin.y() - 2),
        (origin.x(), origin.y() + library.height() - 1, origin.x() - 2, origin.y() + library.height() + 1),
        (
            origin.x() + library.width() - 1,
            origin.y() + library.height() - 1,
            origin.x() + library.width() + 1,
            origin.y() + library.height() + 1,
        ),
    )
    for corner_x, corner_y, outside_x, outside_y in probes:
        corner = QColor(image.pixel(corner_x, corner_y))
        outside = QColor(image.pixel(outside_x, outside_y))
        assert max(
            abs(corner.red() - outside.red()),
            abs(corner.green() - outside.green()),
            abs(corner.blue() - outside.blue()),
        ) <= 18, (corner.name(), outside.name())


def test_unplaced_overlay_stacks_items_vertically(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "tray-a"))
    add_ref(harness.board, make_ref("fft", "tray-b"))
    move_to_unplaced(harness.board, make_ref("time", "tray-a"))
    move_to_unplaced(harness.board, make_ref("fft", "tray-b"))
    harness.page.set_board(harness.board)
    qtbot.wait(20)
    tray = harness.page.unplaced_tray()
    QTest.mouseClick(harness.page.tool_rail().panel_button(PANEL_UNPLACED), Qt.LeftButton)
    qapp.processEvents()
    assert harness.page.active_panel() == PANEL_UNPLACED
    assert tray.isVisible()
    items = tray.item_widgets()
    assert len(items) == 2
    assert items[1].y() > items[0].y()
    assert items[1].geometry().top() >= items[0].geometry().bottom() - 2
    assert tray.body().horizontalScrollBar().maximum() == 0
    assert tray.width() >= 320
    assert tray.height() >= 140
    for item in items:
        assert item.height() >= 36
        assert item.width() >= items[0].width() - 2
        assert item.width() >= 240


def test_filter_overlay_is_a_vertical_stack(qtbot):
    harness = _Harness(qtbot)
    qtbot.wait(20)
    filter_button = harness.page.tool_rail().panel_button(PANEL_FILTER)
    assert filter_button is not None
    QTest.mouseClick(filter_button, Qt.LeftButton)
    overlay = harness.page.compare_rail()
    assert harness.page.active_panel() == PANEL_FILTER
    assert overlay.isVisible()
    assert overlay.height() >= 160
    assert overlay.width() <= 320
    buttons = [
        child
        for child in overlay.findChildren(QPushButton)
        if child.objectName() == "ultraViewCompareButton"
    ]
    assert len(buttons) == 5
    for previous, current in zip(buttons, buttons[1:]):
        assert current.y() > previous.y()


def test_free_grid_rail_toggle_does_not_open_an_overlay(qtbot):
    harness = _Harness(qtbot)
    qtbot.wait(20)
    QTest.mouseClick(harness.page.tool_rail().free_grid_button(), Qt.LeftButton)
    assert harness.free_grid == [False]
    assert harness.page.active_panel() is None
    assert not harness.page.compare_rail().isVisible()
    assert not harness.page._layout_popover.isVisible()


def test_free_grid_to_template_overflow_opens_unplaced(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "split_horizontal")
    add_ref(harness.board, make_ref("time", "keep-0"))
    add_ref(harness.board, make_ref("fft", "keep-1"))
    add_ref(harness.board, make_ref("frf", "overflow-0"))
    template_to_free_grid(harness.board)
    harness.page.set_board(harness.board)
    assert harness.page.active_panel() is None
    free_grid_to_template(harness.board, "split_horizontal")
    harness.page.set_board(harness.board)
    qtbot.wait(20)
    assert harness.board.unplaced
    assert harness.page.active_panel() == PANEL_UNPLACED
    assert harness.page.unplaced_tray().body().isVisible()


def test_minimap_hides_when_free_grid_fits_and_on_template(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(1600, 900)
    harness.page.zoom_fit()
    qtbot.wait(20)
    assert not harness.page.free_grid_minimap().isVisible()
    _prepare_free_grid(harness, qtbot, "fit-0")
    harness.page.set_board_zoom(1.6)
    qtbot.wait(20)
    scroll = harness.page.board_scroll_area()
    assert (
        scroll.horizontalScrollBar().maximum() > 0
        or scroll.verticalScrollBar().maximum() > 0
    )
    assert harness.page.free_grid_minimap().isVisible()
    free_grid_to_template(harness.board, harness.board.layout_id)
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    assert not harness.page.free_grid_minimap().isVisible()


def test_closing_layout_panel_does_not_change_layout_mode(qtbot):
    harness = _Harness(qtbot)
    rail = harness.page.tool_rail()
    layout = rail.panel_button(PANEL_LAYOUT)
    assert layout is not None
    assert rail.free_grid_button().property("modeActive") == "true"
    assert layout.property("modeActive") != "true"
    QTest.mouseClick(layout, Qt.LeftButton)
    qtbot.wait(10)
    assert harness.page.active_panel() == PANEL_LAYOUT
    assert layout.property("panelOpen") == "true"
    assert layout.property("modeActive") != "true"
    QTest.mouseClick(layout, Qt.LeftButton)
    qtbot.wait(10)
    assert harness.page.active_panel() is None
    assert layout.property("panelOpen") != "true"
    assert layout.property("modeActive") != "true"
    assert harness.page.board().layout_mode == LAYOUT_MODE_FREE_GRID


def test_new_board_first_show_uses_the_66_percent_working_frame(qtbot):
    harness = _Harness(qtbot)
    fit = harness.page._content_fit_rect()
    from mf4_analyzer.ui.chart_stack.ultraview.free_grid import screen_grid_metrics
    from mf4_analyzer.ui.chart_stack.ultraview.viewport import (
        NEW_BOARD_ZOOM_MAX,
        default_board_zoom,
        two_card_working_frame,
    )

    expected = default_board_zoom(
        (float(fit.width), float(fit.height)),
        two_card_working_frame(screen_grid_metrics(())),
    )
    assert harness.page.board_zoom() == pytest.approx(expected)
    assert harness.page.board_zoom() <= NEW_BOARD_ZOOM_MAX
    assert harness.page.board().layout_mode == LAYOUT_MODE_FREE_GRID


def test_autofit_button_disabled_in_template_mode(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref("time", "a"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "a")
    assert card is not None
    button = card.action_button("fit")
    assert button is not None
    assert button.isVisible()
    assert not button.isEnabled()
    assert "自由网格" in button.toolTip()
    assert harness.page.board().layout_mode == LAYOUT_MODE_TEMPLATE


def test_autofit_button_enabled_on_free_grid_without_selecting(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "fit-ready")
    button = card.action_button("fit")
    assert button is not None
    assert button.isVisible()
    assert button.isEnabled()
    assert "按原图比例" in button.toolTip()
    requested = []
    harness.page.free_grid_autofit_requested.connect(
        lambda section, view_id: requested.append((section, view_id))
    )
    QTest.mouseClick(button, Qt.LeftButton)
    assert requested == [("time", "fit-ready")]


def test_card_context_residents_do_not_overlap_at_800px(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(800, 560)
    add_ref(harness.board, make_ref("time", "time-1"))
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("time", "time-1")
    assert card is not None
    qtbot.wait(20)
    assert harness.page.card_context_island().isHidden()
    bar = card.action_bar()
    assert bar.isVisible()
    visible_actions = [
        button.property("contextAction")
        for button in bar.findChildren(QToolButton)
        if button.isVisible()
    ]
    assert visible_actions == ["open", "focus", "fit", "remove", "more"]
    boxes = [
        button.geometry()
        for button in bar.findChildren(QToolButton)
        if button.isVisible()
    ]
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            assert not first.intersects(second)
    mapped = QRect(bar.mapTo(card, QPoint(0, 0)), bar.size())
    assert card.rect().contains(mapped)


def test_template_title_only_lod_hides_preview_backing_and_keeps_type(qtbot):
    harness = _Harness(qtbot)
    set_layout(harness.board, "hero_left_4")
    add_ref(harness.board, make_ref("order", "View 1"))
    ref = make_ref("order", "View 1")
    harness.page.set_library_rows(
        [
            LibraryRow(
                section="order",
                view_id="View 1",
                name="View 1",
                tab_color="#9b6bd0",
                status=STATUS_MISSING,
                on_board=True,
                source_summary="order-src",
            )
        ]
    )
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="View 1", captured_digest="order-digest"),
    )
    harness.page.set_board(harness.board)
    card = harness.page.card_widget("order", "View 1")
    assert card is not None
    geom_before = QRect(card.geometry())
    harness.page.set_board_zoom(0.35)
    qtbot.wait(10)
    chip = card.findChild(QToolButton, "ultraViewCardTypeChip")
    assert chip is not None and chip.isVisible()
    assert "阶次" in (chip.text() + chip.toolTip() + chip.accessibleName())
    assert card._title.full_text() == "View 1"
    assert not card._image.isVisible() or card._image.height() == 0
    assert not card._footer.isVisible()
    assert card.isVisible()
    assert card.focusPolicy() == Qt.StrongFocus
    assert slot_occupant(harness.page.board(), card.slot_id()) == ref
    del geom_before
    assert harness.page._previews[ref].captured_digest == "order-digest"


def test_lod_matrix_keeps_type_chip_across_window_widths(qtbot):
    harness = _Harness(qtbot)
    add_ref(harness.board, make_ref("time", "View 1"))
    ref = make_ref("time", "View 1")
    harness.page.set_library_rows(
        [
            LibraryRow(
                section="time",
                view_id="View 1",
                name="View 1",
                tab_color="#2d7ff9",
                status=STATUS_MISSING,
                on_board=True,
                source_summary="time-src",
            )
        ]
    )
    harness.page.set_preview(
        ref,
        FakePreview(ref=ref, image=_image(), title="View 1"),
    )
    harness.page.set_board(harness.board)
    for width, height in ((800, 560), (1280, 800), (1440, 900)):
        harness.page.resize(width, height)
        qtbot.wait(10)
        card = harness.page.card_widget("time", "View 1")
        assert card is not None
        for zoom, expect_preview, expect_footer in (
            (1.0, True, True),
            (0.55, True, False),
            (0.35, False, False),
        ):
            harness.page.set_board_zoom(zoom)
            qtbot.wait(10)
            chip = card.findChild(QToolButton, "ultraViewCardTypeChip")
            assert chip is not None and chip.isVisible(), (width, zoom)
            assert "时域" in (chip.text() + chip.toolTip() + chip.accessibleName())
            assert card._title.full_text() == "View 1"
            if expect_preview:
                assert card._image.isVisible() and card._image.height() > 0
            else:
                assert not card._image.isVisible() or card._image.height() == 0
            assert card._footer.isVisible() is expect_footer


def _panel_trigger(page, panel_id):
    if panel_id == PANEL_LIBRARY:
        return page.tool_rail().panel_button(PANEL_LIBRARY)
    if panel_id == "display":
        return page.global_island().display_button()
    if panel_id == "export":
        return page.global_island().export_button()
    raise AssertionError(panel_id)


@pytest.mark.parametrize("panel_id", [PANEL_LIBRARY, "display", "export"])
def test_blank_canvas_click_closes_panel_without_leaving_trigger_focus(qtbot, qapp, panel_id):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    trigger = _panel_trigger(page, panel_id)
    assert page._open_panel(panel_id)
    qapp.processEvents()
    assert page.active_panel() == panel_id
    QTest.mouseClick(page.canvas_host().canvas_widget(), Qt.LeftButton)
    qapp.processEvents()
    assert page.active_panel() is None
    assert trigger.hasFocus() is False
    assert trigger.property("panelOpen") != "true"
    if trigger.isCheckable():
        assert trigger.isChecked() is False


@pytest.mark.parametrize("panel_id", [PANEL_LIBRARY, "display", "export"])
def test_toggle_close_does_not_leave_trigger_focus(qtbot, qapp, panel_id):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    trigger = _panel_trigger(page, panel_id)
    QTest.mouseClick(trigger, Qt.LeftButton)
    qapp.processEvents()
    assert page.active_panel() == panel_id
    QTest.mouseClick(trigger, Qt.LeftButton)
    qapp.processEvents()
    assert page.active_panel() is None
    assert trigger.hasFocus() is False


@pytest.mark.parametrize("panel_id", [PANEL_LIBRARY, "display", "export"])
def test_escape_returns_focus_to_the_panel_trigger(qtbot, qapp, panel_id):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    trigger = _panel_trigger(page, panel_id)
    assert page._open_panel(panel_id)
    qapp.processEvents()
    page.handle_escape()
    qapp.processEvents()
    assert page.active_panel() is None
    assert trigger.hasFocus() is True


def _workspace_with_boards(*names: str):
    workspace = default_workspace()
    workspace.boards[0].name = names[0]
    for name in names[1:]:
        created = create_board(workspace, name=name)
        assert created is not None
    return workspace


def test_board_popover_click_switches_and_row_actions_copy_delete(qtbot, qapp, monkeypatch):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    workspace = _workspace_with_boards("全局对比", "台架 vs 路试", "NVH 复查")
    selected: list[str] = []
    duplicated: list[str] = []
    deleted: list[str] = []
    page.select_board_requested.connect(selected.append)
    page.duplicate_board_requested.connect(duplicated.append)
    page.delete_board_requested.connect(deleted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Yes),
    )
    page.set_workspace(workspace)
    page.board_island().menu_button().click()
    qapp.processEvents()
    popover = page.board_popover()
    assert page.active_panel() == PANEL_BOARDS
    assert popover.isVisible()
    assert popover.current_board_id() == workspace.active_board_id
    target = workspace.boards[1].board_id
    item = next(
        popover.list_widget().item(index)
        for index in range(popover.list_widget().count())
        if popover.list_widget().item(index).data(Qt.UserRole) == target
    )
    popover.list_widget().itemClicked.emit(item)
    qapp.processEvents()
    assert selected == [target]
    assert page.active_panel() is None

    page._open_panel(PANEL_BOARDS)
    qapp.processEvents()
    popover.duplicate_requested.emit(target)
    qapp.processEvents()
    assert duplicated == [target]
    assert page.active_panel() == PANEL_BOARDS
    popover.delete_requested.emit(target)
    qapp.processEvents()
    assert deleted == [target]
    assert not hasattr(page, "_make_board_item_menu")


def test_board_popover_drag_reorder_emits_and_survives_workspace_roundtrip(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    workspace = _workspace_with_boards("A", "B", "C")
    moved: list[tuple[str, int]] = []

    def _apply(board_id: str, new_index: int) -> None:
        moved.append((board_id, new_index))
        reorder_board(workspace, board_id, new_index)
        page.set_workspace(workspace)

    page.reorder_board_requested.connect(_apply)
    page.set_workspace(workspace)
    page._open_panel(PANEL_BOARDS)
    qapp.processEvents()
    first_id = workspace.boards[0].board_id
    page.board_popover().apply_internal_move(first_id, 2)
    qapp.processEvents()
    assert moved == [(first_id, 2)]
    assert [board.board_id for board in workspace.boards][-1] == first_id
    assert page.board_popover().board_ids()[-1] == first_id
    assert page.board_popover().isVisible()


def test_board_popover_create_disables_at_cap_and_delete_cancel_keeps_board(qtbot, qapp, monkeypatch):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    workspace = default_workspace()
    while len(workspace.boards) < MAX_UI_BOARDS:
        assert create_board(workspace, name=f"Board {len(workspace.boards) + 1}") is not None
    page.set_workspace(workspace)
    page._open_panel(PANEL_BOARDS)
    qapp.processEvents()
    assert page.board_popover().create_button().isEnabled() is False
    assert "20" in page.board_popover().create_button().toolTip()

    deleted: list[str] = []
    page.delete_board_requested.connect(deleted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Cancel),
    )
    page._confirm_delete_board(workspace.boards[0].board_id)
    assert deleted == []
    assert len(workspace.boards) == MAX_UI_BOARDS


def test_board_popover_blank_click_closes_without_chevron_residue(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    chevron = page.board_island().menu_button()
    page._open_panel(PANEL_BOARDS)
    qapp.processEvents()
    assert chevron.property("panelOpen") == "true"
    QTest.mouseClick(page.canvas_host().canvas_widget(), Qt.LeftButton)
    qapp.processEvents()
    assert page.active_panel() is None
    assert page.board_popover().isVisible() is False
    assert chevron.hasFocus() is False
    assert chevron.property("panelOpen") != "true"


def test_board_popover_delete_key_does_not_remove_a_board(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    workspace = _workspace_with_boards("A", "B", "C")
    deleted: list[str] = []
    page.delete_board_requested.connect(deleted.append)
    page.set_workspace(workspace)
    page._open_panel(PANEL_BOARDS)
    qapp.processEvents()
    QTest.keyClick(page.board_popover().list_widget(), Qt.Key_Delete)
    qapp.processEvents()
    assert deleted == []
    assert page.board_popover().board_ids() == tuple(board.board_id for board in workspace.boards)
    assert page.active_panel() == PANEL_BOARDS


def test_board_popover_grows_with_new_board_and_keeps_first_row_visible(qtbot, qapp):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    page = harness.page
    workspace = _workspace_with_boards("全局对比")
    page.set_workspace(workspace)
    page._open_panel(PANEL_BOARDS)
    qapp.processEvents()
    popover = page.board_popover()
    first_id = workspace.boards[0].board_id
    height_before = popover.height()
    created = create_board(workspace, name="全局对比 2")
    assert created is not None
    page.set_workspace(workspace)
    qapp.processEvents()
    assert popover.isVisible()
    assert popover.height() > height_before
    assert abs(popover.height() - popover.sizeHint().height()) <= 2
    list_bottom = popover.list_widget().geometry().bottom()
    create_top = popover.create_button().geometry().top()
    assert 0 <= create_top - list_bottom <= 8
    first = popover.list_widget().item(0)
    assert first is not None and first.data(Qt.UserRole) == first_id
    rect = popover.list_widget().visualItemRect(first)
    assert rect.top() >= 0
    assert rect.bottom() <= popover.list_widget().viewport().height()
    last = popover.list_widget().item(popover.list_widget().count() - 1)
    assert last is not None
    last_rect = popover.list_widget().visualItemRect(last)
    assert last_rect.top() >= 0
    assert last_rect.bottom() <= popover.list_widget().viewport().height()
