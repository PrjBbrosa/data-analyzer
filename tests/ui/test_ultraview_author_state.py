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
