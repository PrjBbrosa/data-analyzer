"""Frozen pre-memo tick fitter from ef63e1e6 (2026-09-23).

Independent parity oracle: retain the original candidate enumeration, without
memoization or pruning. Use the same live font metrics as the canvas so
Linux/Windows/macOS font substitution does not become a golden-file failure.
Do not replace this with a call to the optimized production fitter.
"""
import math
import numpy as np
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QWidget
from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font
from mf4_analyzer.qt_chart_fonts import CHART_FONT_PT

_TARGET_BOTTOM_TICK_NICE_FACTORS = (1.0, 2.0, 2.5, 5.0, 10.0)
_TARGET_BOTTOM_TICK_MIN_GAP_PX = 10.0
_TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX = 0.0
_TARGET_BOTTOM_TICK_EDGE_PAD_PX = 2.0
_TARGET_BOTTOM_TICK_MIN_COUNT = 3


def reference_bottom_ticks(
    axis, view_box, target_count: int, owner: QWidget | None = None
) -> bool:
    """Pin bottom-axis ticks to a readable target count when geometry exists."""
    try:
        if owner is not None and not owner.isVisible():
            return False
        (lo, hi), _yr = view_box.viewRange()
        width = float(axis.size().width())
    except Exception:
        return False
    lo = float(lo)
    hi = float(hi)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return False
    if width <= 1.0:
        return False

    target = max(_TARGET_BOTTOM_TICK_MIN_COUNT, int(target_count))
    raw_step = (hi - lo) / max(1, target - 1)
    if not np.isfinite(raw_step) or raw_step <= 0:
        return False

    metrics = QFontMetrics(_pg_chart_font(CHART_FONT_PT))
    extreme_narrow = width < target * 8.0
    min_gap = (
        _TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX
        if extreme_narrow else
        min(
            _TARGET_BOTTOM_TICK_MIN_GAP_PX,
            max(
                _TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX,
                width / max(1.0, target * 6.0),
            ),
        )
    )
    edge_pad = 0.0 if extreme_narrow else _TARGET_BOTTOM_TICK_EDGE_PAD_PX
    candidates = []
    exponent = math.floor(math.log10(raw_step))
    for exp in range(exponent - 2, exponent + 4):
        scale = 10.0 ** exp
        for factor in _TARGET_BOTTOM_TICK_NICE_FACTORS:
            step = factor * scale
            if step <= 0:
                continue
            start = math.ceil(lo / step) * step
            values = []
            value = start
            guard = 0
            while value <= hi + step * 1e-9 and guard < 500:
                if value >= lo - step * 1e-9:
                    values.append(
                        0.0 if abs(value) < step * 1e-10 else float(value)
                    )
                value += step
                guard += 1
            if len(values) < _TARGET_BOTTOM_TICK_MIN_COUNT:
                continue
            try:
                labels = axis.tickStrings(
                    values,
                    getattr(axis, "scale", 1.0),
                    step,
                )
            except Exception:
                labels = [f"{value:g}" for value in values]

            previous_right = None
            fitted = []
            too_dense = False
            for tick_value, label in zip(values, labels):
                x_pos = (float(tick_value) - lo) / (hi - lo) * width
                text = str(label)
                try:
                    text_width = float(metrics.horizontalAdvance(text))
                except AttributeError:  # pragma: no cover - older Qt fallback
                    text_width = float(metrics.width(text))
                left = x_pos - text_width / 2.0
                right = x_pos + text_width / 2.0
                if left < edge_pad:
                    continue
                if right > width - edge_pad:
                    continue
                if previous_right is not None and left - previous_right < min_gap:
                    # Interior labels collide → this step is too fine. Reject the
                    # WHOLE candidate rather than thinning it: a thinned over-fine
                    # step (e.g. 0.01) yields non-round, truncated ticks (0.21,
                    # 0.69, …) that can hit the target count exactly and beat the
                    # genuine nice steps, leaving the right edge tickless. This
                    # mirrors tick_density.py:_fit_x_tick_labels, whose `return
                    # None` is why the time-domain axis never had this bug. In
                    # extreme-narrow mode min_gap is 0 and thinning is the only
                    # way to fit any labels, so keep skipping there.
                    if extreme_narrow:
                        continue
                    too_dense = True
                    break
                fitted.append((float(tick_value), text))
                previous_right = right
            if too_dense or len(fitted) < _TARGET_BOTTOM_TICK_MIN_COUNT:
                continue
            candidates.append((
                abs(len(fitted) - target),
                -len(fitted),
                abs(math.log(step / raw_step)) if raw_step > 0 else 0.0,
                fitted,
            ))

    if not candidates:
        return False
    _distance, _neg_count, _nice_distance, ticks = min(candidates)
    try:
        axis.setStyle(maxTickLevel=0)
        axis.setTicks([ticks, []])
    except Exception:
        return False
    return True
