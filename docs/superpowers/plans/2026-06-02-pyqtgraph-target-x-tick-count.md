# PyQtGraph Target X Tick Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TimeDomain pyqtgraph X-axis tick control behave like a target major-tick count (`10` means roughly 10 visible major labels when space allows), while automatically backing off before numeric labels overlap or overflow.

**Architecture:** Keep pyqtgraph's adaptive behavior for Y axes, but replace the TimeDomain X-axis density mapping with explicit safe major tick lists via `AxisItem.setTicks([[...], []])`. Generate only major ticks, choose nice intervals, and filter by actual label pixel rectangles before painting. Recompute on tick-density changes, X-range changes, first plot build, and resize settle.

**Tech Stack:** PyQt5, pyqtgraph `AxisItem`, `QFontMetrics`, existing `TimeDomainCanvasPG`, pytest with `QT_QPA_PLATFORM=offscreen`.

---

## Current Evidence

- Inspector text says tick density controls the approximate number of major ticks: `mf4_analyzer/ui/inspector_sections.py:1419-1427`.
- `MainWindow` passes the values into TimeDomain: `mf4_analyzer/ui/main_window.py:1117-1118`.
- Current pyqtgraph implementation maps `x=10` to `setTickDensity(1.0)` and `x=20` to `setTickDensity(2.0)`: `mf4_analyzer/ui/pg_canvases.py:2642-2670`.
- In a 1200 px wide, `0..100` range probe, current behavior was:
  - `x=10` -> 6 major labels: `0,20,40,60,80,100`
  - `x=20` -> 11 major labels: `0,10,20,...,100`
  - `x=30` -> 21 major labels
- pyqtgraph supports explicit labels with `AxisItem.setTicks(ticks)`, and `setTicks(None)` restores the default system. This is safer than `setTickSpacing(major, minor)` because historical tests already caught minor-level label piles and slow repaint from fixed spacing.

## Design Decisions

- `spin_xt` remains user-facing as "target X major tick count", not a density multiplier.
- The target is approximate because readable axes should prefer nice intervals and no overlap over exact arbitrary intervals.
- Acceptance band:
  - Target `10`: produce about `9..11` labels when the axis has enough space.
  - Target `20`: produce about `18..21` labels when the axis has enough space.
  - If labels would overlap or overflow, produce fewer labels and keep all labels readable.
- Do not change Y-axis behavior in this plan. Y axes stay on pyqtgraph adaptive density with `maxTickLevel=0`.
- Do not enable minor tick labels.
- Do not change curve downsampling, AA, cache, pan/zoom, or export paths.

## Files

- Modify: `mf4_analyzer/ui/pg_canvases.py`
  - Add nice-step and label-fit helpers.
  - Apply explicit target ticks to X axes only.
  - Refresh explicit X ticks after range and resize changes.
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
  - Add regression tests for target count, overflow backoff, X-range refresh, subplot alignment, and preserving Y adaptive behavior.

## Algorithm

1. Read `x_n` from `self._tick_density`.
2. For each X axis, get:
   - current X range from the axis handle,
   - actual axis width in pixels,
   - tick font from `_pg_chart_font(9)`.
3. Generate candidate nice steps around `raw_step = (hi - lo) / max(1, target - 1)`.
4. For each candidate step, create tick values inside the visible range.
5. Format labels using pyqtgraph's own `axis.tickStrings(values, scale, spacing)` when possible; fallback to compact `g` formatting.
6. Use `QFontMetrics.horizontalAdvance(label)` to build centered label rectangles at their pixel positions.
7. Reject candidates where any label rectangle:
   - starts before the axis left edge,
   - extends past the axis right edge,
   - overlaps the previous label plus a small gap.
8. Pick the candidate with:
   - no rectangle collision,
   - count closest to target,
   - nice interval preference.
9. Apply via `axis.setTicks([[(value, label), ...], []])`.
10. If the range/width is invalid, clear explicit ticks with `axis.setTicks(None)` and fall back to pyqtgraph adaptive density.

Suggested constants:

```python
_TARGET_X_TICK_NICE_FACTORS = (1.0, 2.0, 2.5, 5.0, 10.0)
_TARGET_X_TICK_MIN_GAP_PX = 10.0
_TARGET_X_TICK_EDGE_PAD_PX = 2.0
_TARGET_X_TICK_MIN_COUNT = 3
```

---

### Task 1: Add Red Tests For Target X Tick Count

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Add shared tick inspection helpers near the existing visual-style tests**

```python
def _major_tick_labels(axis):
    levels = getattr(axis, "_tickLevels", None)
    assert levels is not None, "expected explicit X tick levels"
    assert len(levels) >= 1
    return list(levels[0])


def _label_rects_for_axis(axis, values_and_labels, lo, hi):
    from PyQt5.QtGui import QFontMetrics
    from mf4_analyzer.ui.pg_canvases import _pg_chart_font

    width = float(axis.size().width())
    metrics = QFontMetrics(_pg_chart_font(9))
    rects = []
    span = float(hi - lo)
    assert span > 0
    for value, label in values_and_labels:
        x = (float(value) - float(lo)) / span * width
        try:
            w = float(metrics.horizontalAdvance(str(label)))
        except AttributeError:
            w = float(metrics.width(str(label)))
        rects.append((x - w / 2.0, x + w / 2.0, str(label)))
    return rects
```

- [ ] **Step 2: Add the failing target-count test**

```python
def test_x_tick_target_count_used_when_width_allows(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()

    axis = canvas.axes_list[0].x_axis_item()

    canvas.set_tick_density(10, 6)
    QCoreApplication.processEvents()
    labels_10 = _major_tick_labels(axis)
    assert 9 <= len(labels_10) <= 11

    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()
    labels_20 = _major_tick_labels(axis)
    assert 18 <= len(labels_20) <= 21

    canvas.deleteLater()
```

- [ ] **Step 3: Run test to verify it fails on current adaptive-density behavior**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_x_tick_target_count_used_when_width_allows -q
```

Expected: FAIL because `_tickLevels` is currently `None` or because `x=10` produces about 6 labels through `setTickDensity`.

---

### Task 2: Add Red Tests For Overflow Backoff And X-Range Refresh

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Add a narrow-axis no-overlap test**

```python
def test_x_tick_target_count_backs_off_before_label_overlap(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(360, 360)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 1_000_000.0, 5000)
    rows = [("speed", True, t, np.sin(t / 100000.0), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(30, 6)
    QCoreApplication.processEvents()

    handle = canvas.axes_list[0]
    axis = handle.x_axis_item()
    lo, hi = handle.get_xlim()
    labels = _major_tick_labels(axis)
    rects = _label_rects_for_axis(axis, labels, lo, hi)

    assert len(labels) < 30
    previous_right = None
    for left, right, label in rects:
        assert left >= -0.5, f"label {label!r} overflows left edge"
        assert right <= float(axis.size().width()) + 0.5, (
            f"label {label!r} overflows right edge"
        )
        if previous_right is not None:
            assert left - previous_right >= 8.0, (
                f"adjacent X tick labels overlap: previous_right={previous_right}, "
                f"left={left}, label={label!r}"
            )
        previous_right = right

    canvas.deleteLater()
```

- [ ] **Step 2: Add an X-range refresh test**

```python
def test_target_x_ticks_refresh_after_xlim_change(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1000, 500)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    handle = canvas.axes_list[0]
    before = [value for value, _label in _major_tick_labels(handle.x_axis_item())]
    handle.set_xlim(20.0, 40.0)
    QCoreApplication.processEvents()
    after = [value for value, _label in _major_tick_labels(handle.x_axis_item())]

    assert before != after
    assert min(after) >= 20.0 - 1e-9
    assert max(after) <= 40.0 + 1e-9
    assert 18 <= len(after) <= 21

    canvas.deleteLater()
```

- [ ] **Step 3: Run both tests to verify they fail**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::test_x_tick_target_count_backs_off_before_label_overlap \
  tests/ui/test_pg_timedomain_canvas.py::test_target_x_ticks_refresh_after_xlim_change -q
```

Expected: FAIL because explicit target X ticks do not exist yet.

---

### Task 3: Implement Explicit Safe X Major Ticks

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: Add imports and constants**

Add near the top:

```python
import math
```

Add near the existing pyqtgraph constants:

```python
_TARGET_X_TICK_NICE_FACTORS = (1.0, 2.0, 2.5, 5.0, 10.0)
_TARGET_X_TICK_MIN_GAP_PX = 10.0
_TARGET_X_TICK_EDGE_PAD_PX = 2.0
_TARGET_X_TICK_MIN_COUNT = 3
```

- [ ] **Step 2: Replace X-axis density application with target tick application**

Change `_apply_tick_density_to_all_axes()` so X axes use explicit target ticks and Y axes stay adaptive:

```python
def _apply_tick_density_to_all_axes(self):
    _x_n, y_n = self._tick_density
    y_density = max(0.35, min(3.0, float(y_n) / 6.0))
    self._apply_target_x_ticks_to_all_axes()
    for handle in self.axes_list:
        y_axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
        self._apply_axis_tick_density(y_axis, y_density)
```

- [ ] **Step 3: Add target tick helper methods inside `TimeDomainCanvasPG`**

Add these methods near `_apply_tick_density_to_all_axes()`:

```python
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


def _apply_target_x_ticks(self, axis, handle):
    try:
        lo, hi = handle.get_xlim()
        axis_width = float(axis.size().width())
    except Exception:
        self._reset_x_ticks_to_adaptive(axis)
        return
    ticks = self._compute_target_x_ticks(axis, float(lo), float(hi), axis_width)
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
        max(0.35, min(3.0, float(self._tick_density[0]) / 10.0)),
    )
```

- [ ] **Step 4: Add the generator and collision filter**

```python
def _compute_target_x_ticks(self, axis, lo, hi, axis_width):
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return []
    if axis_width <= 1.0:
        return []

    target = max(_TARGET_X_TICK_MIN_COUNT, int(self._tick_density[0]))
    candidates = []
    for step in self._nice_x_tick_steps((hi - lo) / max(1, target - 1)):
        values = self._x_tick_values_for_step(lo, hi, step)
        if len(values) < _TARGET_X_TICK_MIN_COUNT:
            continue
        labels = self._format_x_tick_labels(axis, values, step)
        if not self._x_tick_labels_fit(values, labels, lo, hi, axis_width):
            continue
        candidates.append((abs(len(values) - target), -len(values), step, values, labels))

    if not candidates:
        return []
    _distance, _neg_count, _step, values, labels = min(candidates)
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


def _x_tick_labels_fit(self, values, labels, lo, hi, axis_width):
    metrics = QFontMetrics(_pg_chart_font(9))
    span = hi - lo
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
            return False
        if right > axis_width - _TARGET_X_TICK_EDGE_PAD_PX:
            return False
        if previous_right is not None and left - previous_right < _TARGET_X_TICK_MIN_GAP_PX:
            return False
        previous_right = right
    return True
```

- [ ] **Step 5: Run Task 1 and Task 2 tests**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::test_x_tick_target_count_used_when_width_allows \
  tests/ui/test_pg_timedomain_canvas.py::test_x_tick_target_count_backs_off_before_label_overlap \
  tests/ui/test_pg_timedomain_canvas.py::test_target_x_ticks_refresh_after_xlim_change -q
```

Expected: PASS.

---

### Task 4: Refresh Target X Ticks On Range, Resize, And Rebuild

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Add a subplot shared-ticks regression**

```python
def test_subplot_rows_share_target_x_ticks(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 800)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t + i), "#1769e0", "", "f")
        for i in range(3)
    ]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    tick_sets = [
        tuple(value for value, _label in _major_tick_labels(handle.x_axis_item()))
        for handle in canvas.axes_list
    ]
    assert len(set(tick_sets)) == 1
    assert 18 <= len(tick_sets[0]) <= 21

    canvas.deleteLater()
```

- [ ] **Step 2: Add an overlay shared-bottom-axis regression**

```python
def test_overlay_target_x_ticks_apply_to_x_master_axis(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t + i), "#1769e0", "", "f")
        for i in range(3)
    ]
    canvas.plot_channels(rows, mode="overlay")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    axis = canvas._x_master_handle.x_axis_item()
    labels = _major_tick_labels(axis)
    assert 18 <= len(labels) <= 21

    canvas.deleteLater()
```

- [ ] **Step 3: Wire refresh points**

Add `self._apply_target_x_ticks_to_all_axes()` after the places that already settle X range or canvas geometry:

```python
# In set_tick_density(), covered by _apply_tick_density_to_all_axes().

# In _on_xrange_changed(...), after any sibling / overlay X propagation:
self._apply_target_x_ticks_to_all_axes()

# In _on_resize_settled(), before schedule_idle_quality():
self._apply_target_x_ticks_to_all_axes()

# At the end of plot_channels(), after _set_xrange_to_data_union(),
# _apply_tick_density_to_all_axes() already runs and should apply the first set.
```

- [ ] **Step 4: Run the new refresh tests**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::test_subplot_rows_share_target_x_ticks \
  tests/ui/test_pg_timedomain_canvas.py::test_overlay_target_x_ticks_apply_to_x_master_axis -q
```

Expected: PASS.

---

### Task 5: Preserve Existing Safety Contracts

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Update the adaptive-density safety test**

Replace the old expectation that every axis has `_tickSpacing is None` with a split assertion:

```python
def test_set_tick_density_keeps_y_ticks_adaptive_and_x_ticks_major_only(qapp):
    from PyQt5.QtCore import QCoreApplication

    canvas = _pg_canvas(qapp)
    canvas.resize(1200, 800)
    canvas.show()
    QCoreApplication.processEvents()

    canvas.plot_channels(_five_channel_rows()[:5], mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    for handle in canvas.axes_list:
        x_axis = handle.x_axis_item()
        y_axis = handle.y_axis_item()
        assert x_axis is not None
        assert y_axis is not None
        assert getattr(x_axis, "_tickSpacing", None) is None
        assert getattr(y_axis, "_tickSpacing", None) is None
        assert x_axis.style.get("maxTickLevel") == 0
        assert y_axis.style.get("maxTickLevel") == 0
        assert getattr(x_axis, "_tickLevels", None) is not None
        assert getattr(y_axis, "_tickLevels", None) is None
        assert len(getattr(x_axis, "_tickLevels")[1]) == 0
```

- [ ] **Step 2: Run the safety test**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_set_tick_density_keeps_y_ticks_adaptive_and_x_ticks_major_only -q
```

Expected: PASS.

- [ ] **Step 3: Run layout-settle regression**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode::test_subplot_x_grid_geometry_is_aligned_before_first_frame -q
```

Expected: PASS. This confirms the explicit X ticks did not re-skew subplot rows.

---

### Task 6: Visual And Suite Verification

**Files:**
- No additional code changes unless verification exposes a concrete defect.

- [ ] **Step 1: Run focused pyqtgraph suite**

Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Generate before/after style screenshots for human inspection**

Use a small throwaway script or inline command to render:

- `/tmp/pg_target_xticks_10.png`: 1200 px wide, `x=10`, `0..100` range.
- `/tmp/pg_target_xticks_20.png`: 1200 px wide, `x=20`, `0..100` range.
- `/tmp/pg_target_xticks_narrow.png`: 360 px wide, `x=30`, `0..1_000_000` range.

Expected visual checks:

- `x=10` shows roughly 10 major labels, not 6.
- `x=20` shows roughly 20 major labels, not 11.
- Narrow view drops labels until they do not overlap.
- Subplot vertical grid lines remain aligned.

- [ ] **Step 3: Run lesson status**

Run:

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

Expected: `lesson_required: False`, unless implementation discovers a new durable failure pattern.

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(ui): honor target x-axis tick count safely"
```

Do not add unrelated files such as `docs/2026-06-01-five-ui-issues-diagnosis.md`.

---

## Risks And Mitigations

- **Risk:** Explicit ticks become stale after pan/zoom.
  - **Mitigation:** Refresh in `_on_xrange_changed()` and after resize settle.
- **Risk:** Too many labels slow repaint.
  - **Mitigation:** `spin_xt` max is 30; helper generates at most one major tick level and no data-array work.
- **Risk:** Edge labels are skipped or clipped.
  - **Mitigation:** test label rectangles against axis width before applying.
- **Risk:** Subplot rows get different X grids.
  - **Mitigation:** compute/apply the same target tick list to every subplot X axis after shared X range propagation.
- **Risk:** Hidden upper subplot X axes unexpectedly show labels.
  - **Mitigation:** keep existing bottom-axis `showValues` logic; explicit ticks provide positions, not visibility.

## Out Of Scope

- No changes to Y-axis tick semantics.
- No changes to Inspector layout or labels in this plan.
- No changes to pyqtgraph menu axis forms.
- No AA, export, copy-image, or curve downsampling changes.
