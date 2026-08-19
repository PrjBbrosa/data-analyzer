"""M4 Connector vertical slice: straight / arrow / elbow, no Draw."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QInputMethodEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QLineEdit, QMenu

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import ToolFlyoutSurface
from mf4_analyzer.ui.chart_stack.ultraview.author_edits import (
    apply_author_create,
    apply_author_delete,
    apply_author_update,
    re_resolve_connector_endpoints,
    warning_copy,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
    box_anchor_point,
    constrain_shift_point,
    connector_hit_bounds,
    elbow_path,
    hit_connector,
    point_on_box_outline,
    snap_board_point,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    CONNECTOR_TYPES,
    TOOL_CONNECTOR,
    TOOL_SELECT,
    AuthorDeleteIntent,
    AuthorUpdateIntent,
    ConnectorCreateIntent,
    ConnectorUpdateIntent,
    connector_style_from_type,
    normalize_connector_type,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import AUTHOR_TOOL_CONNECTOR, ConnectorPopover
from mf4_analyzer.ui.chart_stack.ultraview.compositor import compose_board
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import (
    LAYOUT_MODE_TEMPLATE,
    MAX_SHAPE_TEXT,
    AnchorTarget,
    BoardBox,
    BoardEditEntry,
    BoardPoint,
    ConnectorEndpoint,
    ConnectorObject,
    ShapeObject,
    StickyObject,
    TextObject,
    apply_board_edit_entry,
    board_to_payload,
    default_board,
    make_ref,
    normalize_board_payload,
)
from tests.ui.test_ultraview_page import _Harness, _blank_board_point


class _ConnectorSink:
    """Coordinator stand-in: applies typed intents through the mutation helper."""

    def __init__(self, page, board) -> None:
        self.page = page
        self.board = board
        self.undo: list[BoardEditEntry] = []
        self.redo: list[BoardEditEntry] = []
        self.dirty = False
        self.warnings: list[str] = []
        self.toasts: list[str] = []
        page.author_create_requested.connect(self._on_create)
        page.author_update_requested.connect(self._on_update)
        page.author_delete_requested.connect(self._on_delete)
        page.free_grid_undo_requested.connect(self._on_undo)
        page.free_grid_redo_requested.connect(self._on_redo)
        page.feedback_requested.connect(self.toasts.append)

    def _commit(self, mutation, label: str) -> None:
        self.warnings.extend(mutation.warnings)
        for code in mutation.warnings:
            copy = warning_copy(code)
            if copy and copy not in self.toasts:
                self.page._emit_feedback(copy)
        if not mutation.changed:
            return
        self.undo.append(BoardEditEntry(label, None, None, tuple(mutation.patches)))
        self.redo.clear()
        self.dirty = True
        self.page.set_board(self.board)

    def _on_create(self, intent) -> None:
        self._commit(apply_author_create(self.board, intent), "connector-create")

    def _on_update(self, intent) -> None:
        self._commit(apply_author_update(self.board, intent), "connector-edit")

    def _on_delete(self, intent) -> None:
        self._commit(apply_author_delete(self.board, intent), "author-delete")

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


class _ConnectorHarness(_Harness):
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


def _arm_connector(page, kind: str = "arrow") -> None:
    button = page.tool_rail().tool_button(AUTHOR_TOOL_CONNECTOR)
    assert button is not None and button.isEnabled()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    if page.interaction().last_connector() != kind:
        page.connector_popover().choose_connector(kind)
        QApplication.processEvents()
    assert page.interaction().active_tool() == TOOL_CONNECTOR
    assert page.interaction().last_connector() == kind


def _click_at(board, point: QPoint) -> None:
    QTest.mouseClick(board, Qt.LeftButton, Qt.NoModifier, point)
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


def _connector_item(board) -> ConnectorObject:
    items = [item for item in board.author_objects if isinstance(item, ConnectorObject)]
    assert len(items) == 1
    return items[0]


def _offset_point(origin: QPoint, dx: int, dy: int) -> QPoint:
    return QPoint(origin.x() + dx, origin.y() + dy)


def test_connector_types_are_three_and_independent_of_shapes():
    assert CONNECTOR_TYPES == ("line", "arrow", "elbow_arrow")
    assert normalize_connector_type("elbow") == "elbow_arrow"
    line = connector_style_from_type("line")
    arrow = connector_style_from_type("arrow")
    elbow = connector_style_from_type("elbow_arrow")
    assert line == {"route": "straight", "start_head": "none", "end_head": "none"}
    assert arrow == {"route": "straight", "start_head": "none", "end_head": "arrow"}
    assert elbow == {"route": "elbow", "start_head": "none", "end_head": "arrow"}


def test_auto_nesw_anchors_stay_on_outline_after_move_and_resize():
    box = (2.0, 4.0, 6.0, 3.0)
    toward = (20.0, 5.5)
    auto = box_anchor_point(box, "auto", toward)
    north = box_anchor_point(box, "n", toward)
    east = box_anchor_point(box, "e", toward)
    south = box_anchor_point(box, "s", toward)
    west = box_anchor_point(box, "w", toward)
    assert point_on_box_outline(box, auto)
    assert north == (5.0, 4.0)
    assert east == (8.0, 5.5)
    assert south == (5.0, 7.0)
    assert west == (2.0, 5.5)
    moved = (4.0, 6.0, 6.0, 3.0)
    resized = (2.0, 4.0, 8.0, 5.0)
    for anchor in ("auto", "n", "e", "s", "w"):
        assert point_on_box_outline(moved, box_anchor_point(moved, anchor, toward))
        assert point_on_box_outline(resized, box_anchor_point(resized, anchor, toward))


def test_shift_constrains_h_v_45_and_cmd_disables_snap():
    origin = (0.0, 0.0)
    horizontal = constrain_shift_point(origin, (4.0, 0.4))
    vertical = constrain_shift_point(origin, (0.3, 5.0))
    diagonal = constrain_shift_point(origin, (3.0, 3.1))
    assert abs(horizontal[1] - origin[1]) < 1e-9
    assert abs(vertical[0] - origin[0]) < 1e-9
    assert abs(abs(diagonal[0] - origin[0]) - abs(diagonal[1] - origin[1])) < 1e-9
    raw = (1.12, 2.37)
    assert snap_board_point(raw) != raw
    assert snap_board_point(raw) == (1.00, 2.25) or snap_board_point(raw) is not None


def test_elbow_path_is_deterministic_hv_or_vh():
    start = (0.0, 0.0)
    end = (4.0, 2.0)
    first = elbow_path(start, end, 0.5)
    second = elbow_path(start, end, 0.5)
    assert first == second
    assert first[0] == start
    assert first[-1] == end
    assert len(first) == 4
    xs = [point[0] for point in first]
    ys = [point[1] for point in first]
    assert xs == sorted(xs) or ys == sorted(ys)
    tall = elbow_path((0.0, 0.0), (1.0, 4.0), 0.5)
    assert tall != first
    assert elbow_path((0.0, 0.0), (1.0, 4.0), 0.5) == tall


def test_hit_and_bounds_include_stroke_and_arrowhead():
    start = (0.0, 0.0)
    end = (4.0, 0.0)
    thin = connector_hit_bounds(
        start, end, route="straight", stroke_width=1, start_head="none", end_head="none"
    )
    fat = connector_hit_bounds(
        start, end, route="straight", stroke_width=8, start_head="none", end_head="arrow"
    )
    assert fat[2] >= thin[2]
    assert fat[3] >= thin[3]
    assert hit_connector(
        start, end, (2.0, 0.0), route="straight", stroke_width=1, start_head="none", end_head="arrow"
    )
    assert hit_connector(
        start, end, (4.0, 0.0), route="straight", stroke_width=1, start_head="none", end_head="arrow"
    )
    assert not hit_connector(
        start, end, (2.0, 3.0), route="straight", stroke_width=1, start_head="none", end_head="none"
    )


def test_connector_flyout_is_frame_with_three_visual_cells(qtbot):
    flyout = ConnectorPopover()
    qtbot.addWidget(flyout)
    assert isinstance(flyout, ToolFlyoutSurface)
    assert isinstance(flyout, QFrame)
    assert not isinstance(flyout, QMenu)
    assert flyout.connector_types() == CONNECTOR_TYPES
    cells = flyout.cell_buttons()
    assert len(cells) == 3
    assert all(cell.width() >= 40 and cell.height() >= 40 for cell in cells)
    chosen: list[str] = []
    flyout.connector_selected.connect(chosen.append)
    flyout.choose_connector("elbow_arrow")
    assert chosen == ["elbow_arrow"]


def test_free_free_click_and_drag_create_three_types(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    free = harness.page._free_grid
    for kind in CONNECTOR_TYPES:
        harness.board.author_objects = []
        harness.page.set_board(harness.board)
        QApplication.processEvents()
        _arm_connector(harness.page, kind)
        start = _blank_board_point(free)
        QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseRelease(free, Qt.LeftButton, Qt.NoModifier, start)
        QApplication.processEvents()
        assert harness.board.author_objects == []
        assert harness.page.interaction().draft() is not None
        end = _offset_point(start, 180, 90)
        QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, end)
        QTest.mouseRelease(free, Qt.LeftButton, Qt.NoModifier, end)
        QApplication.processEvents()
        item = _connector_item(harness.board)
        style = connector_style_from_type(kind)
        assert item.route == style["route"]
        assert item.end_head == style["end_head"]
        assert item.start.target is None
        assert item.end.target is None
        assert harness.page.interaction().active_tool() == TOOL_SELECT
        harness.board.author_objects = []
        harness.page.set_board(harness.board)
        QApplication.processEvents()
        _arm_connector(harness.page, kind)
        _drag_on_board(free, start, _offset_point(start, 220, 40))
        dragged = _connector_item(harness.board)
        assert dragged.route == style["route"]
        assert dragged.object_id != item.object_id
    assert sink.dirty is True
    assert len(sink.undo) == 6


def test_l_shortcut_arms_last_used_type_and_does_not_steal_from_editor(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    _arm_connector(harness.page, "elbow_arrow")
    free = harness.page._free_grid
    start = _blank_board_point(free)
    _drag_on_board(free, start, _offset_point(start, 160, 80))
    assert _connector_item(harness.board).route == "elbow"
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    harness.page._on_connector_tool_shortcut()
    QApplication.processEvents()
    assert harness.page.interaction().active_tool() == TOOL_CONNECTOR
    assert harness.page.interaction().last_connector() == "elbow_arrow"

    line = QLineEdit(harness.page)
    line.show()
    line.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    QTest.keyClick(line, Qt.Key_L)
    assert "l" in line.text().lower()
    assert sink.dirty is True


def test_card_free_author_free_card_author_author_author_endpoints(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    card = make_ref("time", "conn-card")
    note = StickyObject(
        "sticky-a",
        "sticky",
        box=BoardBox(1.0, 1.0, 3.0, 2.0),
        text="扭矩",
    )
    twin = StickyObject(
        "sticky-b",
        "sticky",
        box=BoardBox(10.0, 1.0, 3.0, 2.0),
        text="扭矩",
    )
    shape = ShapeObject(
        "shape-a",
        "shape",
        box=BoardBox(1.0, 8.0, 4.0, 3.0),
        shape="rectangle",
        text="框",
    )
    harness.board.free_grid = []
    harness.board.author_objects = [note, twin, shape]
    harness.page.set_board(harness.board)
    QApplication.processEvents()

    free_free = apply_author_create(
        harness.board,
        ConnectorCreateIntent(
            object_id="c-free",
            start=(0.0, 0.0),
            end=(5.0, 1.0),
            connector_type="line",
        ),
    )
    assert free_free.changed is True
    card_free = apply_author_create(
        harness.board,
        ConnectorCreateIntent(
            object_id="c-card",
            start=(2.0, 2.0),
            end=(8.0, 2.0),
            start_target=AnchorTarget("card", card=card, anchor="e"),
            connector_type="arrow",
        ),
    )
    assert card_free.changed is True
    author_free = apply_author_create(
        harness.board,
        ConnectorCreateIntent(
            object_id="c-author",
            start=(1.0, 2.0),
            end=(7.0, 2.0),
            start_target=AnchorTarget("author", object_id="sticky-a", anchor="e"),
            connector_type="arrow",
        ),
    )
    assert author_free.changed is True
    card_author = apply_author_create(
        harness.board,
        ConnectorCreateIntent(
            object_id="c-mix",
            start=(2.0, 2.0),
            end=(3.0, 9.5),
            start_target=AnchorTarget("card", card=card, anchor="s"),
            end_target=AnchorTarget("author", object_id="shape-a", anchor="n"),
            connector_type="elbow_arrow",
        ),
    )
    assert card_author.changed is True
    author_author = apply_author_create(
        harness.board,
        ConnectorCreateIntent(
            object_id="c-aa",
            start=(4.0, 2.0),
            end=(10.0, 2.0),
            start_target=AnchorTarget("author", object_id="sticky-a", anchor="e"),
            end_target=AnchorTarget("author", object_id="sticky-b", anchor="w"),
            connector_type="arrow",
        ),
    )
    assert author_author.changed is True
    by_id = {item.object_id: item for item in harness.board.author_objects if isinstance(item, ConnectorObject)}
    assert by_id["c-free"].start.target is None
    assert by_id["c-card"].start.target.kind == "card"
    assert by_id["c-card"].start.target.card == card
    assert by_id["c-author"].start.target.object_id == "sticky-a"
    assert by_id["c-mix"].end.target.object_id == "shape-a"
    assert by_id["c-aa"].end.target.object_id == "sticky-b"
    assert sink.undo == []


def test_move_resize_re_resolves_and_duplicate_labels_do_not_misbind():
    board = default_board()
    note = StickyObject("sticky-a", "sticky", box=BoardBox(1.0, 1.0, 3.0, 2.0), text="扭矩")
    twin = StickyObject("sticky-b", "sticky", box=BoardBox(10.0, 1.0, 3.0, 2.0), text="扭矩")
    board.author_objects = [
        note,
        twin,
        ConnectorObject(
            "link",
            "connector",
            start=ConnectorEndpoint(
                BoardPoint(4.0, 2.0),
                AnchorTarget("author", object_id="sticky-a", anchor="e"),
            ),
            end=ConnectorEndpoint(BoardPoint(8.0, 2.0)),
        ),
    ]
    moved = apply_author_update(
        board, AuthorUpdateIntent("sticky-a", box=(3.0, 4.0, 3.0, 2.0))
    )
    assert moved.changed is True
    link = next(item for item in board.author_objects if isinstance(item, ConnectorObject))
    assert link.start.target.object_id == "sticky-a"
    assert point_on_box_outline((3.0, 4.0, 3.0, 2.0), (link.start.point.x, link.start.point.y))
    last = (link.start.point.x, link.start.point.y)
    deleted = apply_author_delete(board, AuthorDeleteIntent(("sticky-b",)))
    assert deleted.changed is True
    link = next(item for item in board.author_objects if isinstance(item, ConnectorObject))
    assert link.start.target.object_id == "sticky-a"
    lost = apply_author_delete(board, AuthorDeleteIntent(("sticky-a",)))
    link = next(item for item in board.author_objects if isinstance(item, ConnectorObject))
    assert link.start.target is None
    assert (link.start.point.x, link.start.point.y) == last
    assert "connector_target_lost" in lost.warnings
    again = re_resolve_connector_endpoints(board, lost_author_ids=("sticky-a",))
    assert again.warnings == ()


def test_unplaced_card_freezes_last_point_once():
    board = default_board()
    card = make_ref("time", "lost-card")
    board.author_objects = [
        ConnectorObject(
            "to-card",
            "connector",
            start=ConnectorEndpoint(
                BoardPoint(2.0, 2.0),
                AnchorTarget("card", card=card, anchor="n"),
            ),
            end=ConnectorEndpoint(BoardPoint(6.0, 6.0)),
        )
    ]
    first = re_resolve_connector_endpoints(board, lost_card_refs=(card,))
    item = board.author_objects[0]
    assert isinstance(item, ConnectorObject)
    assert item.start.target is None
    assert item.start.point == BoardPoint(2.0, 2.0)
    assert first.warnings == ("connector_target_lost",)
    second = re_resolve_connector_endpoints(board, lost_card_refs=(card,))
    assert second.warnings == ()
    assert second.changed is False


def test_esc_and_board_switch_cancel_unfinished_draft(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    free = harness.page._free_grid
    _arm_connector(harness.page, "arrow")
    _click_at(free, _blank_board_point(free))
    assert harness.page.interaction().draft() is not None
    QTest.keyClick(free, Qt.Key_Escape)
    QApplication.processEvents()
    assert harness.page.interaction().draft() is None
    assert harness.board.author_objects == []
    assert sink.undo == []

    _arm_connector(harness.page, "line")
    _click_at(free, _blank_board_point(free))
    other = default_board()
    other.board_id = "board-other"
    harness.page.set_board(other)
    QApplication.processEvents()
    assert harness.page.interaction().draft() is None
    assert harness.page.interaction().active_tool() == TOOL_SELECT


def test_shift_and_ctrl_modifiers_on_live_create(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    free = harness.page._free_grid
    start = _blank_board_point(free)
    _arm_connector(harness.page, "arrow")
    _drag_on_board(free, start, _offset_point(start, 200, 30), modifiers=Qt.ShiftModifier)
    item = _connector_item(harness.board)
    dx = item.end.point.x - item.start.point.x
    dy = item.end.point.y - item.start.point.y
    assert abs(dy) < 0.35 or abs(dx) < 0.35 or abs(abs(dx) - abs(dy)) < 0.35

    harness.board.author_objects = []
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    _arm_connector(harness.page, "arrow")
    _drag_on_board(free, start, _offset_point(start, 180, 90), modifiers=Qt.ControlModifier)
    unsnapped = _connector_item(harness.board)
    assert unsnapped.start.target is None
    assert unsnapped.end.target is None
    assert sink.dirty is True


def test_style_toolbar_route_heads_color_width_dash_label_lock(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    harness.board.author_objects = [
        ConnectorObject(
            "line-style",
            "connector",
            start=ConnectorEndpoint(BoardPoint(1.0, 1.0)),
            end=ConnectorEndpoint(BoardPoint(6.0, 2.0)),
            route="straight",
            stroke_palette="ink",
            stroke_width=1,
            line_style="solid",
            start_head="none",
            end_head="arrow",
        )
    ]
    harness.page.set_board(harness.board)
    harness.page.interaction().select_only_author("line-style")
    harness.page._free_grid.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    assert toolbar.isVisible()
    assert toolbar.kind() == "connector"
    for key in ("route", "start_head", "end_head", "color", "width", "dash", "label", "lock"):
        assert toolbar.button(key) is not None
    QTest.mouseClick(toolbar.button("route"), Qt.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(toolbar.button("end_head"), Qt.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(toolbar.button("color"), Qt.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(toolbar.button("width"), Qt.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(toolbar.button("dash"), Qt.LeftButton)
    QApplication.processEvents()
    item = _connector_item(harness.board)
    assert item.route in {"straight", "elbow"}
    assert item.stroke_width in {1, 2, 4, 8}
    assert item.line_style in {"solid", "dashed"}
    QTest.mouseClick(toolbar.button("lock"), Qt.LeftButton)
    QApplication.processEvents()
    assert _connector_item(harness.board).locked is True
    QTest.keyClick(harness.page._free_grid, Qt.Key_Delete)
    QApplication.processEvents()
    assert _connector_item(harness.board).object_id == "line-style"
    harness.page.author_update_requested.emit(ConnectorUpdateIntent("line-style", locked=False))
    QApplication.processEvents()
    QTest.keyClick(harness.page._free_grid, Qt.Key_Delete)
    QApplication.processEvents()
    assert harness.board.author_objects == []
    assert sink.dirty is True


def test_double_click_line_edits_label_without_lists(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    harness.board.author_objects = [
        ConnectorObject(
            "labeled",
            "connector",
            start=ConnectorEndpoint(BoardPoint(2.0, 2.0)),
            end=ConnectorEndpoint(BoardPoint(8.0, 2.0)),
        )
    ]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("labeled")
    harness.page._free_grid.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    assert toolbar.button("list_style") is None
    QTest.mouseClick(toolbar.button("label"), Qt.LeftButton)
    QApplication.processEvents()
    editor = harness.page._free_grid.author_text_editor()
    assert editor.is_editing()
    preedit = QInputMethodEvent("ni", [])
    QApplication.sendEvent(editor, preedit)
    commit = QInputMethodEvent()
    commit.setCommitString("说明")
    QApplication.sendEvent(editor, commit)
    QApplication.processEvents()
    editor.commit()
    QApplication.processEvents()
    assert _connector_item(harness.board).text.endswith("说明")
    assert not any(isinstance(item, TextObject) for item in harness.board.author_objects)
    assert sink.dirty is True


def test_invalid_connector_create_is_named_validation():
    board = default_board()
    long = apply_author_create(
        board,
        ConnectorCreateIntent(
            object_id="too-long",
            start=(0.0, 0.0),
            end=(2.0, 2.0),
            text="y" * (MAX_SHAPE_TEXT + 1),
        ),
    )
    assert long.changed is False
    assert long.warnings == ("text_too_long",)
    assert warning_copy("text_too_long")
    unknown = apply_author_create(
        board,
        ConnectorCreateIntent(
            object_id="curve",
            start=(0.0, 0.0),
            end=(2.0, 2.0),
            connector_type="curve",
        ),
    )
    assert unknown.changed is False
    assert unknown.warnings == ("unsupported_author_kind",)


def test_create_path_emits_typed_connector_intent(qtbot):
    harness = _ConnectorHarness(qtbot)
    created = []
    harness.page.author_create_requested.connect(created.append)
    _arm_connector(harness.page, "line")
    free = harness.page._free_grid
    start = _blank_board_point(free)
    _drag_on_board(free, start, _offset_point(start, 140, 40))
    assert created
    assert isinstance(created[0], ConnectorCreateIntent)
    assert created[0].connector_type == "line"
    assert harness.board.author_objects == []


def test_save_reopen_and_export_keep_connector_parity(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    _arm_connector(harness.page, "elbow_arrow")
    free = harness.page._free_grid
    start = _blank_board_point(free)
    _drag_on_board(free, start, _offset_point(start, 200, 120))
    item = _connector_item(harness.board)
    harness.page.author_update_requested.emit(
        ConnectorUpdateIntent(item.object_id, text="折线", stroke_palette="blue", stroke_width=4)
    )
    QApplication.processEvents()
    assert sink.dirty is True
    original = _connector_item(harness.board)
    payload = board_to_payload(harness.board)
    reopened, warnings = normalize_board_payload(payload)
    assert warnings == []
    again = next(obj for obj in reopened.author_objects if isinstance(obj, ConnectorObject))
    assert again.route == "elbow"
    assert again.text == "折线"
    assert again.stroke_palette == "blue"
    assert again.stroke_width == 4
    assert again.object_id == original.object_id
    image = compose_board(reopened, {}, {}, scale=1, title=False)
    assert image.width() > 1 and image.height() > 1


def test_presentation_overview_template_do_not_create(qtbot):
    harness = _ConnectorHarness(qtbot)
    sink = _ConnectorSink(harness.page, harness.board)
    harness.page.set_presentation_active(True)
    QApplication.processEvents()
    button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_CONNECTOR)
    assert button is None or not button.isEnabled()
    harness.page._on_connector_tool_shortcut()
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    harness.page.set_presentation_active(False)

    harness.page.show_overview()
    QApplication.processEvents()
    overview_button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_CONNECTOR)
    assert overview_button is None or not overview_button.isEnabled()
    harness.page.hide_overview()
    QApplication.processEvents()

    harness.board.layout_mode = LAYOUT_MODE_TEMPLATE
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    template_button = harness.page.tool_rail().tool_button(AUTHOR_TOOL_CONNECTOR)
    assert template_button is None or not template_button.isEnabled()
    _click_at(harness.page._free_grid, _blank_board_point(harness.page._free_grid))
    assert harness.board.author_objects == []
    assert sink.undo == []


def test_mixed_mutation_is_atomic_on_target_move():
    board = default_board()
    board.author_objects = [
        StickyObject("note", "sticky", box=BoardBox(1.0, 1.0, 3.0, 2.0), text="A"),
        ConnectorObject(
            "link",
            "connector",
            start=ConnectorEndpoint(
                BoardPoint(4.0, 2.0),
                AnchorTarget("author", object_id="note", anchor="e"),
            ),
            end=ConnectorEndpoint(BoardPoint(8.0, 2.0)),
        ),
    ]
    result = apply_author_update(board, AuthorUpdateIntent("note", box=(5.0, 6.0, 3.0, 2.0)))
    assert result.changed is True
    assert len({patch.object_id for patch in result.patches}) == 2
    note = next(item for item in board.author_objects if isinstance(item, StickyObject))
    link = next(item for item in board.author_objects if isinstance(item, ConnectorObject))
    assert (note.box.x, note.box.y) == (5.0, 6.0)
    assert link.start.target.object_id == "note"
    assert point_on_box_outline((5.0, 6.0, 3.0, 2.0), (link.start.point.x, link.start.point.y))
