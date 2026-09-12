"""UI-neutral line amplitude ranges from original samples and visible segments."""
from __future__ import annotations

import numpy as np


def _values_and_valid(values, valid_mask):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1:
        raise ValueError('line values must be one-dimensional')
    valid = np.isfinite(values)
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool)
        if mask.shape != values.shape:
            raise ValueError('valid_mask must match line values shape')
        valid &= mask
    return values, valid


def _as_line_arrays(x, y, valid_mask):
    y, valid = _values_and_valid(y, valid_mask)
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.shape != y.shape:
        raise ValueError('x and y must be one-dimensional with equal shapes')
    finite_x = np.isfinite(x)
    valid = valid & finite_x
    return x, y, valid, finite_x


def _finite_ascending_xlim(xlim):
    limits = np.asarray(xlim, dtype=float)
    if limits.shape != (2,) or not np.all(np.isfinite(limits)) or limits[1] < limits[0]:
        raise ValueError('xlim must be a finite ascending pair')
    return float(limits[0]), float(limits[1])


def _finite_run_bounds(finite):
    n = int(finite.size)
    if n == 0:
        return np.empty(0, dtype=np.intp), np.empty(0, dtype=np.intp)
    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[-1] = False
    padded[1:-1] = finite
    d = np.diff(padded.astype(np.int8, copy=False))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)


def line_amplitude_limits(values, *, amplitude_mode, valid_mask=None):
    """Return padded finite limits or None; validate 1D/equal shapes.

    Masks come from original linear amplitudes; finite deep dB valleys are
    never inferred to be invalid from their distance below a peak.
    """
    values, valid = _values_and_valid(values, valid_mask)
    finite = values[valid]
    if not finite.size:
        return None
    lo, hi = float(np.min(finite)), float(np.max(finite))
    if hi > lo:
        span = hi - lo
        # Scale first only when the subtraction overflows; preserve ordinary
        # range arithmetic and its rounding for engineering-scale values.
        pad = span * 0.05 if np.isfinite(span) else hi * 0.05 - lo * 0.05
    elif 'db' in str(amplitude_mode).lower():
        pad = 1.0
    else:
        pad = abs(lo) * 0.05 if lo else 1.0
    # At float64 limits padding saturates at the representable boundary.
    # Every original finite sample stays covered without emitting infinities.
    largest = float(np.finfo(float).max)
    return max(-largest, lo - pad), min(largest, hi + pad)


def visible_line_values(x, y, xlim, *, valid_mask=None):
    """Return valid in-window values plus finite boundary intersections.

    Only adjacent valid points may form a segment, so NaNs and invalid source
    amplitudes remain gaps. The original arrays are never changed.
    """
    x, y, valid, _finite_x = _as_line_arrays(x, y, valid_mask)
    lo, hi = _finite_ascending_xlim(xlim)
    result = [y[valid & (x >= lo) & (x <= hi)]]
    adjacent = valid[:-1] & valid[1:]
    for boundary in (lo, hi):
        crossing = adjacent & (((x[:-1] < boundary) & (x[1:] > boundary)) | ((x[:-1] > boundary) & (x[1:] < boundary)))
        indices = np.flatnonzero(crossing)
        fraction = (boundary - x[indices]) / (x[indices + 1] - x[indices])
        result.append(y[indices] * (1.0 - fraction) + y[indices + 1] * fraction)
    return np.concatenate(result)


class LineRangeQuery:
    """Window query over original samples; extrema are unpadded.

    ``slice_start``/``slice_stop`` are inclusive source indices covering
    in-window valid samples and adjacent crossing legs, or ``(0, -1)``
    when empty. Padding stays in :func:`line_amplitude_limits`.
    """

    __slots__ = (
        'slice_start', 'slice_stop', 'crossings',
        'y_min', 'y_max', 'fully_covered', 'index_key',
        'used_cached_full_bounds', 'reused_interior_y',
        'used_ordered_path',
    )

    def __init__(
        self,
        slice_start,
        slice_stop,
        crossings,
        y_min,
        y_max,
        fully_covered,
        index_key,
        used_cached_full_bounds=False,
        reused_interior_y=False,
        used_ordered_path=False,
    ):
        self.slice_start = int(slice_start)
        self.slice_stop = int(slice_stop)
        self.crossings = tuple(crossings)
        self.y_min = y_min
        self.y_max = y_max
        self.fully_covered = bool(fully_covered)
        self.index_key = index_key
        self.used_cached_full_bounds = bool(used_cached_full_bounds)
        self.reused_interior_y = bool(reused_interior_y)
        self.used_ordered_path = bool(used_ordered_path)


class PreparedLineRange:
    """Read-only window index over original X/Y samples.

    Holds references to validated arrays, finite-X runs, and full-valid
    amplitude bounds. Created at result ingest; holds no Qt objects and
    does not copy X/Y on each :meth:`query`.
    """

    __slots__ = (
        '_x', '_y', '_valid', '_finite_x', '_finite_xy',
        '_adjacent_valid', '_x_runs', '_x_is_ordered_finite',
        '_valid_count', '_valid_x_min', '_valid_x_max',
        '_full_y_min', '_full_y_max', '_valid_idx_first', '_valid_idx_last',
        '_finite_x_min', '_finite_x_max',
        '_interior_key', '_interior_ext',
    )

    def __init__(self, x, y, valid, finite_x):
        self._x = x
        self._y = y
        self._valid = valid
        self._finite_x = finite_x
        self._finite_xy = finite_x & np.isfinite(y)
        n = int(x.size)
        self._adjacent_valid = (
            valid[:-1] & valid[1:] if n >= 2
            else np.empty(0, dtype=bool)
        )
        starts, stops = _finite_run_bounds(finite_x)
        runs = []
        for start, stop in zip(starts.tolist(), stops.tolist()):
            start = int(start)
            stop = int(stop)
            seg = x[start:stop]
            ordered = (stop - start) <= 1 or bool(np.all(seg[1:] >= seg[:-1]))
            runs.append((start, stop, ordered))
        self._x_runs = tuple(runs)
        self._x_is_ordered_finite = bool(
            n == 0 or (bool(finite_x.all()) and (n <= 1 or bool(np.all(x[1:] >= x[:-1]))))
        )
        if valid.any():
            vx = x[valid]
            vy = y[valid]
            self._valid_count = int(vy.size)
            self._valid_x_min = float(vx.min())
            self._valid_x_max = float(vx.max())
            self._full_y_min = float(vy.min())
            self._full_y_max = float(vy.max())
            self._valid_idx_first = int(np.argmax(valid))
            self._valid_idx_last = int(n - 1 - np.argmax(valid[::-1]))
        else:
            self._valid_count = 0
            self._valid_x_min = None
            self._valid_x_max = None
            self._full_y_min = None
            self._full_y_max = None
            self._valid_idx_first = None
            self._valid_idx_last = None
        if finite_x.any():
            fx = x[finite_x]
            self._finite_x_min = float(fx.min())
            self._finite_x_max = float(fx.max())
        else:
            self._finite_x_min = None
            self._finite_x_max = None
        self._interior_key = None
        self._interior_ext = (None, None)

    @property
    def x(self):
        return self._x

    @property
    def y(self):
        return self._y

    @property
    def valid(self):
        return self._valid

    @property
    def finite_x(self):
        return self._finite_x

    @property
    def finite_xy(self):
        return self._finite_xy

    @property
    def ordered(self):
        return self._x_is_ordered_finite

    @property
    def full_y_min(self):
        return self._full_y_min

    @property
    def full_y_max(self):
        return self._full_y_max

    @property
    def finite_x_min(self):
        return self._finite_x_min

    @property
    def finite_x_max(self):
        return self._finite_x_max

    def query(self, xlim, *, force_general_path=False):
        lo, hi = _finite_ascending_xlim(xlim)
        if self._valid_count == 0:
            return self._empty_query(fully_covered=True, used_cached_full_bounds=True)
        if lo <= self._valid_x_min and hi >= self._valid_x_max:
            return LineRangeQuery(
                slice_start=self._valid_idx_first,
                slice_stop=self._valid_idx_last,
                crossings=(),
                y_min=self._full_y_min,
                y_max=self._full_y_max,
                fully_covered=True,
                index_key=('full', self._valid_idx_first, self._valid_idx_last, False),
                used_cached_full_bounds=True,
                reused_interior_y=True,
                used_ordered_path=self._x_is_ordered_finite and not force_general_path,
            )
        if self._x_is_ordered_finite and not force_general_path:
            return self._query_ordered(lo, hi)
        return self._query_general(lo, hi)

    def plot_source_slice(self, xlim):
        """Inclusive finite-X source slice covering inside samples and overlapping legs.

        ``xlim`` may be reversed; non-finite pairs yield an empty ``(0, -1)``.
        """
        limits = np.asarray(xlim, dtype=float)
        if limits.shape != (2,) or not np.all(np.isfinite(limits)):
            return 0, -1
        lo, hi = float(limits[0]), float(limits[1])
        if hi < lo:
            lo, hi = hi, lo
        first = None
        last = None
        for start, stop, ordered in self._x_runs:
            run_first, run_last = self._run_plot_slice(start, stop, ordered, lo, hi)
            if run_first is None:
                continue
            first = run_first if first is None else min(first, run_first)
            last = run_last if last is None else max(last, run_last)
        if first is None:
            return 0, -1
        return int(first), int(last)

    def _empty_query(self, *, fully_covered, used_cached_full_bounds=False,
                     used_ordered_path=False, reused_interior_y=False,
                     index_key=(-1, -1, False)):
        return LineRangeQuery(
            slice_start=0,
            slice_stop=-1,
            crossings=(),
            y_min=None,
            y_max=None,
            fully_covered=fully_covered,
            index_key=index_key,
            used_cached_full_bounds=used_cached_full_bounds,
            reused_interior_y=reused_interior_y,
            used_ordered_path=used_ordered_path,
        )

    def _interp_at(self, i, boundary):
        x = self._x
        y = self._y
        x0 = x[i]
        x1 = x[i + 1]
        fraction = (boundary - x0) / (x1 - x0)
        return float(y[i] * (1.0 - fraction) + y[i + 1] * fraction)

    def _slice_extrema(self, left, right):
        if right <= left:
            return None, None
        sl_valid = self._valid[left:right]
        sl_y = self._y[left:right]
        if sl_valid.all():
            return float(sl_y.min()), float(sl_y.max())
        if not sl_valid.any():
            return None, None
        finite = sl_y[sl_valid]
        return float(finite.min()), float(finite.max())

    def _merge_extrema(self, interior_min, interior_max, crossing_ys):
        if crossing_ys:
            cmin = min(crossing_ys)
            cmax = max(crossing_ys)
            if interior_min is None:
                return cmin, cmax
            return min(interior_min, cmin), max(interior_max, cmax)
        return interior_min, interior_max

    def _query_ordered(self, lo, hi):
        x = self._x
        valid = self._valid
        n = int(x.size)
        left = int(np.searchsorted(x, lo, side='left'))
        right = int(np.searchsorted(x, hi, side='right'))
        crossings = []
        left_cross = (
            0 < left < n
            and bool(valid[left - 1] and valid[left])
            and x[left - 1] < lo < x[left]
        )
        if left_cross:
            crossings.append((lo, self._interp_at(left - 1, lo)))
        right_cross = (
            0 < right < n
            and bool(valid[right - 1] and valid[right])
            and x[right - 1] < hi < x[right]
        )
        if right_cross:
            crossings.append((hi, self._interp_at(right - 1, hi)))
        interior_key = (left, right)
        if interior_key == self._interior_key:
            reused = True
            interior_min, interior_max = self._interior_ext
        else:
            reused = False
            interior_min, interior_max = self._slice_extrema(left, right)
            self._interior_key = interior_key
            self._interior_ext = (interior_min, interior_max)
        y_min, y_max = self._merge_extrema(
            interior_min, interior_max, [cy for _b, cy in crossings],
        )
        first = last = None
        if right > left:
            first, last = left, right - 1
        if left_cross:
            pair_lo, pair_hi = left - 1, left
            first = pair_lo if first is None else min(first, pair_lo)
            last = pair_hi if last is None else max(last, pair_hi)
        if right_cross:
            pair_lo, pair_hi = right - 1, right
            first = pair_lo if first is None else min(first, pair_lo)
            last = pair_hi if last is None else max(last, pair_hi)
        if first is None:
            return self._empty_query(
                fully_covered=False,
                used_ordered_path=True,
                reused_interior_y=reused,
                index_key=(-1, -1, False),
            )
        has_crossings = bool(crossings)
        return LineRangeQuery(
            slice_start=first,
            slice_stop=last,
            crossings=crossings,
            y_min=y_min,
            y_max=y_max,
            fully_covered=False,
            index_key=(first, last, has_crossings),
            used_cached_full_bounds=False,
            reused_interior_y=reused,
            used_ordered_path=True,
        )

    def _query_general(self, lo, hi):
        x = self._x
        y = self._y
        valid = self._valid
        inside = valid & (x >= lo) & (x <= hi)
        inside_idx = np.flatnonzero(inside)
        if inside_idx.size:
            interior = y[inside]
            interior_min = float(interior.min())
            interior_max = float(interior.max())
            first = int(inside_idx[0])
            last = int(inside_idx[-1])
        else:
            interior_min = interior_max = None
            first = last = None
        crossings = []
        adjacent = self._adjacent_valid
        for boundary in (lo, hi):
            crossing = adjacent & (
                ((x[:-1] < boundary) & (x[1:] > boundary))
                | ((x[:-1] > boundary) & (x[1:] < boundary))
            )
            indices = np.flatnonzero(crossing)
            if not indices.size:
                continue
            fraction = (boundary - x[indices]) / (x[indices + 1] - x[indices])
            cy = y[indices] * (1.0 - fraction) + y[indices + 1] * fraction
            pair_first = int(indices[0])
            pair_last = int(indices[-1]) + 1
            first = pair_first if first is None else min(first, pair_first)
            last = pair_last if last is None else max(last, pair_last)
            for value in cy:
                crossings.append((float(boundary), float(value)))
        if first is None:
            return self._empty_query(fully_covered=False, used_ordered_path=False)
        y_min, y_max = self._merge_extrema(
            interior_min, interior_max, [cy for _b, cy in crossings],
        )
        return LineRangeQuery(
            slice_start=first,
            slice_stop=last,
            crossings=crossings,
            y_min=y_min,
            y_max=y_max,
            fully_covered=False,
            index_key=(first, last, bool(crossings)),
            used_cached_full_bounds=False,
            reused_interior_y=False,
            used_ordered_path=False,
        )

    def _run_plot_slice(self, start, stop, ordered, lo, hi):
        if stop <= start:
            return None, None
        if ordered:
            seg = self._x[start:stop]
            left_rel = int(np.searchsorted(seg, lo, side='left'))
            right_rel = int(np.searchsorted(seg, hi, side='right'))
            left = start + left_rel
            right = start + right_rel
            first = last = None
            if right > left:
                first, last = left, right - 1
            if left > start and left < stop:
                first = left - 1 if first is None else min(first, left - 1)
                last = left if last is None else max(last, left)
            if right < stop and right > start:
                first = right if first is None else min(first, right)
                last = right if last is None else max(last, right)
            if first is None:
                return None, None
            return first, last
        seg_x = self._x[start:stop]
        inside = np.flatnonzero((seg_x >= lo) & (seg_x <= hi))
        if seg_x.size >= 2:
            overlap = (
                (np.minimum(seg_x[:-1], seg_x[1:]) <= hi)
                & (np.maximum(seg_x[:-1], seg_x[1:]) >= lo)
            )
            pairs = np.flatnonzero(overlap)
        else:
            pairs = np.empty(0, dtype=np.intp)
        if not inside.size and not pairs.size:
            return None, None
        first_rel = min(
            int(inside[0]) if inside.size else seg_x.size,
            int(pairs[0]) if pairs.size else seg_x.size,
        )
        last_rel = max(
            int(inside[-1]) if inside.size else -1,
            int(pairs[-1]) + 1 if pairs.size else -1,
        )
        return start + first_rel, start + last_rel


def prepare_line_range(x, y, *, valid_mask=None, force_general_path=False):
    """Build a read-only :class:`PreparedLineRange` for repeated window queries.

    Rank and same-shape checks match :func:`visible_line_values`. Incompatible
    X/Y are rejected; lengths are never silently truncated. ``force_general_path``
    keeps monotonic finite data on the exact general path for tests.
    """
    x, y, valid, finite_x = _as_line_arrays(x, y, valid_mask)
    prepared = PreparedLineRange(x, y, valid, finite_x)
    if force_general_path:
        prepared._x_is_ordered_finite = False
    return prepared
