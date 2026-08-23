"""Qt-free regression coverage for future UltraView Board extensions."""
from __future__ import annotations

import pytest

from mf4_analyzer.ui import ultraview_state as uvs


def _free_grid_payload(*, author_objects):
    return {
        "schema": uvs.ULTRAVIEW_SCHEMA,
        "board": {
            "board_id": "author-board",
            "layout_mode": "free_grid",
            "layout_id": "hero_left_4",
            "free_grid": {"columns": uvs.GRID_COLUMNS, "placements": []},
            "unplaced": [],
            "author_objects": author_objects,
        },
    }


def test_recognized_author_objects_round_trip_to_typed_qt_free_dtos():
    payload = _free_grid_payload(
        author_objects=[
            {
                "id": "sticky-1",
                "kind": "sticky",
                "box": {"x": -2.5, "y": 1.25, "width": 4, "height": 3},
                "text": "测试便签",
                "palette": "yellow",
                "shape": "square",
                "font_size": "auto",
            },
            {
                "id": "text-1",
                "kind": "text",
                "box": {"x": 2, "y": 1, "width": 5, "height": 2},
                "text": "说明",
                "font_role": "sans",
                "font_size": 16,
                "bold": True,
                "italic": False,
                "underline": False,
                "align": "left",
                "list_style": "none",
                "text_palette": "ink",
                "fill_palette": None,
                "opacity": 100,
                "link": "https://example.test",
            },
            {
                "id": "shape-1",
                "kind": "shape",
                "box": {"x": 9, "y": 2, "width": 4, "height": 3},
                "shape": "rhombus",
                "text": "判定",
                "fill_palette": "blue",
                "stroke_palette": "ink",
                "stroke_width": 2,
                "line_style": "solid",
                "text_style": {"font_size": 14, "bold": True, "align": "center"},
            },
            {
                "id": "stroke-1",
                "kind": "stroke",
                "points": [{"x": -3, "y": -1}, {"x": -2, "y": 0}],
                "tool": "pen",
                "palette": "blue",
                "width_px_100": 3,
            },
            {
                "id": "connector-1",
                "kind": "connector",
                "start": {
                    "point": {"x": 0, "y": 0},
                    "target": {"kind": "author", "object_id": "sticky-1", "anchor": "e"},
                },
                "end": {"point": {"x": 10, "y": 2}, "target": None},
                "route": "elbow",
                "elbow_bias": 0.5,
                "line_style": "dashed",
                "stroke_palette": "ink",
                "stroke_width": 2,
                "start_head": "none",
                "end_head": "arrow",
            },
        ]
    )

    board, warnings = uvs.normalize_board_payload(payload)

    assert warnings == []
    assert [type(item) for item in board.author_objects] == [
        uvs.StickyObject,
        uvs.TextObject,
        uvs.ShapeObject,
        uvs.StrokeObject,
        uvs.ConnectorObject,
    ]
    assert board.author_objects[0].box == uvs.BoardBox(-2.5, 1.25, 4, 3)
    assert board.author_objects[3].points == (
        uvs.BoardPoint(-3, -1),
        uvs.BoardPoint(-2, 0),
    )
    assert board.author_objects[4].start.target == uvs.AnchorTarget(
        kind="author", object_id="sticky-1", anchor="e"
    )
    restored, restored_warnings = uvs.normalize_board_payload(uvs.board_to_payload(board))
    assert restored_warnings == []
    assert restored.author_objects == board.author_objects


def test_author_normalization_rejects_known_invalid_items_but_preserves_unknown_order():
    payload = _free_grid_payload(
        author_objects=[
            {"id": "future-a", "kind": "future", "nested": {"keep": [1, 2]}},
            {
                "id": "bad-point",
                "kind": "stroke",
                "points": [{"x": float("nan"), "y": 0}, {"x": 1, "y": 1}],
                "tool": "pen",
                "palette": "blue",
                "width_px_100": 3,
            },
            {
                "id": "sticky-1",
                "kind": "sticky",
                "box": {"x": 0, "y": 0, "width": 2, "height": 2},
                "text": "ok",
                "palette": "yellow",
                "shape": "square",
                "font_size": "auto",
            },
            {
                "id": "sticky-1",
                "kind": "sticky",
                "box": {"x": 3, "y": 0, "width": 2, "height": 2},
                "text": "duplicate",
                "palette": "yellow",
                "shape": "square",
                "font_size": "auto",
            },
            {"id": "future-b", "kind": "another_future", "nested": ["A", {"B": 2}]},
        ]
    )

    board, warnings = uvs.normalize_board_payload(payload)

    assert [item.object_id for item in board.author_objects if not isinstance(item, uvs.UnknownAuthorObject)] == ["sticky-1"]
    assert [item.raw["id"] for item in board.author_objects if isinstance(item, uvs.UnknownAuthorObject)] == ["future-a", "future-b"]
    assert "illegal_author_object: stroke/bad-point" in warnings
    assert "duplicate_author_object_id: sticky-1" in warnings
    saved = uvs.board_to_payload(board)["board"]["author_objects"]
    assert [item["id"] for item in saved] == ["future-a", "sticky-1", "future-b"]
    saved[0]["nested"]["keep"].append(3)
    assert board.author_objects[0].raw["nested"]["keep"] == [1, 2]


def test_author_limits_safety_and_structured_target_are_deterministic():
    oversized_text = "x" * (uvs.MAX_STICKY_TEXT + 1)
    oversized_points = [{"x": 0, "y": 0}] * (uvs.MAX_STROKE_POINTS + 1)
    payload = _free_grid_payload(
        author_objects=[
            {
                "id": "outside",
                "kind": "sticky",
                "box": {"x": uvs.SAFETY_COLUMN_MAX - 1, "y": 0, "width": 2, "height": 2},
                "text": "x",
                "palette": "yellow",
                "shape": "square",
                "font_size": "auto",
            },
            {
                "id": "long-text",
                "kind": "sticky",
                "box": {"x": 0, "y": 0, "width": 2, "height": 2},
                "text": oversized_text,
                "palette": "yellow",
                "shape": "square",
                "font_size": "auto",
            },
            {
                "id": "long-stroke",
                "kind": "stroke",
                "points": oversized_points,
                "tool": "pen",
                "palette": "blue",
                "width_px_100": 3,
            },
            {
                "id": "connector",
                "kind": "connector",
                "start": {
                    "point": {"x": 0, "y": 0},
                    "target": {"kind": "author", "object_id": "missing", "anchor": "n"},
                },
                "end": {"point": {"x": 1, "y": 1}, "target": None},
                "route": "straight",
                "elbow_bias": None,
                "line_style": "solid",
                "stroke_palette": "ink",
                "stroke_width": 1,
                "start_head": "none",
                "end_head": "arrow",
            },
        ]
    )

    board, warnings = uvs.normalize_board_payload(payload)

    assert [item.object_id for item in board.author_objects] == ["connector"]
    assert board.author_objects[0].start.target is None
    assert "illegal_author_object: sticky/outside" in warnings
    assert "illegal_author_object: sticky/long-text" in warnings
    assert "illegal_author_object: stroke/long-stroke" in warnings
    assert "dangling_author_target: missing" in warnings


def test_board_item_key_and_anchor_target_reject_ambiguous_identity():
    card = uvs.make_ref("time", "same-name")
    assert uvs.BoardItemKey.card(card).to_dict() == {
        "kind": "card", "ref": {"section": "time", "view_id": "same-name"}
    }
    assert uvs.BoardItemKey.author("same-name").to_dict() == {
        "kind": "author", "object_id": "same-name"
    }
    with pytest.raises(uvs.UltraViewStateError):
        uvs.BoardItemKey("card", object_id="same-name")
    with pytest.raises(uvs.UltraViewStateError):
        uvs.AnchorTarget(kind="author", card=card, object_id="same-name")


def test_author_objects_clone_and_object_cap_are_independent_and_bounded():
    objects = [
        {
            "id": f"sticky-{index}",
            "kind": "sticky",
            "box": {"x": index % 20, "y": index // 20, "width": 1, "height": 1},
            "text": "x",
            "palette": "yellow",
            "shape": "square",
            "font_size": "auto",
        }
        for index in range(uvs.MAX_AUTHOR_OBJECTS + 1)
    ]
    workspace, warnings = uvs.normalize_workspace_payload(
        {
            "schema": uvs.ULTRAVIEW_SCHEMA,
            "workspace": {
                "active_board_id": "author-board",
                "boards": [_free_grid_payload(author_objects=objects)["board"]],
            },
        }
    )

    original = uvs.active_board(workspace)
    assert len(original.author_objects) == uvs.MAX_AUTHOR_OBJECTS
    assert "author_object_limit" in warnings
    clone = uvs.duplicate_board(workspace, "author-board")
    assert clone is not None
    assert clone.author_objects == original.author_objects
    assert clone.author_objects is not original.author_objects


def test_author_objects_persist_but_do_not_change_card_preview_identity_digest():
    board = uvs.default_board()
    before = uvs.presentation_digest(uvs.board_identity_payload(board))
    board.author_objects = [
        uvs.StickyObject(
            object_id="sticky-1",
            kind="sticky",
            box=uvs.BoardBox(0, 0, 2, 2),
            text="作者说明",
            palette="yellow",
        )
    ]

    assert "author_objects" in uvs.board_to_payload(board)["board"]
    assert uvs.presentation_digest(uvs.board_identity_payload(board)) == before


def test_unknown_nested_author_objects_are_deeply_isolated_through_duplicate_and_save():
    """Future Board fields cannot alias the source payload or a Board duplicate."""
    payload = {
        "schema": uvs.ULTRAVIEW_SCHEMA,
        "workspace": {
            "active_board_id": "original",
            "boards": [
                {
                    "board_id": "original",
                    "name": "原板",
                    "layout_mode": "free_grid",
                    "layout_id": "hero_left_4",
                    "free_grid": {"columns": uvs.GRID_COLUMNS, "placements": []},
                    "unplaced": [],
                    "future_extension": {
                        "author_objects": [
                            {
                                "id": "note-1",
                                "style": {"fill": "yellow", "tags": ["A", "B"]},
                            },
                            {"id": "note-2", "style": {"fill": "blue", "tags": []}},
                        ]
                    },
                }
            ],
        },
    }
    expected_author_objects = [
        {"id": "note-1", "style": {"fill": "yellow", "tags": ["A", "B"]}},
        {"id": "note-2", "style": {"fill": "blue", "tags": []}},
    ]

    workspace, warnings = uvs.normalize_workspace_payload(payload)
    assert warnings == []
    original = uvs.active_board(workspace)
    clone = uvs.duplicate_board(workspace, original.board_id)
    assert clone is not None

    clone.passthrough["future_extension"]["author_objects"][0]["style"]["fill"] = "pink"
    clone.passthrough["future_extension"]["author_objects"][0]["style"]["tags"].append("C")
    assert uvs.rename_board(workspace, clone.board_id, "作者副本") == []
    uvs.set_workspace_show_card_actions(workspace, True)

    saved = uvs.workspace_to_payload(workspace)
    original_saved, clone_saved = saved["workspace"]["boards"]
    assert original.passthrough["future_extension"]["author_objects"] == expected_author_objects
    assert payload["workspace"]["boards"][0]["future_extension"]["author_objects"] == expected_author_objects
    assert original_saved["future_extension"]["author_objects"] == expected_author_objects
    assert clone_saved["future_extension"]["author_objects"] == [
        {"id": "note-1", "style": {"fill": "pink", "tags": ["A", "B", "C"]}},
        {"id": "note-2", "style": {"fill": "blue", "tags": []}},
    ]
    assert [item["id"] for item in original_saved["future_extension"]["author_objects"]] == [
        "note-1",
        "note-2",
    ]
    original_saved["future_extension"]["author_objects"][0]["style"]["fill"] = "black"
    assert original.passthrough["future_extension"]["author_objects"] == expected_author_objects


def _sticky(object_id: str, *, x: float = 10.0, locked: bool = False):
    return uvs.StickyObject(
        object_id,
        "sticky",
        locked=locked,
        box=uvs.BoardBox(x, 10.0, 4.0, 3.0),
        text="便签",
        palette="yellow",
    )


def _unknown(object_id: str = "ghost"):
    return uvs.UnknownAuthorObject({"id": object_id, "kind": "widget", "label": "便签"})


def _connector(object_id: str, *, start_id: str | None = None, end_id: str | None = None):
    start_target = (
        uvs.AnchorTarget("author", object_id=start_id, anchor="e") if start_id else None
    )
    end_target = uvs.AnchorTarget("author", object_id=end_id, anchor="w") if end_id else None
    return uvs.ConnectorObject(
        object_id,
        "connector",
        start=uvs.ConnectorEndpoint(uvs.BoardPoint(5.0, 2.5), start_target),
        end=uvs.ConnectorEndpoint(uvs.BoardPoint(10.0, 2.5), end_target),
        route="straight",
        end_head="arrow",
    )


def _adjacent_cards():
    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    first = uvs.make_ref("time", "a")
    second = uvs.make_ref("time", "b")
    uvs.add_ref(board, first)
    uvs.add_ref(board, second)
    span_c = 4 * uvs.GRID_RESOLUTION
    span_r = 3 * uvs.GRID_RESOLUTION
    assert (
        uvs.set_free_grid_rects(
            board,
            (
                (first, uvs.GridRect(0, 0, span_c, span_r)),
                (second, uvs.GridRect(span_c, 0, span_c, span_r)),
            ),
        )
        == []
    )
    return board, first, second


def _item(board, object_id: str):
    for item in board.author_objects:
        if getattr(item, "object_id", "") == object_id:
            return item
        raw = getattr(item, "raw", None)
        if isinstance(raw, dict) and raw.get("id") == object_id:
            return item
    return None


def test_plan_selection_nudge_does_not_write_live_board_on_collision():
    from mf4_analyzer.ui.ultraview_edits import plan_selection_nudge

    board, first, second = _adjacent_cards()
    board.author_objects = [_sticky("note", x=10.0)]
    before = uvs.board_to_payload(board)
    plan = plan_selection_nudge(board, (first,), ("note",), 1.0, 0.0)
    assert plan.rejected
    assert "grid_collision" in {code.split(":", 1)[0] for code in plan.warnings}
    assert uvs.board_to_payload(board) == before
    assert plan.as_entry() is None


def test_mixed_nudge_success_moves_card_and_author_as_one_entry():
    from mf4_analyzer.ui.ultraview_edits import (
        commit_selection_plan,
        plan_selection_nudge,
    )

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    ref = uvs.make_ref("time", "ok")
    uvs.add_ref(board, ref)
    board.author_objects = [_sticky("note", x=10.0)]
    before_rect = uvs.free_grid_placement_for(board, ref).rect
    plan = plan_selection_nudge(board, (ref,), ("note",), 1.0, 0.0)
    assert not plan.rejected
    assert uvs.free_grid_placement_for(board, ref).rect == before_rect
    assert _item(board, "note").box.x == 10.0
    assert commit_selection_plan(board, plan) is True
    assert uvs.free_grid_placement_for(board, ref).rect.column == before_rect.column + 1
    assert _item(board, "note").box.x == 11.0
    entry = plan.as_entry()
    assert entry is not None
    assert entry.label == "mixed-nudge"
    assert uvs.apply_board_edit_entry(board, entry, forward=False) is True
    assert uvs.free_grid_placement_for(board, ref).rect == before_rect
    assert _item(board, "note").box.x == 10.0
    assert uvs.apply_board_edit_entry(board, entry, forward=True) is True
    assert uvs.free_grid_placement_for(board, ref).rect.column == before_rect.column + 1


def test_mixed_nudge_collision_moves_neither_and_has_no_entry():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board, first, _second = _adjacent_cards()
    board.author_objects = [_sticky("note", x=10.0)]
    card_rect = uvs.free_grid_placement_for(board, first).rect
    plan = plan_selection_nudge(board, (first,), ("note",), 1.0, 0.0)
    assert plan.rejected
    assert commit_selection_plan(board, plan) is False
    assert uvs.free_grid_placement_for(board, first).rect == card_rect
    assert _item(board, "note").box.x == 10.0
    assert any(code.split(":", 1)[0] == "grid_collision" for code in plan.warnings)


def test_mixed_nudge_past_safety_moves_neither():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    ref = uvs.make_ref("time", "bound")
    uvs.add_ref(board, ref)
    board.author_objects = [_sticky("note", x=4.0)]
    card_rect = uvs.free_grid_placement_for(board, ref).rect
    dx = float(uvs.SAFETY_COLUMN_MIN - card_rect.column - 4)
    plan = plan_selection_nudge(board, (ref,), ("note",), dx, 0.0)
    assert plan.rejected
    assert commit_selection_plan(board, plan) is False
    assert uvs.free_grid_placement_for(board, ref).rect == card_rect
    assert _item(board, "note").box.x == 4.0
    assert any(code.split(":", 1)[0] == "invalid_grid_rect" for code in plan.warnings)


def test_mixed_nudge_locked_author_rejects_and_moves_neither():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    ref = uvs.make_ref("time", "lock")
    uvs.add_ref(board, ref)
    board.author_objects = [_sticky("free", x=2.0), _sticky("held", x=8.0, locked=True)]
    before = uvs.board_to_payload(board)
    before_rect = uvs.free_grid_placement_for(board, ref).rect
    plan = plan_selection_nudge(board, (ref,), ("free", "held"), 1.0, 0.0)
    assert plan.rejected
    assert plan.skipped_locked == ("held",)
    assert plan.affected_card_refs == ()
    assert plan.affected_author_ids == ()
    assert plan.as_entry() is None
    assert any(code.split(":", 1)[0] == "author_locked" for code in plan.warnings)
    assert commit_selection_plan(board, plan) is False
    assert uvs.board_to_payload(board) == before
    assert uvs.free_grid_placement_for(board, ref).rect == before_rect
    assert _item(board, "free").box.x == 2.0
    assert _item(board, "held").box.x == 8.0


def test_mixed_nudge_unknown_author_rejects_and_does_not_dangle_connector():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    ref = uvs.make_ref("time", "ghost")
    uvs.add_ref(board, ref)
    board.author_objects = [
        _sticky("note", x=10.0),
        _unknown("ghost"),
        _connector("line", start_id="note", end_id="ghost"),
    ]
    before = uvs.board_to_payload(board)
    plan = plan_selection_nudge(board, (ref,), ("note", "ghost", "line"), 1.0, 0.0)
    assert plan.rejected
    assert plan.skipped_unknown == ("ghost",)
    assert plan.as_entry() is None
    assert any(code.split(":", 1)[0] == "unknown_author_object" for code in plan.warnings)
    assert commit_selection_plan(board, plan) is False
    assert uvs.board_to_payload(board) == before
    assert _item(board, "note").box.x == 10.0
    ghost = _item(board, "ghost")
    assert isinstance(ghost, uvs.UnknownAuthorObject)
    assert ghost.raw.get("id") == "ghost"
    line = _item(board, "line")
    assert isinstance(line, uvs.ConnectorObject)
    assert line.start.target is not None
    assert line.start.target.object_id == "note"
    assert line.end.target is not None
    assert line.end.target.object_id == "ghost"


def test_mixed_nudge_missing_card_ref_rejects_without_author_commit():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    placed = uvs.make_ref("time", "ok")
    missing = uvs.make_ref("time", "gone")
    uvs.add_ref(board, placed)
    board.author_objects = [_sticky("note", x=10.0)]
    before = uvs.board_to_payload(board)
    plan = plan_selection_nudge(board, (placed, missing), ("note",), 1.0, 0.0)
    assert plan.rejected
    assert plan.label == "mixed-nudge"
    assert plan.as_entry() is None
    assert any(code.split(":", 1)[0] == "missing_card_ref" for code in plan.warnings)
    assert commit_selection_plan(board, plan) is False
    assert uvs.board_to_payload(board) == before
    assert _item(board, "note").box.x == 10.0


def test_mixed_nudge_unplaced_card_rejects_whole_intent():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    placed = uvs.make_ref("time", "grid")
    tray = uvs.make_ref("time", "tray")
    uvs.add_ref(board, placed)
    uvs.add_ref(board, tray)
    assert uvs.move_to_unplaced(board, tray) == []
    board.author_objects = [_sticky("note", x=10.0)]
    before = uvs.board_to_payload(board)
    plan = plan_selection_nudge(board, (placed, tray), ("note",), 1.0, 0.0)
    assert plan.rejected
    assert any(code.split(":", 1)[0] == "unplaced_card" for code in plan.warnings)
    assert commit_selection_plan(board, plan) is False
    assert uvs.board_to_payload(board) == before


def test_mixed_nudge_stale_selection_rejects_without_history_entry():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board = uvs.default_board()
    board.layout_mode = uvs.LAYOUT_MODE_TEMPLATE
    live = uvs.make_ref("time", "live")
    stale = uvs.make_ref("time", "stale")
    uvs.add_ref(board, live)
    uvs.add_ref(board, stale)
    board.author_objects = [_sticky("note", x=4.0)]
    before = uvs.board_to_payload(board)
    plan = plan_selection_nudge(board, (live, stale), ("note",), 1.0, 0.0)
    assert plan.rejected
    assert any(code.split(":", 1)[0] == "stale_card_ref" for code in plan.warnings)
    assert plan.as_entry() is None
    assert commit_selection_plan(board, plan) is False
    assert uvs.board_to_payload(board) == before


def test_mixed_delete_missing_or_locked_target_rejects_and_keeps_board():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_delete

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    placed = uvs.make_ref("time", "keep")
    missing = uvs.make_ref("time", "absent")
    uvs.add_ref(board, placed)
    board.author_objects = [_sticky("note", x=20.0, locked=True)]
    before = uvs.board_to_payload(board)
    missing_plan = plan_selection_delete(board, (placed, missing), ("note",))
    assert missing_plan.rejected
    assert any(code.split(":", 1)[0] == "missing_card_ref" for code in missing_plan.warnings)
    assert commit_selection_plan(board, missing_plan) is False
    locked_plan = plan_selection_delete(board, (placed,), ("note",))
    assert locked_plan.rejected
    assert any(code.split(":", 1)[0] == "author_locked" for code in locked_plan.warnings)
    assert commit_selection_plan(board, locked_plan) is False
    assert uvs.board_to_payload(board) == before
    assert uvs.free_grid_placement_for(board, placed) is not None
    assert _item(board, "note") is not None


def test_mixed_delete_undo_redo_and_save_reopen_restore_membership():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_delete

    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    ref = uvs.make_ref("time", "save")
    uvs.add_ref(board, ref)
    board.author_objects = [_sticky("note", x=20.0), _connector("line", start_id="note")]
    before_payload = uvs.board_to_payload(board)
    plan = plan_selection_delete(board, (ref,), ("note",))
    assert not plan.rejected
    assert uvs.free_grid_placement_for(board, ref) is not None
    assert commit_selection_plan(board, plan) is True
    assert _item(board, "note") is None
    assert ref in board.unplaced
    assert uvs.free_grid_placement_for(board, ref) is None
    entry = plan.as_entry()
    assert entry is not None
    assert uvs.apply_board_edit_entry(board, entry, forward=False) is True
    assert _item(board, "note") is not None
    assert uvs.free_grid_placement_for(board, ref) is not None
    restored, warnings = uvs.normalize_board_payload(uvs.board_to_payload(board))
    assert warnings == []
    assert uvs.free_grid_placement_for(restored, ref) is not None
    assert uvs.apply_board_edit_entry(board, entry, forward=True) is True
    assert ref in board.unplaced
    reopened, reopen_warnings = uvs.normalize_board_payload(before_payload)
    assert reopen_warnings == []
    assert uvs.free_grid_placement_for(reopened, ref) is not None
    assert _item(reopened, "note") is not None


def test_repeated_nudge_records_only_accepted_intents():
    from mf4_analyzer.ui.ultraview_edits import commit_selection_plan, plan_selection_nudge

    board, first, second = _adjacent_cards()
    span_c = 4 * uvs.GRID_RESOLUTION
    span_r = 3 * uvs.GRID_RESOLUTION
    assert (
        uvs.set_free_grid_rects(
            board,
            (
                (first, uvs.GridRect(0, 0, span_c, span_r)),
                (second, uvs.GridRect(span_c + 1, 0, span_c, span_r)),
            ),
        )
        == []
    )
    board.author_objects = [_sticky("note", x=1.0)]
    accepted = []
    first_plan = plan_selection_nudge(board, (first,), ("note",), 1.0, 0.0)
    assert not first_plan.rejected
    assert commit_selection_plan(board, first_plan) is True
    accepted.append(first_plan.as_entry())
    card_rect = uvs.free_grid_placement_for(board, first).rect
    note_x = _item(board, "note").box.x
    rejected = plan_selection_nudge(board, (first,), ("note",), 1.0, 0.0)
    assert rejected.rejected
    assert commit_selection_plan(board, rejected) is False
    assert uvs.free_grid_placement_for(board, first).rect == card_rect
    assert _item(board, "note").box.x == note_x
    assert len(accepted) == 1
    assert any(code.split(":", 1)[0] == "grid_collision" for code in rejected.warnings)
