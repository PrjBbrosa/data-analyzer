"""Pairing rule for one physical path's saved rows and reloaded groups."""
from mf4_analyzer.ui.project_source_match import (
    LEVEL_EVIDENCE,
    LEVEL_IDENTITY,
    LEVEL_MISSING,
    LEVEL_SOLE,
    LEVEL_UNVERIFIED,
    SourceCandidateFact,
    SourceRefFact,
    loader_channel_names,
    match_project_sources,
)


def _ref(key, *, group_id="", channels=(), fs=None, time_source="column", edits=()):
    return SourceRefFact(
        key=key,
        group_id=group_id,
        loader_channels=frozenset(channels),
        fs=fs,
        time_source=time_source,
    )


def _cand(key, *, group_id="", channels=(), fs=None):
    return SourceCandidateFact(
        key=key,
        group_id=group_id,
        channels=frozenset(channels),
        measured_fs=fs,
    )


def _levels(refs, candidates):
    return {
        item.ref_key: (item.candidate_key, item.level)
        for item in match_project_sources(refs, candidates)
    }


def test_loader_channel_names_drop_derives_and_restore_removes():
    names = loader_channel_names(
        ["torque", "scaled", "speed"],
        [
            {"op": "derive", "name": "scaled"},
            {"op": "remove", "names": ["rack", "scaled"]},
        ],
    )
    assert names == frozenset({"torque", "speed", "rack"})


def test_identity_wins_over_load_order():
    paired = _levels(
        (
            _ref("a", group_id="slow", channels={"rack"}),
            _ref("b", group_id="fast", channels={"torque"}),
        ),
        (
            _cand("new-fast", group_id="fast", channels={"torque"}),
            _cand("new-slow", group_id="slow", channels={"rack"}),
        ),
    )
    assert paired == {
        "a": ("new-slow", LEVEL_IDENTITY),
        "b": ("new-fast", LEVEL_IDENTITY),
    }


def test_disjoint_channel_names_are_unique_evidence():
    paired = _levels(
        (
            _ref("a", channels={"torque", "speed"}),
            _ref("b", channels={"rack"}),
        ),
        (
            _cand("slow", channels={"rack"}, fs=50.0),
            _cand("fast", channels={"torque", "speed"}, fs=100.0),
        ),
    )
    assert paired == {
        "a": ("fast", LEVEL_EVIDENCE),
        "b": ("slow", LEVEL_EVIDENCE),
    }


def test_same_names_and_same_rate_stay_positional_and_unverified():
    paired = _levels(
        (
            _ref("a", channels={"torque"}, fs=100.0),
            _ref("b", channels={"torque"}, fs=100.0),
        ),
        (
            _cand("first", channels={"torque"}, fs=100.0),
            _cand("second", channels={"torque"}, fs=100.0),
        ),
    )
    assert paired == {
        "a": ("first", LEVEL_UNVERIFIED),
        "b": ("second", LEVEL_UNVERIFIED),
    }


def test_measured_rate_breaks_a_same_name_tie_unless_the_rate_was_manual():
    column = _levels(
        (
            _ref("a", channels={"torque"}, fs=100.0, time_source="column"),
            _ref("b", channels={"torque"}, fs=50.0, time_source="column"),
        ),
        (
            _cand("slow", channels={"torque"}, fs=50.0),
            _cand("fast", channels={"torque"}, fs=100.0),
        ),
    )
    assert column == {
        "a": ("fast", LEVEL_EVIDENCE),
        "b": ("slow", LEVEL_EVIDENCE),
    }
    manual = _levels(
        (
            _ref("a", channels={"torque"}, fs=100.0, time_source="manual"),
            _ref("b", channels={"torque"}, fs=50.0, time_source="manual"),
        ),
        (
            _cand("slow", channels={"torque"}, fs=50.0),
            _cand("fast", channels={"torque"}, fs=100.0),
        ),
    )
    assert manual["a"][1] == LEVEL_UNVERIFIED
    assert manual["b"][1] == LEVEL_UNVERIFIED


def test_one_row_and_one_group_is_the_file_itself():
    paired = _levels(
        (_ref("a", channels=()),),
        (_cand("only", channels={"torque"}),),
    )
    assert paired == {"a": ("only", LEVEL_SOLE)}


def test_two_rows_without_channel_evidence_stay_unverified():
    paired = _levels(
        (_ref("a", channels=()), _ref("b", channels=())),
        (_cand("first", channels={"torque"}), _cand("second", channels={"rack"})),
    )
    assert paired == {
        "a": ("first", LEVEL_UNVERIFIED),
        "b": ("second", LEVEL_UNVERIFIED),
    }


def test_a_vanished_group_is_missing_and_the_file_is_not_paired_twice():
    paired = _levels(
        (
            _ref("fast", group_id="fast", channels={"torque"}),
            _ref("slow", group_id="slow", channels={"rack"}),
        ),
        (_cand("new-fast", group_id="fast", channels={"torque"}),),
    )
    assert paired == {
        "fast": ("new-fast", LEVEL_IDENTITY),
        "slow": (None, LEVEL_MISSING),
    }


def test_extra_group_stays_unreferenced_when_the_others_are_unique():
    paired = _levels(
        (
            _ref("a", channels={"torque"}),
            _ref("b", channels={"rack"}),
        ),
        (
            _cand("fast", channels={"torque"}),
            _cand("slow", channels={"rack"}),
            _cand("extra", channels={"pressure"}),
        ),
    )
    assert paired == {
        "a": ("fast", LEVEL_EVIDENCE),
        "b": ("slow", LEVEL_EVIDENCE),
    }


def test_root_is_not_a_split_identity():
    paired = _levels(
        (_ref("a", group_id="root", channels={"torque"}),),
        (_cand("only", group_id="root", channels={"torque"}, fs=10.0),),
    )
    assert paired == {"a": ("only", LEVEL_EVIDENCE)}


def test_ambiguous_count_mismatch_does_not_invent_a_second_load():
    paired = _levels(
        (
            _ref("a", channels={"torque"}),
            _ref("b", channels={"torque"}),
        ),
        (_cand("only", channels={"torque"}),),
    )
    assert paired == {
        "a": ("only", LEVEL_UNVERIFIED),
        "b": (None, LEVEL_MISSING),
    }
