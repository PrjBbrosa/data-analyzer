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

from collections.abc import Sequence


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
