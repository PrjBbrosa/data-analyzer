import ast
import math
from pathlib import Path

import pytest

from mf4_analyzer.ui.view_overlay_state import (
    merge_remarks_for_capture,
    normalize_cursor_placement,
    normalize_remark,
    normalize_remarks,
    remap_remarks,
)


_LEGAL = {
    "source": ["fid-a", "torque"],
    "x": 1.25,
    "y": 3.5,
    "label_dx": 0.08,
    "label_dy": 0.4,
}


def test_normalize_remark_roundtrip_keeps_legal_fields():
    got = normalize_remark(_LEGAL)
    assert got == {
        "source": ["fid-a", "torque"],
        "x": 1.25,
        "y": 3.5,
        "label_dx": 0.08,
        "label_dy": 0.4,
    }
    assert normalize_remarks([_LEGAL]) == [got]


def test_normalize_remark_emits_tuple_source_as_json_two_list():
    raw = dict(_LEGAL)
    raw["source"] = ("fid-a", "torque")
    got = normalize_remark(raw)
    assert got is not None
    assert got["source"] == ["fid-a", "torque"]
    assert isinstance(got["source"], list)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not-a-mapping",
        {"x": 1.0, "y": 2.0, "label_dx": 0.0, "label_dy": 0.0},
        {"source": ["fid-a"], "x": 1.0, "y": 2.0, "label_dx": 0.0, "label_dy": 0.0},
        {"source": ["fid-a", "torque", "extra"], "x": 1.0, "y": 2.0,
         "label_dx": 0.0, "label_dy": 0.0},
        {"source": {"fid": "fid-a", "channel": "torque"},
         "x": 1.0, "y": 2.0, "label_dx": 0.0, "label_dy": 0.0},
        {"source": "ab", "x": 1.0, "y": 2.0, "label_dx": 0.0, "label_dy": 0.0},
        {"source": ["fid-a", "torque"], "y": 2.0, "label_dx": 0.0, "label_dy": 0.0},
        {"source": ["fid-a", "torque"], "x": 1.0, "label_dx": 0.0, "label_dy": 0.0},
        {"source": ["fid-a", "torque"], "x": 1.0, "y": 2.0, "label_dy": 0.0},
        {"source": ["fid-a", "torque"], "x": 1.0, "y": 2.0, "label_dx": 0.0},
        {"source": ["fid-a", None], "x": 1.0, "y": 2.0, "label_dx": 0.0, "label_dy": 0.0},
    ],
)
def test_normalize_remark_drops_missing_short_or_mapping_source(raw):
    assert normalize_remark(raw) is None


@pytest.mark.parametrize("key", ["x", "y", "label_dx", "label_dy"])
@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan, "nope", True, None])
def test_normalize_remark_drops_non_finite_numbers(key, bad):
    raw = dict(_LEGAL)
    raw[key] = bad
    assert normalize_remark(raw) is None


def test_normalize_remark_strips_prefixed_display_name_to_raw_channel():
    raw = dict(_LEGAL)
    raw["source"] = ["fid-a", "[a.csv] torque"]
    got = normalize_remark(raw)
    assert got is not None
    assert got["source"] == ["fid-a", "torque"]


def test_merge_remarks_treats_prefixed_live_source_as_raw_checked_key():
    live = [{
        **_LEGAL,
        "source": ["fid-a", "[session] torque"],
        "x": 2.0,
    }]
    previous = [{**_LEGAL, "x": 1.0}]
    got = merge_remarks_for_capture(
        live,
        previous,
        attached_file_ids=["fid-a"],
        checked=[("fid-a", "torque")],
        hidden_channels=[],
    )
    assert len(got) == 1
    assert got[0]["source"] == ["fid-a", "torque"]
    assert got[0]["x"] == 2.0
    raw = dict(_LEGAL)
    raw["note"] = "keep-me"
    raw["style"] = {"color": "#fff"}
    got = normalize_remark(raw)
    assert got is not None
    assert got["note"] == "keep-me"
    assert got["style"] == {"color": "#fff"}
    assert got["source"] == ["fid-a", "torque"]


def test_normalize_remarks_skips_illegal_items_and_non_lists():
    legal = dict(_LEGAL)
    illegal = {"source": ["fid-a"], "x": 1.0, "y": 2.0, "label_dx": 0.0, "label_dy": 0.0}
    assert normalize_remarks([illegal, legal, None]) == [normalize_remark(legal)]
    assert normalize_remarks(None) == []
    assert normalize_remarks(legal) == []
    assert normalize_remarks("not-a-list") == []


@pytest.mark.parametrize(
    "mode, raw",
    [
        ("off", {"ax": 1.0, "bx": 2.0}),
        ("single", {"ax": 1.0, "bx": 2.0}),
        ("dual", None),
        ("dual", {"bx": 2.0}),
        ("dual", {"ax": math.inf, "bx": 2.0}),
        ("dual", {"ax": math.nan}),
        ("dual", {"ax": "nope"}),
    ],
)
def test_normalize_cursor_placement_none_unless_dual_with_finite_ax(mode, raw):
    assert normalize_cursor_placement(raw, cursor_mode=mode) is None


def test_normalize_cursor_placement_allows_null_bx_and_strips_chrome():
    got = normalize_cursor_placement(
        {"ax": 1.0, "bx": 2.5, "placing": True, "html": "<b>pill</b>", "x": 9.0},
        cursor_mode="dual",
    )
    assert got == {"ax": 1.0, "bx": 2.5}

    only_a = normalize_cursor_placement({"ax": 1.25}, cursor_mode="dual")
    assert only_a == {"ax": 1.25, "bx": None}

    null_b = normalize_cursor_placement({"ax": 1.0, "bx": None}, cursor_mode="dual")
    assert null_b == {"ax": 1.0, "bx": None}


def test_remap_remarks_rewrites_fid_drops_missing_and_keeps_extra_keys():
    remarks = [
        {**_LEGAL, "note": "keep"},
        {
            "source": ["gone", "rpm"],
            "x": 0.0,
            "y": 1.0,
            "label_dx": 0.0,
            "label_dy": 0.0,
        },
    ]
    got = remap_remarks(remarks, {"fid-a": "fid-z"})
    assert got == [
        {
            "source": ["fid-z", "torque"],
            "x": 1.25,
            "y": 3.5,
            "label_dx": 0.08,
            "label_dy": 0.4,
            "note": "keep",
        }
    ]
    assert remap_remarks(remarks, {}) == []
    assert remap_remarks(None, {"fid-a": "fid-z"}) == []


def test_merge_remarks_keeps_hidden_source_when_live_is_empty():
    previous = [{**_LEGAL, "note": "hidden"}]
    got = merge_remarks_for_capture(
        [],
        previous,
        attached_file_ids=["fid-a"],
        checked=[("fid-a", "torque")],
        hidden_channels=[("fid-a", "torque")],
    )
    assert got == [{**_LEGAL, "note": "hidden"}]


def test_merge_remarks_drops_visible_source_missing_from_live():
    got = merge_remarks_for_capture(
        [],
        [_LEGAL],
        attached_file_ids=["fid-a"],
        checked=[("fid-a", "torque")],
        hidden_channels=[],
    )
    assert got == []


def test_merge_remarks_live_wins_same_source_and_keeps_other_hidden():
    live = [
        {
            "source": ["fid-a", "torque"],
            "x": 9.0,
            "y": 8.0,
            "label_dx": 0.1,
            "label_dy": 0.2,
        }
    ]
    hidden = {
        "source": ["fid-a", "rpm"],
        "x": 0.5,
        "y": 1.0,
        "label_dx": 0.0,
        "label_dy": 0.0,
    }
    stale_visible = dict(_LEGAL)
    got = merge_remarks_for_capture(
        live,
        [stale_visible, hidden],
        attached_file_ids=["fid-a"],
        checked=[("fid-a", "torque"), ("fid-a", "rpm")],
        hidden_channels=[("fid-a", "rpm")],
    )
    assert got == [
        {
            "source": ["fid-a", "torque"],
            "x": 9.0,
            "y": 8.0,
            "label_dx": 0.1,
            "label_dy": 0.2,
        },
        hidden,
    ]


def test_merge_remarks_drops_source_that_left_the_view():
    got = merge_remarks_for_capture(
        [],
        [_LEGAL],
        attached_file_ids=["other"],
        checked=[],
        hidden_channels=[],
    )
    assert got == []


def test_overlay_module_does_not_import_qt_or_canvas():
    path = (
        Path(__file__).resolve().parents[1]
        / "mf4_analyzer"
        / "ui"
        / "view_overlay_state.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.append(node.module)
            imported.extend(alias.name for alias in node.names)
    blob = " ".join(imported)
    assert "PyQt5" not in blob
    assert "pyqtgraph" not in blob
    assert "pg_canvas" not in blob
