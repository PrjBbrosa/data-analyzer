"""Qt-free UltraView board / digest / axis contracts (UV-A01–A05, A10, A25, A27)."""
from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path

import pytest

from mf4_analyzer.ui import ultraview_state as uvs


STATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "ultraview_state.py"
)


def _ref(section="time", view_id="view-a") -> uvs.UltraViewRef:
    return uvs.make_ref(section, view_id)


def _filled(layout_id: str, count: int | None = None) -> uvs.UltraViewBoardState:
    board = uvs.default_board()
    uvs.set_layout(board, layout_id)
    slots = uvs.layout_slots(board.layout_id)
    n = len(slots) if count is None else count
    for i in range(n):
        uvs.add_ref(board, _ref("time", f"v{i}"))
    return board


def test_module_has_no_qt_or_compute_imports():
    tree = ast.parse(STATE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    forbidden = {
        "PyQt5",
        "sip",
        "MainWindow",
        "chart_stack",
        "numpy",
        "signal",
        "batch_compute",
    }
    assert forbidden.isdisjoint(imported)


def test_ref_accepts_only_gui_sections_and_stable_id():
    for section in uvs.SOURCE_SECTIONS:
        ref = uvs.make_ref(section, "stable-id")
        assert ref.section == section
        assert ref.view_id == "stable-id"

    with pytest.raises(uvs.UltraViewStateError):
        uvs.make_ref("order_time", "stable-id")
    with pytest.raises(uvs.UltraViewStateError):
        uvs.make_ref("time", "")
    with pytest.raises(uvs.UltraViewStateError):
        uvs.make_ref("time", "   ")
    assert uvs.parse_ref_payload({"section": "order_time", "view_id": "x"}) is None
    assert uvs.parse_ref_payload({"section": "fft", "view_id": "abc"}) == _ref(
        "fft", "abc"
    )


def test_default_board_identity():
    board = uvs.default_board()
    assert board.name == "全局对比"
    assert board.layout_id == "hero_left_4"
    assert board.layout_mode == uvs.LAYOUT_MODE_FREE_GRID
    assert board.viewport == {}
    assert board.primary_ratio == pytest.approx(0.67)
    assert board.placements == []
    assert board.unplaced == []
    assert board.board_id
    other = uvs.default_board()
    assert other.board_id != board.board_id


def test_workspace_board_lifecycle_keeps_board_identity_and_membership_isolated():
    workspace = uvs.default_workspace()
    first = uvs.active_board(workspace)
    ref = _ref("fft", "first")
    uvs.add_ref(first, ref)

    second = uvs.create_board(workspace, name="频谱对比")
    assert [board.name for board in workspace.boards] == ["全局对比", "频谱对比"]
    assert uvs.active_board(workspace) is second
    assert ref not in uvs.membership_set(second)

    clone = uvs.duplicate_board(workspace, first.board_id)
    assert clone is not None
    assert clone.board_id not in {first.board_id, second.board_id}
    assert ref in uvs.membership_set(clone)
    assert uvs.active_board(workspace) is clone

    assert uvs.rename_board(workspace, clone.board_id, "副本") == []
    assert clone.name == "副本"
    assert uvs.reorder_board(workspace, clone.board_id, 0) == []
    assert workspace.boards[0] is clone
    assert uvs.delete_board(workspace, clone.board_id) == []
    assert clone not in workspace.boards
    assert uvs.delete_board(workspace, first.board_id) == []
    assert uvs.delete_board(workspace, second.board_id) == ["last_board_retained"]


def test_ui_board_limit_blocks_create_but_loader_keeps_all_boards():
    workspace = uvs.default_workspace()
    for _ in range(19):
        assert uvs.create_board(workspace) is not None
    assert len(workspace.boards) == 20
    assert uvs.create_board(workspace) is None
    assert uvs.duplicate_board(workspace, workspace.boards[0].board_id) is None

    payload = {
        "schema": 3,
        "workspace": {
            "active_board_id": "b0",
            "boards": [
                {
                    "board_id": f"b{index}",
                    "name": f"B{index}",
                    "layout_id": "hero_left_4",
                    "placements": [],
                    "unplaced": [],
                }
                for index in range(21)
            ],
        },
    }
    loaded, warnings = uvs.normalize_workspace_payload(payload)
    assert len(loaded.boards) == 21
    assert any(item.startswith("ui_board_limit") for item in warnings)
    assert all(board.layout_mode == uvs.LAYOUT_MODE_TEMPLATE for board in loaded.boards)


def test_best_template_for_picks_smallest_equal_grid_that_fits():
    assert uvs.best_template_for(0) == "split_horizontal"
    assert uvs.best_template_for(1) == "split_horizontal"
    assert uvs.best_template_for(2) == "split_horizontal"
    assert uvs.best_template_for(3) == "grid_2x2"
    assert uvs.best_template_for(4) == "grid_2x2"
    assert uvs.best_template_for(5) == "grid_3x2"
    assert uvs.best_template_for(6) == "grid_3x2"
    assert uvs.best_template_for(7) == "grid_3x3"
    assert uvs.best_template_for(9) == "grid_3x3"
    assert uvs.best_template_for(10) == "grid_4x3"
    assert uvs.best_template_for(12) == "grid_4x3"
    assert uvs.best_template_for(24) == "grid_4x3"


def test_missing_layout_mode_restores_as_template_not_current_default():
    payload = {
        "schema": 3,
        "board": {
            "layout_id": "grid_2x2",
            "placements": [
                {"slot_id": "tl", "section": "time", "view_id": "a"},
            ],
        },
    }
    board, warnings = uvs.normalize_board_payload(payload)
    assert warnings == []
    assert board.layout_mode == uvs.LAYOUT_MODE_TEMPLATE
    assert board.layout_id == "grid_2x2"
    assert [item.ref.view_id for item in board.placements] == ["a"]


def test_hostile_tray_payload_truncates_membership_with_warning():
    unplaced = [
        {"section": "time", "view_id": f"tray-{index}"}
        for index in range(uvs.MAX_BOARD_MEMBERSHIP + 8)
    ]
    payload = {
        "schema": 3,
        "workspace": {"boards": [{"placements": [], "unplaced": unplaced}]},
    }
    loaded, warnings = uvs.normalize_workspace_payload(payload)
    board = uvs.active_board(loaded)
    assert len(uvs.membership_set(board)) == uvs.MAX_BOARD_MEMBERSHIP
    assert any(item.startswith("membership_truncated") for item in warnings)


def test_workspace_migrates_schema_one_and_preserves_future_until_mutation():
    legacy = {
        "schema": 1,
        "board": {
            "board_id": "legacy-board",
            "name": "旧总览",
            "layout_id": "split_horizontal",
            "primary_ratio": 0.67,
            "placements": [{"slot_id": "left", "section": "time", "view_id": "old"}],
            "unplaced": [],
        },
    }
    migrated, warnings = uvs.normalize_workspace_payload(legacy)
    assert warnings == []
    assert uvs.active_board(migrated).board_id == "legacy-board"
    payload = uvs.workspace_to_payload(migrated)
    assert payload["schema"] == uvs.ULTRAVIEW_SCHEMA
    assert payload["workspace"]["boards"][0]["placements"][0]["view_id"] == "old"

    future = {"schema": 99, "workspace": {"boards": [{"unknown": "keep"}]}, "future": True}
    opaque, warnings = uvs.normalize_workspace_payload(future)
    assert warnings == ["future_ultraview_schema: 99"]
    assert uvs.workspace_to_payload(opaque) == future
    uvs.create_board(opaque)
    assert uvs.workspace_to_payload(opaque)["schema"] == uvs.ULTRAVIEW_SCHEMA


def test_future_schema_overlays_sidecar_descriptor_without_dropping_opaque_body():
    future = {"schema": 99, "workspace": {"boards": [{"unknown": "keep"}]}, "future": True}
    workspace, warnings = uvs.normalize_workspace_payload(future)
    assert warnings == ["future_ultraview_schema: 99"]
    descriptor = {
        "format": 1,
        "path": "session.tlproj.ultraview/abc.uvpz",
        "generation": "abc",
        "manifest_sha256": "a" * 64,
    }
    uvs.set_workspace_preview_sidecar(workspace, descriptor)
    payload = uvs.workspace_to_payload(workspace)
    assert payload["schema"] == 99
    assert payload["future"] is True
    assert payload["workspace"]["boards"][0]["unknown"] == "keep"
    assert payload["preview_sidecar"] == descriptor
    uvs.set_workspace_preview_sidecar(workspace, None)
    assert "preview_sidecar" not in uvs.workspace_to_payload(workspace)


def test_free_grid_legalizes_collisions_and_template_conversion_keeps_tray():
    board = _filled("hero_left_4")
    tray_ref = _ref("order", "tray")
    uvs.add_ref(board, tray_ref)
    original = set(uvs.all_refs(board))

    assert uvs.template_to_free_grid(board) == []
    assert board.layout_mode == uvs.LAYOUT_MODE_FREE_GRID
    assert tray_ref in board.unplaced
    first, second = [item.ref for item in board.free_grid[:2]]
    first_rect = board.free_grid[0].rect
    second_before = board.free_grid[1].rect
    assert uvs.set_free_grid_rect(board, second, first_rect) == ["grid_collision"]
    assert board.free_grid[1].rect == second_before

    assert uvs.free_grid_to_template(board, "split_horizontal") == []
    assert board.layout_mode == uvs.LAYOUT_MODE_TEMPLATE
    assert set(uvs.all_refs(board)) == original
    assert tray_ref in board.unplaced


def test_set_free_grid_rects_is_atomic_and_rejects_overflow():
    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    first = _ref("time", "one")
    second = _ref("fft", "two")
    uvs.add_ref(board, first)
    uvs.add_ref(board, second)
    assert uvs.set_free_grid_rect(board, first, uvs.GridRect(0, 0, 4, 3)) == []
    assert uvs.set_free_grid_rect(board, second, uvs.GridRect(6, 0, 4, 3)) == []
    assert uvs.set_free_grid_rects(
        board,
        [
            (first, uvs.GridRect(0, 1, 4, 3)),
            (second, uvs.GridRect(6, 1, 4, 3)),
        ],
    ) == []
    assert uvs.free_grid_placement_for(board, first).rect == uvs.GridRect(0, 1, 4, 3)
    assert uvs.free_grid_placement_for(board, second).rect == uvs.GridRect(6, 1, 4, 3)
    assert uvs.set_free_grid_rects(
        board,
        [(first, uvs.GridRect(0, 1, 4, 3)), (second, uvs.GridRect(0, 1, 4, 3))],
    ) == ["grid_collision"]
    assert uvs.free_grid_placement_for(board, second).rect == uvs.GridRect(6, 1, 4, 3)
    assert uvs.set_free_grid_rects(
        board, [(first, uvs.GridRect(1, 1, 12, 3))]
    ) == ["invalid_grid_rect"]
    assert uvs.free_grid_placement_for(board, first).rect == uvs.GridRect(0, 1, 4, 3)


def test_template_to_free_grid_uses_stable_non_overlapping_conversion_maps():
    for layout_id in uvs.LAYOUT_SLOTS:
        board = _filled(layout_id)
        uvs.template_to_free_grid(board)
        assert len(board.free_grid) == min(len(uvs.LAYOUT_SLOTS[layout_id]), uvs.MAX_PLACED_CARDS)
        for index, item in enumerate(board.free_grid):
            assert item.ref.view_id == f"v{index}"
            for other in board.free_grid[index + 1:]:
                assert not uvs._grid_overlaps(item.rect, other.rect)


def test_free_grid_preset_and_organize_keep_geometry_legal():
    board = uvs.default_board()
    uvs.template_to_free_grid(board)
    first = _ref("time", "one")
    second = _ref("fft", "two")
    uvs.add_ref(board, first)
    uvs.add_ref(board, second)
    assert uvs.set_free_grid_rect(board, first, uvs.GridRect(0, 8, 4, 3)) == []
    assert uvs.set_free_grid_rect(board, second, uvs.GridRect(6, 12, 4, 3)) == []
    assert uvs.apply_free_grid_preset(board, first, "wide") == []
    assert uvs.free_grid_placement_for(board, first).rect == uvs.GridRect(0, 8, 6, 3)
    assert uvs.organize_free_grid(board) == []
    assert uvs.free_grid_placement_for(board, first).rect.row == 0
    assert uvs.free_grid_placement_for(board, second).rect.row == 3


def test_free_grid_payload_moves_duplicate_and_collision_to_tray_with_warning():
    payload = {
        "schema": 3,
        "board": {
            "board_id": "grid-board",
            "name": "自由网格",
            "layout_mode": "free_grid",
            "free_grid": {
                "columns": 12,
                "placements": [
                    {"section": "time", "view_id": "a", "column": 0, "row": 0, "column_span": 4, "row_span": 3},
                    {"section": "fft", "view_id": "b", "column": 1, "row": 1, "column_span": 4, "row_span": 3},
                    {"section": "frf", "view_id": "c", "column": 8, "row": 0, "column_span": 4, "row_span": 3},
                ],
            },
            "unplaced": [{"section": "frf", "view_id": "c"}],
        },
    }
    board, warnings = uvs.normalize_board_payload(payload)
    assert board.layout_mode == uvs.LAYOUT_MODE_FREE_GRID
    assert [item.ref.view_id for item in board.free_grid] == ["a", "c"]
    assert [ref.view_id for ref in board.unplaced] == ["b"]
    assert "grid_to_tray: fft/b" in warnings
    assert "duplicate_ref: frf/c" in warnings
    restored, roundtrip_warnings = uvs.normalize_board_payload(uvs.board_to_payload(board))
    assert roundtrip_warnings == []
    assert uvs.all_refs(restored) == uvs.all_refs(board)


@pytest.mark.parametrize(
    "start, target, placed, overflow",
    [
        ("grid_3x2", "split_horizontal", ["v0", "v1"], ["v2", "v3", "v4", "v5"]),
        ("grid_3x2", "grid_2x2", ["v0", "v1", "v2", "v3"], ["v4", "v5"]),
        ("hero_left_4", "split_vertical", ["v0", "v1"], ["v2", "v3"]),
        ("grid_2x2", "grid_3x2", ["v0", "v1", "v2", "v3"], []),
    ],
)
def test_capacity_operations_preserve_every_ref_in_tray(
    start, target, placed, overflow
):
    board = _filled(start)
    original = set(uvs.all_refs(board))
    uvs.set_layout(board, target)
    assert [p.ref.view_id for p in board.placements] == placed
    assert [ref.view_id for ref in board.unplaced] == overflow
    assert set(uvs.all_refs(board)) == original
    assert len(uvs.all_refs(board)) == len(set(uvs.all_refs(board)))


def test_full_board_add_goes_to_tray():
    board = _filled("hero_left_4")
    extra = _ref("fft", "extra")
    uvs.add_ref(board, extra)
    assert extra in board.unplaced
    assert extra not in uvs.placed_ref_set(board)
    uvs.add_ref(board, extra)
    assert board.unplaced.count(extra) == 1


def test_replace_moves_old_ref_to_tray():
    board = _filled("split_horizontal", 2)
    old = board.placements[0].ref
    new = _ref("frf", "new")
    uvs.replace_slot(board, "left", new)
    assert uvs.slot_occupant(board, "left") == new
    assert old in board.unplaced
    assert old not in uvs.placed_ref_set(board)


def test_replace_free_grid_ref_keeps_rect_and_trays_old():
    board = uvs.default_board()
    first = _ref("time", "a")
    second = _ref("fft", "b")
    uvs.add_ref(board, first)
    uvs.template_to_free_grid(board)
    old_rect = board.free_grid[0].rect
    assert not uvs.replace_free_grid_ref(board, first, second)
    assert [item.ref for item in board.free_grid] == [second]
    assert board.free_grid[0].rect == old_rect
    assert first in board.unplaced


def test_swap_slots_does_not_use_tray():
    board = _filled("split_horizontal", 2)
    left = uvs.slot_occupant(board, "left")
    right = uvs.slot_occupant(board, "right")
    uvs.swap_slots(board, "left", "right")
    assert uvs.slot_occupant(board, "left") == right
    assert uvs.slot_occupant(board, "right") == left
    assert board.unplaced == []


def test_tray_drop_onto_occupied_slot_returns_old_ref():
    board = _filled("split_horizontal", 2)
    extra = _ref("order", "tray")
    uvs.add_ref(board, extra)
    occupant = uvs.slot_occupant(board, "left")
    uvs.place_from_unplaced(board, "left", extra)
    assert uvs.slot_occupant(board, "left") == extra
    assert occupant in board.unplaced
    assert extra not in board.unplaced


def test_move_to_unplaced_keeps_membership_remove_does_not():
    board = _filled("grid_2x2", 1)
    ref = board.placements[0].ref
    uvs.move_to_unplaced(board, ref)
    assert ref in board.unplaced
    assert placement_missing(board, ref)
    uvs.remove_ref(board, ref)
    assert ref not in uvs.membership_set(board)


def placement_missing(board, ref) -> bool:
    return uvs.placement_for(board, ref) is None


def test_orphan_rebind_uses_replace_flow():
    board = uvs.default_board()
    uvs.set_layout(board, "hero_left_4")
    orphan = _ref("time", "gone")
    uvs.add_ref(board, orphan)
    replacement = _ref("fft", "alive")
    uvs.rebind_ref(board, orphan, replacement)
    assert uvs.slot_occupant(board, "primary") == replacement
    assert orphan not in uvs.membership_set(board)

    payload = uvs.board_to_payload(board)
    restored, warnings = uvs.normalize_board_payload(payload)
    assert warnings == []
    assert restored.placements[0].ref == replacement


def test_orphan_rebind_from_tray_removes_old_ref():
    board = uvs.default_board()
    orphan = _ref("time", "gone")
    uvs.add_ref(board, orphan)
    uvs.move_to_unplaced(board, orphan)
    replacement = _ref("fft", "alive")
    uvs.rebind_ref(board, orphan, replacement)
    assert orphan not in uvs.membership_set(board)
    assert replacement in board.unplaced
    assert uvs.placement_for(board, replacement) is None

    payload = uvs.board_to_payload(board)
    restored, warnings = uvs.normalize_board_payload(payload)
    assert warnings == []
    assert replacement in restored.unplaced
    assert orphan not in uvs.membership_set(restored)


def test_normalize_keeps_legal_missing_refs_and_warns_on_illegal():
    payload = {
        "schema": 1,
        "board": {
            "board_id": "board-1",
            "name": "整车问题总览",
            "layout_id": "not-a-layout",
            "primary_ratio": 1.5,
            "show_titles": True,
            "show_sources": False,
            "placements": [
                {"slot_id": "primary", "section": "time", "view_id": "keep"},
                {"slot_id": "primary", "section": "fft", "view_id": "dup-slot"},
                {"slot_id": "aux_0", "section": "order_time", "view_id": "bad"},
                {"slot_id": "aux_1", "section": "fft", "view_id": ""},
                {"slot_id": "aux_2", "section": "time", "view_id": "keep"},
            ],
            "unplaced": [
                {"section": "frf", "view_id": "tray"},
                {"section": "time", "view_id": "keep"},
            ],
        },
    }
    board, warnings = uvs.normalize_board_payload(payload)
    codes = [item.split(":", 1)[0] for item in warnings]
    assert "unknown_layout" in codes
    assert "illegal_ratio" in codes
    assert "illegal_section" in codes
    assert "empty_view_id" in codes
    assert "duplicate_slot" in codes
    assert "duplicate_ref" in codes
    assert board.layout_id == "hero_left_4"
    assert 0.40 <= board.primary_ratio <= 0.80
    assert [p.ref.view_id for p in board.placements] == ["keep"]
    assert [ref.view_id for ref in board.unplaced] == ["dup-slot", "tray"]


def test_unknown_schema_degrades_to_empty_board():
    board, warnings = uvs.normalize_board_payload({"schema": 99, "board": {}})
    assert board.placements == []
    assert board.unplaced == []
    assert any(item.startswith("unknown_ultraview_schema") for item in warnings)


def test_presentation_digest_is_key_order_independent_and_stable():
    left = uvs.presentation_digest({"b": 1, "a": {"y": 2, "x": 3}})
    right = uvs.presentation_digest({"a": {"x": 3, "y": 2}, "b": 1})
    assert left == right
    assert len(left) == 64
    canonical = {
        "digest_schema": 1,
        "payload": {"a": {"x": 3, "y": 2}, "b": 1},
    }
    expected = hashlib.sha256(
        json.dumps(
            canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    assert left == expected


def test_presentation_digest_includes_whatever_caller_passes():
    base = {
        "checked": [["f0", "rpm"]],
        "xlim": [0.0, 1.0],
        "markup_revision": 1,
    }
    # Name/color are presentation-only and must be omitted by the payload
    # builder. The digest function itself is a pure encoder: extra keys change
    # the hash, which is how UV-A05 is enforced at the capture boundary.
    assert uvs.presentation_digest(base) != uvs.presentation_digest(
        {**base, "name": "View 2", "tab_color": "#fff"}
    )


@pytest.mark.parametrize(
    "change",
    [
        {"xlim": [0.0, 2.0]},
        {"params": {"nfft": 4096}},
        {"filter": {"enabled": True}},
        {"data_signature": ("probed", 1)},
        {"markup_revision": 2},
        {"result_generation": 3},
    ],
)
def test_presentation_digest_pixel_affecting_fields_change_hash(change):
    base = {
        "checked": [["f0", "rpm"]],
        "xlim": [0.0, 1.0],
        "params": {"nfft": 2048},
        "filter": {"enabled": False},
        "data_signature": ("probed", 0),
        "markup_revision": 1,
        "result_generation": 1,
    }
    mutated = dict(base)
    mutated.update(change)
    assert uvs.presentation_digest(base) != uvs.presentation_digest(mutated)


def test_presentation_digest_rejects_unserializable_and_nonfinite():
    with pytest.raises(TypeError):
        uvs.presentation_digest({"obj": object()})
    with pytest.raises(TypeError):
        uvs.presentation_digest({"x": math.nan})
    with pytest.raises(TypeError):
        uvs.presentation_digest({"x": math.inf})


def test_derive_preview_status_never_optimistically_fresh():
    assert (
        uvs.derive_preview_status(False, True, "abc", "abc") == uvs.STATUS_ORPHANED
    )
    assert (
        uvs.derive_preview_status(True, False, "abc", "abc") == uvs.STATUS_MISSING
    )
    assert (
        uvs.derive_preview_status(True, True, "abc", "abc") == uvs.STATUS_FRESH
    )
    assert (
        uvs.derive_preview_status(True, True, "abc", "xyz") == uvs.STATUS_STALE
    )
    assert (
        uvs.derive_preview_status(True, True, "abc", None) == uvs.STATUS_STALE
    )
    assert (
        uvs.derive_preview_status(True, False, None, None) == uvs.STATUS_MISSING
    )


def test_axis_consistency_uses_structured_kind_unit_and_tolerance():
    facts = uvs.axis_consistency_facts(
        [
            {"axis_kind": "frequency", "x_unit": "Hz", "x_range": (0.0, 100.0)},
            {"axis_kind": "frequency", "x_unit": "kHz", "x_range": (0.0, 100.0)},
            {"axis_kind": "time", "x_unit": "s", "x_range": (0.0, 1.0)},
            {"axis_kind": "time", "x_unit": "s", "x_range": (0.0, 1.0 + 1e-12)},
            {"axis_kind": "order", "x_unit": "order", "x_range": (0.0, 20.0)},
            {"axis_kind": "order", "x_unit": "order", "x_range": (0.0, 21.0)},
        ]
    )
    assert facts.unit_inconsistent_kinds == ("frequency",)
    assert facts.range_inconsistent_kinds == ("order",)
    assert "time" not in facts.range_inconsistent_kinds


def test_compare_filter_does_not_require_board_mutation():
    board = _filled("grid_2x2", 2)
    payload = uvs.board_to_payload(board)
    assert uvs.card_matches_compare_filter("time", "all")
    assert uvs.card_matches_compare_filter("time", "time")
    assert not uvs.card_matches_compare_filter("frequency", "time")
    assert uvs.board_to_payload(board) == payload


def test_ratio_clamp_and_nudge():
    board = uvs.default_board()
    uvs.set_ratio(board, 0.2)
    assert board.primary_ratio == pytest.approx(0.40)
    uvs.set_ratio(board, 0.9)
    assert board.primary_ratio == pytest.approx(0.80)
    uvs.set_ratio(board, 0.67)
    uvs.nudge_ratio(board, -1)
    assert board.primary_ratio == pytest.approx(0.62)
    equal = uvs.default_board()
    uvs.set_layout(equal, "grid_2x2")
    assert equal.primary_ratio == pytest.approx(0.67)
    assert not uvs.is_hero_layout(equal.layout_id)


def test_free_grid_payload_keeps_layout_id_ratio_and_all_placements():
    board = _filled("grid_3x3")
    uvs.set_ratio(board, 0.55)
    uvs.template_to_free_grid(board)
    payload = uvs.board_to_payload(board)
    inner = payload["board"]
    assert inner["layout_id"] == "grid_3x3"
    assert inner["primary_ratio"] == pytest.approx(0.55)
    assert inner["layout_mode"] == uvs.LAYOUT_MODE_FREE_GRID
    assert len(inner["free_grid"]["placements"]) == 9
    restored, warnings = uvs.normalize_board_payload(payload)
    assert warnings == []
    assert restored.layout_id == "grid_3x3"
    assert restored.primary_ratio == pytest.approx(0.55)
    assert restored.layout_mode == uvs.LAYOUT_MODE_FREE_GRID
    assert len(restored.free_grid) == 9
    assert uvs.free_grid_to_template(restored, restored.layout_id) == []
    assert restored.layout_id == "grid_3x3"
    assert len(restored.placements) == 9
    assert restored.unplaced == []


def test_expanding_layout_refills_tray_with_warning():
    board = _filled("grid_2x2")
    for index in range(4, 8):
        uvs.add_ref(board, _ref("time", f"v{index}"))
    assert [ref.view_id for ref in board.unplaced] == ["v4", "v5", "v6", "v7"]
    warnings = uvs.set_layout(board, "grid_4x3")
    assert [item.ref.view_id for item in board.placements] == [f"v{i}" for i in range(8)]
    assert board.unplaced == []
    assert "tray_refilled: 4" in warnings


def test_shrinking_layout_overflows_to_tray_with_warning():
    board = _filled("grid_4x3")
    warnings = uvs.set_layout(board, "grid_2x2")
    assert [item.ref.view_id for item in board.placements] == ["v0", "v1", "v2", "v3"]
    assert [ref.view_id for ref in board.unplaced] == [f"v{i}" for i in range(4, 12)]
    assert "layout_overflow: 8" in warnings


def test_organize_free_grid_is_idempotent():
    board = uvs.default_board()
    uvs.add_ref(board, _ref("time", "a"))
    uvs.add_ref(board, _ref("fft", "b"))
    uvs.template_to_free_grid(board)
    first = board.free_grid[0].ref
    second = board.free_grid[1].ref
    assert uvs.set_free_grid_rect(board, first, uvs.GridRect(0, 2, 4, 2)) == []
    assert uvs.set_free_grid_rect(board, second, uvs.GridRect(6, 5, 3, 3)) == []
    assert uvs.organize_free_grid(board) == []
    once = [item.rect for item in board.free_grid]
    assert once == [uvs.GridRect(0, 0, 4, 2), uvs.GridRect(6, 2, 3, 3)]
    assert uvs.organize_free_grid(board) == []
    assert [item.rect for item in board.free_grid] == once


def test_viewport_round_trip_is_outside_identity_digest():
    board = uvs.default_board()
    payload = uvs.board_to_payload(board)
    assert "viewport" not in payload["board"]
    missing = dict(payload)
    missing["board"] = dict(payload["board"])
    restored, warnings = uvs.normalize_board_payload(missing)
    assert warnings == []
    assert restored.viewport == {}
    identity = uvs.presentation_digest(uvs.board_identity_payload(board))
    board.viewport = {"zoom": 1.6, "center_x": 120.0, "center_y": 40.0}
    again, warnings = uvs.normalize_board_payload(uvs.board_to_payload(board))
    assert warnings == []
    assert again.viewport["zoom"] == pytest.approx(1.6)
    assert again.viewport["center_x"] == pytest.approx(120.0)
    assert uvs.presentation_digest(uvs.board_identity_payload(again)) == identity
    assert "viewport" in uvs.board_to_payload(again)["board"]


def test_viewport_illegal_values_clamp_with_warning():
    payload = uvs.board_to_payload(uvs.default_board())
    payload["board"]["viewport"] = {
        "zoom": 9,
        "center_x": "nope",
        "center_y": float("inf"),
    }
    board, warnings = uvs.normalize_board_payload(payload)
    assert board.viewport["zoom"] == pytest.approx(2.0)
    assert board.viewport["center_x"] == pytest.approx(0.0)
    assert board.viewport["center_y"] == pytest.approx(0.0)
    assert any(item.startswith("viewport_zoom_clamped") for item in warnings)
    assert any(item.startswith("viewport_center_x_clamped") for item in warnings)
    assert any(item.startswith("viewport_center_y_clamped") for item in warnings)


def test_unknown_board_fields_passthrough_with_viewport():
    payload = uvs.board_to_payload(uvs.default_board())
    payload["board"]["viewport"] = {"zoom": 0.5, "center_x": 1.0, "center_y": 2.0}
    payload["board"]["future_camera"] = {"keep": True}
    board, warnings = uvs.normalize_board_payload(payload)
    assert warnings == []
    out = uvs.board_to_payload(board)
    assert out["board"]["viewport"]["zoom"] == pytest.approx(0.5)
    assert out["board"]["future_camera"] == {"keep": True}
