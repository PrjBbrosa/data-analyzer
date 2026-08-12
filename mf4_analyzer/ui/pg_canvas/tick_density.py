"""Inspector tick-density helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import math

import numpy as np
from PyQt5.QtGui import QFontMetrics

from ._backref import _CanvasBackref
from .fonts import _pg_chart_font


_TARGET_X_TICK_NICE_FACTORS = (1.0, 2.0, 2.5, 5.0, 10.0)
_TARGET_X_TICK_MIN_GAP_PX = 10.0
_TARGET_X_TICK_EDGE_PAD_PX = 2.0
_TARGET_X_TICK_MIN_COUNT = 3

class TickDensityController(_CanvasBackref):
    """Own and apply Inspector tick-density settings."""

    _owned_names = frozenset({"density", "ticks_cache"})

    _delegate_names = frozenset({
        "set_tick_density",
        "_apply_tick_density_to_all_axes",
        "_apply_target_x_ticks_to_all_axes",
        "_x_tick_axis_handles",
        "_use_adaptive_x_ticks_during_range_change",
        "_apply_target_x_ticks",
        "_reset_x_ticks_to_adaptive",
        "_compute_target_x_ticks",
        "_nice_x_tick_steps",
        "_x_tick_values_for_step",
        "_format_x_tick_labels",
        "_fit_x_tick_labels",
        "_apply_axis_tick_density",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        # Defaults mirror DEFAULT_CHART_TICK_DENSITY / 「密」preset.
        self.density = (20, 15)
        self.ticks_cache = {}

    def set_tick_density(self, x, y):
        """Apply inspector-controlled tick density to PG axes."""
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except Exception:
            x_n, y_n = self.density
        self.density = (x_n, y_n)
        if self._overlay_mode:
            self._overlay_axes.divisions = y_n
            self._overlay_axes._build_overlay_y_grid()
            self._overlay_axes._repin_overlay_channel_ticks()
            self._apply_target_x_ticks_to_all_axes()
            self.draw_idle()
            return
        self._apply_tick_density_to_all_axes()
        self._unify_subplot_left_axis_widths()
        self._unify_subplot_bottom_axis_heights()
        self.draw_idle()

    def _apply_tick_density_to_all_axes(self):
        _x_n, y_n = self.density
        y_density = max(0.35, min(3.0, float(y_n) / 6.0))
        self._apply_target_x_ticks_to_all_axes()
        for handle in self.axes_list:
            y_axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            self._apply_axis_tick_density(y_axis, y_density)

    def _apply_target_x_ticks_to_all_axes(self):
        seen = set()
        for handle in self._x_tick_axis_handles():
            axis = handle.x_axis_item() if hasattr(handle, "x_axis_item") else None
            if axis is None:
                continue
            key = id(axis)
            if key in seen:
                continue
            seen.add(key)
            self._apply_target_x_ticks(axis, handle)

    def _x_tick_axis_handles(self):
        handles = list(self.axes_list)
        if self._overlay_mode and self._x_master_handle is not None:
            handles.insert(0, self._x_master_handle)
        return handles

    def _use_adaptive_x_ticks_during_range_change(self):
        """Release stale explicit X ticks once per interaction burst."""
        seen = set()
        for handle in self._x_tick_axis_handles():
            axis = handle.x_axis_item() if hasattr(handle, "x_axis_item") else None
            if axis is None:
                continue
            key = id(axis)
            if key in seen:
                continue
            seen.add(key)
            if getattr(axis, "_tickLevels", None) is not None:
                self._reset_x_ticks_to_adaptive(axis)

    def _apply_target_x_ticks(self, axis, handle):
        try:
            lo, hi = handle.get_xlim()
            axis_width = float(axis.size().width())
        except Exception:
            self._reset_x_ticks_to_adaptive(axis)
            return
        key = (float(lo), float(hi), round(axis_width, 1), int(self.density[0]))
        ticks = self.ticks_cache.get(key)
        if ticks is None:
            ticks = self._compute_target_x_ticks(axis, float(lo), float(hi), axis_width)
            if len(self.ticks_cache) > 32:
                self.ticks_cache.clear()
            self.ticks_cache[key] = ticks
        if not ticks:
            self._reset_x_ticks_to_adaptive(axis)
            return
        try:
            axis.setStyle(maxTickLevel=0)
            axis.setTicks([ticks, []])
        except Exception:
            self._reset_x_ticks_to_adaptive(axis)

    def _reset_x_ticks_to_adaptive(self, axis):
        try:
            axis.setTicks(None)
        except Exception:
            pass
        self._apply_axis_tick_density(
            axis,
            max(0.35, min(3.0, float(self.density[0]) / 10.0)),
        )

    def _compute_target_x_ticks(self, axis, lo, hi, axis_width):
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            return []
        if axis_width <= 1.0:
            return []

        target = max(_TARGET_X_TICK_MIN_COUNT, int(self.density[0]))
        raw_step = (hi - lo) / max(1, target - 1)
        candidates = []
        for step in self._nice_x_tick_steps(raw_step):
            values = self._x_tick_values_for_step(lo, hi, step)
            if len(values) < _TARGET_X_TICK_MIN_COUNT:
                continue
            labels = self._format_x_tick_labels(axis, values, step)
            fit = self._fit_x_tick_labels(values, labels, lo, hi, axis_width)
            if not fit:
                continue
            fit_values, fit_labels = fit
            candidates.append((
                abs(len(fit_values) - target),
                -len(fit_values),
                abs(math.log(step / raw_step)) if raw_step > 0 else 0.0,
                step,
                fit_values,
                fit_labels,
            ))

        if not candidates:
            return []
        _distance, _neg_count, _nice_distance, _step, values, labels = min(candidates)
        return [(float(value), str(label)) for value, label in zip(values, labels)]

    def _nice_x_tick_steps(self, raw_step):
        if not np.isfinite(raw_step) or raw_step <= 0:
            return []
        exponent = math.floor(math.log10(raw_step))
        bases = []
        for exp in range(exponent - 2, exponent + 4):
            scale = 10.0 ** exp
            for factor in _TARGET_X_TICK_NICE_FACTORS:
                step = factor * scale
                if step > 0:
                    bases.append(step)
        return sorted(set(bases), key=lambda step: abs(math.log(step / raw_step)))

    def _x_tick_values_for_step(self, lo, hi, step):
        start = math.ceil(lo / step) * step
        values = []
        value = start
        guard = 0
        while value <= hi + step * 1e-9 and guard < 500:
            if value >= lo - step * 1e-9:
                values.append(0.0 if abs(value) < step * 1e-10 else float(value))
            value += step
            guard += 1
        return values

    def _format_x_tick_labels(self, axis, values, spacing):
        try:
            return axis.tickStrings(values, getattr(axis, "scale", 1.0), spacing)
        except Exception:
            return [f"{value:g}" for value in values]

    def _fit_x_tick_labels(self, values, labels, lo, hi, axis_width):
        metrics = QFontMetrics(_pg_chart_font(9))
        span = hi - lo
        fit_values = []
        fit_labels = []
        previous_right = None
        for value, label in zip(values, labels):
            x = (float(value) - lo) / span * axis_width
            text = str(label)
            try:
                width = float(metrics.horizontalAdvance(text))
            except AttributeError:  # pragma: no cover - older Qt fallback
                width = float(metrics.width(text))
            left = x - width / 2.0
            right = x + width / 2.0
            if left < _TARGET_X_TICK_EDGE_PAD_PX:
                continue
            if right > axis_width - _TARGET_X_TICK_EDGE_PAD_PX:
                continue
            if previous_right is not None and left - previous_right < _TARGET_X_TICK_MIN_GAP_PX:
                return None
            fit_values.append(float(value))
            fit_labels.append(text)
            previous_right = right
        if len(fit_values) < _TARGET_X_TICK_MIN_COUNT:
            return None
        return fit_values, fit_labels

    def _apply_axis_tick_density(self, axis, density):
        if axis is None:
            return
        set_style = getattr(axis, "setStyle", None)
        if callable(set_style):
            try:
                set_style(maxTickLevel=0)
            except Exception:
                pass
        reset_spacing = getattr(axis, "setTickSpacing", None)
        if callable(reset_spacing):
            try:
                reset_spacing()
            except Exception:
                pass
        set_density = getattr(axis, "setTickDensity", None)
        if callable(set_density):
            try:
                set_density(float(density))
            except Exception:
                pass


__all__ = ["TickDensityController"]
