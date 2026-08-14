"""UltraView page harness: library, cards, tray, drag, focus (UV-A02/A06–A12)."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QCoreApplication, QEvent, QMimeData, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QComboBox, QPushButton, QToolButton, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.layouts import (
    BOARD_PADDING,
    MIN_CARD_CHROME_HEIGHT,
    SLOT_GUTTER,
    slot_rects,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import legal_grid_rect
from mf4_analyzer.ui.chart_stack.ultraview.chrome import PANEL_FILTER, PANEL_LIBRARY, PANEL_UNPLACED
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    BoardSwitcher,
    FEEDBACK_AVOID_BOUNDARY,
    FEEDBACK_OUT_OF_GRID,
    MISSING_CARD_COPY,
    LibraryRow,
    UltraViewCard,
    UnplacedTray,
    extract_ref_strings,
    make_ref_mime,
)
from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    MAX_GRID_ROWS,
    LAYOUT_SLOTS,
    SOURCE_SECTIONS,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_REF_MIME,
    FreeGridPlacement,
    GridRect,
    LAYOUT_MODE_FREE_GRID,
    UltraViewRef,
    _legal_grid_rect,
    add_ref,
    board_to_payload,
    default_board,
    first_empty_slot,
    free_grid_to_template,
    make_ref,
    membership_set,
    move_to_unplaced,
    place_from_unplaced,
    rebind_ref,
    remove_ref,
    replace_slot,
    set_layout,
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
        self.page.add_ref_requested.connect(self._on_add)
        self.page.replace_slot_requested.connect(self._on_replace)
        self.page.swap_slots_requested.connect(self._on_swap)
        self.page.place_from_unplaced_requested.connect(self._on_place)
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
    assert button.width() <= 20
    assert button.height() <= 20
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
    assert plus.green() > plus.red() + 20
    assert minus.red() > minus.green() + 20
    assert plus.green() > minus.green() + 20
    assert minus.red() > plus.red() + 8

    header_fill = _sample_pixel(header, max(12, header.width() // 2), header.height() // 2)
    selected_fill = _sample_pixel(
        remove_row, max(12, remove_row.width() // 2), remove_row.height() // 2
    )
    selected_chroma = selected_fill.blue() - selected_fill.red()
    header_chroma = header_fill.blue() - header_fill.red()
    assert selected_chroma > 24
    assert selected_chroma > header_chroma + 20
    assert abs(header_fill.red() - header_fill.blue()) < 18


def test_add_paths_share_one_intent(qtbot):
    harness = _Harness(qtbot)
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
    assert harness.page.board_zoom() >= 1.0

    card.setFocus()
    qtbot.keyClick(card, Qt.Key_Return)
    qtbot.keyClick(card, Qt.Key_O)
    qtbot.keyClick(card, Qt.Key_Delete)
    assert ("frf", "frf-1") in harness.opened
    assert ("frf", "frf-1") in harness.removed


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
    button = card.findChild(QToolButton, "ultraViewCardFocusButton")
    assert button is not None
    assert button.isVisible() is True
    mapped = QRect(button.mapTo(card, QPoint(0, 0)), button.size())
    assert card.rect().adjusted(1, 1, -1, -1).contains(mapped)
    assert button.width() == 24
    assert button.height() == 24
    assert mapped.left() >= 6
    assert mapped.top() >= 4
    assert mapped.right() <= card.width() - 6
    assert mapped.bottom() <= card.header_height()
    assert not button.icon().isNull()
    grabbed = button.grab().toImage()
    blues = 0
    for x in range(0, grabbed.width(), 2):
        for y in range(0, grabbed.height(), 2):
            pixel = QColor(grabbed.pixel(x, y))
            if pixel.blue() > pixel.red() + 8 and pixel.blue() > 140:
                blues += 1
    assert blues >= 8, "focus chip must render a visible blue fill/stroke"


def test_card_swap_clears_replacement_arm_then_add_is_pure(qtbot):
    """UVL-A03: card-drag swap is not an armed completion; later add is a pure add."""
    harness = _Harness(qtbot)
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


def test_free_grid_drop_clamps_span_inside_board(qtbot):
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
    assert free._legal_grid_rect(clamped) == _legal_grid_rect(clamped)
    assert column + span.column_span <= GRID_COLUMNS
    assert row + span.row_span <= MAX_GRID_ROWS


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


def _east_handle_pos(card) -> QPoint:
    return QPoint(max(0, card.width() - 4), max(0, card.height() // 2))


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


def test_free_grid_overlap_drop_prompts_and_moves_blocker(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card, other) = _prepare_free_grid(harness, qtbot, "block-0", "block-1")
    monkeypatch.setattr(harness.page, "confirm_auto_avoid", lambda: True)
    group = []
    toasts = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: group.append(("single", args)))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    _drag_card(card, QPoint(16, 16), QPoint(16 + unit * 6, 16))
    assert toasts == []
    assert group == [
        (
            ("time", "block-0", 6, 0, 6, 3),
            ("time", "block-1", 6, 3, 6, 3),
        )
    ]


def test_free_grid_overlap_drop_declined_does_not_commit(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card, other) = _prepare_free_grid(harness, qtbot, "skip-0", "skip-1")
    origin = QRect(card.geometry())
    monkeypatch.setattr(harness.page, "confirm_auto_avoid", lambda: False)
    requested = []
    group = []
    toasts = []
    harness.page.free_grid_geometry_requested.connect(lambda *args: requested.append(args))
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    _drag_card(card, QPoint(16, 16), QPoint(16 + unit * 6, 16))
    assert requested == []
    assert group == []
    assert toasts == []
    assert not free.gesture().is_armed()
    assert free.ghost_overlay()._ghost_rect is None
    assert card.geometry().topLeft() == origin.topLeft()
    assert other.geometry().topLeft() != origin.topLeft()


def test_free_grid_overlap_at_boundary_toasts_without_commit(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    monkeypatch.setattr(harness.page, "confirm_auto_avoid", lambda: True)
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
    origin = QRect(card.geometry())
    group = []
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = free.metrics().row_height + free.metrics().gutter
    _drag_card(card, QPoint(16, 16), QPoint(16, 16 + unit))
    assert group == []
    assert toasts == [FEEDBACK_AVOID_BOUNDARY]
    assert card.geometry().topLeft() == origin.topLeft()


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


def test_free_grid_overlap_resize_prompts_and_moves_blocker(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card, _other) = _prepare_free_grid(harness, qtbot, "hit-0", "hit-1")
    monkeypatch.setattr(harness.page, "confirm_auto_avoid", lambda: True)
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
    assert toasts == []
    assert group == [
        (
            ("time", "hit-0", 0, 0, 8, 3),
            ("time", "hit-1", 6, 3, 6, 3),
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


def test_free_grid_group_out_of_bounds_move_toasts_without_commit(qtbot):
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
    assert group == []
    assert toasts == [FEEDBACK_OUT_OF_GRID]


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
    assert island.isVisible()
    assert harness.page.handle_escape() is True
    assert _selection_view_ids(free) == set()
    assert harness.page.selected_ref() is None
    assert not island.isVisible()
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
    assert island.isVisible()
    assert card.model().selected
    assert harness.page.handle_escape() is True
    assert harness.page.selected_ref() is None
    assert not island.isVisible()
    assert not card.model().selected
    assert harness.page.handle_escape() is False


def test_free_grid_empty_click_hides_card_context_island(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "empty-click")
    _select_card(card)
    island = harness.page.card_context_island()
    assert island.isVisible()
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, QPoint(4, 4))
    assert harness.page.selected_ref() is None
    assert _selection_view_ids(free) == set()
    assert not island.isVisible()


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
    assert island.isVisible()
    grid = harness.page.board_grid()
    QTest.mouseClick(grid, Qt.LeftButton, Qt.NoModifier, _gutter_point(grid))
    assert harness.page.selected_ref() is None
    assert not island.isVisible()


def test_board_host_padding_click_hides_card_context_island(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "host-pad")
    card = harness.page.card_widget("time", "host-pad")
    assert card is not None
    _select_card(card)
    island = harness.page.card_context_island()
    assert island.isVisible()
    QTest.mouseClick(
        harness.page._board_host, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2)
    )
    assert harness.page.selected_ref() is None
    assert not island.isVisible()


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
    free.dragEnterEvent(_enter(mime, pos))
    free.dragMoveEvent(_move(mime, pos))
    free.dropEvent(_drop(mime, pos))
    assert harness.grid_replaced == []
    assert harness.added == []


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


def test_free_grid_out_of_bounds_move_toasts_without_commit(qtbot):
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
    assert requested == []
    assert toasts == ["不能移出网格"]


def test_free_grid_edge_drop_prompts_and_shrinks_left_neighbors(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    monkeypatch.setattr(harness.page, "confirm_auto_avoid", lambda: True)
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(make_ref("time", "left-0"), GridRect(0, 0, 4, 3)),
        FreeGridPlacement(make_ref("time", "left-1"), GridRect(0, 3, 4, 3)),
        FreeGridPlacement(make_ref("time", "right-0"), GridRect(4, 0, 8, 6)),
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    free = harness.page._free_grid
    card = harness.page.card_widget("time", "right-0")
    assert card is not None and card.width() > 20
    group = []
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = free.metrics().column_width + free.metrics().gutter
    _drag_card(card, QPoint(24, 24), QPoint(24 + unit, 24))
    assert toasts == []
    assert group == [
        (
            ("time", "left-0", 0, 0, 3, 3),
            ("time", "left-1", 0, 3, 3, 3),
            ("time", "right-0", 3, 0, 9, 6),
        )
    ]


def test_free_grid_edge_drop_declined_does_not_commit(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    monkeypatch.setattr(harness.page, "confirm_auto_avoid", lambda: False)
    harness.board.layout_mode = LAYOUT_MODE_FREE_GRID
    harness.board.placements.clear()
    harness.board.unplaced.clear()
    harness.board.free_grid = [
        FreeGridPlacement(make_ref("time", "left-0"), GridRect(0, 0, 4, 3)),
        FreeGridPlacement(make_ref("time", "left-1"), GridRect(0, 3, 4, 3)),
        FreeGridPlacement(make_ref("time", "right-0"), GridRect(4, 0, 8, 6)),
    ]
    harness.page.set_board(harness.board)
    qtbot.wait(10)
    card = harness.page.card_widget("time", "right-0")
    assert card is not None
    origin = QRect(card.geometry())
    group = []
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = harness.page._free_grid.metrics().column_width + harness.page._free_grid.metrics().gutter
    _drag_card(card, QPoint(24, 24), QPoint(24 + unit, 24))
    assert group == []
    assert toasts == []
    assert card.geometry().topLeft() == origin.topLeft()


def test_free_grid_out_of_bounds_clamps_into_empty_cell_without_toast(qtbot):
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
    toasts = []
    harness.page.free_grid_group_geometry_requested.connect(group.append)
    harness.page.feedback_requested.connect(toasts.append)
    unit = free.metrics().column_width + free.metrics().gutter
    _drag_card(card, QPoint(16, 16), QPoint(16 - unit * 4, 16))
    assert toasts == []
    assert group == [(("time", "clamp-1", 0, 0, 4, 3),)]


def test_inactive_canvas_drops_stale_cards_when_mode_switches(qtbot):
    harness = _Harness(qtbot)
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
    assert library.height() >= 400
    headers = [library.section_headers()[section] for section in SOURCE_SECTIONS]
    assert len(headers) == 5
    header_y = []
    for header in headers:
        assert header.height() >= 22
        assert header.text()
        header_y.append(header.mapTo(library, QPoint(0, 0)).y())
    for previous, current in zip(header_y, header_y[1:]):
        assert current >= previous + 22
    rows = [widget for widget in library.row_widgets() if widget.isVisible()]
    assert len(rows) >= 6
    for row in rows:
        assert row.height() >= 36


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
    assert harness.free_grid == [True]
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
