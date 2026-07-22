"""Pure contracts for bounded BLF/DBC candidate selection."""

from types import SimpleNamespace


def _probe(
    *, strength, decoded_ratio, signal_count, decoded_signal_count=None,
):
    return SimpleNamespace(
        strength=strength,
        decoded_frame_ratio=decoded_ratio,
        signal_names=tuple(f"signal_{index}" for index in range(signal_count)),
        decoded_signal_count=(
            signal_count
            if decoded_signal_count is None
            else decoded_signal_count
        ),
    )


def test_candidate_identity_is_order_independent_and_path_normalized(tmp_path):
    from mf4_analyzer.blf_dbc_candidates import dbc_candidate_identity

    first = tmp_path / "first.dbc"
    second = tmp_path / "second.dbc"
    first.touch()
    second.touch()
    alias = tmp_path / "first-alias.dbc"
    alias.symlink_to(first)

    assert dbc_candidate_identity([first, second, alias]) == dbc_candidate_identity(
        [second, first]
    )


def test_recent_history_deduplicates_equivalent_dbc_sets(tmp_path):
    from mf4_analyzer.blf_dbc_candidates import deduplicate_dbc_sets

    first = tmp_path / "first.dbc"
    second = tmp_path / "second.dbc"
    first.touch()
    second.touch()

    deduplicated = deduplicate_dbc_sets(
        [[first, second], [second, first], [first]]
    )

    assert len(deduplicated) == 2
    assert deduplicated[0] == (str(first.resolve()), str(second.resolve()))
    assert deduplicated[1] == (str(first.resolve()),)


def test_structural_prefilter_ranks_id_overlap_without_decoding_frames():
    from mf4_analyzer.blf_dbc_candidates import prefilter_candidates

    blf_id_counts = {0x100: 80, 0x200: 15, 0x300: 5}
    candidates = [
        {"paths": ["recent.dbc"], "recent_rank": 2, "dbc_frame_ids": {0x300}},
        {
            "paths": ["high-overlap.dbc"],
            "recent_rank": 1,
            "dbc_frame_ids": {0x100, 0x200},
        },
        {"paths": ["none.dbc"], "recent_rank": 3, "dbc_frame_ids": {0x999}},
    ]

    ranked = prefilter_candidates(candidates, blf_id_counts)

    assert [candidate["paths"][0] for candidate in ranked] == [
        "high-overlap.dbc",
        "recent.dbc",
        "none.dbc",
    ]
    assert ranked[0]["structural_score"].frame_coverage == 0.95


def test_auto_probe_limit_is_three():
    from mf4_analyzer.blf_dbc_candidates import AUTO_PROBE_LIMIT

    assert AUTO_PROBE_LIMIT == 3


def test_strong_candidate_ranks_before_weak_recent_candidate():
    from mf4_analyzer.blf_dbc_candidates import rank_candidates

    recent_weak = {
        "paths": ["recent.dbc"],
        "recent_rank": 10,
        "probe": _probe(strength="weak", decoded_ratio=0.7, signal_count=20),
    }
    older_strong = {
        "paths": ["strong.dbc"],
        "recent_rank": 1,
        "probe": _probe(strength="strong", decoded_ratio=0.8, signal_count=2),
    }

    assert rank_candidates([recent_weak, older_strong])[0] is older_strong


def test_equal_strength_ranks_by_unique_signal_names_not_decoded_samples():
    from mf4_analyzer.blf_dbc_candidates import rank_candidates

    repetitive = {
        "paths": ["repetitive.dbc"],
        "recent_rank": 1,
        "probe": _probe(
            strength="strong",
            decoded_ratio=0.9,
            signal_count=1,
            decoded_signal_count=10_000,
        ),
    }
    richer = {
        "paths": ["richer.dbc"],
        "recent_rank": 1,
        "probe": _probe(
            strength="strong",
            decoded_ratio=0.9,
            signal_count=5,
            decoded_signal_count=5,
        ),
    }

    assert rank_candidates([repetitive, richer])[0] is richer


def test_unprobed_candidate_is_reported_as_unverified():
    from mf4_analyzer.blf_dbc_candidates import candidate_status

    assert candidate_status({"paths": ["later.dbc"], "probe": None}) == "unverified"
