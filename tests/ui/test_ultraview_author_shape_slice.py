"""M3 Shape vertical slice: five closed shapes, no connectors."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QInputMethodEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QLineEdit, QMenu, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import ToolFlyoutSurface
from mf4_analyzer.ui.chart_stack.ultraview.author_edits import (
    apply_author_create,
    apply_author_delete,
    apply_author_update,
    warning_copy,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
    board_box_to_pixels,
    hit_box_handle,
    pixels_to_board_point,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    CLOSED_SHAPE_TYPES,
    SHAPE_DEFAULT_HEIGHT,
    SHAPE_DEFAULT_WIDTH,
    SHAPE_MIN_HEIGHT,
    SHAPE_MIN_WIDTH,
    TOOL_SELECT,
    TOOL_SHAPES,
    ShapeCreateIntent,
    ShapeUpdateIntent,
    shape_box_from_click,
    shape_box_from_points,
    resize_shape_box,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import AUTHOR_TOOL_SHAPES, ShapePopover
from mf4_analyzer.ui.chart_stack.ultraview.compositor import compose_board
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import (
    LAYOUT_MODE_TEMPLATE,
    MAX_SHAPE_TEXT,
    BoardBox,
    BoardEditEntry,
    ShapeObject,
    TextObject,
    apply_board_edit_entry,
    board_to_payload,
    default_board,
    normalize_board_payload,
)
from tests.ui.test_ultraview_page import _Harness, _blank_board_point


class _ShapeSink:
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
        self._commit(apply_author_create(self.board, intent), "shape-create")

    def _on_update(self, intent) -> None:
        self._commit(apply_author_update(self.board, intent), "shape-edit")

    def _on_delete(self, intent) -> None:
        self._commit(apply_author_delete(self.board, intent), "shape-delete")

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


class _ShapeHarness(_Harness):
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


def _arm_shape(page, shape: str = "rectangle") -> None:
    button = page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    assert button is not None and button.isEnabled()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    if page.interaction().last_shape() != shape:
        page.shape_popover().choose_shape(shape)
        QApplication.processEvents()
    assert page.interaction().active_tool() == TOOL_SHAPES
    assert page.interaction().last_shape() == shape


def _click_blank(free) -> None:
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    QApplication.processEvents()


def _drag_on_board(
    board,
    start: QPoint,
    end: QPoint,
    *,
    modifiers=Qt.NoModifier,
) -> None:
    QTest.mousePress(board, Qt.LeftButton, Qt.NoModifier, start)
    event = QMouseEvent(
        QEvent.MouseMove,
        end,
        board.mapToGlobal(end),
        Qt.NoButton,
        Qt.LeftButton,
        modifiers,
    )
    QApplication.sendEvent(board, event)
    QTest.mouseRelease(board, Qt.LeftButton, modifiers, end)
    QApplication.processEvents()


def _shape_item(board) -> ShapeObject:
    shapes = [item for item in board.author_objects if isinstance(item, ShapeObject)]
    assert len(shapes) == 1
    assert not any(isinstance(item, TextObject) for item in board.author_objects)
    return shapes[0]


def test_closed_shape_types_are_five_and_exclude_connectors():
    assert CLOSED_SHAPE_TYPES == (
        "rectangle",
        "rounded_rectangle",
        "oval",
        "rhombus",
        "triangle",
    )
    for forbidden in ("line", "arrow", "elbow", "elbow_arrow", "block_arrow", "divider"):
        assert forbidden not in CLOSED_SHAPE_TYPES


def test_shape_click_and_drag_boxes_honor_default_min_shift_alt_and_snap():
    click = shape_box_from_click((1.0, 2.0))
    assert click[2] == SHAPE_DEFAULT_WIDTH
    assert click[3] == SHAPE_DEFAULT_HEIGHT
    tiny = shape_box_from_points((0.0, 0.0), (0.1, 0.1))
    assert tiny[2] == SHAPE_DEFAULT_WIDTH
    assert tiny[3] == SHAPE_DEFAULT_HEIGHT
    drag = shape_box_from_points((10.0, 10.0), (14.0, 13.0))
    assert drag[2] == 4.0
    assert drag[3] == 3.0
    square = shape_box_from_points((10.0, 10.0), (14.0, 12.0), keep_aspect=True)
    assert square[2] == square[3]
    centered = shape_box_from_points((10.0, 10.0), (12.0, 11.0), from_center=True)
    assert centered[0] == 8.0
    assert centered[1] == 9.0
    assert centered[2] == 4.0
    assert centered[3] == 2.0
    snapped = shape_box_from_points((10.12, 10.12), (14.12, 13.12), snap=True)
    unsnapped = shape_box_from_points((10.12, 10.12), (14.12, 13.12), snap=False)
    assert snapped != unsnapped


def test_negative_shape_box_stays_signed_and_safety_clamps():
    negative = shape_box_from_click((-6.0, -3.0))
    assert negative[0] == -6.0
    assert negative[1] == -3.0
    clamped = shape_box_from_click((10_000.0, 10_000.0))
    assert clamped[0] + clamped[2] <= 120.0
    assert clamped[1] + clamped[3] <= 192.0


def test_eight_handles_resize_and_move_keep_min_size():
    box = (4.0, 4.0, 4.0, 3.0)
    for handle in ("nw", "n", "ne", "w", "e", "sw", "s", "se"):
        resized = resize_shape_box(box, handle, 1.0, 1.0)
        assert resized[2] >= SHAPE_MIN_WIDTH
        assert resized[3] >= SHAPE_MIN_HEIGHT
    moved = resize_shape_box(box, "move", 2.0, -1.0)
    assert moved[0] == 6.0
    assert moved[1] == 3.0
    assert moved[2] == 4.0
    assert moved[3] == 3.0
    aspect = resize_shape_box(box, "se", 4.0, 0.0, keep_aspect=True)
    assert abs(aspect[2] / aspect[3] - 4.0 / 3.0) < 0.05
    centered = resize_shape_box(box, "e", 2.0, 0.0, from_center=True)
    assert centered[2] >= box[2]


def test_shape_flyout_is_frame_with_five_visual_cells(qtbot):
    flyout = ShapePopover()
    qtbot.addWidget(flyout)
    assert isinstance(flyout, ToolFlyoutSurface)
    assert isinstance(flyout, QFrame)
    assert not isinstance(flyout, QMenu)
    assert flyout.shape_types() == CLOSED_SHAPE_TYPES
    cells = flyout.cell_buttons()
    assert len(cells) == 8
    assert all(cell.height() >= 36 for cell in cells)
    chosen: list[str] = []
    flyout.shape_selected.connect(chosen.append)
    flyout.choose_shape("triangle")
    assert chosen == ["triangle"]


def test_five_shapes_click_and_drag_create(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    free = harness.page._free_grid
    for shape in CLOSED_SHAPE_TYPES:
        harness.board.author_objects = []
        harness.page.set_board(harness.board)
        QApplication.processEvents()
        _arm_shape(harness.page, shape)
        _click_blank(free)
        item = _shape_item(harness.board)
        assert item.shape == shape
        assert item.text == ""
        assert item.box.width == SHAPE_DEFAULT_WIDTH
        assert item.box.height == SHAPE_DEFAULT_HEIGHT
        assert not any(isinstance(obj, TextObject) for obj in harness.board.author_objects)
        assert harness.page.interaction().active_tool() == TOOL_SELECT
        created_id = item.object_id
        harness.board.author_objects = []
        harness.page.set_board(harness.board)
        QApplication.processEvents()
        _arm_shape(harness.page, shape)
        start = _blank_board_point(free)
        end = QPoint(start.x() + 280, start.y() + 160)
        _drag_on_board(free, start, end)
        dragged = _shape_item(harness.board)
        assert dragged.shape == shape
        assert dragged.object_id != created_id
        assert dragged.box.width >= SHAPE_MIN_WIDTH
        assert dragged.box.height >= SHAPE_MIN_HEIGHT
        assert (dragged.box.width, dragged.box.height) != (
            SHAPE_DEFAULT_WIDTH,
            SHAPE_DEFAULT_HEIGHT,
        )
    assert sink.dirty is True
    assert len(sink.undo) == 10


def test_s_shortcut_arms_last_used_shape_and_does_not_steal_from_editor(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    _arm_shape(harness.page, "oval")
    _click_blank(harness.page._free_grid)
    assert _shape_item(harness.board).shape == "oval"
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    harness.page._on_shape_tool_shortcut()
    QApplication.processEvents()
    assert harness.page.interaction().active_tool() == TOOL_SHAPES
    assert harness.page.interaction().last_shape() == "oval"

    line = QLineEdit(harness.page)
    line.show()
    line.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    QTest.keyClick(line, Qt.Key_S)
    assert "s" in line.text().lower()


def test_shift_alt_cmd_modifiers_change_live_create_box(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    free = harness.page._free_grid
    _arm_shape(harness.page, "rectangle")
    start = _blank_board_point(free)
    end = QPoint(start.x() + 240, start.y() + 80)
    origin = pixels_to_board_point(
        (float(start.x()), float(start.y())),
        free.metrics(),
        origin_offset=free.author_paint_layer().model().origin_offset,
    )
    assert origin is not None
    _drag_on_board(free, start, end, modifiers=Qt.ShiftModifier)
    assert sink.dirty is True
    square = _shape_item(harness.board)
    assert abs(square.box.width - square.box.height) < 0.3

    harness.board.author_objects = []
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    _arm_shape(harness.page, "rectangle")
    _drag_on_board(free, start, end, modifiers=Qt.AltModifier)
    centered = _shape_item(harness.board)
    plain = shape_box_from_points(
        origin,
        pixels_to_board_point(
            (float(end.x()), float(end.y())),
            free.metrics(),
            origin_offset=free.author_paint_layer().model().origin_offset,
        ),
    )
    assert (centered.box.x, centered.box.y) != (plain[0], plain[1])

    harness.board.author_objects = []
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    _arm_shape(harness.page, "rectangle")
    _drag_on_board(free, start, end, modifiers=Qt.ControlModifier)
    unsnapped = _shape_item(harness.board)
    assert unsnapped.box.width >= SHAPE_MIN_WIDTH
    assert unsnapped.box.height >= SHAPE_MIN_HEIGHT


def test_move_resize_delete_lock_use_existing_author_apis(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    harness.board.author_objects = [
        ShapeObject(
            "shape-geo",
            "shape",
            box=BoardBox(2.0, 2.0, 4.0, 3.0),
            shape="rectangle",
            text="框",
        )
    ]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    mapped = board_box_to_pixels(
        (2.0, 2.0, 4.0, 3.0),
        harness.page._free_grid.metrics(),
        origin_offset=harness.page._free_grid.author_paint_layer().model().origin_offset,
    )
    assert mapped is not None
    handle = hit_box_handle(
        (int(mapped[0]), int(mapped[1]), int(mapped[2]), int(mapped[3])),
        (int(mapped[0] + mapped[2] - 2), int(mapped[1] + mapped[3] - 2)),
    )
    assert handle == "se"
    harness.page.author_update_requested.emit(
        ShapeUpdateIntent("shape-geo", box=(3.0, 2.0, 4.0, 3.0))
    )
    QApplication.processEvents()
    harness.page.author_update_requested.emit(
        ShapeUpdateIntent("shape-geo", box=(3.0, 2.0, 6.0, 3.0))
    )
    QApplication.processEvents()
    item = _shape_item(harness.board)
    assert item.box.x == 3.0
    assert item.box.width == 6.0
    assert len(sink.undo) == 2

    harness.page.interaction().select_only_author("shape-geo")
    harness.page._free_grid.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    lock = toolbar.button("lock")
    assert lock is not None
    QTest.mouseClick(lock, Qt.LeftButton)
    QApplication.processEvents()
    assert _shape_item(harness.board).locked is True
    toasts: list[str] = []
    harness.page.feedback_requested.connect(toasts.append)
    QTest.keyClick(harness.page._free_grid, Qt.Key_Delete)
    QApplication.processEvents()
    assert _shape_item(harness.board).object_id == "shape-geo"
    assert toasts
    harness.page.author_update_requested.emit(ShapeUpdateIntent("shape-geo", locked=False))
    QApplication.processEvents()
    QTest.keyClick(harness.page._free_grid, Qt.Key_Delete)
    QApplication.processEvents()
    assert harness.board.author_objects == []


def test_style_toolbar_fill_stroke_width_dash_corner_and_type_switch(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    harness.board.author_objects = [
        ShapeObject(
            "shape-style",
            "shape",
            box=BoardBox(2.0, 2.0, 4.0, 3.0),
            shape="rectangle",
            text="样式",
            fill_palette=None,
            stroke_palette="ink",
            stroke_width=1,
            line_style="solid",
            corner_radius=0,
        )
    ]
    harness.page.set_board(harness.board)
    harness.page.interaction().select_only_author("shape-style")
    harness.page._free_grid.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    assert toolbar.isVisible()
    assert toolbar.kind() == "shape"
    assert toolbar.button("fill") is not None
    assert toolbar.button("stroke") is not None
    assert toolbar.button("width") is not None
    assert toolbar.button("dash") is not None
    assert toolbar.button("corner") is not None
    def _pick(value) -> None:
        picker = harness.page.format_picker()
        assert picker.isVisible()
        chips = [
            child
            for child in picker.findChildren(QToolButton)
            if child.property("choiceValue") == value
        ]
        assert chips, value
        QTest.mouseClick(chips[0], Qt.LeftButton)
        QApplication.processEvents()

    QTest.mouseClick(toolbar.button("fill"), Qt.LeftButton)
    QApplication.processEvents()
    _pick("yellow")
    QTest.mouseClick(toolbar.button("stroke"), Qt.LeftButton)
    QApplication.processEvents()
    _pick("red")
    QTest.mouseClick(toolbar.button("width"), Qt.LeftButton)
    QApplication.processEvents()
    _pick(4)
    QTest.mouseClick(toolbar.button("dash"), Qt.LeftButton)
    QApplication.processEvents()
    _pick("dashed")
    QTest.mouseClick(toolbar.button("corner"), Qt.LeftButton)
    QApplication.processEvents()
    _pick(8)
    item = _shape_item(harness.board)
    assert item.fill_palette is not None
    assert item.stroke_palette != "ink" or item.stroke_width != 1 or item.line_style != "solid"
    assert item.corner_radius in {0, 8, 16, 24}
    assert item.text == "样式"
    box = (item.box.x, item.box.y, item.box.width, item.box.height)
    QTest.mouseClick(toolbar.button("shape"), Qt.LeftButton)
    QApplication.processEvents()
    _pick("rounded_rectangle")
    switched = _shape_item(harness.board)
    assert switched.shape == "rounded_rectangle"
    assert (switched.box.x, switched.box.y, switched.box.width, switched.box.height) == box
    assert switched.text == "样式"
    assert switched.fill_palette == item.fill_palette
    harness.page._refresh_author_toolbar()
    assert harness.page.selection_toolbar().button("corner") is not None

    harness.page.author_update_requested.emit(
        ShapeUpdateIntent("shape-style", shape="oval")
    )
    QApplication.processEvents()
    harness.page._refresh_author_toolbar()
    assert harness.page.selection_toolbar().button("corner") is None
    assert len(sink.undo) >= 2


def test_shape_label_ime_empty_and_6000_is_not_a_text_object(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    _arm_shape(harness.page, "rhombus")
    _click_blank(harness.page._free_grid)
    item = _shape_item(harness.board)
    assert item.text == ""
    assert len(sink.undo) == 1
    harness.page.interaction().select_only_author(item.object_id)
    harness.page._free_grid.sync_selection_projection()
    mapped = board_box_to_pixels(
        (item.box.x, item.box.y, item.box.width, item.box.height),
        harness.page._free_grid.metrics(),
        origin_offset=harness.page._free_grid.author_paint_layer().model().origin_offset,
    )
    assert mapped is not None
    center = QPoint(int(mapped[0] + mapped[2] / 2), int(mapped[1] + mapped[3] / 2))
    QTest.mouseDClick(harness.page._free_grid, Qt.LeftButton, Qt.NoModifier, center)
    QApplication.processEvents()
    editor = harness.page._free_grid.author_text_editor()
    assert editor.is_editing()
    preedit = QInputMethodEvent("ni", [])
    QApplication.sendEvent(editor, preedit)
    QTest.keyClick(editor, Qt.Key_Escape)
    QApplication.processEvents()
    assert editor.is_editing()
    commit = QInputMethodEvent()
    commit.setCommitString("菱形说明")
    QApplication.sendEvent(editor, commit)
    QApplication.processEvents()
    editor.commit()
    QApplication.processEvents()
    labeled = _shape_item(harness.board)
    assert labeled.text.endswith("菱形说明")
    assert not any(isinstance(obj, TextObject) for obj in harness.board.author_objects)

    editor_again = harness.page._free_grid.author_text_editor()
    QTest.mouseDClick(harness.page._free_grid, Qt.LeftButton, Qt.NoModifier, center)
    QApplication.processEvents()
    editor_again.setPlainText("")
    editor_again.commit()
    QApplication.processEvents()
    assert _shape_item(harness.board).text == ""
    assert isinstance(_shape_item(harness.board), ShapeObject)

    QTest.mouseDClick(harness.page._free_grid, Qt.LeftButton, Qt.NoModifier, center)
    QApplication.processEvents()
    toasts: list[str] = []
    harness.page.feedback_requested.connect(toasts.append)
    editor = harness.page._free_grid.author_text_editor()
    editor.setPlainText("x" * MAX_SHAPE_TEXT)
    assert len(editor.toPlainText()) == MAX_SHAPE_TEXT
    editor.setPlainText("x" * (MAX_SHAPE_TEXT + 1))
    assert len(editor.toPlainText()) == MAX_SHAPE_TEXT
    assert toasts
    assert "6000" in toasts[0]


def test_invalid_shape_create_is_named_validation():
    board = default_board()
    long = apply_author_create(
        board,
        ShapeCreateIntent(
            object_id="shape-long",
            box=(1.0, 1.0, 4.0, 3.0),
            shape="rectangle",
            text="y" * (MAX_SHAPE_TEXT + 1),
        ),
    )
    assert long.changed is False
    assert long.warnings == ("text_too_long",)
    assert warning_copy("text_too_long")
    unknown = apply_author_create(
        board,
        ShapeCreateIntent(
            object_id="shape-line",
            box=(1.0, 1.0, 4.0, 3.0),
            shape="line",
        ),
    )
    assert unknown.changed is False
    assert unknown.warnings == ("unsupported_author_kind",)


def test_create_path_emits_typed_shape_intent_not_text(qtbot):
    harness = _ShapeHarness(qtbot)
    created = []
    harness.page.author_create_requested.connect(created.append)
    _arm_shape(harness.page, "triangle")
    _click_blank(harness.page._free_grid)
    assert created
    assert isinstance(created[0], ShapeCreateIntent)
    assert created[0].shape == "triangle"
    assert harness.board.author_objects == []


def test_save_reopen_and_export_keep_shape_parity(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    _arm_shape(harness.page, "rounded_rectangle")
    _click_blank(harness.page._free_grid)
    item = _shape_item(harness.board)
    harness.page.author_update_requested.emit(
        ShapeUpdateIntent(item.object_id, text="圆角", fill_palette="blue", corner_radius=16)
    )
    QApplication.processEvents()
    assert sink.dirty is True
    original = _shape_item(harness.board)
    payload = board_to_payload(harness.board)
    reopened, warnings = normalize_board_payload(payload)
    assert warnings == []
    again = reopened.author_objects[0]
    assert isinstance(again, ShapeObject)
    assert again.shape == "rounded_rectangle"
    assert again.text == "圆角"
    assert again.fill_palette == "blue"
    assert again.corner_radius == 16
    assert again.object_id == original.object_id
    image = compose_board(reopened, {}, {}, scale=1, title=False)
    assert image.width() > 1 and image.height() > 1


def test_presentation_overview_template_do_not_create(qtbot):
    harness = _ShapeHarness(qtbot)
    sink = _ShapeSink(harness.page, harness.board)
    harness.page.set_presentation_active(True)
    QApplication.processEvents()
    button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    assert button is None or not button.isEnabled()
    harness.page._on_shape_tool_shortcut()
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    harness.page.set_presentation_active(False)

    harness.page.show_overview()
    QApplication.processEvents()
    overview_button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    assert overview_button is None or not overview_button.isEnabled()
    harness.page.hide_overview()
    QApplication.processEvents()

    harness.board.layout_mode = LAYOUT_MODE_TEMPLATE
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    template_button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    assert template_button is None or not template_button.isEnabled()
    _click_blank(harness.page._free_grid)
    assert harness.board.author_objects == []
    assert sink.undo == []
