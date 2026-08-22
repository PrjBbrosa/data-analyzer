"""R4 Sticky vertical slice: QTest rail → canvas → CJK → undo → payload."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel

from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    STICKY_DEFAULT_HEIGHT,
    STICKY_DEFAULT_WIDTH,
    TOOL_SELECT,
    TOOL_STICKY,
    AuthorCreateIntent,
    sticky_box_from_click,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import pixels_to_board_point
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOL_DRAW,
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    RAIL_BUTTON_SIZE_COMPACT,
    RELEASE_AUTHOR_TOOLS,
)
from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import ISLAND_GAP
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    BoardEditEntry,
    StickyObject,
    apply_board_edit_entry,
    board_to_payload,
    create_author_object,
    default_board,
    delete_author_objects,
    normalize_board_payload,
    update_author_object,
)
from tests.ui.test_ultraview_page import _Harness, _blank_board_point


class _AuthorSink:
    """Coordinator stand-in: consumes Page intents, never the user create path."""

    def __init__(self, page, board) -> None:
        self.page = page
        self.board = board
        self.undo: list[BoardEditEntry] = []
        self.redo: list[BoardEditEntry] = []
        self.dirty = False
        page.author_create_requested.connect(self._on_create)
        page.author_update_requested.connect(self._on_update)
        page.author_delete_requested.connect(self._on_delete)
        page.free_grid_undo_requested.connect(self._on_undo)
        page.free_grid_redo_requested.connect(self._on_redo)

    def _commit(self, mutation, label: str) -> None:
        if not mutation.changed:
            return
        self.undo.append(
            BoardEditEntry(label, None, None, tuple(mutation.patches))
        )
        self.redo.clear()
        self.dirty = True
        self.page.set_board(self.board)

    def _on_create(self, intent: AuthorCreateIntent) -> None:
        item = StickyObject(
            intent.object_id,
            "sticky",
            box=BoardBox(*intent.box),
            text=intent.text,
            palette=intent.palette,
        )
        self._commit(create_author_object(self.board, item), "sticky-create")

    def _on_update(self, intent) -> None:
        current = next(
            (
                item
                for item in self.board.author_objects
                if item.object_id == intent.object_id
            ),
            None,
        )
        if not isinstance(current, StickyObject):
            return
        box = intent.box
        item = StickyObject(
            current.object_id,
            "sticky",
            locked=current.locked,
            box=BoardBox(*box) if box is not None else current.box,
            text=current.text if intent.text is None else intent.text,
            palette=current.palette if intent.palette is None else intent.palette,
            shape=current.shape,
            font_size=current.font_size,
        )
        self._commit(update_author_object(self.board, intent.object_id, item), "sticky-edit")

    def _on_delete(self, intent) -> None:
        self._commit(
            delete_author_objects(self.board, intent.object_ids),
            "sticky-delete",
        )

    def _on_undo(self) -> None:
        if not self.undo:
            return
        entry = self.undo.pop()
        apply_board_edit_entry(self.board, entry, forward=False)
        self.redo.append(entry)
        self.page.set_board(self.board)

    def _on_redo(self) -> None:
        if not self.redo:
            return
        entry = self.redo.pop()
        apply_board_edit_entry(self.board, entry, forward=True)
        self.undo.append(entry)
        self.page.set_board(self.board)


def _arm_sticky(page) -> None:
    button = page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    assert button is not None and button.isEnabled()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert page.interaction().active_tool() == TOOL_STICKY


def _click_blank(free):
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    QApplication.processEvents()


def _drag_on_board(board, start: QPoint, end: QPoint) -> None:
    """Press/move/release on the board. Offscreen QTest.mouseMove is a no-op."""
    QTest.mousePress(board, Qt.LeftButton, Qt.NoModifier, start)
    event = QMouseEvent(
        QEvent.MouseMove,
        end,
        board.mapToGlobal(end),
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(board, event)
    QTest.mouseRelease(board, Qt.LeftButton, Qt.NoModifier, end)
    QApplication.processEvents()


def test_s3_click_tool_canvas_cjk_undo_redo_save_reopen(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    _arm_sticky(harness.page)
    free = harness.page._free_grid
    _click_blank(free)
    note = free.sticky_note_widget()
    assert note.is_editing()
    note.editor().setPlainText("中文便签")
    note.commit()
    QApplication.processEvents()
    assert len(harness.board.author_objects) == 1
    sticky = harness.board.author_objects[0]
    assert isinstance(sticky, StickyObject)
    assert sticky.text == "中文便签"
    assert sticky.box.width == STICKY_DEFAULT_WIDTH
    assert sticky.box.height == STICKY_DEFAULT_HEIGHT
    assert sink.dirty is True
    assert len(sink.undo) == 1
    assert harness.page.interaction().active_tool() == TOOL_SELECT

    harness.page.free_grid_undo_requested.emit()
    QApplication.processEvents()
    assert harness.board.author_objects == []
    harness.page.free_grid_redo_requested.emit()
    QApplication.processEvents()
    assert len(harness.board.author_objects) == 1
    assert harness.board.author_objects[0].text == "中文便签"

    payload = board_to_payload(harness.board)
    reopened, warnings = normalize_board_payload(payload)
    assert warnings == []
    assert len(reopened.author_objects) == 1
    again = reopened.author_objects[0]
    assert again.text == "中文便签"
    assert again.palette == sticky.palette
    assert (again.box.x, again.box.y, again.box.width, again.box.height) == (
        sticky.box.x,
        sticky.box.y,
        sticky.box.width,
        sticky.box.height,
    )
    assert again.object_id == sticky.object_id


def test_empty_first_exit_does_not_dirty_or_write_history(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    _arm_sticky(harness.page)
    _click_blank(harness.page._free_grid)
    note = harness.page._free_grid.sticky_note_widget()
    assert note.is_editing()
    QTest.keyClick(note.editor(), Qt.Key_Escape)
    QApplication.processEvents()
    assert harness.board.author_objects == []
    assert sink.undo == []
    assert sink.dirty is False


def test_drag_create_uses_start_end_box(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    _arm_sticky(harness.page)
    free = harness.page._free_grid
    start = _blank_board_point(free)
    end = QPoint(start.x() + 120, start.y() + 90)
    origin = pixels_to_board_point(
        (float(start.x()), float(start.y())),
        free.metrics(),
        origin_offset=free._workspace_origin_offset(),
    )
    assert origin is not None
    _drag_on_board(free, start, end)
    note = free.sticky_note_widget()
    assert note.is_editing()
    note.editor().setPlainText("拖出")
    note.commit()
    QApplication.processEvents()
    assert len(harness.board.author_objects) == 1
    box = harness.board.author_objects[0].box
    assert (box.x, box.y, box.width, box.height) != sticky_box_from_click(origin)
    assert box.width >= 2.0 and box.height >= 1.5


def test_presentation_and_overview_disable_sticky_create(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    harness.page.set_presentation_active(True)
    QApplication.processEvents()
    button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    assert button is not None
    assert not button.isEnabled()
    harness.page.set_presentation_active(False)
    harness.page.show_overview()
    QApplication.processEvents()
    assert not harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY).isEnabled()
    harness.page.hide_overview()
    QApplication.processEvents()
    assert harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY).isEnabled()


def test_locked_sticky_refuses_delete_with_feedback(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    harness.board.author_objects = [
        StickyObject(
            "locked-note",
            "sticky",
            locked=True,
            box=BoardBox(1.0, 1.0, 4.0, 3.0),
            text="锁",
        )
    ]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    free = harness.page._free_grid
    free.interaction().select_only_author("locked-note")
    toasts = []
    harness.page.feedback_requested.connect(toasts.append)
    QTest.keyClick(free, Qt.Key_Delete)
    QApplication.processEvents()
    assert harness.board.author_objects[0].object_id == "locked-note"
    assert toasts
    assert sink.undo == []


def test_negative_coordinate_sticky_round_trips_payload(qtbot):
    harness = _Harness(qtbot)
    harness.board.author_objects = [
        StickyObject(
            "neg-note",
            "sticky",
            box=BoardBox(-6.0, -3.0, 2.0, 2.0),
            text="负坐标",
            palette="blue",
        )
    ]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    payload = board_to_payload(harness.board)
    reopened, warnings = normalize_board_payload(payload)
    assert warnings == []
    item = reopened.author_objects[0]
    assert item.box.x == -6.0
    assert item.box.y == -3.0
    assert item.text == "负坐标"


def test_rail_and_sticky_popover_fit_800x560(qtbot):
    page = _Harness(qtbot).page
    page.resize(800, 560)
    QApplication.processEvents()
    rail = page.tool_rail()
    assert rail.is_compact()
    tools = (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    )
    assert tools == RELEASE_AUTHOR_TOOLS
    rail_rect = QRect(0, 0, rail.width(), rail.height())
    hits: list[QRect] = []
    for tool in tools:
        button = rail.tool_button(tool)
        assert button is not None and button.isVisible()
        assert button.width() >= RAIL_BUTTON_SIZE_COMPACT
        assert button.height() >= RAIL_BUTTON_SIZE_COMPACT
        origin = button.mapTo(rail, QPoint(0, 0))
        hit = QRect(origin, button.size())
        assert rail_rect.contains(hit), f"{tool} clipped: {hit} rail={rail_rect}"
        hits.append(hit)
    for index, left in enumerate(hits):
        for right in hits[index + 1 :]:
            assert not left.intersects(right)
    board_island = page.board_island()
    status = page.status_island()
    nav = page.navigation_island()
    band_top = board_island.y() + board_island.height() + ISLAND_GAP
    band_bottom = status.y() - ISLAND_GAP
    available = max(0, band_bottom - band_top)
    assert rail.height() <= available
    assert status.y() >= rail.y() + rail.height()
    rail_host = QRect(rail.x(), rail.y(), rail.width(), rail.height())
    assert not rail_host.intersects(QRect(status.x(), status.y(), status.width(), status.height()))
    assert not rail_host.intersects(QRect(nav.x(), nav.y(), nav.width(), nav.height()))
    rail.set_badge("unplaced", 4)
    rail.set_stale_count(2)
    QApplication.processEvents()
    host_buttons = [
        rail.tool_button(tool)
        for tool in tools
        if rail.tool_button(tool) is not None
    ]
    host_buttons.extend(
        button
        for button in (
            rail.panel_button("library"),
            rail.free_grid_button(),
            rail.panel_button("layout"),
            rail.panel_button("filter"),
            rail.panel_button("unplaced"),
            rail.sync_all_button(),
        )
        if button is not None
    )
    for badge in rail.findChildren(QLabel):
        if badge.isHidden() or badge.width() <= 0:
            continue
        badge_hit = QRect(badge.mapTo(rail, QPoint(0, 0)), badge.size())
        assert rail_rect.contains(badge_hit)
        owners = [
            button
            for button in host_buttons
            if QRect(button.mapTo(rail, QPoint(0, 0)), button.size()).intersects(badge_hit)
        ]
        assert len(owners) <= 1, f"{badge.objectName()} covers multiple rail buttons"
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    popover = page.sticky_popover()
    popover.popup(sticky.mapToGlobal(sticky.rect().center()))
    QApplication.processEvents()
    assert popover.isVisible()
    assert len(popover.palette_buttons()) == 16
    popover.close()


def test_second_sticky_click_shows_palette_and_create_uses_it(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    popover = harness.page.sticky_popover()
    assert popover.isVisible()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert not popover.isVisible()
    assert harness.page.interaction().active_tool() == TOOL_STICKY
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert popover.isVisible()
    red = popover.palette_buttons()[3]
    QTest.mouseClick(red, Qt.LeftButton)
    QApplication.processEvents()
    assert not popover.isVisible()
    assert harness.page.interaction().sticky_palette() == "red"
    _click_blank(harness.page._free_grid)
    note = harness.page._free_grid.sticky_note_widget()
    assert note.is_editing()
    note.editor().setPlainText("红便签")
    note.commit()
    QApplication.processEvents()
    assert harness.board.author_objects[0].palette == "red"


def test_pinned_sticky_stays_armed_after_commit(qtbot):
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, harness.board)
    button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    QTest.mouseDClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert harness.page.interaction().pinned_tool() == TOOL_STICKY
    _click_blank(harness.page._free_grid)
    note = harness.page._free_grid.sticky_note_widget()
    note.editor().setPlainText("钉住")
    note.commit()
    QApplication.processEvents()
    assert harness.page.interaction().active_tool() == TOOL_STICKY


def test_qtest_create_does_not_call_state_helper_as_the_user_path(qtbot):
    harness = _Harness(qtbot)
    created = []
    harness.page.author_create_requested.connect(created.append)
    _arm_sticky(harness.page)
    _click_blank(harness.page._free_grid)
    note = harness.page._free_grid.sticky_note_widget()
    note.editor().setPlainText("信号")
    note.commit()
    QApplication.processEvents()
    assert created
    assert isinstance(created[0], AuthorCreateIntent)
    assert created[0].text == "信号"
    assert harness.board.author_objects == []
