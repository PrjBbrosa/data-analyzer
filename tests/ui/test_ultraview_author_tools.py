"""UltraView R3: one BoardInteractionController owns tool/selection/draft."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtCore import QEvent, QPoint, QSize, Qt
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
    POINTER_MODE_LASER,
    POINTER_MODE_MOUSE,
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
from mf4_analyzer.ui.chart_stack.ultraview.laser_cursor import (
    LASER_CURSOR_HOTSPOT,
    LASER_CURSOR_LOGICAL_SIZE,
    LASER_CURSOR_PALETTE_VERSION,
    clear_laser_cursor_cache,
    laser_cursor_cache_key,
    laser_pointer_cursor,
)
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
    _east_handle_pos,
    _marquee,
    _prepare_free_grid,
    _send_mouse_move,
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
    from mf4_analyzer.ui.chart_stack.ultraview.board_pointer import PointerHitFacts

    facts = PointerHitFacts(
        editor_active=True,
        viewport_pan=True,
        resize_handle="e",
        author_hits_rev_z=(author,),
        card=card,
    )
    assert facts.resolve() == resolve_board_hit(
        editor_active=True,
        viewport_pan=True,
        resize_handle="e",
        author_hits_rev_z=(author,),
        card=card,
    )


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


def test_pointer_mode_is_transient_and_laser_keeps_select_state_without_payload():
    board = default_board()
    before = board_to_payload(board)
    controller = BoardInteractionController()
    assert controller.pointer_mode() == POINTER_MODE_MOUSE
    assert controller.is_laser_active() is False
    controller.select_only_author("missing")
    controller.set_pointer_mode("not-a-mode")
    assert controller.pointer_mode() == POINTER_MODE_MOUSE
    controller.set_active_tool(TOOL_STICKY)
    controller.begin_draft(TOOL_STICKY, origin=(1.0, 1.0))
    controller.activate_pointer_mode(POINTER_MODE_LASER)
    assert controller.pointer_mode() == POINTER_MODE_LASER
    assert controller.active_tool() == TOOL_SELECT
    assert controller.is_laser_active() is True
    assert controller.selection() == frozenset({AuthorKey("missing")})
    assert controller.draft() is None
    assert controller.transient_state()["pointer_mode"] == POINTER_MODE_LASER
    assert board_to_payload(board) == before
    controller.set_pointer_mode(POINTER_MODE_MOUSE)
    assert controller.active_tool() == TOOL_SELECT
    assert controller.selection() == frozenset({AuthorKey("missing")})
    assert controller.consume_escape() == ESC_SELECTION
    assert controller.pointer_mode() == POINTER_MODE_MOUSE
    controller.reset_session()
    assert controller.pointer_mode() == POINTER_MODE_MOUSE


def test_laser_cursor_keeps_select_clicks_and_resize_handles(qtbot):
    harness = _Harness(qtbot)
    free, (left, right) = _prepare_free_grid(harness, qtbot, "laser-0", "laser-1")
    controller = harness.page.interaction()
    before = board_to_payload(harness.board)
    _select_card(left)
    selected = controller.card_selection()
    harness.page._apply_pointer_mode(POINTER_MODE_LASER)
    QApplication.processEvents()
    assert controller.is_laser_active() is True
    assert controller.active_tool() == TOOL_SELECT
    assert controller.card_selection() == selected
    assert free.cursor().shape() == Qt.BitmapCursor
    laser_cursor = free.cursor()
    assert laser_cursor.pixmap().size() == QSize(32, 32)
    assert laser_cursor.hotSpot() == QPoint(25, 5)
    assert laser_cursor.pixmap().toImage().pixelColor(25, 5).red() > 180
    assert harness.page.board_scroll_area().viewport().cursor().shape() == Qt.BitmapCursor
    QTest.mouseClick(right, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    QApplication.processEvents()
    assert controller.is_laser_active() is True
    assert controller.card_selection() == frozenset({make_ref("time", "laser-1")})
    assert board_to_payload(harness.board) == before
    _send_mouse_move(right, _east_handle_pos(right), buttons=Qt.NoButton)
    assert right.cursor().shape() == Qt.SizeHorCursor
    harness.page._apply_pointer_mode(POINTER_MODE_MOUSE)
    assert controller.card_selection() == frozenset({make_ref("time", "laser-1")})
    assert harness.page.board_scroll_area().viewport().cursor().shape() == Qt.ArrowCursor


def _laser_dot_color(cursor):
    pixmap = cursor.pixmap()
    image = pixmap.toImage()
    dpr = float(pixmap.devicePixelRatioF()) or 1.0
    hot = cursor.hotSpot()
    x = min(image.width() - 1, max(0, int(round(hot.x() * dpr))))
    y = min(image.height() - 1, max(0, int(round(hot.y() * dpr))))
    return image.pixelColor(x, y)


def test_laser_cursor_pixmap_backing_and_hotspot_follow_dpr(qtbot):
    del qtbot
    clear_laser_cursor_cache()
    one = laser_pointer_cursor(dpr=1.0)
    two = laser_pointer_cursor(dpr=2.0)
    hot_x, hot_y = LASER_CURSOR_HOTSPOT
    hotspot = QPoint(hot_x, hot_y)

    one_pixmap = one.pixmap()
    assert abs(one_pixmap.devicePixelRatioF() - 1.0) < 1e-6
    assert one_pixmap.width() == LASER_CURSOR_LOGICAL_SIZE
    assert one_pixmap.height() == LASER_CURSOR_LOGICAL_SIZE
    assert one_pixmap.width() / one_pixmap.devicePixelRatioF() == LASER_CURSOR_LOGICAL_SIZE
    assert one.hotSpot() == hotspot
    assert _laser_dot_color(one).red() > 180

    two_pixmap = two.pixmap()
    assert abs(two_pixmap.devicePixelRatioF() - 2.0) < 1e-6
    assert two_pixmap.width() == LASER_CURSOR_LOGICAL_SIZE * 2
    assert two_pixmap.height() == LASER_CURSOR_LOGICAL_SIZE * 2
    assert two_pixmap.width() / two_pixmap.devicePixelRatioF() == LASER_CURSOR_LOGICAL_SIZE
    assert two.hotSpot() == hotspot
    assert _laser_dot_color(two).red() > 180


def test_laser_cursor_cache_identity_uses_dpr_size_and_palette(qtbot):
    del qtbot
    clear_laser_cursor_cache()
    one = laser_pointer_cursor(dpr=1.0)
    assert one is laser_pointer_cursor(dpr=1.0)
    two = laser_pointer_cursor(dpr=2.0)
    sized = laser_pointer_cursor(dpr=1.0, logical_size=48)
    paletted = laser_pointer_cursor(
        dpr=1.0,
        palette_version=LASER_CURSOR_PALETTE_VERSION + 1,
    )
    assert one is not two
    assert one is not sized
    assert one is not paletted
    assert laser_cursor_cache_key(dpr=1.0) != laser_cursor_cache_key(dpr=2.0)
    assert laser_cursor_cache_key(dpr=1.0, logical_size=32) != laser_cursor_cache_key(
        dpr=1.0, logical_size=48
    )
    assert laser_cursor_cache_key(dpr=1.0, palette_version=1) != laser_cursor_cache_key(
        dpr=1.0, palette_version=2
    )
    clear_laser_cursor_cache()
    rebuilt = laser_pointer_cursor(dpr=1.0)
    assert rebuilt is not one
    assert rebuilt is laser_pointer_cursor(dpr=1.0)


def test_laser_cursor_lifecycle_clears_cache_on_reset_screen_change_and_hide(qtbot):
    clear_laser_cursor_cache()
    board = FreeGridBoard()
    qtbot.addWidget(board)
    board.set_creation_allowed(True)
    board.interaction().activate_pointer_mode(POINTER_MODE_LASER)
    board.sync_tool_cursor()
    first = board.pointer_cursor()
    assert first is not None
    assert first is laser_pointer_cursor(dpr=float(board.devicePixelRatioF()) or 1.0)
    assert board.cursor().shape() == Qt.BitmapCursor

    board.reset_transient_interaction()
    assert board.interaction().is_laser_active() is False
    assert board.pointer_cursor() is None
    assert board.cursor().shape() != Qt.BitmapCursor

    board.set_creation_allowed(True)
    board.interaction().activate_pointer_mode(POINTER_MODE_LASER)
    board.sync_tool_cursor()
    after_reset = board.pointer_cursor()
    assert after_reset is not None
    assert after_reset is not first

    screen_change = getattr(QEvent, "ScreenChangeInternal", None) or getattr(
        QEvent, "DevicePixelRatioChange", None
    )
    if screen_change is not None:
        QApplication.sendEvent(board, QEvent(screen_change))
        after_screen = board.pointer_cursor()
        assert after_screen is not None
        assert after_screen is not after_reset

    live = board.pointer_cursor()
    # Page presentation / overview / leave-FreeGrid call set_creation_allowed(False).
    board.set_creation_allowed(False)
    assert board.pointer_cursor() is None
    assert board.cursor().shape() != Qt.BitmapCursor
    board.set_creation_allowed(True)
    board.interaction().activate_pointer_mode(POINTER_MODE_LASER)
    board.sync_tool_cursor()
    after_gate = board.pointer_cursor()
    assert after_gate is not None
    assert after_gate is not live

    board.show()
    qtbot.waitExposed(board)
    shown = board.pointer_cursor()
    board.hide()
    QApplication.processEvents()
    assert board.cursor().shape() != Qt.BitmapCursor
    board.show()
    qtbot.waitExposed(board)
    restored = board.pointer_cursor()
    assert restored is not None
    assert restored is not shown


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
    assert page.visible_author_tools() == ("select", "sticky", "text", "shapes", "draw")
    assert page.tool_rail().visible_author_tools() == ("select", "sticky", "text", "shapes", "draw")
    assert RELEASE_AUTHOR_TOOLS == ("select", "sticky", "text", "shapes", "draw")
    assert page.interaction() is page._free_grid.interaction()
    assert page._free_grid.gesture().interaction is page.interaction()


def test_author_controller_is_composed_bridge_not_second_session(qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.free_grid_author_controller import (
        FreeGridAuthorController,
    )
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage

    harness = _Harness(qtbot)
    page = harness.page
    board = page._free_grid
    controller = board.author_controller()
    assert isinstance(controller, FreeGridAuthorController)
    assert board.interaction() is page.interaction()
    assert board.interaction() is board._interaction
    assert controller is not board.interaction()
    assert isinstance(board.interaction(), BoardInteractionController)
    assert board._author_geometry_session is controller.geometry_session
    board._author_geometry_session = {"kind": "move"}
    assert controller.geometry_session is board._author_geometry_session
    assert controller.geometry_session == {"kind": "move"}
    board._author_geometry_session = None
    assert controller.geometry_session is None
    page_source = (ULTRAVIEW_ROOT / "page.py").read_text(encoding="utf-8")
    assert "_author_geometry_session" not in page_source
    assert FreeGridAuthorController not in UltraViewPage.__mro__
    assert not issubclass(UltraViewPage, FreeGridAuthorController)


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


def test_release_page_shows_select_sticky_text_and_shapes(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(1280, 760)
    page.show()
    page.set_board(default_board())
    QApplication.processEvents()
    assert page.visible_author_tools() == ("select", "sticky", "text", "shapes", "draw")
    rail = page.tool_rail()
    assert rail.visible_author_tools() == ("select", "sticky", "text", "shapes", "draw")
    assert rail.creation_section_visible() is True
    assert rail.tool_button("select") is not None
    assert rail.tool_button("text") is not None
    assert rail.tool_button("shapes") is not None
    assert rail.tool_button("connector") is None
    assert rail.tool_button("draw") is not None
    assert RELEASE_AUTHOR_TOOLS == ("select", "sticky", "text", "shapes", "draw")


def test_page_and_board_do_not_grow_parallel_selection_writes():
    page_tree = ast.parse((ULTRAVIEW_ROOT / "page.py").read_text(encoding="utf-8"))
    free_grid_tree = ast.parse((ULTRAVIEW_ROOT / "free_grid_board.py").read_text(encoding="utf-8"))
    gesture_tree = ast.parse((ULTRAVIEW_ROOT / "gesture.py").read_text(encoding="utf-8"))
    page_hits = _self_stores(_class(page_tree, "UltraViewPage"), {"_selected"})
    board_hits = _self_stores(
        _class(free_grid_tree, "FreeGridBoard"),
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
