"""Unit contracts for the collision-safe pyqtgraph channel mapping."""

from __future__ import annotations

import pytest

from mf4_analyzer.ui.pg_canvas._shared import (
    _ChannelKeyDict,
    _view_state_channel_key,
)


_LABEL = "[same-file-label] torque"
_KEY_A = _view_state_channel_key("file-A", _LABEL)
_KEY_B = _view_state_channel_key("file-B", _LABEL)


def _colliding_dict() -> _ChannelKeyDict:
    mapping = _ChannelKeyDict()
    mapping.set_with_label(_KEY_A, _LABEL, "A-data")
    mapping.set_with_label(_KEY_B, _LABEL, "B-data")
    return mapping


def test_setdefault_existing_collision_does_not_create_masking_phantom_key():
    mapping = _colliding_dict()

    result = mapping.setdefault(_LABEL, "phantom")

    # Ambiguous compatibility reads remain last-bound-wins, but setdefault
    # must not insert a bare display key that masks both composite entries.
    assert result == "B-data"
    assert len(mapping) == 2
    assert not dict.__contains__(mapping, _LABEL)
    assert mapping[_LABEL] == "B-data"
    assert list(mapping.composite_items()) == [
        (_KEY_A, _LABEL, "A-data"),
        (_KEY_B, _LABEL, "B-data"),
    ]


def test_setdefault_absent_key_inserts_exactly_once():
    mapping = _colliding_dict()

    assert mapping.setdefault("new-channel", "new-data") == "new-data"
    assert mapping.setdefault("new-channel", "other-data") == "new-data"

    assert len(mapping) == 3
    assert mapping["new-channel"] == "new-data"


def test_pop_ambiguous_label_removes_only_last_bound_composite_entry():
    mapping = _colliding_dict()

    assert mapping.pop(_LABEL) == "B-data"

    assert len(mapping) == 1
    assert mapping[_KEY_A] == "A-data"
    assert mapping[_LABEL] == "A-data"
    assert _KEY_B not in mapping
    assert not dict.__contains__(mapping, _LABEL)


def test_delitem_composite_key_does_not_delete_same_label_sibling():
    mapping = _colliding_dict()

    del mapping[_KEY_A]

    assert len(mapping) == 1
    assert mapping[_KEY_B] == "B-data"
    assert mapping[_LABEL] == "B-data"
    assert _KEY_A not in mapping
    assert not dict.__contains__(mapping, _LABEL)


def test_copy_preserves_type_composite_identity_and_colliding_entries():
    mapping = _colliding_dict()

    clone = mapping.copy()

    assert isinstance(clone, _ChannelKeyDict)
    assert clone is not mapping
    assert list(clone.composite_items()) == list(mapping.composite_items())
    assert len(clone) == 2


def test_update_from_channel_key_dict_preserves_both_colliding_entries():
    source = _colliding_dict()
    target = _ChannelKeyDict()

    target.update(source)

    assert list(target.composite_items()) == list(source.composite_items())
    assert len(target) == 2
    assert not dict.__contains__(target, _LABEL)


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        ({"plain": 1}, [("plain", "plain", 1)]),
        ([(_view_state_channel_key("file-C", "speed"), 2)],
         [(_view_state_channel_key("file-C", "speed"), "speed", 2)]),
    ],
)
def test_update_keeps_plain_mapping_and_pair_iterable_behaviour(other, expected):
    mapping = _ChannelKeyDict()

    mapping.update(other, keyword=3)

    assert list(mapping.composite_items()) == [*expected, ("keyword", "keyword", 3)]


def test_resolve_unique_fails_closed_for_absent_or_ambiguous_labels():
    mapping = _colliding_dict()

    assert mapping.resolve_unique("missing") is None
    assert mapping.resolve_unique(_LABEL) is None
    assert mapping.resolve_unique(_KEY_A) == _KEY_A
    assert mapping.resolve_unique(_KEY_B) == _KEY_B

    mapping.pop(_KEY_B)
    assert mapping.resolve_unique(_LABEL) == _KEY_A


def test_as_composite_dict_is_lossless_for_colliding_labels():
    mapping = _colliding_dict()

    assert mapping.as_composite_dict() == {
        _KEY_A: "A-data",
        _KEY_B: "B-data",
    }


def test_plain_dict_conversions_document_phase2_collision_limit():
    mapping = _colliding_dict()

    # Accepted Phase 1 limitation: the display-key iteration surface cannot be
    # represented losslessly by a plain dict. Use as_composite_dict() instead;
    # changing this contract belongs to Phase 2 surface separation.
    assert len(dict(mapping)) == 1
    assert len({**mapping}) == 1
    assert len({key: value for key, value in mapping.items()}) == 1
    assert len(mapping.as_composite_dict()) == 2
