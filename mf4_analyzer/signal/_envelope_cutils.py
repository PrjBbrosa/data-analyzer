"""Optional ``asammdf.blocks.cutils.positions`` wrapper for time-domain
envelope downsampling.

This module is the Phase-3 deliverable of
``docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md``.
It exposes a single public function, :func:`positions_envelope`, which
matches the output semantics of
:func:`mf4_analyzer.ui.canvases.build_envelope` and routes through the
C-extension when the input shape is favourable, falling back to the
numpy implementation otherwise.

Design constraints (from the design spec §3.5 / §4.3):

- The C function ``cutils.positions`` is OPTIONAL — the wrapper must
  probe it once at import time via ``getattr+callable`` and cache the
  result in :data:`_HAS_POSITIONS_C`. Tests force the fallback by
  monkey-patching this flag, not by mocking ``asammdf``. This honors
  the codex-phantom-api-surface-guards lesson.
- The wrapper must fall back to :func:`build_envelope` on every input
  shape that would cause a parity break or a copy-storm:

  * C function unavailable
  * not monotonic (asammdf C routine assumes monotonic timestamps)
  * arrays too small to benefit (``n_vis < 2 * pixel_width``)
  * non-contiguous or wrong-dtype timestamps / samples
  * any NaN present in the visible slice (the C routine uses naive
    ``<`` / ``>`` comparisons that promote NaN to "winner")

- System-level fallback reasons (C unavailable, non-monotonic input,
  NaN in window, non-contiguous slice, dtype mismatch) are logged
  ONCE per process via the module logger to avoid hot-path spam.
  Per-call shape branches (xlim=None, empty input, small visible
  window, no-op bucket size) are NOT logged — they are deterministic
  per-call decisions.

The call shape mirrors ``asammdf.gui.widgets.plot.PlotSignal.trim_c``
(`.venv/lib/python3.12/site-packages/asammdf/gui/widgets/plot.py:1063-1193`):
preallocated ``positions``/``samples``/``timestamps`` output buffers,
``steps`` = bucket size, ``count`` = bucket count, ``rest`` = size of
the last bucket, plus ``dtype.kind`` and ``dtype.itemsize``.

We do NOT vendor any asammdf source — we call the live extension on the
data we own.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Tuple

import numpy as np

# build_envelope lives in the UI module today (canvases.py) because the
# matplotlib canvas is its primary consumer. Importing the function — not
# the canvas class — keeps this module UI-free. T7 will move
# build_envelope here once the new canvas is the only consumer.
from mf4_analyzer.ui.canvases import build_envelope, _is_monotonic_array


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# One-time probe of the optional C path.
#
# Per the codex-phantom-api-surface-guards lesson, this is NEVER a
# MagicMock. We use importlib.util.find_spec + getattr+callable to
# discover the real entry point without faking the surface.
# ---------------------------------------------------------------------------

def _probe_positions_c() -> bool:
    """Return True iff ``asammdf.blocks.cutils.positions`` is callable."""
    if importlib.util.find_spec("asammdf") is None:
        return False
    try:
        from asammdf.blocks import cutils  # noqa: WPS433 - optional dep
    except Exception:
        return False
    return callable(getattr(cutils, "positions", None))


_HAS_POSITIONS_C: bool = _probe_positions_c()

# One-shot fallback-reason log set; we want the *first* miss to be loud
# (so engineers can see why the C path is dormant) but subsequent misses
# silent so the hot path stays clean.
_LOGGED_FALLBACK_REASONS: set[str] = set()


def _log_fallback_once(reason: str) -> None:
    """Log a fallback reason at INFO level the first time it happens."""
    if reason in _LOGGED_FALLBACK_REASONS:
        return
    _LOGGED_FALLBACK_REASONS.add(reason)
    _log.info("positions_envelope: falling back to build_envelope (%s)", reason)


def _reset_logged_reasons() -> None:
    """Test-only hook: re-arm the once-per-process fallback log set.

    Production code never calls this — the once-per-process semantics
    are a feature, not a bug. Tests that want to observe multiple
    invocations of the same system-level fallback branch reset the set
    between scenarios so the log assertion is deterministic.
    """
    _LOGGED_FALLBACK_REASONS.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def positions_envelope(
    t,
    sig,
    *,
    xlim: Tuple[float, float],
    pixel_width: int,
    is_monotonic: bool | None = None,
):
    """Viewport-aware min/max envelope with optional C-path acceleration.

    Parameters
    ----------
    t, sig : np.ndarray
        Same-length 1-D arrays. ``t`` must be non-decreasing for the C
        path to be taken; non-monotonic input is routed to the legacy
        fallback (which itself returns the inputs untouched).
    xlim : tuple(float, float)
        Visible x-axis range ``(x0, x1)``. ``None`` is NOT accepted
        here — the full-range contract belongs to
        :func:`build_envelope`. We pass through to it explicitly when a
        caller insists.
    pixel_width : int
        Approximate pixel width of the visible axis; drives the bucket
        count.
    is_monotonic : bool | None
        Caller-supplied monotonicity flag. ``None`` triggers an
        ``np.diff`` scan inside :func:`build_envelope`; production
        callers should always provide it.

    Returns
    -------
    (t_out, sig_out) : tuple of np.ndarray
        Same shape and semantics as :func:`build_envelope`.

    Fallback policy
    ---------------
    The wrapper falls back to :func:`build_envelope` in several
    branches. The logging contract is split between branches that
    pertain to environmental / installation state of the inputs
    (logged once per process) and branches that are per-call shape
    decisions (NOT logged, because the log line would be either
    silently amortized or hot-path spam).

    System-level fallbacks — logged exactly once per process via
    :func:`_log_fallback_once`:

    - ``c_unavailable`` (``_HAS_POSITIONS_C`` is False);
    - ``non_monotonic`` (caller-flagged or detected);
    - ``nan_in_window`` (any NaN in the visible slice);
    - ``non_contiguous`` (visible-slice arrays not C-contiguous);
    - ``dtype_mismatch`` (timestamp dtype != float64).

    Per-call shape decisions — NOT logged (deterministic per-call
    branches):

    - ``xlim_none`` (full-range contract passthrough);
    - ``empty_input`` (zero-length arrays);
    - ``empty_visible_window`` (xlim clipping yields zero samples);
    - ``small_visible`` (``n_vis <= 2 * pixel_width``);
    - ``no_op_bucket`` (bucket size would be 1, no compression).
    """
    # The full-range contract belongs to build_envelope; pass through.
    # Per-call shape branch: NOT logged (see docstring "Fallback policy").
    if xlim is None:
        return build_envelope(
            t, sig, xlim=None, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    if not _HAS_POSITIONS_C:
        # System-level fallback: C extension absent on this install.
        # Logged once per process so engineers see the dormant C path.
        _log_fallback_once("c_unavailable")
        return build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    t = np.asarray(t)
    sig = np.asarray(sig)
    n_total = sig.size
    if n_total == 0:
        # Empty input: defer to reference (it has explicit empty-array
        # contract).
        return build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1

    # Monotonicity gate — the C function searchsorts in our wrapper and
    # min/max-scans linearly per bucket; it assumes monotone t.
    if n_total >= 2:
        if is_monotonic is None:
            is_monotonic = _is_monotonic_array(t)
        if not is_monotonic:
            _log_fallback_once("non_monotonic")
            return build_envelope(
                t, sig, xlim=xlim, pixel_width=pixel_width,
                is_monotonic=False,
            )

    # xlim normalisation (matches build_envelope).
    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    i0 = int(np.searchsorted(t, x0, side="left"))
    i1 = int(np.searchsorted(t, x1, side="right"))
    if i1 <= i0:
        # Empty visible window — mirror build_envelope's empty slice.
        return t[i0:i0], sig[i0:i0]

    t_vis = t[i0:i1]
    s_vis = sig[i0:i1]
    n_vis = s_vis.size

    # Small-visible shortcut (bit-identical with build_envelope).
    if n_vis <= 2 * pixel_width:
        return t_vis, s_vis

    # Bucket layout EXACTLY matching build_envelope's: pixel_width
    # buckets where the LAST bucket absorbs the remainder. The C
    # routine, by contrast, splits the remainder into a partial
    # (count+1)-th bucket. To preserve parity we run the C routine on
    # the divisible head (n_head = bs * (pixel_width - 1)) and compute
    # the tail bucket (size n_vis - n_head) in numpy.
    n_buckets = int(pixel_width)
    bs = max(1, n_vis // n_buckets)
    n_buckets = max(1, n_vis // bs)  # may shrink if n_vis < pixel_width
    if bs <= 1:
        # No real compression — defer to reference (avoids paying C
        # call overhead for a no-op).
        return build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    # NaN gate: the C routine uses naive comparisons that promote NaN.
    # Any NaN in the visible slice -> fall back so we preserve the
    # nanargmin/nanargmax + NaN-break semantics of build_envelope.
    if np.issubdtype(s_vis.dtype, np.floating) and bool(np.isnan(s_vis).any()):
        _log_fallback_once("nan_in_window")
        return build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    # Contiguity / dtype gate. asammdf's trim_c .copy()s on non-contig;
    # we choose to fall back instead because the copy is O(n_vis) and
    # may exceed the C path's savings on small visible windows.
    if not s_vis.flags.c_contiguous or not t_vis.flags.c_contiguous:
        _log_fallback_once("non_contiguous")
        return build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    # Timestamps MUST be float64 for the C routine's `f8` buffer dtype.
    if t_vis.dtype != np.float64:
        _log_fallback_once("dtype_mismatch")
        return build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    # Half-precision floats: trim_c upcasts to float64; we mirror that.
    work_s = s_vis
    if work_s.dtype.kind == "f" and work_s.itemsize == 2:
        work_s = work_s.astype(np.float64)

    # Drive the C call over the divisible head ----------------------------
    # If n_vis is exactly divisible by bs the entire array is one call;
    # otherwise we hold back the final bucket so we can absorb the
    # remainder in numpy (parity with build_envelope's last-bucket rule).
    n_head_buckets = n_buckets - 1 if (n_vis % bs) else n_buckets
    n_head = bs * n_head_buckets

    # The C function expects `count` and `rest`. For a perfectly
    # divisible head, `rest = bs` (signals "full last bucket"); for
    # n_head == 0 (only one tail bucket) we skip the C call entirely.
    out_t = np.empty(2 * n_buckets, dtype=t_vis.dtype)
    out_s_dtype = np.result_type(work_s.dtype, np.float64)
    out_s = np.empty(2 * n_buckets, dtype=out_s_dtype)

    # Local import: keeps the module importable even if asammdf is
    # absent (probe handles the public-API guard above).
    from asammdf.blocks import cutils  # noqa: WPS433

    out_count = 0
    if n_head_buckets > 0:
        head_s = work_s[:n_head]
        head_t = t_vis[:n_head]
        # Re-check contiguity after slicing the head — slicing keeps it
        # contiguous when the parent is, but we're paranoid.
        if not head_s.flags.c_contiguous:
            head_s = np.ascontiguousarray(head_s)
        if not head_t.flags.c_contiguous:
            head_t = np.ascontiguousarray(head_t)

        # asammdf's trim_c uses scratch buffers sized 2*count; we
        # allocate per-call (the canvas-level pixmap cache will be the
        # multi-call amortizer).
        buf_pos = np.empty(2 * n_head_buckets, dtype="i4")
        buf_s = np.empty(2 * n_head_buckets, dtype=head_s.dtype)
        buf_t = np.empty(2 * n_head_buckets, dtype="f8")

        # rest = bs means "last bucket has the full step size", which
        # is what we want because the head is exactly divisible.
        cutils.positions(
            head_s, head_t,
            buf_s, buf_t, buf_pos,
            int(bs),                  # steps
            int(n_head_buckets),      # count
            int(bs),                  # rest
            head_s.dtype.kind,
            int(head_s.dtype.itemsize),
        )
        size = 2 * n_head_buckets
        # The C routine writes (min, max) per bucket in time order;
        # cast samples to out_s.dtype which equals result_type(work_s,
        # float64) — same as build_envelope's output dtype.
        out_t[:size] = buf_t[:size]
        out_s[:size] = buf_s[:size]
        out_count = size

    # Compute the tail bucket in numpy with the SAME nan-aware semantics
    # as build_envelope's per-bucket loop. We already vetted that no
    # NaN is present in the visible slice, so plain argmin/argmax are
    # bit-identical with the loop above.
    if n_head_buckets < n_buckets:
        tail_s = s_vis[n_head:]
        tail_t = t_vis[n_head:]
        if tail_s.size == 0:
            pass  # nothing to emit
        else:
            rel_lo = int(np.argmin(tail_s))
            rel_hi = int(np.argmax(tail_s))
            if rel_lo <= rel_hi:
                out_t[out_count] = tail_t[rel_lo]
                out_s[out_count] = tail_s[rel_lo]
                out_count += 1
                if rel_hi != rel_lo:
                    out_t[out_count] = tail_t[rel_hi]
                    out_s[out_count] = tail_s[rel_hi]
                    out_count += 1
            else:
                out_t[out_count] = tail_t[rel_hi]
                out_s[out_count] = tail_s[rel_hi]
                out_count += 1
                out_t[out_count] = tail_t[rel_lo]
                out_s[out_count] = tail_s[rel_lo]
                out_count += 1

    return out_t[:out_count], out_s[:out_count]


__all__ = ["positions_envelope", "_HAS_POSITIONS_C", "_reset_logged_reasons"]
