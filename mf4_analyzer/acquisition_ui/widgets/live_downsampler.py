"""Sparkline min/max downsampler.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Center Pane:

    Sparkline rendering downsamples per the ``live_downsampler``
    contract: given N timestamped samples and W target pixels, emit
    min-max bins so each pixel column is one ``(min, max)`` pair.

Contract details pinned by Stage 4 brief:

- Input is an iterable of ``(timestamp_s, value)`` pairs already sorted
  in time order (the caller appends to a deque, so order is monotonic).
- ``W`` is the target number of pixel columns. Always positive.
- ``N`` is the number of samples. May be less than ``W`` — in that case
  emit one bin per sample (each bin's min == max == that sample's
  value), and pad the right side with ``None`` placeholders rather than
  interpolating. The Qt painter renders ``None`` columns as a gap.
- When ``N >= W`` we partition the time axis into W equal-width buckets
  spanning ``[t[0], t[-1]]`` and emit ``(min, max)`` per bucket. Empty
  buckets (no samples) emit ``None``; the painter renders a gap there.

The module is pure-Python (no NumPy, no Qt) so the contract is
testable without ``QT_QPA_PLATFORM=offscreen`` and without an array
dependency. NumPy would be marginally faster on long buffers but the
sparkline use case keeps N small (≤ ~5000 samples per card).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterator, Sequence


# A single output column is either a (min, max) pair or ``None`` (gap).
Bin = tuple[float, float] | None


def downsample_minmax(
    samples: Sequence[tuple[float, float]],
    target_pixels: int,
) -> list[Bin]:
    """Reduce ``samples`` to exactly ``target_pixels`` min/max bins.

    Parameters
    ----------
    samples:
        Sequence of ``(timestamp_s, value)`` pairs in time order. May be
        empty.
    target_pixels:
        Width of the sparkline in pixels. Must be a positive integer.

    Returns
    -------
    list[Bin]
        List of length exactly ``target_pixels``. Each element is
        either ``(min, max)`` for the samples that fell in that
        column, or ``None`` for an empty column / right-pad slot.

    Raises
    ------
    ValueError
        If ``target_pixels`` is non-positive.
    """
    if target_pixels <= 0:
        raise ValueError(f"target_pixels must be positive, got {target_pixels}")

    n = len(samples)
    if n == 0:
        # Empty: all gaps.
        return [None] * target_pixels

    if n < target_pixels:
        # One bin per sample, right-pad the rest as gaps. The brief is
        # explicit: "no interpolation".
        out: list[Bin] = [(float(v), float(v)) for _, v in samples]
        out.extend([None] * (target_pixels - n))
        return out

    # N >= W: partition the time axis [t_min, t_max] into W buckets.
    t_min = float(samples[0][0])
    t_max = float(samples[-1][0])
    span = t_max - t_min
    if span <= 0.0:
        # Degenerate case: every sample at the same timestamp. Fall
        # back to one bin spanning all samples plus right-padded gaps.
        all_values = [float(v) for _, v in samples]
        out = [(min(all_values), max(all_values))]
        out.extend([None] * (target_pixels - 1))
        return out

    bucket_width = span / target_pixels

    # Pre-allocate W empty bucket accumulators (None == empty bucket).
    buckets: list[tuple[float, float] | None] = [None] * target_pixels

    for ts, value in samples:
        ts_f = float(ts)
        val_f = float(value)
        # Map ts -> bucket index in [0, W-1].
        rel = (ts_f - t_min) / bucket_width
        idx = int(rel)
        if idx >= target_pixels:
            # Right edge: clamp the last sample into the final bucket.
            idx = target_pixels - 1
        cur = buckets[idx]
        if cur is None:
            buckets[idx] = (val_f, val_f)
        else:
            lo, hi = cur
            if val_f < lo:
                lo = val_f
            if val_f > hi:
                hi = val_f
            buckets[idx] = (lo, hi)

    return buckets


# Fixed display-bucket width for the incremental rolling downsampler
# (spec §A6 / plan Task A-6). 10 ms buckets keep a 30 s live window at ≤
# ``30 / 0.010 = 3000`` buckets (+1 boundary bucket), so a card that
# received 30 s @ 1 ms (30 000 raw samples) paints from at most ~3001
# summaries instead of scanning the raw deque every frame.
_DISPLAY_BUCKET_S = 0.010

# A single rolling bucket is a mutable ``[key, vmin, vmax, last, last_ts]``
# list (mutability + O(1) attribute-free access matter on the push hot
# path). ``key`` is the integer 10 ms bucket index ``floor(ts / bucket_s)``.
_KEY, _MIN, _MAX, _LAST, _LAST_TS = 0, 1, 2, 3, 4

# A read-only bucket summary handed to the painter / reviewer:
# ``(t_start, vmin, vmax, last, last_ts)`` where ``t_start = key * bucket_s``.
BucketSummary = tuple[float, float, float, float, float]


class RollingDisplayBuckets:
    """O(1)-push rolling min/max/last display buckets over a live window.

    This is a **display-layer** downsampler (NOT an FFT/order numerical
    algorithm): its sole job is to bound the *per-frame* paint cost of the
    live sparkline. The narrow-Y overlay perf lesson
    (``2026-06-22-narrow-y-overlay-cost-is-stroke-count-not-data``) and the
    ``project-timedomain-perf-raster-bound`` MEMORY both establish that the
    live paint frame is CPU-raster / stroke-count bound, and that scanning
    a large raw buffer every frame is pure waste. So the painter merges at
    most ``⌈window / bucket_s⌉ + 1`` (= 3001 for 30 s @ 10 ms) pre-reduced
    buckets into the ``W`` pixel columns, and never iterates the raw 30 s
    deque (which is retained *only* for honest statistics).

    Contract (each preserved exactly across push/trim, verified by the
    signal-processing reviewer):

    - ``push(ts, value)`` is O(1): it either updates the *current* (newest)
      bucket's ``min``/``max``/``last``/``last_ts`` in place, or appends a
      fresh bucket when ``ts`` crosses into a new 10 ms slot.
    - ``vmin`` / ``vmax`` are the exact extremes of every finite sample that
      landed in the bucket; ``last`` is the value of the newest such sample
      (by stream time), ``last_ts`` its timestamp.
    - ``trim(t_min)`` drops whole buckets whose slot ends at/below ``t_min``,
      keeping the boundary bucket that still straddles ``t_min`` (the raw
      deque trims to the exact sample, so a ≤10 ms boundary bucket may hold
      one just-expired sample — negligible against a 30 s window).
    - A ``deque(maxlen=...)`` safety cap guarantees ``len(self) <= 3001`` at
      all times even between trims, so the invariant never depends on the
      caller calling ``trim`` on schedule.

    Non-finite samples are skipped for the bucket summaries (the raw
    low-density path still renders NaN gaps precisely via ``_split_runs``);
    a downsampled envelope must not fold a NaN into its min/max.
    """

    __slots__ = ("_bucket_s", "_buckets")

    def __init__(
        self, window_s: float, bucket_s: float = _DISPLAY_BUCKET_S
    ) -> None:
        self._bucket_s = float(bucket_s)
        # +1 for the boundary bucket that straddles ``newest - window``.
        maxlen = int(round(window_s / self._bucket_s)) + 1
        self._buckets: deque[list[float]] = deque(maxlen=maxlen)

    @property
    def bucket_s(self) -> float:
        return self._bucket_s

    def push(self, ts: float, value: float) -> None:
        """Fold one ``(ts, value)`` sample into its 10 ms bucket, O(1)."""
        if not (math.isfinite(ts) and math.isfinite(value)):
            # Skip non-finite: ``math.floor(nan/inf)`` raises anyway, and a
            # downsampled band must not include a NaN in its min/max.
            return
        key = math.floor(ts / self._bucket_s)
        buckets = self._buckets
        if buckets:
            cur = buckets[-1]
            cur_key = cur[_KEY]
            if key == cur_key:
                if value < cur[_MIN]:
                    cur[_MIN] = value
                if value > cur[_MAX]:
                    cur[_MAX] = value
                cur[_LAST] = value
                cur[_LAST_TS] = ts
                return
            if key < cur_key:
                # Out-of-order sample (stream restarts are handled by the
                # owner calling ``clear()``): fold the extremes into the
                # current bucket without regressing ``last`` / ``last_ts``,
                # so a stray late sample can never rewind the trace's head.
                if value < cur[_MIN]:
                    cur[_MIN] = value
                if value > cur[_MAX]:
                    cur[_MAX] = value
                return
        # New (strictly newer) bucket. ``deque(maxlen)`` auto-drops the
        # oldest bucket, so the rolling window is bounded even without trim.
        buckets.append([float(key), value, value, value, ts])

    def trim(self, t_min: float | None) -> None:
        """Drop buckets whose 10 ms slot ends at/below ``t_min``.

        ``None`` ⇒ no trim. The boundary bucket that still straddles
        ``t_min`` is kept so the left edge is not chopped a whole slot early.
        """
        if t_min is None:
            return
        boundary_key = math.floor(t_min / self._bucket_s)
        buckets = self._buckets
        while buckets and buckets[0][_KEY] < boundary_key:
            buckets.popleft()

    def clear(self) -> None:
        self._buckets.clear()

    def __len__(self) -> int:
        return len(self._buckets)

    def is_empty(self) -> bool:
        return not self._buckets

    def latest_ts(self) -> float | None:
        """Newest sample's stream timestamp (the sparkline x anchor), O(1)."""
        if not self._buckets:
            return None
        return self._buckets[-1][_LAST_TS]

    def value_bounds(self) -> tuple[float | None, float | None]:
        """Exact ``(min, max)`` over all buckets' extremes (≤ 3001 iters).

        Equals the raw buffer's finite min/max because each bucket already
        holds the exact per-slot extremes — so the high-density scale is
        identical to the low-density (raw) scale, no visible seam on the
        density transition.
        """
        mn = math.inf
        mx = -math.inf
        for b in self._buckets:
            if b[_MIN] < mn:
                mn = b[_MIN]
            if b[_MAX] > mx:
                mx = b[_MAX]
        if not math.isfinite(mn):
            return None, None
        return mn, mx

    def iter_summaries(self) -> Iterator[BucketSummary]:
        """Yield ``(t_start, vmin, vmax, last, last_ts)`` per bucket, in time
        order. The painter consumes this instead of the raw deque."""
        bs = self._bucket_s
        for b in self._buckets:
            yield (b[_KEY] * bs, b[_MIN], b[_MAX], b[_LAST], b[_LAST_TS])

    def summaries(self) -> list[BucketSummary]:
        """Materialised :meth:`iter_summaries` snapshot (reviewer / tests)."""
        return list(self.iter_summaries())
