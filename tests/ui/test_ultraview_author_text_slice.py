"""M2 Text vertical slice: T → create/edit/format → undo → save/export."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QInputMethodEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.author_edits import (
    apply_author_create,
    apply_author_update,
    warning_copy,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import board_box_to_pixels, pixels_to_board_point
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    TEXT_DEFAULT_HEIGHT,
    TEXT_DEFAULT_WIDTH,
    TEXT_MIN_HEIGHT,
    TEXT_MIN_WIDTH,
    TOOL_SELECT,
    TOOL_TEXT,
    TextCreateIntent,
    TextUpdateIntent,
    text_box_from_click,
    text_box_from_points,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_widgets import is_text_input_widget
from mf4_analyzer.ui.chart_stack.ultraview.chrome import AUTHOR_TOOL_TEXT
from mf4_analyzer.ui.chart_stack.ultraview.compositor import compose_board
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import (
    LAYOUT_MODE_TEMPLATE,
    MAX_TEXT_TEXT,
    BoardBox,
    BoardEditEntry,
    TextObject,
    apply_board_edit_entry,
    board_to_payload,
    default_board,
    normalize_board_payload,
)
from tests.ui.test_ultraview_page import _Harness, _blank_board_point


class _TextSink:
    """Coordinator stand-in: applies typed intents through the mutation helper."""

    def __init__(self, page, board) -> None:
        self.page = page
        self.board = board
        self.undo: list[BoardEditEntry] = []
        self.redo: list[BoardEditEntry] = []
        self.dirty = False
        self.warnings: list[str] = []
        page.author_create_requested.connect(self._on_create)
        page.author_update_requested.connect(self._on_update)
        page.author_delete_requested.connect(self._on_delete)
        page.free_grid_undo_requested.connect(self._on_undo)
        page.free_grid_redo_requested.connect(self._on_redo)

    def _commit(self, mutation, label: str) -> None:
        self.warnings.extend(mutation.warnings)
        if not mutation.changed:
            return
        self.undo.append(BoardEditEntry(label, None, None, tuple(mutation.patches)))
        self.redo.clear()
        self.dirty = True
        self.page.set_board(self.board)

    def _on_create(self, intent) -> None:
        self._commit(apply_author_create(self.board, intent), "text-create")

    def _on_update(self, intent) -> None:
        self._commit(apply_author_update(self.board, intent), "text-edit")

    def _on_delete(self, intent) -> None:
        from mf4_analyzer.ui.chart_stack.ultraview.author_edits import apply_author_delete

        self._commit(apply_author_delete(self.board, intent), "text-delete")

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


class _TextHarness(_Harness):
    def __init__(self, qtbot):
        self.board = default_board()
        self.page = UltraViewPage()
        qtbot.addWidget(self.page)
        self.page.resize(1600, 900)
        self.page.show()
        self.added = []
        self.replaced = []
        self.swapped = []
        self.placed = []
        self.grid_replaced = []
        self.grid_inserted = []
        self.unplaced = []
        self.removed = []
        self.opened = []
        self.synced = []
        self.focused = []
        self.armed = []
        self.rebound = []
        self.located = []
        self.copied_cards = []
        self.copied_board = 0
        self.exports = []
        self.auto_arrange = 0
        self.grid_undo = 0
        self.filters = []
        self.layouts = []
        self.free_grid = []
        self.ratio_steps = []
        self.presentation = []
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
        self.page.auto_arrange_requested.connect(self._record_auto_arrange)
        self.page.free_grid_undo_requested.connect(self._record_grid_undo)
        self.page.compare_filter_changed.connect(self._record_filter)
        self.page.layout_changed.connect(self._record_layout)
        self.page.free_grid_toggled.connect(self._record_free_grid)
        self.page.ratio_nudge_requested.connect(self._record_ratio)
        self.page.presentation_toggled.connect(self._record_presentation)
        self.page.set_library_rows([])
        self.page.set_board(self.board)


def _arm_text(page) -> None:
    button = page.tool_rail().tool_button(AUTHOR_TOOL_TEXT)
    assert button is not None and button.isEnabled()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert page.interaction().active_tool() == TOOL_TEXT


def _click_blank(free) -> None:
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    QApplication.processEvents()


def _drag_on_board(board, start: QPoint, end: QPoint) -> None:
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


def _text_item(board) -> TextObject:
    assert len(board.author_objects) == 1
    item = board.author_objects[0]
    assert isinstance(item, TextObject)
    return item


def test_text_click_and_drag_boxes_honor_default_and_min_size():
    click = text_box_from_click((1.0, 2.0))
    assert click[2] == TEXT_DEFAULT_WIDTH
    assert click[3] == TEXT_DEFAULT_HEIGHT
    drag = text_box_from_points((0.0, 0.0), (0.2, 0.1))
    assert drag[2] == TEXT_DEFAULT_WIDTH
    assert drag[3] == TEXT_DEFAULT_HEIGHT
    real = text_box_from_points((10.0, 10.0), (14.0, 11.5))
    assert real[2] >= TEXT_MIN_WIDTH
    assert real[3] >= TEXT_MIN_HEIGHT
    assert real[2] == 4.0
    assert real[3] == 1.5


def test_negative_text_box_stays_signed_and_safety_clamps():
    negative = text_box_from_click((-6.0, -3.0))
    assert negative[0] == -6.0
    assert negative[1] == -3.0
    clamped = text_box_from_click((10_000.0, 10_000.0))
    assert clamped[0] + clamped[2] <= 120.0
    assert clamped[1] + clamped[3] <= 192.0


def test_is_text_input_widget_covers_editors_and_viewport_descendants(qtbot):
    line = QLineEdit()
    rich = QTextEdit()
    plain = QPlainTextEdit()
    for widget in (line, rich, plain):
        qtbot.addWidget(widget)
        widget.show()
    child = QWidget(plain.viewport())
    child.setFocusPolicy(Qt.StrongFocus)
    assert is_text_input_widget(line) is True
    assert is_text_input_widget(rich) is True
    assert is_text_input_widget(plain) is True
    assert is_text_input_widget(plain.viewport()) is True
    assert is_text_input_widget(child) is True
    assert is_text_input_widget(QWidget()) is False


def test_t_shortcut_does_not_steal_from_line_edit_or_viewport_descendant(qtbot):
    harness = _TextHarness(qtbot)
    line = QLineEdit(harness.page)
    line.show()
    line.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    QTest.keyClick(line, Qt.Key_T)
    assert "t" in line.text().lower()
    assert harness.page.interaction().active_tool() == TOOL_SELECT

    editor = QPlainTextEdit(harness.page)
    editor.show()
    child = QWidget(editor.viewport())
    child.setFocusPolicy(Qt.StrongFocus)
    child.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert is_text_input_widget(QApplication.focusWidget()) is True
    harness.page._on_text_tool_shortcut()
    assert harness.page.interaction().active_tool() == TOOL_SELECT


def test_click_create_cjk_commit_is_one_object_and_one_history(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    free = harness.page._free_grid
    _click_blank(free)
    editor = free.author_text_editor()
    assert editor.is_editing()
    editor.setPlainText("中文说明")
    editor.commit()
    QApplication.processEvents()
    item = _text_item(harness.board)
    assert item.text == "中文说明"
    assert item.box.width == TEXT_DEFAULT_WIDTH
    assert item.box.height == TEXT_DEFAULT_HEIGHT
    assert sink.dirty is True
    assert len(sink.undo) == 1
    assert harness.page.interaction().active_tool() == TOOL_SELECT


def test_empty_first_exit_does_not_dirty_or_write_history(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    assert editor.is_editing()
    QTest.keyClick(editor, Qt.Key_Escape)
    QApplication.processEvents()
    assert harness.board.author_objects == []
    assert sink.undo == []
    assert sink.dirty is False


def test_drag_create_uses_start_end_width(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    free = harness.page._free_grid
    start = _blank_board_point(free)
    end = QPoint(start.x() + 400, start.y() + 80)
    origin = pixels_to_board_point(
        (float(start.x()), float(start.y())),
        free.metrics(),
        origin_offset=free.author_paint_layer().model().origin_offset,
    )
    assert origin is not None
    _drag_on_board(free, start, end)
    editor = free.author_text_editor()
    assert editor.is_editing()
    editor.setPlainText("拖宽")
    editor.commit()
    QApplication.processEvents()
    box = _text_item(harness.board).box
    assert (box.x, box.y, box.width, box.height) != text_box_from_click(origin)
    assert box.width >= TEXT_MIN_WIDTH
    assert box.height >= TEXT_MIN_HEIGHT


def test_ime_preedit_does_not_let_board_steal_enter_or_escape(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    preedit = QInputMethodEvent("ni", [])
    QApplication.sendEvent(editor, preedit)
    QTest.keyClick(editor, Qt.Key_Escape)
    QApplication.processEvents()
    assert editor.is_editing()
    QTest.keyClick(editor, Qt.Key_Return)
    QApplication.processEvents()
    assert editor.is_editing()
    commit = QInputMethodEvent()
    commit.setCommitString("你")
    QApplication.sendEvent(editor, commit)
    QApplication.processEvents()
    editor.commit()
    QApplication.processEvents()
    assert _text_item(harness.board).text.endswith("你")
    assert len(sink.undo) == 1


def test_focus_out_commits_non_empty_and_cancels_empty(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    editor.setPlainText("失焦提交")
    other = QWidget(harness.page)
    other.setFocusPolicy(Qt.StrongFocus)
    other.show()
    other.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert _text_item(harness.board).text == "失焦提交"
    assert len(sink.undo) == 1

    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    empty = harness.page._free_grid.author_text_editor()
    assert empty.is_editing()
    other.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert len(harness.board.author_objects) == 1
    assert len(sink.undo) == 1


def test_board_switch_and_window_deactivate_leave_no_editor(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    assert harness.page._free_grid.author_text_editor().is_editing()
    other = default_board()
    other.board_id = "board-other"
    harness.page.set_board(other)
    QApplication.processEvents()
    assert not harness.page._free_grid.author_text_editor().is_editing()
    assert other.author_objects == []
    assert sink.undo == []

    harness.page.set_board(harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    editor.setPlainText("停用")
    QApplication.sendEvent(harness.page, QEvent(QEvent.WindowDeactivate))
    QApplication.processEvents()
    assert not editor.is_editing()
    assert _text_item(harness.board).text == "停用"


def test_char_cap_blocks_6001_and_emits_one_feedback(qtbot):
    harness = _TextHarness(qtbot)
    _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    toasts: list[str] = []
    harness.page.feedback_requested.connect(toasts.append)
    editor.setPlainText("x" * MAX_TEXT_TEXT)
    assert len(editor.toPlainText()) == MAX_TEXT_TEXT
    editor.setPlainText("x" * (MAX_TEXT_TEXT + 1))
    assert len(editor.toPlainText()) == MAX_TEXT_TEXT
    assert toasts
    assert "6000" in toasts[0]


def test_invalid_link_and_font_role_fallback_are_named_validation():
    board = default_board()
    bad = apply_author_create(
        board,
        TextCreateIntent(
            object_id="text-bad-link",
            box=(1.0, 1.0, 6.0, 1.0),
            text="链接",
            link="javascript:alert(1)",
        ),
    )
    assert bad.changed is False
    assert bad.warnings == ("invalid_text_link",)
    assert warning_copy("invalid_text_link")
    assert board.author_objects == []

    ok = apply_author_create(
        board,
        TextCreateIntent(
            object_id="text-font",
            box=(1.0, 1.0, 6.0, 1.0),
            text="字体",
            font_role="comic",
        ),
    )
    assert ok.changed is True
    assert ok.warnings == ()
    assert isinstance(board.author_objects[0], TextObject)
    assert board.author_objects[0].font_role == "sans"

    long = apply_author_create(
        board,
        TextCreateIntent(
            object_id="text-long",
            box=(2.0, 2.0, 6.0, 1.0),
            text="y" * (MAX_TEXT_TEXT + 1),
        ),
    )
    assert long.changed is False
    assert long.warnings == ("text_too_long",)


def test_move_resize_style_each_write_one_history(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    harness.board.author_objects = [
        TextObject(
            "text-geo",
            "text",
            box=BoardBox(2.0, 2.0, 6.0, 2.0),
            text="几何",
        )
    ]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.author_update_requested.emit(
        TextUpdateIntent("text-geo", box=(3.0, 2.0, 6.0, 2.0))
    )
    QApplication.processEvents()
    harness.page.author_update_requested.emit(
        TextUpdateIntent("text-geo", box=(3.0, 2.0, 8.0, 2.0))
    )
    QApplication.processEvents()
    harness.page.author_update_requested.emit(
        TextUpdateIntent("text-geo", bold=True)
    )
    QApplication.processEvents()
    item = _text_item(harness.board)
    assert item.box.x == 3.0
    assert item.box.width == 8.0
    assert item.bold is True
    assert len(sink.undo) == 3


def test_selection_toolbar_applies_whole_box_format(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    harness.board.author_objects = [
        TextObject("text-fmt", "text", box=BoardBox(2.0, 2.0, 6.0, 2.0), text="格式")
    ]
    harness.page.set_board(harness.board)
    harness.page.interaction().select_only_author("text-fmt")
    harness.page._free_grid.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    assert toolbar.isVisible()
    assert toolbar.kind() == "text"
    assert toolbar.height() == 48
    bold = toolbar.button("bold")
    assert bold is not None
    assert "整个文本框" in bold.toolTip()
    QTest.mouseClick(bold, Qt.LeftButton)
    QApplication.processEvents()
    assert _text_item(harness.board).bold is True
    assert len(sink.undo) == 1


def test_save_reopen_and_export_keep_text_parity(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    assert editor.is_editing()
    editor.setPlainText("导出对照")
    editor.commit()
    QApplication.processEvents()
    assert sink.dirty is True
    original = _text_item(harness.board)
    payload = board_to_payload(harness.board)
    reopened, warnings = normalize_board_payload(payload)
    assert warnings == []
    again = reopened.author_objects[0]
    assert isinstance(again, TextObject)
    assert again.text == "导出对照"
    assert again.object_id == original.object_id
    assert (again.box.x, again.box.y, again.box.width, again.box.height) == (
        original.box.x,
        original.box.y,
        original.box.width,
        original.box.height,
    )
    image = compose_board(reopened, {}, {}, scale=1, title=False)
    assert image.width() > 1 and image.height() > 1


def test_presentation_overview_template_do_not_create_or_leave_editor(qtbot):
    harness = _TextHarness(qtbot)
    sink = _TextSink(harness.page, harness.board)
    harness.page.set_presentation_active(True)
    QApplication.processEvents()
    button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_TEXT)
    assert button is None or not button.isEnabled()
    harness.page._on_text_tool_shortcut()
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    harness.page.set_presentation_active(False)

    harness.page.show_overview()
    QApplication.processEvents()
    overview_button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_TEXT)
    assert overview_button is None or not overview_button.isEnabled()
    harness.page.hide_overview()
    QApplication.processEvents()

    harness.board.layout_mode = LAYOUT_MODE_TEMPLATE
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    template_button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_TEXT)
    assert template_button is None or not template_button.isEnabled()
    _click_blank(harness.page._free_grid)
    assert not harness.page._free_grid.author_text_editor().is_editing()
    assert harness.board.author_objects == []
    assert sink.undo == []


def test_create_path_emits_typed_text_intent_not_state_helper(qtbot):
    harness = _TextHarness(qtbot)
    created = []
    harness.page.author_create_requested.connect(created.append)
    _arm_text(harness.page)
    _click_blank(harness.page._free_grid)
    editor = harness.page._free_grid.author_text_editor()
    editor.setPlainText("意图")
    editor.commit()
    QApplication.processEvents()
    assert created
    assert isinstance(created[0], TextCreateIntent)
    assert created[0].text == "意图"
    assert harness.board.author_objects == []
