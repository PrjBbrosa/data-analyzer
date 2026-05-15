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

import pytest

from mf4_analyzer.acquisition_ui.widgets.live_downsampler import (
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
