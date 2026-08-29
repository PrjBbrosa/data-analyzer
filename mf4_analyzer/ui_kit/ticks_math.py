"""Pure nice-number tick math helpers shared across the UI layers.

This module is the lowest layer of the UI dependency graph: it must not
import from ``mf4_analyzer.ui`` (Analyzer) or
``mf4_analyzer.acquisition_ui`` (Cockpit). Both upper packages depend on
``ui_kit``; the pyqtgraph canvas re-exports these helpers from
``mf4_analyzer.ui.pg_canvas.ticks_math`` for backward compatibility, and the
Cockpit live-card sparklines consume them directly.
"""

from __future__ import annotations

import math


def _snap_y_to_divisions(y: float, n: int) -> float:
    """Round ``y`` to the nearest k/n grid boundary."""
    return round(y * n) / n


# A span this small RELATIVE to its own magnitude carries no displayable
# information: it is float64 rounding residue, not signal.
#
# Why it needs its own floor (2026-08-09 "纵坐标 35.0000000034 把 canvas 推到
# 右边"): a channel produced by channel maths — ``A*3 - A*2 - A``, ``A - B``,
# ``A/B*B`` — is constant in intent but NOT bit-exact, so its min and max
# differ by ~1e-16 relative. ``_frame_handle_y`` used to special-case only
# ``hi <= lo`` (a genuinely constant RAW channel), so the residue sailed
# through as a real span and Y was auto-framed onto a ~1e-14 wide window.
# pyqtgraph's default ``AxisItem.tickStrings`` then derives its decimal places
# from the tick spacing and, for ``0.001 <= |v| < 10000``, formats FIXED —
# no ``%g``, no scientific fallback — so every label came out as
# ``'35.000000000000000'``: 18 characters, 143 px of font metrics against the
# 24 px a normal ``-35`` needs. ``pin_left_axes_to_common_width`` then pinned
# EVERY subplot row's left axis to that width (it takes the max and is
# deliberately monotonically non-decreasing), pushing the whole plot area
# right and never releasing it.
#
# 1e-9 is four decades above the residue any float64 computation leaves, and
# far below any Y window a user would deliberately fit to: at 35 Nm it is a
# 3.5e-8 Nm band. Legitimate "zoom into the ripple on a large offset" views
# sit around 1e-5..1e-3 relative and are untouched.
_DEGENERATE_SPAN_RATIO = 1e-9


def finite_non_degenerate_range(lo, hi):
    """Return a finite, non-degenerate ``(lo, hi)`` window, else ``None``.

    Reuses ``_DEGENERATE_SPAN_RATIO`` so analysis viewport capture, ViewState
    restore, and tick framing cannot invent a second emptiness threshold.
    """
    try:
        lo_f = float(lo)
        hi_f = float(hi)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lo_f) and math.isfinite(hi_f)):
        return None
    span = hi_f - lo_f
    magnitude = max(abs(lo_f), abs(hi_f))
    if not (span > magnitude * _DEGENERATE_SPAN_RATIO and span > 0.0):
        return None
    return (lo_f, hi_f)


def ranges_overlap(left, right) -> bool:
    """True when two axis windows share a finite, non-degenerate intersection."""
    if left is None or right is None:
        return False
    try:
        a = finite_non_degenerate_range(left[0], left[1])
        b = finite_non_degenerate_range(right[0], right[1])
    except (TypeError, ValueError, IndexError):
        return False
    if a is None or b is None:
        return False
    return finite_non_degenerate_range(max(a[0], b[0]), min(a[1], b[1])) is not None

# Cap on the significant digits a tick label may print. Beyond this the digits
# describe rounding noise rather than measurement: sensor payloads in MF4/HDF
# are float32 (7 decimal digits) and even float64-derived computed channels
# carry nothing meaningful past ~9. Sits well under float64's 15-17, so this
# only ever engages on an axis whose resolution has gone below ~1e-8 relative.
MAX_TICK_SIGNIFICANT_DIGITS = 9


def pad_y_extent(lo, hi, *, fraction=0.05):
    """Return ``(lo, hi)`` padded for display, collapsing residue-only spans.

    Two regimes, and the whole point is that the second one exists:

    * a real span is padded by ``fraction`` on each side, unchanged behaviour;
    * a span at or below ``_DEGENERATE_SPAN_RATIO`` of its own magnitude is
      treated as the constant it is — centred on its midpoint and opened to
      ``+/- fraction`` of that midpoint (or ``+/- 1`` at zero), which is what
      an exactly-constant channel has always got.

    The degenerate branch subsumes the old ``hi <= lo`` test: a zero or
    inverted span satisfies the ratio trivially, and for ``lo == hi`` the
    midpoint IS the value, so the result is byte-identical to the padding the
    old code applied. See ``_DEGENERATE_SPAN_RATIO`` for why the ratio test
    has to be there at all.

    Non-finite input is returned untouched — a caller that cannot produce a
    finite extent has a problem this function cannot fix, and inventing a
    range would hide it.
    """
    try:
        lo = float(lo)
        hi = float(hi)
    except (TypeError, ValueError):
        return lo, hi
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return lo, hi
    try:
        fraction = float(fraction)
    except (TypeError, ValueError):
        fraction = 0.05
    span = hi - lo
    magnitude = max(abs(lo), abs(hi))
    if span > magnitude * _DEGENERATE_SPAN_RATIO and span > 0.0:
        pad = span * fraction
        return lo - pad, hi + pad
    center = (lo + hi) / 2.0
    pad = abs(center) * fraction or 1.0
    return center - pad, center + pad


def bounded_tick_strings(
    values, scale, spacing, *, max_significant=MAX_TICK_SIGNIFICANT_DIGITS
):
    """``AxisItem.tickStrings`` with the printed digit count bounded.

    Reproduces pyqtgraph 0.14's default formatting EXACTLY while the label
    stays inside ``max_significant`` significant digits — every ordinary
    engineering axis in this app is byte-identical, which is what keeps the
    tick-label width measurements in ``ui_kit.axis_metrics`` and the batch /
    GUI render parity guards agreeing.

    The one divergence is the branch pyqtgraph has no exit from: for
    ``0.001 <= |v| < 10000`` it formats fixed with ``places`` derived from
    ``spacing``, so a microscopic spacing prints every digit of the mantissa
    (``'35.000000000000000'``). Past the budget this switches to ``%g``, which
    picks whichever of fixed/scientific is shorter and drops the noise digits.

    Honest limitation: at that point adjacent ticks CAN render identically,
    because at 1e-15 relative resolution they genuinely are the same number to
    any displayable precision. Bounding the label is all this can do; showing
    distinct short labels there would need offset notation (an axis-level
    ``+3.5e1`` annotation), which is a separate feature. ``pad_y_extent``
    is what keeps auto-framing from ever landing there.

    Raises ``ValueError``/``OverflowError`` on a non-positive or non-finite
    ``spacing * scale``, exactly as pyqtgraph's own ``log10`` call does; the
    caller is expected to fall back to ``super().tickStrings``.
    """
    scale = float(scale)
    spacing = float(spacing)
    places = max(0, math.ceil(-math.log10(spacing * scale)))
    strings = []
    for value in values:
        scaled = float(value) * scale
        if not math.isfinite(scaled) or abs(scaled) < .001 or abs(scaled) >= 10000:
            strings.append("%g" % scaled)
            continue
        # Digits the fixed form would print: those left of the point plus
        # ``places`` right of it. ``log10`` is safe here — the branch above
        # already excluded zero and everything below 0.001.
        significant = places + math.floor(math.log10(abs(scaled))) + 1
        if significant <= max_significant:
            strings.append(("%%0.%df" % places) % scaled)
        else:
            strings.append("%.*g" % (max_significant, scaled))
    return strings


_NICE_STEP_MANTISSAS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8]


def _nice_per_div(raw):
    """Return the smallest nice step that is >= ``raw``."""
    try:
        value = float(raw)
    except Exception:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    exp = math.floor(math.log10(value))
    base = 10.0 ** exp
    mantissa = value / base
    for step in _NICE_STEP_MANTISSAS:
        if step >= mantissa - 1e-9:
            return step * base
    return 10.0 * base


def _adjacent_nice_step(step, direction):
    """Return the neighboring nice step below/above ``step``."""
    current = _nice_per_div(step)
    if current is None:
        return None
    exponent = math.floor(math.log10(current))
    candidates = []
    for exp in range(exponent - 2, exponent + 3):
        base = 10.0 ** exp
        for mantissa in _NICE_STEP_MANTISSAS:
            candidates.append(mantissa * base)
    candidates = sorted(set(candidates))
    tol = max(abs(current) * 1e-9, 1e-12)
    if direction < 0:
        lower = [value for value in candidates if value < current - tol]
        return lower[-1] if lower else current / 10.0
    higher = [value for value in candidates if value > current + tol]
    return higher[0] if higher else current * 10.0


def _fmt_tick(value, per_div=None):
    """Format a graticule tick compactly enough for narrow overlay axes."""
    try:
        value = float(value)
    except Exception:
        return ""
    if not math.isfinite(value):
        return ""
    if per_div is not None:
        try:
            step = float(per_div)
        except Exception:
            step = 0.0
        if math.isfinite(step) and step > 0:
            if value == 0.0 or abs(value) < step * 1e-6:
                return "0"
            decimals = max(0, math.ceil(-math.log10(step)) + 1)
            fixed = f"{value:.{decimals}f}"
            if "." in fixed:
                fixed = fixed.rstrip("0").rstrip(".")
            if fixed == "-0":
                fixed = "0"

            # Resolve one hundredth of a division without forming value/step,
            # whose intermediate result can overflow or underflow.
            sig = max(
                2,
                math.ceil(
                    math.log10(abs(value)) - math.log10(step) + 2.0
                ) + 1,
            )
            scientific = f"{value:.{sig - 1}e}"
            error_limit = 0.01 * step
            numeric_epsilon = 4.0 * math.ulp(error_limit)
            candidates = []
            for preference, label in enumerate((fixed, scientific)):
                if abs(float(label) - value) <= error_limit + numeric_epsilon:
                    candidates.append((len(label), preference, label))
            if candidates:
                return min(candidates)[2]
            # Defensive fallback for the edge of IEEE-754 precision. The
            # adaptive candidate is designed to satisfy the bound above.
            return scientific
    # Wheel-pan ticks accumulate as ``lo - step*per_div + k*per_div`` (see
    # overlay_axes._handle_wheel_dispatch); the zero-crossing division lands on
    # a tiny float residue (~1e-15) instead of exact 0.0. Snap it so the axis
    # reads "0" rather than "1.78e-15". No real overlay tick sits below 1e-9.
    if abs(value) < 1e-9:
        return "0"
    if abs(value) >= 1e6 or abs(value) < 1e-4:
        return f"{value:.2e}"
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return f"{int(rounded)}"
    return f"{value:g}"


def _frame_to_nice(lo, hi, n):
    """Expand ``[lo, hi]`` into ``n`` nice, equal graticule divisions.

    A span at or below ``_DEGENERATE_SPAN_RATIO`` of its own magnitude is
    framed as the constant it is (centre +/- 50%, or +/- 0.5 at zero) rather
    than divided into ``n`` microscopic steps. That ratio test is the same one
    ``pad_y_extent`` applies, and it exists for the same reason: a channel
    produced by channel maths is constant in INTENT but not bit-exact, so its
    ``max - min`` is ~1e-16 relative float64 residue. See
    ``_DEGENERATE_SPAN_RATIO`` for the full mechanism — the short version is
    that dividing the residue gives a per-division step near 1e-15, and every
    consumer of these ticks formats against that step, so the labels come out
    as ``'34.9999999999992'`` and the left axis demands 136 px it does not get.

    The ratio subsumes the old ``span <= 0`` test rather than replacing it:
    at zero magnitude the threshold IS zero, so a genuinely constant or
    inverted input takes exactly the branch it always took, and callers that
    pass an ordinary engineering range are untouched.

    Non-finite spans keep short-circuiting first, so a nan/inf endpoint can
    never reach — and poison — the magnitude comparison.
    """
    try:
        lo = float(lo)
        hi = float(hi)
    except Exception:
        lo, hi = 0.0, 0.0
    if hi < lo:
        lo, hi = hi, lo
    n = max(1, int(n))
    span = hi - lo
    if (
        not math.isfinite(span)
        or span <= max(abs(lo), abs(hi)) * _DEGENERATE_SPAN_RATIO
    ):
        center = (lo + hi) / 2.0
        if not math.isfinite(center):
            center = 0.0
        span = max(abs(center), 1.0)
        lo = center - span / 2.0
        hi = center + span / 2.0
    per_div = _nice_per_div(span / n) or (span / n)
    bottom = math.floor(lo / per_div) * per_div
    top = bottom + n * per_div
    guard = 0
    while top < hi - max(abs(per_div) * 1e-9, 1e-12) and guard < 64:
        per_div = _nice_per_div(per_div * 1.000001) or (per_div * 2.0)
        bottom = math.floor(lo / per_div) * per_div
        top = bottom + n * per_div
        guard += 1
    ticks = [bottom + k * per_div for k in range(n + 1)]
    return bottom, top, ticks


def nice_ticks_within(lo, hi, n):
    """Return ``(per_div, ticks)`` for ~``n`` nice divisions inside ``[lo, hi]``.

    Unlike :func:`_frame_to_nice`, the interval is never widened: a manually
    entered axis range must survive verbatim, so the ticks are simply the nice
    multiples that fall inside it. When the resulting labels do not fit, the
    caller steps down with :func:`coarsen_nice_step`.
    """
    try:
        lo = float(lo)
        hi = float(hi)
    except Exception:
        return None, []
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if not math.isfinite(span) or span <= 0:
        return None, []
    n = max(1, int(n))
    per_div = _nice_per_div(span / n)
    if per_div is None or per_div <= 0:
        return None, []
    return per_div, _ticks_for_step(lo, hi, per_div)


def _ticks_for_step(lo, hi, per_div):
    tol = max(abs(per_div) * 1e-9, 1e-12)
    first = math.ceil((lo - tol) / per_div)
    ticks = []
    for index in range(512):
        value = (first + index) * per_div
        if value > hi + tol:
            break
        # Multiples straddling zero pick up float residue; snap so the axis
        # reads "0" instead of "-1.78e-15".
        ticks.append(0.0 if abs(value) < per_div * 1e-9 else value)
    return ticks


def coarsen_nice_step(per_div, lo, hi):
    """Return the next coarser nice step and its ticks inside ``[lo, hi]``."""
    step = _adjacent_nice_step(per_div, 1)
    if step is None or step <= 0:
        return None, []
    return step, _ticks_for_step(float(lo), float(hi), step)


__all__ = [
    "MAX_TICK_SIGNIFICANT_DIGITS",
    "_NICE_STEP_MANTISSAS",
    "_snap_y_to_divisions",
    "_nice_per_div",
    "_adjacent_nice_step",
    "_fmt_tick",
    "_frame_to_nice",
    "bounded_tick_strings",
    "coarsen_nice_step",
    "nice_ticks_within",
    "pad_y_extent",
]
