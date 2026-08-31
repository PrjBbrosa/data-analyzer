"""Core owner tests for UI-neutral Custom-X major-path analysis."""
from __future__ import annotations

import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from mf4_analyzer.signal.custom_x_paths import (
    REASON_EMPTY,
    REASON_INCOMPATIBLE_SHAPE,
    REASON_MULTIPLE_PATHS,
    REASON_SAME_DIRECTION,
    REASON_SHORT_SEQUENCE,
    REASON_UNIDIRECTIONAL,
    REASON_UNIQUE_PAIR,
    PathContribution,
    sample_custom_x_cursor,
    sample_custom_x_cursor_from_paths,
    sample_custom_x_dual_delta_from_paths,
    analyze_custom_x_paths,
)


def _noisy_single_cycle():
    """One physical out-and-back path with deterministic quantisation chatter."""
    forward = np.linspace(-83.0, 83.0, 2001)
    backward = np.linspace(83.0, -83.0, 2001)[1:]
    x = np.concatenate((forward, backward))
    chatter = np.resize(
        np.asarray((0.20, 0.10, 0.0, -0.10, -0.20, -0.10, 0.0, 0.10)), x.size,
    )
    return x + chatter


def _out_and_back(n=201, lo=-83.0, hi=83.0):
    forward = np.linspace(lo, hi, n)
    backward = np.linspace(hi, lo, n)[1:]
    return np.concatenate((forward, backward))


def test_unique_up_and_down_pair_keeps_acquisition_order_and_indices():
    x = _out_and_back()
    y = np.arange(x.size, dtype=float)
    result = analyze_custom_x_paths(x, y)

    assert result.unique_pair
    assert result.reason == REASON_UNIQUE_PAIR
    assert [item.direction for item in result.accepted] == [1, -1]
    for item in result.accepted:
        np.testing.assert_array_equal(item.x, x[item.indices])
        np.testing.assert_array_equal(item.y, y[item.indices])
        assert np.all(np.isfinite(item.x))
        assert np.all(np.isfinite(item.y))


def test_direction_comes_from_x_not_y_sign():
    x = _out_and_back(n=21)
    expected = None
    for y in (
        np.arange(x.size, dtype=float),
        -np.arange(x.size, dtype=float),
        np.full(x.size, -4.0),
    ):
        result = analyze_custom_x_paths(x, y)
        current = [item.direction for item in result.accepted]
        assert result.unique_pair
        assert current == [1, -1]
        assert expected is None or current == expected
        expected = current


def test_unidirectional_series_is_not_a_forged_pair():
    x = np.linspace(-83.0, 83.0, 401)
    result = analyze_custom_x_paths(x, np.arange(x.size, dtype=float))

    assert not result.unique_pair
    assert result.reason == REASON_UNIDIRECTIONAL
    assert len(result.accepted) == 1
    assert result.accepted[0].direction == 1


def test_short_cycle_is_not_a_forged_pair():
    result = analyze_custom_x_paths(
        [0.0, 1.0, 2.0, 1.0, 0.0], np.arange(5, dtype=float),
    )

    assert not result.unique_pair
    assert result.reason in (REASON_SHORT_SEQUENCE, REASON_UNIDIRECTIONAL)
    assert len(result.accepted) <= 1


def test_undersized_range_visits_stay_in_fallback_not_accepted_paths():
    x = _noisy_single_cycle()
    result = analyze_custom_x_paths(x, np.arange(x.size, dtype=float), x_range=(-0.25, 0.25))

    assert not result.unique_pair
    assert result.reason == REASON_SHORT_SEQUENCE
    assert result.accepted == ()
    assert result.contributions
    assert all(item.sample_count > 0 for item in result.contributions)
    concat_y = np.concatenate(tuple(item.y for item in result.contributions))
    assert np.all(np.isfinite(concat_y))


def test_empty_range_has_no_fake_zero_or_nan_stats():
    x = _out_and_back()
    y = np.arange(x.size, dtype=float)
    result = analyze_custom_x_paths(x, y, x_range=(200.0, 300.0))

    assert not result.unique_pair
    assert result.reason == REASON_EMPTY
    assert result.accepted == ()
    assert result.contributions == ()
    for item in (*result.accepted, *result.contributions):
        assert item.sample_count > 0
        assert not np.any(item.y == 0.0)
        assert np.all(np.isfinite(item.y))


def test_empty_arrays_are_empty_not_numeric_placeholders():
    result = analyze_custom_x_paths(np.asarray([], dtype=float), np.asarray([], dtype=float))

    assert result.reason == REASON_EMPTY
    assert result.accepted == ()
    assert result.contributions == ()


def test_two_same_direction_visits_are_not_an_up_down_pair():
    upward = np.linspace(-30.0, 30.0, 121)
    x = np.concatenate((upward, np.asarray((np.nan,)), upward))
    result = analyze_custom_x_paths(x, np.arange(x.size, dtype=float), x_range=(21.0, 29.0))

    assert not result.unique_pair
    assert result.reason == REASON_SAME_DIRECTION
    assert len(result.accepted) == 2
    assert [item.direction for item in result.accepted] == [1, 1]


def test_three_or_more_major_paths_are_not_collapsed_to_a_pair():
    x = np.concatenate((
        np.linspace(-30.0, 30.0, 121),
        np.linspace(30.0, -30.0, 121)[1:],
        np.linspace(-30.0, 30.0, 121)[1:],
    ))
    result = analyze_custom_x_paths(x, np.arange(x.size, dtype=float), x_range=(21.0, 29.0))

    assert not result.unique_pair
    assert result.reason == REASON_MULTIPLE_PATHS
    assert len(result.accepted) == 3


@pytest.mark.parametrize(
    ("gap_x", "gap_y"),
    ((np.nan, 3.0), (np.inf, 3.0), (2.0, np.nan), (2.0, np.inf)),
)
def test_nonfinite_samples_are_hard_segment_boundaries(gap_x, gap_y):
    x = np.asarray([0.0, 1.0, 2.0, gap_x, 2.0, 1.0, 0.0], dtype=float)
    y = np.asarray([0.0, 1.0, 2.0, gap_y, 4.0, 5.0, 6.0], dtype=float)
    result = analyze_custom_x_paths(x, y)

    assert result.unique_pair
    assert [item.direction for item in result.accepted] == [1, -1]
    assert [item.sample_count for item in result.accepted] == [3, 3]
    used = np.concatenate(tuple(item.indices for item in result.accepted))
    assert 3 not in set(used.tolist())
    assert not np.any(~np.isfinite(x[used]))
    assert not np.any(~np.isfinite(y[used]))


def test_quantisation_chatter_does_not_create_extra_physical_reversals():
    x = _noisy_single_cycle()
    expected = None
    for y in (np.arange(x.size), np.arange(x.size) + 5000, -np.arange(x.size)):
        result = analyze_custom_x_paths(x, y, x_range=(-20.0, 20.0))
        current = [(item.direction, item.sample_count) for item in result.accepted]
        assert result.unique_pair
        assert result.reason == REASON_UNIQUE_PAIR
        assert [item.direction for item in result.accepted] == [1, -1]
        assert all(item.sample_count > 400 for item in result.accepted)
        assert expected is None or current == expected
        expected = current


def test_turn_policy_signature_does_not_take_selection_range():
    from mf4_analyzer.signal import custom_x_paths as module

    assert list(inspect.signature(module._turn_policy).parameters) == ["x"]


def test_turn_policy_uses_complete_segment_span_not_ab_range(monkeypatch):
    from mf4_analyzer.signal import custom_x_paths as module

    seen: list[np.ndarray] = []
    original = module._turn_policy

    def _capture(segment_x):
        seen.append(np.asarray(segment_x, dtype=float).copy())
        return original(segment_x)

    monkeypatch.setattr(module, "_turn_policy", _capture)
    x = _out_and_back()
    analyze_custom_x_paths(x, np.arange(x.size, dtype=float), x_range=(-20.0, 20.0))

    assert seen
    for segment_x in seen:
        assert float(np.ptp(segment_x)) == pytest.approx(166.0)
        assert float(segment_x[0]) == pytest.approx(-83.0)


def test_turning_point_range_still_finds_the_unique_pair():
    """A 1 mm A/B window must not shrink turn_distance below the noise floor."""
    x = _noisy_single_cycle()
    y = np.arange(x.size, dtype=float)
    full = analyze_custom_x_paths(x, y)
    narrow = analyze_custom_x_paths(x, y, x_range=(81.7, 82.7))

    assert full.unique_pair
    assert narrow.unique_pair
    assert [item.direction for item in narrow.accepted] == [1, -1]


def test_misaligned_xy_are_rejected():
    with pytest.raises(ValueError, match="aligned"):
        analyze_custom_x_paths([0.0, 1.0], [0.0])


def _cursor_out_and_back():
    """Two deliberately different local branches at the same X values."""
    rising_x = np.linspace(0.0, 10.0, 101)
    falling_x = np.linspace(10.0, 0.0, 101)[1:]
    x = np.concatenate((rising_x, falling_x))
    y = np.concatenate((10.0 * rising_x, 100.0 + falling_x))
    return x, y


def test_sample_custom_x_cursor_returns_rise_then_fall_values():
    x, y = _cursor_out_and_back()

    result = sample_custom_x_cursor(x, y, 4.0)

    assert result.reason == REASON_UNIQUE_PAIR
    assert [item.direction for item in result.values] == [1, -1]
    assert [item.value for item in result.values] == pytest.approx([40.0, 104.0])


def test_sample_custom_x_cursor_orders_branches_rise_then_fall_not_by_acquisition():
    falling_x = np.linspace(10.0, 0.0, 101)
    rising_x = np.linspace(0.0, 10.0, 101)[1:]
    x = np.concatenate((falling_x, rising_x))
    y = np.concatenate((100.0 + falling_x, 10.0 * rising_x))

    result = sample_custom_x_cursor(x, y, 4.0)

    assert result.reason == REASON_UNIQUE_PAIR
    assert [item.direction for item in result.values] == [1, -1]
    assert [item.value for item in result.values] == pytest.approx([40.0, 104.0])


def test_sample_custom_x_cursor_interpolates_within_each_leg_only():
    x, y = _cursor_out_and_back()

    result = sample_custom_x_cursor(x, y, 4.25)

    assert [item.direction for item in result.values] == [1, -1]
    assert [item.value for item in result.values] == pytest.approx([42.5, 104.25])


def test_sample_custom_x_cursor_reports_one_reliable_direction():
    x = np.arange(101, dtype=np.int64)
    y = 3 * x + 1

    result = sample_custom_x_cursor(x, y, 12.5)

    assert result.reason == REASON_UNIDIRECTIONAL
    assert len(result.values) == 1
    assert result.values[0].direction == 1
    assert result.values[0].value == pytest.approx(38.5)
    assert isinstance(result.values[0].value, float)


def test_sample_custom_x_cursor_rejects_shape_mismatch_without_truncation():
    result = sample_custom_x_cursor(
        np.asarray([0.0, 1.0, 2.0]), np.asarray([10.0, 11.0]), 1.0,
    )

    assert result.values == ()
    assert result.reason == REASON_INCOMPATIBLE_SHAPE


def test_sample_custom_x_cursor_handles_empty_short_and_nonfinite_segments():
    empty = sample_custom_x_cursor(np.asarray([]), np.asarray([]), 1.0)
    short = sample_custom_x_cursor(np.asarray([0.0, 1.0]), np.asarray([0.0, 1.0]), 0.5)
    x, y = _cursor_out_and_back()
    y[100] = np.nan
    segmented = sample_custom_x_cursor(x, y, 4.0)

    assert empty.values == ()
    assert empty.reason == REASON_EMPTY
    assert short.values == ()
    assert short.reason == REASON_SHORT_SEQUENCE
    assert [item.direction for item in segmented.values] == [1, -1]
    assert [item.value for item in segmented.values] == pytest.approx([40.0, 104.0])
    assert all(np.isfinite(item.value) for item in segmented.values)


@pytest.mark.parametrize("x_value", (-0.1, 10.1, np.nan, np.inf))
def test_sample_custom_x_cursor_does_not_extrapolate(x_value):
    x, y = _cursor_out_and_back()

    result = sample_custom_x_cursor(x, y, x_value)

    assert result.values == ()
    assert result.reason == REASON_EMPTY


def test_sample_custom_x_cursor_reports_ambiguous_multi_turn_path():
    x = np.concatenate((
        np.linspace(-30.0, 30.0, 121),
        np.linspace(30.0, -30.0, 121)[1:],
        np.linspace(-30.0, 30.0, 121)[1:],
    ))

    result = sample_custom_x_cursor(x, np.arange(x.size, dtype=float), 24.0)

    assert result.values == ()
    assert result.reason == REASON_MULTIPLE_PATHS


def test_sample_custom_x_cursor_handles_endpoints_dtypes_repeated_turns_and_tolerance():
    rising_x = np.linspace(0.0, 10.0, 101)
    falling_x = np.linspace(10.0, 0.0, 101)
    repeated_turn_x = np.concatenate((rising_x, falling_x))
    repeated_turn_y = np.concatenate((10.0 * rising_x, 100.0 + falling_x))

    low = sample_custom_x_cursor(repeated_turn_x.astype(np.int64), repeated_turn_y.astype(np.int64), 0)
    high = sample_custom_x_cursor(repeated_turn_x.astype(np.float32), repeated_turn_y.astype(np.float32), 10.0)
    noisy_x = _noisy_single_cycle()
    noisy_y = 2.0 * noisy_x + np.where(np.arange(noisy_x.size) < noisy_x.size // 2, 0.0, 1000.0)
    noisy = sample_custom_x_cursor(noisy_x, noisy_y, 20.0)

    assert [item.direction for item in low.values] == [1, -1]
    assert [item.value for item in low.values] == pytest.approx([0.0, 100.0])
    assert [item.direction for item in high.values] == [1, -1]
    assert [item.value for item in high.values] == pytest.approx([100.0, 100.0])
    assert [item.direction for item in noisy.values] == [1, -1]
    assert all(np.isfinite(item.value) for item in noisy.values)


def _plan_channel_x(x, y, lo=None, hi=None):
    from mf4_analyzer.batch_statistics import StatisticSeriesInput, plan_chart_statistics

    config = {
        "enabled": True,
        "range_mode": "custom" if lo is not None else "full",
        "x_min": lo,
        "x_max": hi,
        "metrics": ["max", "min", "mean"],
    }
    series = StatisticSeriesInput(
        x=np.asarray(x, dtype=float), y=np.asarray(y, dtype=float),
        series_key="series", family_key="family", label="series",
    )
    return plan_chart_statistics((series,), config, x_source="channel", x_origin="absolute")


def test_batch_rows_match_core_path_result_on_existing_fixtures():
    x = _noisy_single_cycle()
    y = np.arange(x.size, dtype=float)
    cases = (
        (x, y, (-20.0, 20.0)),
        (x, y, None),
        (x, y, (-0.25, 0.25)),
        (np.asarray([0.0, 1.0, 2.0, 1.0, 0.0]), np.arange(5, dtype=float), None),
        (
            np.concatenate((
                np.linspace(-30.0, 30.0, 121),
                np.linspace(30.0, -30.0, 121)[1:],
                np.linspace(-30.0, 30.0, 121)[1:],
            )),
            None,
            (21.0, 29.0),
        ),
        (
            np.concatenate((np.linspace(-30.0, 30.0, 121), np.asarray((np.nan,)), np.linspace(-30.0, 30.0, 121))),
            None,
            (21.0, 29.0),
        ),
    )
    for series_x, series_y, bounds in cases:
        series_y = np.arange(series_x.size, dtype=float) if series_y is None else series_y
        x_range = bounds
        lo, hi = (None, None) if bounds is None else bounds
        result = analyze_custom_x_paths(series_x, series_y, x_range=x_range)
        plan = _plan_channel_x(series_x, series_y, lo=lo, hi=hi)
        if result.unique_pair:
            assert not plan.diagnostics
            assert [row.direction for row in plan.rows] == [
                "X↑" if item.direction > 0 else "X↓" for item in result.accepted
            ]
            for row, item in zip(plan.rows, result.accepted, strict=True):
                assert row.sample_count == item.sample_count
                assert row.minimum == float(np.min(item.y))
                assert row.maximum == float(np.max(item.y))
                assert row.mean == float(np.mean(item.y))
                assert row.argmin_x == float(item.x[int(np.argmin(item.y))])
                assert row.argmax_x == float(item.x[int(np.argmax(item.y))])
            continue
        if result.reason in (REASON_SAME_DIRECTION, REASON_MULTIPLE_PATHS):
            assert plan.rows == ()
            assert [item.code for item in plan.diagnostics] == [
                "chart_statistics.multiple_x_reversals",
            ]
            continue
        assert not plan.diagnostics
        assert len(plan.rows) == 1
        if result.accepted:
            item = result.accepted[0]
            source_x, source_y = item.x, item.y
        else:
            source_x = np.concatenate(tuple(item.x for item in result.contributions)) if result.contributions else np.asarray([], dtype=float)
            source_y = np.concatenate(tuple(item.y for item in result.contributions)) if result.contributions else np.asarray([], dtype=float)
        row = plan.rows[0]
        assert row.branch_label == "全程"
        assert row.sample_count == int(source_x.size)
        if source_y.size:
            assert row.minimum == float(np.min(source_y))
            assert row.maximum == float(np.max(source_y))
            assert row.mean == float(np.mean(source_y))


def test_custom_x_paths_import_does_not_pull_ui_qt_or_batch_renderer():
    repo_root = Path(__file__).resolve().parents[1]
    script = r"""
import json
import sys

sys.modules['PyQt5'] = None
sys.modules['matplotlib'] = None
sys.modules['matplotlib.pyplot'] = None

try:
    import PyQt5  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print('POISON_INEFFECTIVE_PyQt5')
    sys.exit(2)

import mf4_analyzer.signal.custom_x_paths as module
assert callable(module.analyze_custom_x_paths)
blocked = sorted(
    name for name in sys.modules
    if name == 'mf4_analyzer.ui'
    or name.startswith('mf4_analyzer.ui.')
    or name == 'mf4_analyzer.batch_render'
    or name.startswith('mf4_analyzer.batch_render.')
    or name == 'mf4_analyzer.batch_render_qt'
    or name.startswith('mf4_analyzer.batch_render_qt.')
    or (name == 'PyQt5' and sys.modules[name] is not None)
    or name.startswith('PyQt5.')
)
print(json.dumps({'blocked': blocked, 'marker': 'clean'}))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["marker"] == "clean"
    assert payload["blocked"] == []


def _sample_path_contribution_loop_oracle(contribution, x_value):
    """Retired production loop, kept as the numerical oracle for searchsorted."""
    x = contribution.x
    y = contribution.y
    if not x.size or x_value < float(np.min(x)) or x_value > float(np.max(x)):
        return None
    exact = np.flatnonzero(x == x_value)
    if exact.size:
        return float(y[int(exact[0])])
    for index in range(int(x.size) - 1):
        left_x = float(x[index])
        right_x = float(x[index + 1])
        if not min(left_x, right_x) <= x_value <= max(left_x, right_x):
            continue
        if left_x == right_x:
            continue
        fraction = (x_value - left_x) / (right_x - left_x)
        value = float(y[index]) + fraction * (float(y[index + 1]) - float(y[index]))
        return value if math.isfinite(value) else None
    return None


def _assert_searchsorted_matches_oracle(contribution, x_values):
    from mf4_analyzer.signal.custom_x_paths import _sample_path_contribution

    for x_value in x_values:
        got = _sample_path_contribution(contribution, x_value)
        expected = _sample_path_contribution_loop_oracle(contribution, x_value)
        if expected is None:
            assert got is None
            continue
        assert got is not None
        assert got == pytest.approx(expected, rel=1e-12, abs=1e-12)


def _monotonic_round_trip(rng, n=80):
    up_steps = rng.uniform(0.05, 1.4, size=n)
    down_steps = rng.uniform(0.05, 1.4, size=n)
    x_up = np.concatenate((np.asarray((0.0,)), np.cumsum(up_steps)))
    x_down = x_up[-1] - np.cumsum(down_steps)
    x = np.concatenate((x_up, x_down))
    y = np.concatenate((2.0 * x_up, 50.0 + 0.5 * x_down))
    return x, y


def test_sample_from_paths_matches_one_shot_sample_api():
    x, y = _cursor_out_and_back()
    paths = analyze_custom_x_paths(x, y)
    one_shot = sample_custom_x_cursor(x, y, 4.25)
    split = sample_custom_x_cursor_from_paths(paths, 4.25)

    assert split.reason == one_shot.reason
    assert [item.direction for item in split.values] == [
        item.direction for item in one_shot.values
    ]
    assert [item.value for item in split.values] == pytest.approx(
        [item.value for item in one_shot.values]
    )


def test_searchsorted_sample_matches_old_loop_on_random_round_trips():
    rng = np.random.default_rng(20260831)
    for _ in range(8):
        x, y = _monotonic_round_trip(rng)
        paths = analyze_custom_x_paths(x, y)
        assert paths.accepted
        probes = np.concatenate((
            x[:1],
            x[-1:],
            rng.uniform(float(np.min(x)), float(np.max(x)), size=24),
        ))
        for contrib in paths.accepted:
            _assert_searchsorted_matches_oracle(contrib, probes)


def test_searchsorted_sample_matches_old_loop_at_endpoints_duplicates_and_nonfinite():
    from mf4_analyzer.signal.custom_x_paths import _sample_path_contribution

    rising = PathContribution(
        x=np.asarray([0.0, 1.0, 1.0, 2.0, 3.0]),
        y=np.asarray([10.0, 20.0, 21.0, 30.0, 40.0]),
        indices=np.arange(5),
        direction=1,
    )
    falling = PathContribution(
        x=np.asarray([3.0, 2.0, 2.0, 1.0, 0.0]),
        y=np.asarray([4.0, 3.0, 2.5, 1.0, 0.0]),
        indices=np.arange(5),
        direction=-1,
    )
    nonfinite = PathContribution(
        x=np.asarray([0.0, 1.0, 2.0]),
        y=np.asarray([0.0, np.inf, 2.0]),
        indices=np.arange(3),
        direction=1,
    )
    empty = PathContribution(
        x=np.asarray([], dtype=float),
        y=np.asarray([], dtype=float),
        indices=np.asarray([], dtype=int),
        direction=1,
    )
    probes = (-0.5, 0.0, 0.5, 1.0, 1.5, 3.0, 3.5, np.nan, np.inf)
    _assert_searchsorted_matches_oracle(rising, probes)
    _assert_searchsorted_matches_oracle(falling, probes)
    _assert_searchsorted_matches_oracle(nonfinite, (0.5, 1.5))
    assert _sample_path_contribution(empty, 0.0) is None
    assert _sample_path_contribution_loop_oracle(empty, 0.0) is None
    assert _sample_path_contribution(nonfinite, 0.5) is None
    assert _sample_path_contribution(rising, 1.0) == pytest.approx(20.0)


def test_monotonic_leg_interpolates_via_searchsorted(monkeypatch):
    from mf4_analyzer.signal import custom_x_paths as module

    calls = []
    original = module.np.searchsorted

    def _wrapped(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module.np, "searchsorted", _wrapped)
    contrib = PathContribution(
        x=np.linspace(0.0, 10.0, 21),
        y=np.linspace(0.0, 40.0, 21),
        indices=np.arange(21),
        direction=1,
    )
    value = module._sample_path_contribution(contrib, 4.25)
    assert calls
    assert value == pytest.approx(17.0)


def test_searchsorted_sample_matches_old_loop_on_hysteresis_fixtures():
    from tests._helpers import wwt_factory as wwt

    series_list = (
        wwt.sfns_like_hysteresis_arrays("cycle"),
        wwt.sfns_like_hysteresis_arrays("noisy"),
        wwt.sfns_like_hysteresis_arrays("unidirectional"),
    )
    noisy_x = _noisy_single_cycle()
    extra = ((noisy_x, np.arange(noisy_x.size, dtype=float)),)
    for series in series_list:
        extra += ((series.x, series.y),)
    for x, y in extra:
        paths = analyze_custom_x_paths(x, y)
        lo = float(np.nanmin(x))
        hi = float(np.nanmax(x))
        mid = 0.5 * (lo + hi)
        probes = (lo, mid, hi, lo + 0.1 * (hi - lo), hi - 0.1 * (hi - lo))
        for contrib in (*paths.accepted, *paths.contributions):
            _assert_searchsorted_matches_oracle(contrib, probes)


def test_dual_delta_samples_each_leg_independently_when_both_ends_are_on_it():
    x, y = _cursor_out_and_back()
    paths = analyze_custom_x_paths(x, y)
    deltas = dict(sample_custom_x_dual_delta_from_paths(paths, 2.0, 8.0))

    assert paths.unique_pair
    assert set(deltas) == {1, -1}
    assert deltas[1] == pytest.approx(60.0)
    assert deltas[-1] == pytest.approx(6.0)


def test_dual_delta_is_none_when_one_end_is_outside_the_leg():
    x, y = _cursor_out_and_back()
    paths = analyze_custom_x_paths(x, y)
    deltas = dict(sample_custom_x_dual_delta_from_paths(paths, -1.0, 4.0))

    assert set(deltas) == {1, -1}
    assert deltas[1] is None
    assert deltas[-1] is None


def test_dual_delta_unidirectional_leg_uses_the_same_interpolator():
    x = np.arange(101, dtype=float)
    y = 3.0 * x + 1.0
    paths = analyze_custom_x_paths(x, y)
    deltas = dict(sample_custom_x_dual_delta_from_paths(paths, 12.5, 20.0))

    assert paths.reason == REASON_UNIDIRECTIONAL
    assert list(deltas) == [1]
    assert deltas[1] == pytest.approx(22.5)

    out_of_range = dict(sample_custom_x_dual_delta_from_paths(paths, 12.5, 200.0))
    assert out_of_range[1] is None


def test_dual_delta_non_finite_cursor_or_difference_is_none():
    x, y = _cursor_out_and_back()
    paths = analyze_custom_x_paths(x, y)
    for x_a, x_b in ((math.nan, 4.0), (4.0, math.inf), (math.inf, math.nan)):
        deltas = dict(sample_custom_x_dual_delta_from_paths(paths, x_a, x_b))
        assert set(deltas) == {1, -1}
        assert deltas[1] is None
        assert deltas[-1] is None
