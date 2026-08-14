"""Pure contracts for bounded BLF/DBC candidate selection."""

from types import SimpleNamespace


def _probe(
    *, strength, decoded_ratio, signal_count, decoded_signal_count=None,
    exact_coverage=None, sample_ratio=None,
):
    exact = (
        decoded_ratio if exact_coverage is None else exact_coverage
    )
    sample = decoded_ratio if sample_ratio is None else sample_ratio
    return SimpleNamespace(
        strength=strength,
        decoded_frame_ratio=decoded_ratio,
        sample_decode_success_ratio=sample,
        sample_match_ratio=sample,
        estimated_decoded_frame_ratio=sample,
        matched_frame_count=int(round(1000 * exact)),
        total_frame_count=1000,
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


def test_rank_uses_exact_coverage_and_sample_ratio_not_scaled_decoded_ratio():
    from mf4_analyzer.blf_dbc_candidates import rank_candidates

    first_sampled_strong = {
        "paths": ["front-strong.dbc"],
        "recent_rank": 10,
        "probe": _probe(
            strength="strong",
            decoded_ratio=0.99,
            signal_count=2,
            exact_coverage=0.80,
            sample_ratio=0.85,
        ),
    }
    actually_better = {
        "paths": ["better.dbc"],
        "recent_rank": 1,
        "probe": _probe(
            strength="strong",
            decoded_ratio=0.80,
            signal_count=2,
            exact_coverage=0.95,
            sample_ratio=0.99,
        ),
    }

    ranked = rank_candidates([first_sampled_strong, actually_better])
    assert ranked[0] is actually_better


def test_rank_tie_breaks_by_structure_path_then_stable_filename():
    from mf4_analyzer.blf_dbc_candidates import StructuralScore, rank_candidates

    shared = _probe(
        strength="strong",
        decoded_ratio=0.9,
        signal_count=3,
        exact_coverage=0.9,
        sample_ratio=0.9,
    )
    later_name = {
        "paths": ["/bus/z-end.dbc"],
        "recent_rank": 1,
        "structural_score": StructuralScore(0.5, 0.5, 1),
        "probe": shared,
    }
    earlier_name = {
        "paths": ["/bus/a-start.dbc"],
        "recent_rank": 1,
        "structural_score": StructuralScore(0.5, 0.5, 1),
        "probe": shared,
    }

    ranked = rank_candidates([later_name, earlier_name])
    assert ranked[0] is earlier_name


def test_unprobed_candidate_is_reported_as_unverified():
    from mf4_analyzer.blf_dbc_candidates import candidate_status

    assert candidate_status({"paths": ["later.dbc"], "probe": None}) == "unverified"


def _incomplete_probe(reason):
    """A probe that stopped early: nothing was proved, in either direction."""
    return SimpleNamespace(
        strength="none",
        sampling_complete=False,
        sampling_strategy="incomplete",
        estimate_unavailable_reason=reason,
        decoded_frame_ratio=0.0,
        sample_decode_success_ratio=0.0,
        sample_match_ratio=0.0,
        estimated_decoded_frame_ratio=None,
        matched_frame_count=0,
        total_frame_count=1000,
        signal_names=(),
        decoded_signal_count=0,
    )


def test_cancelled_or_truncated_probe_is_incomplete_not_mismatch():
    """§4.1: absent evidence is not evidence of absence."""
    from mf4_analyzer.blf_dbc_candidates import candidate_status

    for reason in ("cancelled", "truncated_sample", "corrupt_sample"):
        candidate = {
            "paths": ["bus.dbc"],
            "probe_attempted": True,
            "probe": _incomplete_probe(reason),
        }
        assert candidate_status(candidate) == "incomplete"


def test_incomplete_still_reports_a_strength_that_was_actually_proved():
    from mf4_analyzer.blf_dbc_candidates import candidate_status

    partial = _incomplete_probe("cancelled")
    partial.strength = "weak"
    partial.signal_names = ("EngineSpeed",)

    assert candidate_status({"paths": ["bus.dbc"], "probe": partial}) == "weak"


def test_incomplete_ranks_between_unverified_and_mismatch():
    from mf4_analyzer.blf_dbc_candidates import rank_candidates

    # Filenames deliberately sort against the wanted order so the assertion
    # can only pass on the status rank, not on the alphabetical tie-break.
    unverified = {"paths": ["z-unverified.dbc"], "recent_rank": 1, "probe": None}
    incomplete = {
        "paths": ["m-incomplete.dbc"],
        "recent_rank": 1,
        "probe_attempted": True,
        "probe": _incomplete_probe("cancelled"),
    }
    mismatch = {
        "paths": ["a-mismatch.dbc"],
        "recent_rank": 1,
        "probe": _probe(strength="none", decoded_ratio=0.0, signal_count=0),
    }

    ranked = rank_candidates([mismatch, incomplete, unverified])

    assert [candidate["paths"][0] for candidate in ranked] == [
        "z-unverified.dbc",
        "m-incomplete.dbc",
        "a-mismatch.dbc",
    ]
