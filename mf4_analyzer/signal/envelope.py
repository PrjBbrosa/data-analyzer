"""Pure signal-math helpers for viewport-aware envelope downsampling.

Extracted from ``mf4_analyzer.ui.canvases`` (Phase D, 2026-06-18) so
signal consumers do not need to import the UI layer to get these functions.

``mf4_analyzer.ui.canvases`` re-exports all public symbols defined here
so existing ``from mf4_analyzer.ui.canvases import build_envelope`` calls
continue to work without change.
"""

import numpy as np


# Default cap mirrors ``TimeDomainCanvas.MAX_PTS = 8000``. Forward
# referencing the class attribute is impossible because this helper must
# be defined before the class; the constant is duplicated here and kept
# in sync deliberately.
_BUILD_ENVELOPE_LEGACY_MAX_PTS = 8000


def _is_monotonic_array(t):
    """Return True iff ``t`` is non-decreasing. Empty / single-sample -> True."""
    if t is None:
        return True
    arr = np.asarray(t)
    if arr.size < 2:
        return True
    # np.all(np.diff(t) >= 0) allocates diff but matches the spec's contract.
    return bool(np.all(np.diff(arr) >= 0))


def _ds_legacy_pure(t, sig, max_pts=_BUILD_ENVELOPE_LEGACY_MAX_PTS):
    """Module-level twin of :meth:`TimeDomainCanvas._ds_legacy`.

    Verbatim algorithm; ``self.MAX_PTS`` is replaced with the parameter
    ``max_pts`` defaulting to the same 8000 the canvas uses.
    """
    n = len(sig)
    if n <= max_pts:
        return t, sig
    bs = n // (max_pts // 2)
    if bs < 2:
        return t, sig
    idx = []
    for s in range(0, n, bs):
        e = min(s + bs, n)
        c = sig[s:e]
        idx.extend([s + np.argmin(c), s + np.argmax(c)])
    idx = np.unique(np.clip(idx, 0, n - 1))
    return t[idx], sig[idx]


def build_envelope(t, sig, *, xlim, pixel_width, is_monotonic=None):
    """Pure function version of the viewport-aware min/max envelope.

    Parameters
    ----------
    t, sig : np.ndarray
        Same length 1-D arrays. ``t`` should be monotonic for the fast
        path; non-monotonic input falls back to the legacy full-series
        reducer (:func:`_ds_legacy_pure`).
    xlim : tuple(float, float) | None
        Visible x-axis range ``(x0, x1)``. ``None`` means **full range**
        and is equivalent to ``(float(t[0]), float(t[-1]))`` -- this is
        the entry for callers that pass non-viewport-owning series
        (e.g. RPM auxiliary lines on a multi-subplot figure). Empty
        ``t`` with ``xlim=None`` returns the inputs untouched.
    pixel_width : int
        Approximate pixel width of the visible axes -- sets the target
        bucket count.
    is_monotonic : Optional[bool]
        Precomputed monotonicity flag. ``None`` means "scan to verify"
        (safety net for ad-hoc callers / tests).

    Returns
    -------
    (t_out, sig_out) : tuple of np.ndarray
        Time-ordered (min, max) sample pairs per pixel bucket. Small
        visible spans are returned unchanged. NaN buckets emit a single
        NaN break to preserve polyline discontinuities.
    """
    # xlim=None -> full-range fallback (spec §6.4). Empty input is
    # special-cased to avoid IndexError on ``t[0]`` / ``t[-1]``.
    if xlim is None:
        if len(t) == 0:
            return np.asarray(t, dtype=float), np.asarray(sig, dtype=float)
        xlim = (float(t[0]), float(t[-1]))

    t = np.asarray(t)
    sig = np.asarray(sig)
    n_total = len(sig)
    if n_total == 0:
        return t, sig
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1

    # Non-monotonic x -> legacy full-series reduction. searchsorted is
    # invalid here; trust the precomputed flag when supplied, else scan.
    if n_total >= 2:
        if is_monotonic is None:
            is_monotonic = _is_monotonic_array(t)
        if not is_monotonic:
            return _ds_legacy_pure(t, sig)

    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    # Visible window via searchsorted (monotonic t).
    i0 = int(np.searchsorted(t, x0, side='left'))
    i1 = int(np.searchsorted(t, x1, side='right'))
    if i1 <= i0:
        return t[i0:i0], sig[i0:i0]

    t_vis = t[i0:i1]
    s_vis = sig[i0:i1]
    n_vis = len(s_vis)

    # Small-visible shortcut: don't bother bucketing.
    if n_vis <= 2 * pixel_width:
        return t_vis, s_vis

    # Bucket count: ~one bucket per pixel.
    n_buckets = int(pixel_width)
    bs = max(1, n_vis // n_buckets)
    n_buckets = max(1, n_vis // bs)

    out_t = np.empty(2 * n_buckets, dtype=t_vis.dtype)
    out_s = np.empty(2 * n_buckets, dtype=np.result_type(s_vis.dtype,
                                                          np.float64))
    out_count = 0

    for b in range(n_buckets):
        s_start = b * bs
        # Last bucket absorbs the remainder so no samples are dropped.
        s_end = n_vis if b == n_buckets - 1 else s_start + bs
        seg = s_vis[s_start:s_end]
        if seg.size == 0:
            continue
        nan_mask = np.isnan(seg) if np.issubdtype(seg.dtype,
                                                    np.floating) else None
        if nan_mask is not None and nan_mask.all():
            mid_idx = s_start + seg.size // 2
            out_t[out_count] = t_vis[mid_idx]
            out_s[out_count] = np.nan
            out_count += 1
            continue
        if nan_mask is not None and nan_mask.any():
            rel_lo = int(np.nanargmin(seg))
            rel_hi = int(np.nanargmax(seg))
        else:
            rel_lo = int(np.argmin(seg))
            rel_hi = int(np.argmax(seg))
        lo_idx = s_start + rel_lo
        hi_idx = s_start + rel_hi
        # Emit min/max in TIME ORDER so the line traversal is monotonic.
        if lo_idx <= hi_idx:
            out_t[out_count] = t_vis[lo_idx]
            out_s[out_count] = s_vis[lo_idx]
            out_count += 1
            if hi_idx != lo_idx:
                out_t[out_count] = t_vis[hi_idx]
                out_s[out_count] = s_vis[hi_idx]
                out_count += 1
        else:
            out_t[out_count] = t_vis[hi_idx]
            out_s[out_count] = s_vis[hi_idx]
            out_count += 1
            out_t[out_count] = t_vis[lo_idx]
            out_s[out_count] = s_vis[lo_idx]
            out_count += 1

    return out_t[:out_count], out_s[:out_count]


def build_peak_trace(t, sig, *, xlim, pixel_width, is_monotonic=None):
    """One max sample per pixel bucket (spectra / peak-hold).

    Unlike :func:`build_envelope` (min AND max in time order), this emits a
    single point per bucket so a noisy FFT does not fill into a vertical
    ribbon. Small visible spans (``n_vis <= pixel_width``) pass through
    unchanged. NaN buckets emit a single NaN break.
    """
    if xlim is None:
        if len(t) == 0:
            return np.asarray(t, dtype=float), np.asarray(sig, dtype=float)
        xlim = (float(t[0]), float(t[-1]))

    t = np.asarray(t)
    sig = np.asarray(sig)
    n_total = len(sig)
    if n_total == 0:
        return t, sig
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1

    if n_total >= 2:
        if is_monotonic is None:
            is_monotonic = _is_monotonic_array(t)
        if not is_monotonic:
            return _ds_legacy_pure(t, sig)

    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    i0 = int(np.searchsorted(t, x0, side='left'))
    i1 = int(np.searchsorted(t, x1, side='right'))
    if i1 <= i0:
        return t[i0:i0], sig[i0:i0]

    t_vis = t[i0:i1]
    s_vis = sig[i0:i1]
    n_vis = len(s_vis)

    if n_vis <= pixel_width:
        return t_vis, s_vis

    n_buckets = int(pixel_width)
    bs = max(1, n_vis // n_buckets)
    n_buckets = max(1, n_vis // bs)

    out_t = np.empty(n_buckets, dtype=t_vis.dtype)
    out_s = np.empty(n_buckets, dtype=np.result_type(s_vis.dtype, np.float64))
    out_count = 0

    for b in range(n_buckets):
        s_start = b * bs
        s_end = n_vis if b == n_buckets - 1 else s_start + bs
        seg = s_vis[s_start:s_end]
        if seg.size == 0:
            continue
        nan_mask = np.isnan(seg) if np.issubdtype(seg.dtype, np.floating) else None
        if nan_mask is not None and nan_mask.all():
            mid_idx = s_start + seg.size // 2
            out_t[out_count] = t_vis[mid_idx]
            out_s[out_count] = np.nan
            out_count += 1
            continue
        if nan_mask is not None and nan_mask.any():
            rel_hi = int(np.nanargmax(seg))
        else:
            rel_hi = int(np.argmax(seg))
        hi_idx = s_start + rel_hi
        out_t[out_count] = t_vis[hi_idx]
        out_s[out_count] = s_vis[hi_idx]
        out_count += 1

    return out_t[:out_count], out_s[:out_count]


def straddling_segment(t, sig, xlim):
    """Return the samples that should be drawn for ``xlim``, plus neighbors.

    ``build_envelope`` / ``positions_envelope`` return an empty slice when
    the window sits between two timestamps.  Binding that empty slice
    clears the PlotDataItem, while leaving a dense raster in place lets
    ViewBox stretch one min/max column into a solid colour block.  This
    helper keeps one sample on each side of the gap so the native polyline
    still crosses the view (linear between neighbours, matching the rest
    of the time-domain canvas).
    """
    t = np.asarray(t)
    sig = np.asarray(sig)
    n = min(int(t.size), int(sig.size))
    if n == 0:
        return t[:0], sig[:0]
    try:
        x0, x1 = float(xlim[0]), float(xlim[1])
    except (TypeError, ValueError, IndexError):
        return t[:0], sig[:0]
    if x1 < x0:
        x0, x1 = x1, x0
    i0 = int(np.searchsorted(t[:n], x0, side="left"))
    i1 = int(np.searchsorted(t[:n], x1, side="right"))
    left = i0 - 1 if i0 > 0 else 0
    right = i1 + 1 if i1 < n else n
    if right <= left:
        return t[:0], sig[:0]
    return t[left:right], sig[left:right]
