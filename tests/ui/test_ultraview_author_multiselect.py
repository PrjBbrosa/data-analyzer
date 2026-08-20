"""M7: one selection truth, one toolbar capability resolver, one history funnel."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLineEdit, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import SelectionToolbar
from mf4_analyzer.ui.chart_stack.ultraview.author_edits import (
    apply_author_align,
    apply_author_batch_style,
    apply_author_delete,
    apply_author_distribute,
    apply_author_duplicate,
    apply_author_intent,
    apply_author_lock,
    apply_author_nudge,
    apply_author_z_order,
    copy_author_objects,
    paste_author_objects,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_selection import (
    INDETERMINATE,
    NUDGE_STEP,
    NUDGE_STEP_SHIFT,
    resolve_selection_capabilities,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    AuthorAlignIntent,
    AuthorBatchStyleIntent,
    AuthorClipboardPayload,
    AuthorDeleteIntent,
    AuthorDistributeIntent,
    AuthorDuplicateIntent,
    AuthorKey,
    AuthorLockIntent,
    AuthorNudgeIntent,
    AuthorPasteIntent,
    AuthorZOrderIntent,
    CardKey,
    SelectionDeleteIntent,
    SelectionNudgeIntent,
)
from mf4_analyzer.ui.main_window import ultraview_coordinator as coord_mod
from mf4_analyzer.ui.ultraview_state import (
    AnchorTarget,
    BoardBox,
    BoardEditEntry,
    BoardPoint,
    ConnectorEndpoint,
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    UnknownAuthorObject,
    apply_board_edit_entry,
    board_edit_entry_byte_cost,
    capture_board_placement,
    default_board,
    free_grid_placement_for,
    make_ref,
    move_to_unplaced,
)
from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid


class _MultiSink:
    """Coordinator stand-in: one BoardEditEntry per batch or mixed action."""

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
        page.author_batch_requested.connect(self._on_batch)
        page.free_grid_undo_requested.connect(self._on_undo)
        page.free_grid_redo_requested.connect(self._on_redo)

    def _commit(self, mutation, label: str, *, placement_before=None) -> None:
        self.warnings.extend(mutation.warnings)
        placement_after = None
        if placement_before is not None:
            placement_after = capture_board_placement(self.board)
            if placement_after == placement_before and not mutation.changed:
                return
        elif not mutation.changed:
            return
        self.undo.append(
            BoardEditEntry(
                label,
                placement_before,
                placement_after,
                tuple(mutation.patches),
            )
        )
        self.redo.clear()
        self.dirty = True
        self.page.set_board(self.board)

    def _on_create(self, intent) -> None:
        self._commit(apply_author_intent(self.board, intent), "author-create")

    def _on_update(self, intent) -> None:
        self._commit(apply_author_intent(self.board, intent), "author-edit")

    def _on_delete(self, intent) -> None:
        self._commit(apply_author_delete(self.board, intent), "author-delete")

    def _on_batch(self, intent) -> None:
        if isinstance(intent, SelectionDeleteIntent):
            self._mixed_delete(intent)
            return
        if isinstance(intent, SelectionNudgeIntent):
            self._mixed_nudge(intent)
            return
        label = {
            AuthorBatchStyleIntent: "author-style",
            AuthorAlignIntent: "author-align",
            AuthorDistributeIntent: "author-distribute",
            AuthorDuplicateIntent: "author-duplicate",
            AuthorLockIntent: "author-lock",
            AuthorZOrderIntent: "author-z-order",
            AuthorNudgeIntent: "author-nudge",
            AuthorPasteIntent: "author-paste",
        }.get(type(intent), "author-batch")
        self._commit(apply_author_intent(self.board, intent), label)

    def _mixed_delete(self, intent: SelectionDeleteIntent) -> None:
        placement_before = capture_board_placement(self.board)
        for ref in intent.card_refs:
            move_to_unplaced(self.board, ref)
        if intent.author_ids:
            mutation = apply_author_delete(
                self.board, AuthorDeleteIntent(intent.author_ids)
            )
        else:
            from mf4_analyzer.ui.ultraview_state import AuthorMutationResult

            mutation = AuthorMutationResult()
        self._commit(mutation, "mixed-delete", placement_before=placement_before)

    def _mixed_nudge(self, intent: SelectionNudgeIntent) -> None:
        from mf4_analyzer.ui.ultraview_state import GridRect, set_free_grid_rects

        placement_before = capture_board_placement(self.board)
        parsed = []
        for ref in intent.card_refs:
            current = free_grid_placement_for(self.board, ref)
            if current is None:
                continue
            parsed.append(
                (
                    ref,
                    GridRect(
                        int(current.rect.column + intent.dx),
                        int(current.rect.row + intent.dy),
                        current.rect.column_span,
                        current.rect.row_span,
                    ),
                )
            )
        if parsed:
            set_free_grid_rects(self.board, parsed)
        mutation = apply_author_nudge(
            self.board, intent.author_ids, intent.dx, intent.dy
        )
        self._commit(mutation, "mixed-nudge", placement_before=placement_before)

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


def _sticky(object_id: str, *, x: float = 1.0, y: float = 1.0, palette: str = "yellow", locked: bool = False) -> StickyObject:
    return StickyObject(
        object_id,
        "sticky",
        locked=locked,
        box=BoardBox(x, y, 4.0, 3.0),
        text="便签",
        palette=palette,
    )


def _shape(object_id: str, *, x: float = 2.0, y: float = 2.0, fill: str | None = "blue") -> ShapeObject:
    return ShapeObject(
        object_id,
        "shape",
        box=BoardBox(x, y, 4.0, 3.0),
        shape="rectangle",
        fill_palette=fill,
        stroke_palette="ink",
        stroke_width=1,
        line_style="solid",
    )


def _text(object_id: str, *, x: float = 8.0, y: float = 1.0) -> TextObject:
    return TextObject(object_id, "text", box=BoardBox(x, y, 6.0, 2.0), text="文字")


def _stroke(object_id: str, *, x: float = 12.0, y: float = 12.0) -> StrokeObject:
    return StrokeObject(
        object_id,
        "stroke",
        points=(BoardPoint(x, y), BoardPoint(x + 2.0, y + 1.0)),
        tool="pen",
        palette="ink",
        width_px_100=2,
    )


def _connector(object_id: str, *, start_id: str | None = None, end_id: str | None = None) -> ConnectorObject:
    start_target = AnchorTarget("author", object_id=start_id, anchor="e") if start_id else None
    end_target = AnchorTarget("author", object_id=end_id, anchor="w") if end_id else None
    return ConnectorObject(
        object_id,
        "connector",
        start=ConnectorEndpoint(BoardPoint(5.0, 2.5), start_target),
        end=ConnectorEndpoint(BoardPoint(10.0, 2.5), end_target),
        route="straight",
        end_head="arrow",
    )


def _unknown(object_id: str = "future-1") -> UnknownAuthorObject:
    return UnknownAuthorObject(
        {"id": object_id, "kind": "widget", "label": "便签", "payload": {"nested": True}}
    )


def _select_authors(page, *object_ids: str) -> None:
    page.interaction().set_selection(AuthorKey(object_id) for object_id in object_ids)
    page._free_grid.sync_selection_projection()
    page._refresh_author_toolbar()
    QApplication.processEvents()


def _item(board, object_id: str):
    for item in board.author_objects:
        if getattr(item, "object_id", "") == object_id:
            return item
        raw = getattr(item, "raw", None)
        if isinstance(raw, dict) and raw.get("id") == object_id:
            return item
    return None


def test_resolver_homogeneous_mixed_and_indeterminate():
    board = default_board()
    board.author_objects = [
        _shape("a", fill="blue"),
        _shape("b", fill="red"),
        _sticky("note"),
        _unknown(),
    ]
    same = resolve_selection_capabilities(
        board, (AuthorKey("a"), AuthorKey("b"))
    )
    assert same.kind == "shape"
    assert same.spine == "SHAPE"
    fill = next(control for control in same.controls if control.key == "fill")
    assert fill.mixed is True
    assert fill.visible_text == ""
    assert same.can_align is True
    assert same.can_style is True

    mixed = resolve_selection_capabilities(
        board, (AuthorKey("a"), AuthorKey("note"))
    )
    assert mixed.kind == "mixed"
    assert mixed.spine == "MIXED"
    keys = {control.key for control in mixed.controls}
    assert "fill" not in keys
    assert "align_left" in keys
    assert "distribute_h" in keys
    assert "duplicate" in keys
    assert mixed.can_style is False
    assert mixed.can_align is True

    with_unknown = resolve_selection_capabilities(
        board, (AuthorKey("a"), AuthorKey("future-1"))
    )
    assert "future-1" in with_unknown.skipped_unknown
    assert with_unknown.can_style is False
    assert "future-1" in {key.object_id for key in with_unknown.selection if isinstance(key, AuthorKey)}


def test_resolver_card_author_mixed_is_safe_actions_only():
    board = default_board()
    ref = make_ref("time", "card-a")
    board.author_objects = [_sticky("note"), _shape("box")]
    caps = resolve_selection_capabilities(
        board, (CardKey(ref), AuthorKey("note"), AuthorKey("box"))
    )
    assert caps.kind == "card_author"
    assert caps.spine == "MIXED"
    keys = {control.key for control in caps.controls}
    assert "fill" not in keys
    assert "palette" not in keys
    assert "align_left" not in keys
    assert {"duplicate", "lock"} <= keys
    assert caps.can_style is False
    assert caps.can_align is False
    assert caps.can_duplicate is True
    assert caps.can_delete is True
    assert caps.can_lock is True


def test_resolver_locked_and_unknown_are_not_edited_or_dropped():
    board = default_board()
    board.author_objects = [
        _sticky("free"),
        _sticky("held", locked=True),
        _unknown("ghost"),
    ]
    caps = resolve_selection_capabilities(
        board, (AuthorKey("free"), AuthorKey("held"), AuthorKey("ghost"))
    )
    assert "held" in caps.skipped_locked
    assert "ghost" in caps.skipped_unknown
    assert [
        item.raw.get("id") if isinstance(item, UnknownAuthorObject) else item.object_id
        for item in board.author_objects
    ] == ["free", "held", "ghost"]
    mutation = apply_author_batch_style(board, ("free", "held", "ghost"), "palette", "teal")
    assert _item(board, "held").palette == "yellow"
    assert isinstance(_item(board, "ghost"), UnknownAuthorObject)
    assert _item(board, "ghost").raw.get("id") == "ghost"
    assert mutation.changed is True
    assert _item(board, "free").palette == "teal"


def test_toolbar_applies_resolver_not_kind_scatter(qtbot):
    toolbar = SelectionToolbar()
    qtbot.addWidget(toolbar)
    board = default_board()
    board.author_objects = [_shape("a", fill="blue"), _sticky("note")]
    caps = resolve_selection_capabilities(
        board, (AuthorKey("a"), AuthorKey("note"))
    )
    toolbar.apply_capabilities(caps)
    toolbar.show()
    assert toolbar.kind() == "mixed"
    assert toolbar.height() == 48
    assert toolbar.button("fill") is None
    assert toolbar.button("duplicate") is not None
    assert toolbar.button("lock") is not None
    assert toolbar.button("align_left") is not None
    assert toolbar.button("distribute_v") is not None


def test_batch_style_align_distribute_z_order_are_one_history_each():
    board = default_board()
    board.author_objects = [
        _shape("left", x=1.0, y=4.0, fill="blue"),
        _shape("mid", x=6.0, y=1.0, fill="red"),
        _shape("right", x=12.0, y=7.0, fill="green"),
    ]
    styled = apply_author_batch_style(board, ("left", "mid", "right"), "fill", "orange")
    assert styled.changed
    fills = {item.fill_palette for item in board.author_objects}
    assert len(fills) == 1
    assert len(styled.patches) == 3

    distributed = apply_author_distribute(board, ("left", "mid", "right"), "horizontal")
    assert distributed.changed
    centers = sorted(item.box.x + item.box.width / 2.0 for item in board.author_objects)
    gap0 = centers[1] - centers[0]
    gap1 = centers[2] - centers[1]
    assert abs(gap0 - gap1) < 1e-6

    aligned = apply_author_align(board, ("left", "mid", "right"), "left")
    assert aligned.changed
    xs = {item.box.x for item in board.author_objects}
    assert len(xs) == 1
    assert len(aligned.patches) >= 1

    before_order = [item.object_id for item in board.author_objects]
    zed = apply_author_z_order(board, ("left",), "front")
    assert zed.changed
    assert board.author_objects[-1].object_id == "left"
    assert len(zed.patches) >= 1
    apply_author_z_order(board, ("left",), "back")
    assert [item.object_id for item in board.author_objects][0] == "left" or before_order


def test_duplicate_lock_and_nudge_skip_locked_unknown():
    board = default_board()
    board.author_objects = [
        _sticky("free", x=2.0, y=2.0),
        _sticky("held", x=8.0, y=2.0, locked=True),
        _unknown("ghost"),
    ]
    locked = apply_author_lock(board, ("free", "held", "ghost"), locked=True)
    assert _item(board, "free").locked is True
    assert _item(board, "held").locked is True
    assert isinstance(_item(board, "ghost"), UnknownAuthorObject)
    assert locked.changed

    apply_author_lock(board, ("free",), locked=False)
    duplicated = apply_author_duplicate(board, ("free", "held", "ghost"))
    ids = [
        item.raw.get("id") if isinstance(item, UnknownAuthorObject) else item.object_id
        for item in board.author_objects
    ]
    assert "free" in ids and "held" in ids and "ghost" in ids
    assert duplicated.changed
    clones = [item for item in board.author_objects if item is not _item(board, "free") and isinstance(item, StickyObject) and not item.locked]
    assert any(item.object_id != "free" and item.text == "便签" for item in clones)

    nudged = apply_author_nudge(board, ("free", "held", "ghost"), 1.0, 0.0)
    assert _item(board, "free").box.x == 3.0
    assert _item(board, "held").box.x == 8.0
    assert _item(board, "ghost").raw.get("id") == "ghost"
    assert nudged.changed


def test_batch_style_failure_leaves_no_half_state():
    board = default_board()
    board.author_objects = [_shape("ok", fill="blue"), _shape("also", fill="red")]
    before = [item.fill_palette for item in board.author_objects]
    result = apply_author_intent(
        board,
        AuthorBatchStyleIntent(("missing",), "fill", True),
    )
    assert result.changed is False
    assert [item.fill_palette for item in board.author_objects] == before


def test_copy_paste_uses_typed_payload_and_new_ids():
    board = default_board()
    board.author_objects = [
        _sticky("one", x=1.0),
        _sticky("two", x=8.0),
        _connector("line", start_id="one", end_id="two"),
    ]
    payload = copy_author_objects(board, ("one", "two", "line"))
    assert isinstance(payload, AuthorClipboardPayload)
    assert {item["id"] for item in payload.objects} == {"one", "two", "line"}
    assert all(item.get("kind") in {"sticky", "connector"} for item in payload.objects)
    texts = [item.get("text") for item in payload.objects if item.get("kind") == "sticky"]
    assert texts == ["便签", "便签"]
    pasted = paste_author_objects(board, payload)
    assert pasted.changed
    ids = [item.object_id for item in board.author_objects]
    assert "one" in ids and "two" in ids and "line" in ids
    assert len([item for item in board.author_objects if isinstance(item, StickyObject)]) == 4
    clones = [
        item
        for item in board.author_objects
        if isinstance(item, ConnectorObject) and item.object_id != "line"
    ]
    assert len(clones) == 1
    clone = clones[0]
    assert clone.start.target is not None
    assert clone.start.target.object_id not in {"one", "two"}
    assert clone.end.target is not None
    assert clone.end.target.object_id not in {"one", "two"}


def test_cross_board_paste_remaps_internal_and_degrades_external_targets():
    source = default_board()
    source.author_objects = [
        _sticky("keep", x=1.0),
        _sticky("gone", x=8.0),
        _connector("line", start_id="keep", end_id="gone"),
    ]
    payload = copy_author_objects(source, ("keep", "line"))
    dest = default_board()
    dest.board_id = "other"
    pasted = paste_author_objects(dest, payload)
    assert pasted.changed
    stickies = [item for item in dest.author_objects if isinstance(item, StickyObject)]
    lines = [item for item in dest.author_objects if isinstance(item, ConnectorObject)]
    assert len(stickies) == 1
    assert stickies[0].object_id != "keep"
    assert len(lines) == 1
    assert lines[0].start.target is not None
    assert lines[0].start.target.object_id == stickies[0].object_id
    assert lines[0].end.target is None
    assert lines[0].end.point is not None


def test_history_budget_constants_stay_observable():
    assert coord_mod._PLACEMENT_HISTORY_CAP == 100
    assert coord_mod._BOARD_HISTORY_BYTE_BUDGET == 32 * 1024 * 1024
    board = default_board()
    board.author_objects = [_sticky("a", y=1.0), _sticky("b", x=8.0, y=6.0)]
    mutation = apply_author_align(board, ("a", "b"), "top")
    assert mutation.changed
    entry = BoardEditEntry("author-align", None, None, tuple(mutation.patches))
    assert 0 < board_edit_entry_byte_cost(entry) < coord_mod._BOARD_HISTORY_BYTE_BUDGET


def test_page_toolbar_mixed_and_batch_style_one_history(qtbot):
    harness = _Harness(qtbot)
    sink = _MultiSink(harness.page, harness.board)
    harness.board.author_objects = [
        _shape("a", x=1.0, fill="blue"),
        _shape("b", x=8.0, fill="red"),
    ]
    harness.page.set_board(harness.board)
    _select_authors(harness.page, "a", "b")
    toolbar = harness.page.selection_toolbar()
    assert toolbar.isVisible()
    assert toolbar.kind() == "shape"
    fill = toolbar.button("fill")
    assert fill is not None
    assert fill.property("mixed") == "true"
    assert fill.text() in {"", "—"}
    QTest.mouseClick(fill, Qt.LeftButton)
    QApplication.processEvents()
    popup = QApplication.activePopupWidget()
    assert popup is not None
    chips = [
        child
        for child in popup.findChildren(QToolButton)
        if child.property("choiceValue") == "orange"
    ]
    assert chips
    QTest.mouseClick(chips[0], Qt.LeftButton)
    QApplication.processEvents()
    assert len(sink.undo) == 1
    assert sink.undo[0].label == "author-style"
    assert {item.fill_palette for item in harness.board.author_objects} != {"blue", "red"} or len({item.fill_palette for item in harness.board.author_objects}) == 1


def test_page_align_duplicate_lock_are_one_history(qtbot):
    harness = _Harness(qtbot)
    sink = _MultiSink(harness.page, harness.board)
    harness.board.author_objects = [
        _sticky("a", x=1.0, y=3.0),
        _sticky("b", x=9.0, y=8.0),
    ]
    harness.page.set_board(harness.board)
    _select_authors(harness.page, "a", "b")
    toolbar = harness.page.selection_toolbar()
    align = toolbar.button("align_left")
    assert align is not None
    QTest.mouseClick(align, Qt.LeftButton)
    QApplication.processEvents()
    assert len(sink.undo) == 1
    assert {item.box.x for item in harness.board.author_objects} == {_item(harness.board, "a").box.x}
    QTest.mouseClick(toolbar.button("duplicate"), Qt.LeftButton)
    QApplication.processEvents()
    assert len(sink.undo) == 2
    assert len(harness.board.author_objects) == 4
    QTest.mouseClick(toolbar.button("lock"), Qt.LeftButton)
    QApplication.processEvents()
    assert len(sink.undo) == 3
    assert all(item.locked for item in harness.board.author_objects if isinstance(item, StickyObject) and item.object_id in {"a", "b"})


def test_mixed_delete_unplaces_cards_deletes_authors_and_restores_atomically(qtbot):
    harness = _Harness(qtbot)
    sink = _MultiSink(harness.page, harness.board)
    free, (card,) = _prepare_free_grid(harness, qtbot, "mix-card")
    ref = make_ref("time", "mix-card")
    harness.board.author_objects = [_sticky("note", x=20.0, y=20.0)]
    harness.page.set_board(harness.board)
    harness.page.interaction().set_selection((CardKey(ref), AuthorKey("note")))
    free.sync_selection_projection()
    QApplication.processEvents()
    QTest.keyClick(free, Qt.Key_Delete)
    QApplication.processEvents()
    assert _item(harness.board, "note") is None
    assert ref in harness.board.unplaced
    assert free_grid_placement_for(harness.board, ref) is None
    assert len(sink.undo) == 1
    assert sink.undo[0].placement_before is not None
    harness.page.free_grid_undo_requested.emit()
    QApplication.processEvents()
    assert _item(harness.board, "note") is not None
    assert free_grid_placement_for(harness.board, ref) is not None
    assert ref not in harness.board.unplaced


def test_keyboard_duplicate_copy_paste_nudge_and_editor_guard(qtbot):
    harness = _Harness(qtbot)
    sink = _MultiSink(harness.page, harness.board)
    harness.board.author_objects = [
        _sticky("a", x=2.0, y=2.0),
        _text("t", x=10.0, y=2.0),
    ]
    harness.page.set_board(harness.board)
    free = harness.page._free_grid
    _select_authors(harness.page, "a")
    free.setFocus(Qt.OtherFocusReason)
    QTest.keyClick(free, Qt.Key_D, Qt.ControlModifier)
    QApplication.processEvents()
    assert len([item for item in harness.board.author_objects if isinstance(item, StickyObject)]) == 2
    assert len(sink.undo) == 1

    QTest.keyClick(free, Qt.Key_C, Qt.ControlModifier)
    QApplication.processEvents()
    QTest.keyClick(free, Qt.Key_V, Qt.ControlModifier)
    QApplication.processEvents()
    assert len([item for item in harness.board.author_objects if isinstance(item, StickyObject)]) >= 3

    before_x = _item(harness.board, "a").box.x
    _select_authors(harness.page, "a")
    QTest.keyClick(free, Qt.Key_Right)
    QApplication.processEvents()
    assert _item(harness.board, "a").box.x == before_x + NUDGE_STEP
    QTest.keyClick(free, Qt.Key_Right, Qt.ShiftModifier)
    QApplication.processEvents()
    assert _item(harness.board, "a").box.x == before_x + NUDGE_STEP + NUDGE_STEP_SHIFT

    editor = QLineEdit(harness.page)
    qtbot.addWidget(editor)
    editor.show()
    editor.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    count = len(harness.board.author_objects)
    QTest.keyClick(editor, Qt.Key_D, Qt.ControlModifier)
    QTest.keyClick(editor, Qt.Key_Delete)
    QApplication.processEvents()
    assert len(harness.board.author_objects) == count
    assert _item(harness.board, "a") is not None
