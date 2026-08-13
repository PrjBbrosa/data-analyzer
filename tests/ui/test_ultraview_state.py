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
    assert board.primary_ratio == pytest.approx(0.67)
    assert board.placements == []
    assert board.unplaced == []
    assert board.board_id
    other = uvs.default_board()
    assert other.board_id != board.board_id


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
