"""Live-sparkline downsampler tests (Stage 4).

Pure-Python tests — no Qt platform required.

Contract (spec §Center Pane, plan task):

- Input: N timestamped samples and W target pixels.
- Output: W ``(min, max)`` bins.
- N < W → one bin per sample, right-pad with ``None``, no
  interpolation.
- N >= W → bucket the time axis into W equal-width buckets.
"""

from __future__ import annotations

import math

import pytest

from mf4_analyzer.acquisition_ui.widgets.live_downsampler import (
    _DISPLAY_BUCKET_S,
    RollingDisplayBuckets,
    downsample_minmax,
)


def test_empty_returns_all_gaps():
    out = downsample_minmax([], 4)
    assert out == [None, None, None, None]


def test_target_pixels_zero_raises():
    with pytest.raises(ValueError):
        downsample_minmax([(0.0, 0.0)], 0)


def test_one_bin_per_sample_when_n_less_than_w():
    samples = [(0.0, 1.0), (0.1, 2.0), (0.2, 3.0)]
    out = downsample_minmax(samples, 6)
    # First three bins are (v, v); last three are None.
    assert out[0] == (1.0, 1.0)
    assert out[1] == (2.0, 2.0)
    assert out[2] == (3.0, 3.0)
    assert out[3] is None
    assert out[4] is None
    assert out[5] is None
    # Length is exactly W.
    assert len(out) == 6


def test_n_equal_w_one_bin_per_sample():
    samples = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]
    out = downsample_minmax(samples, 4)
    assert len(out) == 4
    # Each bin spans one bucket. The last sample is clamped into the
    # final bucket (right-edge rule).
    assert out[0] is not None
    assert out[-1] is not None


def test_n_greater_than_w_min_max_per_bucket():
    # 10 samples spread linearly over [0, 1], W=2 ⇒ two buckets of 5
    # samples each. Values are the sample index so min/max are
    # known exactly.
    samples = [(i / 9.0, float(i)) for i in range(10)]
    out = downsample_minmax(samples, 2)
    assert len(out) == 2
    # First bucket: indices 0..4 (or 0..3 due to clamp). Both halves
    # should be non-None and ordered min <= max.
    assert out[0] is not None and out[1] is not None
    lo0, hi0 = out[0]
    lo1, hi1 = out[1]
    assert lo0 <= hi0
    assert lo1 <= hi1
    # First bucket min == 0 (sample 0); last bucket max == 9.
    assert lo0 == 0.0
    assert hi1 == 9.0


def test_degenerate_all_same_timestamp():
    """When N >= W and all timestamps are identical, the first bucket
    spans all samples (min/max), remaining buckets are None.

    Use N >= W (5 samples, 4 target pixels) so we hit the degenerate
    branch in the downsampler rather than the N<W early-return.
    """
    samples = [(1.0, v) for v in (5.0, 7.0, 3.0, 6.0, 4.0)]
    out = downsample_minmax(samples, 4)
    assert out[0] == (3.0, 7.0)
    assert out[1] is None
    assert out[2] is None
    assert out[3] is None


def test_no_interpolation_when_n_less_than_w():
    """Plan-stated contract: N < W tolerates one sample per pixel,
    NO interpolation. We verify by ensuring intermediate slots stay
    None even when the value sequence is monotonic.
    """
    samples = [(0.0, 0.0), (1.0, 1.0)]
    out = downsample_minmax(samples, 5)
    assert out[0] == (0.0, 0.0)
    assert out[1] == (1.0, 1.0)
    assert out[2] is None
    assert out[3] is None
    assert out[4] is None


# ----------------------------------------------------------------------
# Task A-6: RollingDisplayBuckets — O(1)-push rolling 10 ms min/max/last
# display buckets. The painter merges these (≤ 3001 for a 30 s window)
# into the pixel columns instead of scanning the raw 30 s deque, which is
# retained only for honest statistics.
# ----------------------------------------------------------------------


def test_display_bucket_width_is_ten_ms():
    assert _DISPLAY_BUCKET_S == 0.010


def test_push_updates_current_bucket_min_max_last():
    b = RollingDisplayBuckets(window_s=30.0)
    # Five samples all inside the same 10 ms slot [0.000, 0.010).
    for ts, v in [
        (0.000, 5.0),
        (0.002, 9.0),
        (0.004, 3.0),
        (0.006, 8.0),
        (0.008, 6.0),
    ]:
        b.push(ts, v)
    assert len(b) == 1  # a single bucket, updated in place (O(1) push)
    t_start, vmin, vmax, last, last_ts = b.summaries()[0]
    assert t_start == 0.0
    assert vmin == 3.0  # exact min
    assert vmax == 9.0  # exact max
    assert last == 6.0  # newest value by stream time
    assert last_ts == pytest.approx(0.008)


def test_push_crosses_bucket_appends():
    b = RollingDisplayBuckets(window_s=30.0)
    b.push(0.001, 1.0)  # slot 0
    b.push(0.011, 2.0)  # slot 1
    b.push(0.021, 3.0)  # slot 2
    assert len(b) == 3
    starts = [s[0] for s in b.summaries()]
    assert starts == pytest.approx([0.000, 0.010, 0.020])


def test_out_of_order_sample_does_not_rewind_last():
    b = RollingDisplayBuckets(window_s=30.0)
    b.push(0.001, 1.0)
    b.push(0.050, 7.0)  # advance to a later slot
    b.push(0.002, -3.0)  # a stray late sample (before current slot)
    # It widens the current bucket's min but never rewinds ``last``.
    last_summary = b.summaries()[-1]
    _t, vmin, _vmax, last, _last_ts = last_summary
    assert vmin == -3.0
    assert last == 7.0


def test_bucket_count_bounded_over_30s_at_1ms():
    b = RollingDisplayBuckets(window_s=30.0)
    for i in range(30000):  # 30 s @ 1 ms
        b.push(i / 1000.0, float(i))
    assert len(b) <= 3001  # ⌈30/0.010⌉ + 1 boundary bucket


def test_maxlen_caps_buckets_without_trim():
    # Even at 40 s of data and NO trim, the deque(maxlen) safety keeps the
    # invariant ≤ 3001 (never depends on the caller trimming on schedule).
    b = RollingDisplayBuckets(window_s=30.0)
    for i in range(40000):
        b.push(i / 1000.0, float(i))
    assert len(b) <= 3001


def test_trim_removes_expired_buckets():
    b = RollingDisplayBuckets(window_s=30.0)
    for i in range(40000):  # 40 s @ 1 ms
        b.push(i / 1000.0, float(i))
    newest = b.latest_ts()
    b.trim(newest - 30.0)
    starts = [s[0] for s in b.summaries()]
    # Oldest kept bucket straddles ``newest - 30`` (boundary bucket kept),
    # never chops more than one 10 ms slot early.
    assert starts[0] >= (newest - 30.0) - _DISPLAY_BUCKET_S
    assert len(b) <= 3001


def test_trim_none_is_noop():
    b = RollingDisplayBuckets(window_s=30.0)
    b.push(0.0, 1.0)
    b.push(0.02, 2.0)
    b.trim(None)
    assert len(b) == 2


def test_value_bounds_reflects_extremes():
    b = RollingDisplayBuckets(window_s=30.0)
    for i in range(5000):
        b.push(i / 1000.0, math.sin(i * 0.01) * 10.0)
    mn, mx = b.value_bounds()
    raw_vals = [math.sin(i * 0.01) * 10.0 for i in range(5000)]
    assert mn == pytest.approx(min(raw_vals))
    assert mx == pytest.approx(max(raw_vals))


def test_value_bounds_empty_is_none():
    b = RollingDisplayBuckets(window_s=30.0)
    assert b.value_bounds() == (None, None)
    assert b.latest_ts() is None
    assert b.is_empty()


def test_non_finite_samples_skipped():
    b = RollingDisplayBuckets(window_s=30.0)
    b.push(0.001, 1.0)
    b.push(0.002, math.nan)  # skipped, no crash
    b.push(0.003, math.inf)  # skipped
    b.push(math.nan, 5.0)  # non-finite ts skipped (floor(nan) would raise)
    _t, vmin, vmax, last, _last_ts = b.summaries()[0]
    assert vmin == 1.0 and vmax == 1.0 and last == 1.0


def test_clear_empties():
    b = RollingDisplayBuckets(window_s=30.0)
    b.push(0.0, 1.0)
    b.clear()
    assert b.is_empty() and len(b) == 0


def test_min_max_last_fidelity_matches_raw_per_slot():
    """The reviewer's key invariant: for every 10 ms slot the bucket's
    (min, max, last) equal the exact raw per-slot values.

    Expected buckets are reconstructed with the SAME ``floor(ts /
    bucket_s)`` key function the production code uses, so the comparison
    isolates the min/max/last reduction from any float slot-edge rounding
    (an independent ``t_start <= ts < t_start + w`` reconstruction would
    disagree at boundaries like ``0.29 / 0.010 == 28.999…``).
    """
    b = RollingDisplayBuckets(window_s=30.0)
    expected: dict[int, list[float]] = {}
    for i in range(2000):  # 2 s @ 1 ms → ~200 slots of 10 samples each
        ts = i / 1000.0
        v = float(((i * 37) % 101) - 50)  # deterministic non-monotonic
        b.push(ts, v)
        expected.setdefault(math.floor(ts / _DISPLAY_BUCKET_S), []).append(v)
    for t_start, vmin, vmax, last, _last_ts in b.summaries():
        key = round(t_start / _DISPLAY_BUCKET_S)
        slot_vals = expected[key]
        assert vmin == min(slot_vals)
        assert vmax == max(slot_vals)
        assert last == slot_vals[-1]
