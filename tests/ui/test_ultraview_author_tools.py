"""UltraView R3: one BoardInteractionController owns tool/selection/draft."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    ESC_DRAFT,
    ESC_SELECT,
    ESC_SELECTION,
    HIT_AUTHOR,
    HIT_BLANK,
    HIT_CARD,
    HIT_EDITOR,
    HIT_RESIZE_HANDLE,
    HIT_VIEWPORT_PAN,
    STICKY_DEFAULT_HEIGHT,
    STICKY_DEFAULT_WIDTH,
    STICKY_MIN_HEIGHT,
    STICKY_MIN_WIDTH,
    TOOL_SELECT,
    TOOL_STICKY,
    AuthorKey,
    BoardInteractionController,
    CardKey,
    resolve_board_hit,
    sticky_box_from_click,
    sticky_box_from_points,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import RELEASE_AUTHOR_TOOLS
from mf4_analyzer.ui.chart_stack.ultraview.gesture import FreeGridGesture
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.chart_stack.ultraview.widgets import CardViewModel, FreeGridBoard
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    FreeGridPlacement,
    GRID_RESOLUTION,
    GridRect as _GridRect,
    StickyObject,
    board_to_payload,
    default_board,
    make_ref,
)
from tests.ui.test_ultraview_page import (
    _Harness,
    _blank_board_point,
    _drag_card,
    _marquee,
    _prepare_free_grid,
    _select_card,
    _selection_view_ids,
)


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)


def GridRect(column: int, row: int, column_span: int, row_span: int) -> _GridRect:
    return _GridRect(
        column * GRID_RESOLUTION,
        row * GRID_RESOLUTION,
        column_span * GRID_RESOLUTION,
        row_span * GRID_RESOLUTION,
    )


def _payload_has_transient(payload: dict) -> bool:
    blob = str(payload)
    return any(
        token in blob
        for token in (
            "active_tool",
            "pinned_tool",
            "hover_target",
            "'draft'",
            '"draft"',
            "BoardInteraction",
        )
    )


def test_card_and_author_keys_are_not_display_titles():
    card = make_ref("time", "same-name")
    assert CardKey(card) != AuthorKey("same-name")
    assert CardKey(card).ref is card
    assert AuthorKey("  note-1  ").object_id == "note-1"


def test_sticky_click_and_drag_boxes_honor_default_and_min_size():
    click = sticky_box_from_click((1.0, 2.0))
    assert click[2] == STICKY_DEFAULT_WIDTH
    assert click[3] == STICKY_DEFAULT_HEIGHT
    drag = sticky_box_from_points((0.0, 0.0), (0.2, 0.1))
    assert drag[2] == STICKY_DEFAULT_WIDTH
    assert drag[3] == STICKY_DEFAULT_HEIGHT
    real = sticky_box_from_points((10.0, 10.0), (13.0, 12.0))
    assert real[2] >= STICKY_MIN_WIDTH
    assert real[3] >= STICKY_MIN_HEIGHT
    assert real[2] == 3.0
    assert real[3] == 2.0


def test_hit_priority_editor_pan_handle_author_card_blank():
    card = CardKey(make_ref("time", "a"))
    author = AuthorKey("sticky-1")
    assert resolve_board_hit(
        editor_active=True,
        viewport_pan=True,
        resize_handle="e",
        author_hits_rev_z=(author,),
        card=card,
    ).kind == HIT_EDITOR
    assert resolve_board_hit(
        viewport_pan=True,
        resize_handle="e",
        author_hits_rev_z=(author,),
        card=card,
    ).kind == HIT_VIEWPORT_PAN
    assert resolve_board_hit(
        resize_handle="e",
        author_hits_rev_z=(author,),
        card=card,
    ).kind == HIT_RESIZE_HANDLE
    assert resolve_board_hit(
        author_hits_rev_z=(author, AuthorKey("under")),
        card=card,
    ) == resolve_board_hit(author_hits_rev_z=(author,), card=card)
    assert resolve_board_hit(author_hits_rev_z=(author,), card=card).kind == HIT_AUTHOR
    assert resolve_board_hit(card=card).kind == HIT_CARD
    assert resolve_board_hit().kind == HIT_BLANK


def test_gesture_selection_is_controller_projection():
    controller = BoardInteractionController()
    gesture = FreeGridGesture(controller)
    ref = make_ref("time", "g-0")
    gesture.select_only(ref)
    assert controller.card_selection() == frozenset({ref})
    assert gesture.selection() == controller.card_selection()
    gesture.toggle_selected(make_ref("time", "g-1"))
    assert controller.card_selection() == frozenset({ref, make_ref("time", "g-1")})
    gesture.clear_selection()
    assert controller.card_selection() == frozenset()
    assert controller.selection() == frozenset()


def test_tool_draft_cancel_commit_do_not_mutate_payload():
    board = default_board()
    board.author_objects = [
        StickyObject("note-1", "sticky", box=BoardBox(1.0, 1.0, 2.0, 2.0), text="hi")
    ]
    before = board_to_payload(board)
    controller = BoardInteractionController()
    controller.set_active_tool(TOOL_STICKY, pinned=True)
    controller.begin_draft(TOOL_STICKY, origin=(1.0, 2.0))
    controller.select_only_author("note-1")
    controller.begin_transaction("card_geometry", {"rects": {}})
    assert controller.consume_escape() == ESC_DRAFT
    assert controller.draft() is None
    controller.begin_draft(TOOL_STICKY)
    committed = controller.commit_draft()
    assert committed is not None and committed.tool == TOOL_STICKY
    controller.cancel_transaction()
    after = board_to_payload(board)
    assert after == before
    assert not _payload_has_transient(after)
    assert controller.active_tool() == TOOL_STICKY
    assert controller.consume_escape() == ESC_SELECT
    assert controller.active_tool() == TOOL_SELECT
    assert controller.consume_escape() == ESC_SELECTION
    assert not controller.selection()
    assert controller.transient_state()["draft"] is None


def test_sticky_palette_is_copied_into_the_next_draft():
    controller = BoardInteractionController()
    controller.set_sticky_palette("teal")
    draft = controller.begin_draft(TOOL_STICKY, origin=(1.0, 1.0), object_id="n1")
    assert draft.palette == "teal"
    controller.set_sticky_palette("not-a-color")
    assert controller.sticky_palette() == "yellow"
    assert controller.draft() is not None
    assert controller.draft().palette == "yellow"


def test_page_and_gesture_share_one_controller(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    assert page.visible_author_tools() == ("select", "sticky")
    assert page.tool_rail().visible_author_tools() == ("select", "sticky")
    assert RELEASE_AUTHOR_TOOLS == ("select", "sticky")
    assert page.interaction() is page._free_grid.interaction()
    assert page._free_grid.gesture().interaction is page.interaction()


def test_card_only_select_shift_marquee_blank_esc_delete_use_one_owner(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "own-0", "own-1")
    controller = harness.page.interaction()
    _select_card(left)
    assert controller.card_selection() == frozenset({make_ref("time", "own-0")})
    assert _selection_view_ids(free) == {"own-0"}
    assert harness.page.selected_ref() == ("time", "own-0")
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    assert {ref.view_id for ref in controller.card_selection()} == {"own-0", "own-1"}
    assert _selection_view_ids(free) == {"own-0", "own-1"}
    assert harness.page.selected_ref() == ("time", "own-0")

    start = QPoint(8, max(left.geometry().bottom(), right.geometry().bottom()) + 16)
    end = QPoint(
        max(left.geometry().right(), right.geometry().right()) - 8,
        min(left.geometry().top(), right.geometry().top()) + 8,
    )
    _marquee(free, start, end, shift=True)
    assert {ref.view_id for ref in controller.card_selection()} == {"own-0", "own-1"}

    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, _blank_board_point(free))
    assert controller.selection() == frozenset()
    assert _selection_view_ids(free) == set()
    assert harness.page.selected_ref() is None

    _select_card(left)
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    assert harness.page.handle_escape() is True
    assert controller.selection() == frozenset()
    assert harness.page.selected_ref() is None
    assert harness.page.handle_escape() is False

    _select_card(left)
    QTest.mouseClick(right, Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
    left.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(left, Qt.Key_Delete)
    assert set(harness.removed) == {("time", "own-0"), ("time", "own-1")}


def test_author_only_and_mixed_selection_stay_consistent(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "mix-0")
    note = StickyObject(
        "sticky-mix", "sticky", box=BoardBox(20.0, 20.0, 2.0, 2.0), text="便签"
    )
    harness.board.author_objects = [note]
    free.set_author_objects(harness.board.author_objects)
    controller = harness.page.interaction()
    controller.select_only_author("sticky-mix")
    free.sync_selection_projection()
    assert controller.author_selection_ids() == frozenset({"sticky-mix"})
    assert controller.card_selection() == frozenset()
    assert harness.page.selected_ref() is None
    assert free.author_selection_ids() == frozenset({"sticky-mix"})

    controller.toggle_card(make_ref("time", "mix-0"))
    free.sync_selection_projection()
    assert controller.author_selection_ids() == frozenset({"sticky-mix"})
    assert controller.card_selection() == frozenset({make_ref("time", "mix-0")})
    assert harness.page.selected_ref() == ("time", "mix-0")
    assert card.model().selected is True

    assert harness.page.clear_card_selection() is True
    assert controller.selection() == frozenset()
    assert free.author_selection_ids() == frozenset()
    assert card.model().selected is False


def test_board_switch_resets_transient_interaction(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "sw-0")
    _select_card(card)
    controller = harness.page.interaction()
    controller.begin_draft(TOOL_STICKY)
    controller.set_active_tool(TOOL_STICKY)
    other = default_board()
    other.board_id = "board-other"
    harness.page.set_board(other)
    assert controller.selection() == frozenset()
    assert controller.draft() is None
    assert controller.active_tool() == TOOL_SELECT
    assert harness.page.selected_ref() is None


def test_card_move_still_commits_after_controller_wiring(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "mv-0")
    requested = []
    harness.page.free_grid_geometry_requested.connect(lambda *a: requested.append(a))
    metrics = free.metrics()
    unit = metrics.column_width + metrics.gutter
    _drag_card(card, QPoint(16, 16), QPoint(16 + unit, 16))
    assert requested
    assert requested[0][1] == "mv-0"
    assert requested[0][6] in {"move", "drag-move"}


def test_release_page_shows_select_and_sticky_only(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(1280, 760)
    page.show()
    page.set_board(default_board())
    QApplication.processEvents()
    assert page.visible_author_tools() == ("select", "sticky")
    rail = page.tool_rail()
    assert rail.visible_author_tools() == ("select", "sticky")
    assert rail.creation_section_visible() is True
    assert rail.tool_button("text") is None
    assert rail.tool_button("shapes") is None
    assert rail.tool_button("draw") is None
    assert RELEASE_AUTHOR_TOOLS == ("select", "sticky")


def test_page_and_board_do_not_grow_parallel_selection_writes():
    page_tree = ast.parse((ULTRAVIEW_ROOT / "page.py").read_text(encoding="utf-8"))
    widgets_tree = ast.parse((ULTRAVIEW_ROOT / "widgets.py").read_text(encoding="utf-8"))
    gesture_tree = ast.parse((ULTRAVIEW_ROOT / "gesture.py").read_text(encoding="utf-8"))
    page_hits = _self_stores(_class(page_tree, "UltraViewPage"), {"_selected"})
    board_hits = _self_stores(
        _class(widgets_tree, "FreeGridBoard"),
        {"_author_selection_ids", "_card_selection", "_draft", "_selected"},
    )
    gesture_hits = _self_stores(
        _class(gesture_tree, "FreeGridGesture"), {"_selection"}
    )
    assert page_hits == [], page_hits
    assert board_hits == [], board_hits
    assert gesture_hits == [], gesture_hits


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def _is_self_attr(target: ast.AST, names: set[str]) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and target.attr in names
    )


def _self_stores(class_node: ast.ClassDef, names: set[str]) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(class_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if _is_self_attr(target, names):
                    hits.append(f"{target.attr}:{node.lineno}")
        elif isinstance(node, ast.AnnAssign) and _is_self_attr(node.target, names):
            hits.append(f"{node.target.attr}:{node.lineno}")
        elif isinstance(node, ast.AugAssign) and _is_self_attr(node.target, names):
            hits.append(f"{node.target.attr}:{node.lineno}")
    return hits


def _placement(view_id: str, rect: _GridRect) -> FreeGridPlacement:
    return FreeGridPlacement(make_ref("time", view_id), rect)


def _model(view_id: str) -> CardViewModel:
    image = QImage(48, 32, QImage.Format_ARGB32)
    image.fill(Qt.blue)
    return CardViewModel(
        slot_id=view_id,
        section="time",
        view_id=view_id,
        image=image,
    )


def test_standalone_board_resize_still_arms_gesture(qtbot):
    board = FreeGridBoard()
    qtbot.addWidget(board)
    ref = make_ref("time", "rz-0")
    board.set_free_grid(
        [_placement("rz-0", GridRect(0, 0, 4, 3))],
        {ref: _model("rz-0")},
    )
    board.resize(board.minimumSize())
    board.show()
    qtbot.waitExposed(board)
    QApplication.processEvents()
    card = board.card_for("time", "rz-0")
    assert card is not None
    board.select_only("time", "rz-0")
    start = QPoint(card.width() - 2, card.height() // 2)
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, start)
    event = QMouseEvent(
        QEvent.MouseMove,
        QPoint(start.x() + 24, start.y()),
        card.mapToGlobal(QPoint(start.x() + 24, start.y())),
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(card, event)
    QApplication.processEvents()
    assert board.gesture().is_armed()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, QPoint(start.x() + 24, start.y()))
