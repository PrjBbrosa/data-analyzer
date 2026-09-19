"""Qt-free tests for pinned-cursor INTENT state.

Import ``mf4_analyzer.ui.pinned_cursor_state`` directly. ``ui/__init__.py``
is lazy and must not pull Qt into this module.
"""
from __future__ import annotations

import ast
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from mf4_analyzer.ui.pinned_cursor_state import (
    REASON_BOOL_COORD,
    REASON_DUPLICATE_ORDINAL,
    REASON_DUPLICATE_RECORD_ID,
    REASON_INCOMPLETE_DUAL,
    REASON_INVALID_AXIS_IDENTITY,
    REASON_INVALID_BINDINGS,
    REASON_INVALID_PANEL_EXPANDED,
    REASON_MISSING_COORD,
    REASON_NON_FINITE_COORD,
    REASON_UNKNOWN_PAYLOAD_VERSION,
    capture_identity,
    captures_equal,
    clear_collection,
    collection_from_dict,
    collection_to_dict,
    coords_equal,
    duplicate_collection,
    empty_collection,
    next_record,
    normalize_collection,
    remap_collection_fids,
    remove_record,
    PinnedCursorBinding,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "mf4_analyzer" / "ui" / "pinned_cursor_state.py"
_PINNED_CURSOR_STATE_IMPORT_TIMEOUT_S = 30


def _uuid() -> str:
    return str(uuid4())


def _raw_single(**overrides):
    data = {
        "payload_version": 1,
        "record_id": _uuid(),
        "ordinal": 1,
        "mode": "single",
        "domain": "time",
        "x": 1.25,
        "x_unit": "s",
        "bindings": [{"fid": "f0", "channel": "torque"}],
        "presentation": "full",
        "anchor": {"h_edge": "right", "v_edge": "top", "nx": 1.0, "ny": 0.0},
    }
    data.update(overrides)
    return data


def _raw_dual(**overrides):
    data = {
        "payload_version": 1,
        "record_id": _uuid(),
        "ordinal": 1,
        "mode": "dual",
        "domain": "time",
        "ax": 1.0,
        "bx": 2.0,
        "x_unit": "s",
        "bindings": [{"fid": "f0", "channel": "torque"}],
        "presentation": "full",
    }
    data.update(overrides)
    return data


def _collection(*records, next_ordinal=None, scope_id=None):
    payload = {
        "payload_version": 1,
        "scope_id": scope_id or _uuid(),
        "records": list(records),
    }
    if next_ordinal is not None:
        payload["next_ordinal"] = next_ordinal
    collection, dropped = normalize_collection(payload)
    assert dropped == (), dropped
    return collection


def _spec(**overrides):
    data = {
        "mode": "single",
        "domain": "time",
        "x": 1.25,
        "x_unit": "s",
        "bindings": [{"fid": "f0", "channel": "torque"}],
    }
    data.update(overrides)
    return data


def _without(raw, *keys):
    data = dict(raw)
    for key in keys:
        data.pop(key, None)
    return data


def test_empty_collection_defaults():
    collection = empty_collection()
    UUID(collection.scope_id)
    assert collection.records == ()
    assert collection.next_ordinal == 1
    assert collection.payload_version == 1
    assert collection.version == 1
    other = empty_collection()
    assert other.scope_id != collection.scope_id


def test_missing_payload_is_empty_collection():
    missing, dropped = normalize_collection(None)
    assert missing.records == ()
    assert dropped == ()
    from_dict = collection_from_dict(None)
    assert from_dict.records == ()
    UUID(from_dict.scope_id)


@pytest.mark.parametrize(
    "raw, reason",
    [
        (_raw_single(x=None), REASON_MISSING_COORD),
        (_raw_single(x=True), REASON_BOOL_COORD),
        (_raw_single(x=False), REASON_BOOL_COORD),
        (_raw_single(x=math.inf), REASON_NON_FINITE_COORD),
        (_raw_single(x=-math.inf), REASON_NON_FINITE_COORD),
        (_raw_single(x=math.nan), REASON_NON_FINITE_COORD),
        (_raw_single(x="nope"), REASON_NON_FINITE_COORD),
        (_raw_dual(ax=True, bx=2.0), REASON_BOOL_COORD),
        (_raw_dual(ax=1.0, bx=False), REASON_BOOL_COORD),
        (_raw_dual(ax=1.0, bx=None), REASON_INCOMPLETE_DUAL),
        (_without(_raw_dual(ax=1.0), "bx"), REASON_INCOMPLETE_DUAL),
        (_without(_raw_dual(bx=2.0), "ax"), REASON_INCOMPLETE_DUAL),
        (_raw_dual(ax=math.nan, bx=2.0), REASON_NON_FINITE_COORD),
    ],
)
def test_finite_vs_missing_vs_bool_coords_rejected(raw, reason):
    collection, dropped = normalize_collection(
        {"payload_version": 1, "scope_id": _uuid(), "records": [raw]}
    )
    assert collection.records == ()
    assert [item.reason for item in dropped] == [reason]


def test_zero_is_a_legal_finite_coordinate():
    collection = _collection(_raw_single(x=0.0))
    assert collection.records[0].x == 0.0
    assert coords_equal(collection.records[0].x, 0.0)


def test_composite_identity_is_not_display_name():
    raw = _raw_single(
        bindings=[
            {
                "fid": "f0",
                "channel": "MotorTorque",
                "binding_id": "curve-a",
                "display_name": "电机扭矩",
                "color": "#ff00ff",
                "legend": "P1 电机扭矩",
            }
        ]
    )
    collection = _collection(raw)
    binding = collection.records[0].bindings[0]
    assert binding == PinnedCursorBinding(
        fid="f0", channel="MotorTorque", binding_id="curve-a", role="",
    )
    dumped = json.dumps(collection_to_dict(collection), ensure_ascii=False)
    assert "电机扭矩" not in dumped
    assert "#ff00ff" not in dumped
    assert "P1" not in dumped

    same_name = _collection(
        _raw_single(
            ordinal=1,
            bindings=[{"fid": "f0", "channel": "MotorTorque"}],
        ),
        _raw_single(
            ordinal=2,
            bindings=[{"fid": "f1", "channel": "MotorTorque"}],
        ),
        next_ordinal=3,
    )
    assert capture_identity(same_name.records[0]) != capture_identity(
        same_name.records[1]
    )


def test_duplicate_capture_identity_for_same_physical_point():
    first = _collection(
        _raw_single(
            x=1.23456789,
            presentation="full",
            ordinal=1,
            record_id=_uuid(),
            anchor={"h_edge": "right", "v_edge": "top", "nx": 1.0, "ny": 0.0},
        )
    ).records[0]
    second = _collection(
        _raw_single(
            x=1.23456789,
            presentation="mini",
            ordinal=9,
            record_id=_uuid(),
            anchor={"h_edge": "left", "v_edge": "bottom", "nx": 0.2, "ny": 0.8},
        )
    ).records[0]
    assert capture_identity(first) == capture_identity(second)
    assert captures_equal(first, second)
    assert first.record_id != second.record_id
    assert first.ordinal != second.ordinal
    assert first.presentation != second.presentation


def test_points_that_format_to_same_3_decimal_text_stay_distinct():
    left = 1.2341
    right = 1.2344
    assert f"{left:.3f}" == f"{right:.3f}" == "1.234"
    a = _collection(_raw_single(x=left)).records[0]
    b = _collection(_raw_single(x=right)).records[0]
    assert capture_identity(a) != capture_identity(b)
    assert not captures_equal(a, b)
    assert not coords_equal(left, right)


def test_coords_equal_uses_physical_values_not_strings():
    assert coords_equal(1.0, 1.0)
    assert coords_equal(1.0, 1)
    assert not coords_equal(True, 1.0)
    assert not coords_equal(None, 0.0)
    round_tripped = json.loads(json.dumps(1.234567890123))
    assert coords_equal(1.234567890123, round_tripped)


def test_dual_a_equals_b_is_allowed():
    collection = _collection(_raw_dual(ax=3.5, bx=3.5))
    intent = collection.records[0]
    assert intent.ax == 3.5
    assert intent.bx == 3.5
    assert intent.ax == intent.bx


def test_dual_a_greater_than_b_does_not_swap():
    collection = _collection(_raw_dual(ax=10.0, bx=2.0))
    intent = collection.records[0]
    assert intent.ax == 10.0
    assert intent.bx == 2.0
    dumped = collection_to_dict(collection)["records"][0]
    assert dumped["ax"] == 10.0
    assert dumped["bx"] == 2.0


def test_custom_x_axis_identity_round_trip():
    raw = _raw_single(
        domain="channel",
        x=12.5,
        x_unit="deg",
        axis_identity=["fid-steer", "steer_angle"],
        bindings=[
            {
                "fid": "fid-steer",
                "channel": "rack_force",
                "binding_id": "bind-1",
            }
        ],
    )
    collection = _collection(raw)
    restored = collection_from_dict(collection_to_dict(collection))
    intent = restored.records[0]
    assert intent.domain == "channel"
    assert intent.x == 12.5
    assert intent.x_unit == "deg"
    assert intent.axis_identity == ("fid-steer", "steer_angle")
    assert intent.bindings[0].binding_id == "bind-1"
    payload = json.dumps(collection_to_dict(restored))
    json.loads(payload)
    assert "axis_identity" in collection_to_dict(restored)["records"][0]
    assert isinstance(collection_to_dict(restored)["records"][0]["axis_identity"], list)


def test_axis_identity_mapping_is_rejected():
    raw = _raw_single(
        domain="channel",
        axis_identity={"fid": "fid-steer", "channel": "steer_angle"},
    )
    collection, dropped = normalize_collection(
        {"payload_version": 1, "scope_id": _uuid(), "records": [raw]}
    )
    assert collection.records == ()
    assert [item.reason for item in dropped] == [REASON_INVALID_AXIS_IDENTITY]


def test_seconds_are_not_treated_as_hz():
    time_pin = _collection(
        _raw_single(domain="time", x=100.0, x_unit="s")
    ).records[0]
    freq_pin = _collection(
        _raw_single(domain="frequency", x=100.0, x_unit="Hz")
    ).records[0]
    frf_pin = _collection(
        _raw_single(domain="frf", x=100.0, x_unit="Hz")
    ).records[0]
    assert time_pin.domain != freq_pin.domain
    assert capture_identity(time_pin) != capture_identity(freq_pin)
    assert capture_identity(freq_pin) != capture_identity(frf_pin)
    assert not captures_equal(time_pin, freq_pin)


def test_extra_binding_id_distinguishes_same_channel():
    shared = {"fid": "f0", "channel": "torque"}
    first = _collection(
        _raw_single(bindings=[{**shared, "binding_id": "curve-a"}])
    ).records[0]
    second = _collection(
        _raw_single(bindings=[{**shared, "binding_id": "curve-b"}])
    ).records[0]
    assert capture_identity(first) != capture_identity(second)


def test_fft_frf_role_identity_is_not_a_display_name():
    ref = _collection(
        _raw_single(
            domain="frf",
            x=40.0,
            x_unit="Hz",
            bindings=[
                {
                    "fid": "f0",
                    "channel": "torque",
                    "role": "reference",
                }
            ],
        )
    ).records[0]
    resp = _collection(
        _raw_single(
            domain="frf",
            x=40.0,
            x_unit="Hz",
            bindings=[
                {
                    "fid": "f0",
                    "channel": "torque",
                    "role": "response",
                }
            ],
        )
    ).records[0]
    assert capture_identity(ref) != capture_identity(resp)


def test_ordinal_is_monotonic_and_delete_does_not_fill_holes():
    collection = empty_collection()
    collection, p1 = next_record(collection, _spec(x=1.0))
    collection, p2 = next_record(collection, _spec(x=2.0))
    collection, p3 = next_record(collection, _spec(x=3.0))
    assert [item.ordinal for item in collection.records] == [1, 2, 3]
    assert collection.next_ordinal == 4
    collection = remove_record(collection, p2.record_id)
    assert [item.ordinal for item in collection.records] == [1, 3]
    assert collection.next_ordinal == 4
    collection, p4 = next_record(collection, _spec(x=4.0))
    assert p4.ordinal == 4
    assert [item.ordinal for item in collection.records] == [1, 3, 4]
    assert collection.next_ordinal == 5
    assert p1.ordinal == 1
    assert p3.ordinal == 3


def test_duplicate_record_id_is_dropped():
    shared_id = _uuid()
    first = _raw_single(record_id=shared_id, ordinal=1, x=1.0)
    dup = _raw_single(record_id=shared_id, ordinal=2, x=2.0)
    collection, dropped = normalize_collection(
        {
            "payload_version": 1,
            "scope_id": _uuid(),
            "records": [first, dup],
        }
    )
    assert len(collection.records) == 1
    assert collection.records[0].x == 1.0
    assert [item.reason for item in dropped] == [REASON_DUPLICATE_RECORD_ID]


def test_duplicate_ordinal_in_payload_is_dropped():
    first = _raw_single(ordinal=1, x=1.0)
    dup = _raw_single(ordinal=1, x=2.0)
    third = _raw_single(ordinal=2, x=3.0)
    collection, dropped = normalize_collection(
        {
            "payload_version": 1,
            "scope_id": _uuid(),
            "records": [first, dup, third],
        }
    )
    assert [item.ordinal for item in collection.records] == [1, 2]
    assert collection.records[0].x == 1.0
    assert [item.reason for item in dropped] == [REASON_DUPLICATE_ORDINAL]
    assert collection.next_ordinal == 3


def test_scope_id_is_stable_on_serialize():
    collection = _collection(_raw_single(), next_ordinal=2)
    encoded = collection_to_dict(collection)
    restored = collection_from_dict(encoded)
    again = collection_to_dict(restored)
    assert encoded["scope_id"] == restored.scope_id == again["scope_id"]
    assert encoded["scope_id"] == collection.scope_id
    json.dumps(encoded, allow_nan=False)


def test_panel_expanded_defaults_false_and_omits_legacy_payload_field():
    collection = _collection(_raw_single())

    intent = collection.records[0]
    encoded = collection_to_dict(collection)

    assert intent.panel_expanded is False
    assert encoded["payload_version"] == 1
    assert encoded["records"][0]["payload_version"] == 1
    assert "panel_expanded" not in encoded["records"][0]
    assert collection_from_dict(encoded).records[0].panel_expanded is False


@pytest.mark.parametrize("value", ["true", "false", 0, 1, None, [], {}])
def test_panel_expanded_rejects_non_bool_with_diagnostic(value, caplog):
    raw = _raw_single(panel_expanded=value)
    with caplog.at_level(
        "WARNING", logger="mf4_analyzer.ui.pinned_cursor_state",
    ):
        collection = collection_from_dict({
            "payload_version": 1,
            "scope_id": _uuid(),
            "records": [raw],
        })

    assert len(collection.records) == 1
    assert collection.records[0].panel_expanded is False
    assert "panel_expanded" not in collection_to_dict(collection)["records"][0]
    assert any(
        REASON_INVALID_PANEL_EXPANDED in record.message
        for record in caplog.records
    )


def test_panel_expanded_true_survives_roundtrip_clone_and_fid_remap():
    collection = _collection(_raw_single(panel_expanded=True))

    encoded = collection_to_dict(collection)
    restored = collection_from_dict(json.loads(json.dumps(encoded)))
    copied = duplicate_collection(restored)
    remapped = remap_collection_fids(restored, {"f0": "F0"})

    assert encoded["records"][0]["panel_expanded"] is True
    assert restored.records[0].panel_expanded is True
    assert copied.records[0].panel_expanded is True
    assert remapped.records[0].panel_expanded is True
    assert remapped.records[0].bindings[0].fid == "F0"


def test_time_and_analysis_codecs_preserve_expanded_pin_intent():
    from mf4_analyzer.ui.analysis_view_state import PaneState
    from mf4_analyzer.ui.view_state import ViewState

    collection = _collection(_raw_single(panel_expanded=True))
    time_view = ViewState(
        name="Time", tab_color="#2d7ff9", pinned_cursors=collection,
    )
    analysis_pane = PaneState(pinned_cursors=collection)

    restored_time = ViewState.from_dict(time_view.to_dict())
    restored_pane = PaneState.from_dict(analysis_pane.to_dict())

    assert restored_time.pinned_cursors.records[0].panel_expanded is True
    assert restored_pane.pinned_cursors.records[0].panel_expanded is True


def test_duplicate_remints_scope_and_record_ids_keeps_ordinals():
    collection = empty_collection()
    collection, p1 = next_record(collection, _spec(x=1.0))
    collection, p2 = next_record(collection, _spec(x=2.0))
    copied = duplicate_collection(collection)
    assert copied.scope_id != collection.scope_id
    UUID(copied.scope_id)
    assert [item.ordinal for item in copied.records] == [1, 2]
    assert copied.next_ordinal == collection.next_ordinal == 3
    original_ids = {p1.record_id, p2.record_id}
    copied_ids = {item.record_id for item in copied.records}
    assert original_ids.isdisjoint(copied_ids)
    assert all(UUID(item.record_id) for item in copied.records)
    assert capture_identity(copied.records[0]) == capture_identity(p1)


def test_unknown_payload_version_is_skipped_with_diagnostic():
    scope = _uuid()
    valid = _raw_single()
    collection, dropped = normalize_collection(
        {
            "payload_version": 99,
            "scope_id": scope,
            "next_ordinal": 8,
            "records": [valid],
        }
    )
    assert collection.records == ()
    assert collection.scope_id == scope
    assert [item.reason for item in dropped] == [REASON_UNKNOWN_PAYLOAD_VERSION]
    assert valid["x"] == 1.25

    keep = _raw_single(ordinal=1, x=4.0)
    skip = _raw_single(ordinal=2, x=5.0, payload_version=2)
    mixed, mixed_dropped = normalize_collection(
        {
            "payload_version": 1,
            "scope_id": _uuid(),
            "records": [keep, skip],
        }
    )
    assert len(mixed.records) == 1
    assert mixed.records[0].x == 4.0
    assert [item.reason for item in mixed_dropped] == [
        REASON_UNKNOWN_PAYLOAD_VERSION
    ]


def test_one_corrupt_record_is_dropped_and_rest_kept():
    good_a = _raw_single(ordinal=1, x=1.0)
    bad = _raw_single(ordinal=2, x=True)
    good_b = _raw_dual(ordinal=3, ax=8.0, bx=9.0)
    html = _raw_single(ordinal=4, x=3.0, html="<b>pill</b>", samples=[1, 2, 3])
    collection, dropped = normalize_collection(
        {
            "payload_version": 1,
            "scope_id": _uuid(),
            "records": [good_a, bad, good_b, html, "not-a-record"],
        }
    )
    assert [item.ordinal for item in collection.records] == [1, 3, 4]
    assert collection.records[0].x == 1.0
    assert collection.records[1].ax == 8.0
    assert collection.records[1].bx == 9.0
    dumped = json.dumps(collection_to_dict(collection))
    assert "<b>pill</b>" not in dumped
    assert "samples" not in dumped
    assert any(item.reason == REASON_BOOL_COORD for item in dropped)
    assert any(item.reason == "invalid_record" for item in dropped)


def test_fid_remap_rewrites_known_and_drops_unknown():
    raw = _raw_single(
        domain="channel",
        x=0.4,
        x_unit="mm",
        axis_identity=["old-a", "steer_angle"],
        bindings=[
            {"fid": "old-a", "channel": "torque", "binding_id": "b1"},
            {"fid": "old-b", "channel": "rpm", "role": "reference"},
        ],
    )
    collection = _collection(raw)
    remapped = remap_collection_fids(
        collection, {"old-a": "new-a", "unrelated": "nope"},
    )
    assert len(remapped.records) == 1
    intent = remapped.records[0]
    assert intent.axis_identity == ("new-a", "steer_angle")
    assert len(intent.bindings) == 1
    assert intent.bindings[0].fid == "new-a"
    assert intent.bindings[0].channel == "torque"
    assert intent.bindings[0].binding_id == "b1"
    same_name = remap_collection_fids(
        collection, {"some-other-file-named-the-same": "new-a"},
    )
    assert same_name.records == ()
    assert same_name.scope_id == collection.scope_id


def test_fid_remap_drops_record_when_all_bindings_unknown():
    collection = _collection(
        _raw_single(bindings=[{"fid": "gone", "channel": "torque"}]),
    )
    remapped = remap_collection_fids(collection, {"f0": "F0"})
    assert remapped.records == ()
    assert remapped.scope_id == collection.scope_id
    assert remapped.next_ordinal == collection.next_ordinal


def test_fid_remap_drops_record_when_custom_x_axis_fid_unknown():
    collection = _collection(_raw_single(
        domain="channel",
        x=0.4,
        x_unit="mm",
        axis_identity=["gone-x", "steer_angle"],
        bindings=[{"fid": "old-a", "channel": "torque"}],
    ))
    remapped = remap_collection_fids(collection, {"old-a": "new-a"})
    assert remapped.records == ()


def test_empty_bindings_record_is_illegal():
    collection, dropped = normalize_collection(
        {
            "payload_version": 1,
            "scope_id": _uuid(),
            "records": [
                _raw_single(bindings=[]),
                _without(_raw_single(), "bindings"),
            ],
        }
    )
    assert collection.records == ()
    assert [item.reason for item in dropped] == [
        REASON_INVALID_BINDINGS,
        REASON_INVALID_BINDINGS,
    ]


def test_next_record_rejects_empty_bindings():
    with pytest.raises(ValueError, match="invalid_bindings"):
        next_record(empty_collection(), _spec(bindings=[]))


def test_collection_from_dict_logs_dropped_records(caplog):
    import logging

    bad = _raw_single(x=True)
    with caplog.at_level(
        logging.WARNING, logger="mf4_analyzer.ui.pinned_cursor_state",
    ):
        restored = collection_from_dict(
            {
                "payload_version": 1,
                "scope_id": _uuid(),
                "records": [bad],
            }
        )
    assert restored.records == ()
    assert any(
        REASON_BOOL_COORD in rec.message for rec in caplog.records
    )


def test_clear_collection_keeps_scope_and_ordinal_counter():
    collection = empty_collection()
    collection, _p1 = next_record(collection, _spec(x=1.0))
    collection, _p2 = next_record(collection, _spec(x=2.0))
    scope = collection.scope_id
    cleared = clear_collection(collection)
    assert cleared.records == ()
    assert cleared.scope_id == scope
    assert cleared.next_ordinal == 3


def test_next_record_assigns_uuid_and_ordinal():
    collection, intent = next_record(empty_collection(), _spec())
    UUID(intent.record_id)
    assert intent.ordinal == 1
    assert collection.records == (intent,)


def test_json_round_trip_does_not_emit_nan():
    collection = _collection(
        _raw_single(x=1.5),
        _raw_dual(ordinal=2, ax=4.0, bx=1.0),
        next_ordinal=3,
    )
    payload = collection_to_dict(collection)
    encoded = json.dumps(payload, allow_nan=False)
    restored = collection_from_dict(json.loads(encoded))
    assert restored.records[0].x == 1.5
    assert restored.records[1].ax == 4.0
    assert restored.records[1].bx == 1.0


def test_intent_is_frozen():
    intent = _collection(_raw_single()).records[0]
    with pytest.raises(AttributeError):
        intent.x = 9.0  # type: ignore[misc]


def test_pinned_cursor_state_stays_qt_free():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            imported.extend(alias.name for alias in node.names)
    blob = " ".join(imported)
    assert all("Qt" not in name and "PyQt" not in name for name in imported)
    assert "pyqtgraph" not in blob
    assert "cursor_display_model" not in blob
    assert "PyQt5" not in blob


def test_pinned_cursor_state_import_does_not_load_qt():
    script = r"""
import json
import sys

sys.modules["PyQt5"] = None
sys.modules["PyQt5.QtCore"] = None
sys.modules["PyQt5.QtGui"] = None
sys.modules["PyQt5.QtWidgets"] = None
sys.modules["pyqtgraph"] = None

try:
    import PyQt5  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print(json.dumps({"error": "poison_ineffective"}))
    raise SystemExit(2)

import mf4_analyzer.ui.pinned_cursor_state as pinned

live = sorted(
    name
    for name, mod in sys.modules.items()
    if mod is not None
    and (
        name == "PyQt5"
        or name.startswith("PyQt5.")
        or name == "pyqtgraph"
        or name.startswith("pyqtgraph.")
    )
)
print(
    json.dumps(
        {
            "live": live,
            "cursor_model": "mf4_analyzer.ui.cursor_display_model" in sys.modules,
            "empty": len(pinned.empty_collection().records),
        }
    )
)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=_PINNED_CURSOR_STATE_IMPORT_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["live"] == []
    assert payload["cursor_model"] is False
    assert payload["empty"] == 0
