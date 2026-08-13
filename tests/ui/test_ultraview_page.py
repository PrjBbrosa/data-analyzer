"""UltraView page harness: library, cards, tray, drag, focus (UV-A02/A06–A12)."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QMimeData, QPoint, Qt
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
from PyQt5.QtWidgets import QPushButton, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.layouts import MIN_CARD_CHROME_HEIGHT
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    MISSING_CARD_COPY,
    LibraryRow,
    UltraViewCard,
    extract_ref_strings,
    make_ref_mime,
)
from mf4_analyzer.ui.ultraview_state import (
    SOURCE_SECTIONS,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_REF_MIME,
    UltraViewRef,
    add_ref,
    board_to_payload,
    default_board,
    make_ref,
    move_to_unplaced,
    place_from_unplaced,
    remove_ref,
    replace_slot,
    set_layout,
    swap_slots,
)

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
        self.unplaced: list[tuple[str, str]] = []
        self.removed: list[tuple[str, str]] = []
        self.opened: list[tuple[str, str]] = []
        self.focused: list[tuple[str, str]] = []
        self.armed: list[tuple[str, str]] = []
        self.located: list[tuple[str, str]] = []
        self.copied_cards: list[tuple[str, str]] = []
        self.copied_board = 0
        self.exports: list[int] = []
        self.filters: list[str] = []
        self.layouts: list[str] = []
        self.ratio_steps: list[int] = []
        self.presentation: list[bool] = []
        self.page.add_ref_requested.connect(self._on_add)
        self.page.replace_slot_requested.connect(self._on_replace)
        self.page.swap_slots_requested.connect(self._on_swap)
        self.page.place_from_unplaced_requested.connect(self._on_place)
        self.page.move_to_unplaced_requested.connect(self._on_unplaced)
        self.page.remove_ref_requested.connect(self._on_remove)
        self.page.open_source_requested.connect(self._record_open)
        self.page.focus_requested.connect(self._record_focus)
        self.page.rebind_arm_requested.connect(self._record_arm)
        self.page.locate_ref_requested.connect(self._record_locate)
        self.page.copy_card_image_requested.connect(self._record_copy_card)
        self.page.copy_board_requested.connect(self._record_copy_board)
        self.page.export_png_requested.connect(self._record_export)
        self.page.compare_filter_changed.connect(self._record_filter)
        self.page.layout_changed.connect(self._record_layout)
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

    def _record_focus(self, section: str, view_id: str) -> None:
        self.focused.append((section, view_id))

    def _record_arm(self, section: str, view_id: str) -> None:
        self.armed.append((section, view_id))

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
    for name in ("page.py", "widgets.py", "layouts.py"):
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
    library.set_selected("order", "order-1")
    empty = page.slot_widget("aux_1")
    empty.add_clicked.emit("aux_1")
    assert harness.added == [("order", "order-1")]

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


def test_overflow_tray_is_visible_and_persisted(qtbot):
    harness = _Harness(qtbot)
    tray = harness.page.unplaced_tray()
    assert tray.title_bar().isVisible()
    assert tray.body().isHidden()
    harness.fill_board(4)
    add_ref(harness.board, make_ref("fft", "overflow-1"))
    harness.page.set_board(harness.board)
    assert [ref.view_id for ref in harness.board.unplaced] == ["overflow-1"]
    assert tray.title_bar().isVisible()
    assert tray.is_expanded()
    assert not tray.body().isHidden()
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
    assert page.unplaced_tray().is_expanded()
    assert ("order", "tray-restored") in [item.ref() for item in page.unplaced_tray().item_widgets()]


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
    by_text["替换"].trigger()
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
    assert ("frf", "frf-1") in harness.focused

    card.setFocus()
    qtbot.keyClick(card, Qt.Key_Return)
    qtbot.keyClick(card, Qt.Key_O)
    qtbot.keyClick(card, Qt.Key_Delete)
    assert ("frf", "frf-1") in harness.opened
    assert ("frf", "frf-1") in harness.removed


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
    harness.page.handle_escape()
    assert harness.page.replacement_slot() is None


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
    assert page.unplaced_tray().objectName() == "ultraViewUnplacedTray"
    assert page.compare_rail().objectName() == "ultraViewCompareRail"
    assert page.board_toolbar().objectName() == "ultraViewBoardToolbar"
    assert page.focus_layer().objectName() == "ultraViewFocusLayer"
