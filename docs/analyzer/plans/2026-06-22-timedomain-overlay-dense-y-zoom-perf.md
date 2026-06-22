# Time-Domain Overlay Dense Y-Zoom Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make high-sample-rate time-domain overlay charts responsive when users zoom a channel's Y axis into a narrow range on a full-screen plot.

**Architecture:** Keep the existing pyqtgraph TimeDomainCanvasPG pipeline: raw samples stay in `channel_data`, X viewport reduction stays in `positions_envelope`, and only the displayed envelope sent to `PlotDataItem.setData` changes. Add Y-aware display clipping, make Y range part of the refresh key, and cap overlay envelope bucket counts using the existing overlay density budget.

**Tech Stack:** Python 3.12, PyQt5, pyqtgraph, numpy, pytest-qt, repository venv at `.\.venv\Scripts\python.exe`.

---

## File Structure

- Modify `mf4_analyzer/ui/pg_canvas/renderer.py`
  - Owns visible envelope refresh.
  - Add helper functions for expanded Y clip bounds, finite-value clipping, Y range quantization, and effective overlay pixel width.
  - Apply helpers inside `_refresh_visible_data()` before `PlotDataItem.setData`.

- Modify `mf4_analyzer/ui/pg_canvas/canvas.py`
  - Owns refresh timers and public canvas state.
  - Add `_schedule_visible_data_refresh()` so Y-only changes can reuse the same debounce path as X changes.

- Modify `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
  - Owns overlay Y drag, wheel zoom/pan, snap, and box-zoom Y redirects.
  - Call `_schedule_visible_data_refresh()` after every overlay `set_ylim(...)` path that changes displayed Y ranges.

- Modify `tests/ui/test_pg_timedomain_canvas.py`
  - Add regression tests for Y clipping, raw-data preservation, overlay point budget, and Y-change refresh scheduling.
  - Keep tests structural and deterministic; do not assert absolute frame timing in default UI tests.

- Modify `tests/perf/test_timedomain_pan_perf.py`
  - Add or extend an opt-in slow benchmark for dense overlay + narrow Y range.
  - Print timings only; do not fail on machine-specific thresholds.

---

### Task 1: Add Display-Only Y Clipping Helpers

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write failing helper tests**

Append tests near the existing envelope/render hot-path tests in `tests/ui/test_pg_timedomain_canvas.py`:

```python
def test_clip_envelope_to_visible_y_preserves_nan_breaks():
    from mf4_analyzer.ui.pg_canvas.renderer import _clip_envelope_to_visible_y

    y = np.array([-1000.0, -2.0, np.nan, 0.0, 3.0, 1000.0])

    out = _clip_envelope_to_visible_y(y, (-10.0, 10.0))

    assert out.tolist()[0] == -10.0
    assert out.tolist()[1] == -2.0
    assert np.isnan(out[2])
    assert out.tolist()[3] == 0.0
    assert out.tolist()[4] == 3.0
    assert out.tolist()[5] == 10.0
    assert y[0] == -1000.0, "helper must not mutate input arrays"
```

Add a bounds test with a fake axis/ViewBox:

```python
class _FakeRect:
    def __init__(self, height):
        self._height = height

    def height(self):
        return self._height


class _FakeViewBox:
    def sceneBoundingRect(self):
        return _FakeRect(100.0)


class _FakeAxis:
    view_box = _FakeViewBox()

    def get_ylim(self):
        return (-50.0, 50.0)


def test_expanded_y_clip_bounds_adds_pixel_margin():
    from mf4_analyzer.ui.pg_canvas.renderer import _expanded_y_clip_bounds

    lo, hi = _expanded_y_clip_bounds(_FakeAxis(), pixel_margin=3.0)

    assert lo == pytest.approx(-53.0)
    assert hi == pytest.approx(53.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
New-Item -ItemType Directory -Force -Path ".state\pytest-tmp" | Out-Null
$tmp=(Resolve-Path ".state\pytest-tmp").Path
$env:TEMP=$tmp
$env:TMP=$tmp
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::test_clip_envelope_to_visible_y_preserves_nan_breaks tests\ui\test_pg_timedomain_canvas.py::test_expanded_y_clip_bounds_adds_pixel_margin
```

Expected: both tests fail with import errors for the missing helper functions.

- [ ] **Step 3: Implement helper functions**

Add these module-level helpers near the top of `mf4_analyzer/ui/pg_canvas/renderer.py`, after `_legacy_positions_envelope()`:

```python
_Y_CLIP_PIXEL_MARGIN = 3.0


def _expanded_y_clip_bounds(axis_facade, *, pixel_margin=_Y_CLIP_PIXEL_MARGIN):
    """Return visible Y bounds expanded by a small pixel margin."""
    try:
        lo, hi = axis_facade.get_ylim()
        lo = float(lo)
        hi = float(hi)
    except Exception:
        return None
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if not (np.isfinite(lo) and np.isfinite(hi) and np.isfinite(span) and span > 0):
        return None
    height = 1.0
    vb = getattr(axis_facade, "view_box", None)
    if vb is not None:
        try:
            rect = vb.sceneBoundingRect()
            height = max(float(rect.height()), 1.0)
        except Exception:
            height = 1.0
    pad = span * max(0.0, float(pixel_margin)) / height
    return lo - pad, hi + pad


def _clip_envelope_to_visible_y(values, bounds):
    """Clip finite display envelope values while preserving NaN breaks."""
    if bounds is None:
        return values
    lo, hi = bounds
    if not (np.isfinite(lo) and np.isfinite(hi) and hi > lo):
        return values
    arr = np.asarray(values)
    if arr.size == 0:
        return arr
    out = arr.astype(arr.dtype, copy=True)
    finite = np.isfinite(out)
    if finite.any():
        out[finite] = np.clip(out[finite], lo, hi)
    return out
```

- [ ] **Step 4: Run helper tests**

Run the same two tests from Step 2.

Expected: both tests pass.

- [ ] **Step 5: Commit task**

Do not commit if later tasks are being done in the same working session and the user requested one final commit. Otherwise:

```powershell
git add mf4_analyzer/ui/pg_canvas/renderer.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "test: cover time overlay y clipping helpers"
```

---

### Task 2: Clip Visible Overlay Envelopes During Refresh

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write failing display clipping test**

Append this test near the TimeDomainCanvasPG setData hot-path tests:

```python
def test_overlay_refresh_clips_display_envelope_to_visible_y(qapp):
    from PyQt5.QtCore import QCoreApplication

    canvas = _pg_canvas(qapp)
    canvas.resize(1000, 500)
    canvas.show()
    QCoreApplication.processEvents()

    n = 50_000
    t = np.linspace(0.0, 10.0, n, dtype=np.float64)
    huge = (5000.0 * np.sin(2 * np.pi * 80.0 * t)).astype(np.float64)
    other = (100.0 * np.cos(2 * np.pi * 3.0 * t)).astype(np.float64)

    canvas.plot_channels([
        ("huge", True, t, huge, "#dc2626", "m/s^2", "fid-1"),
        ("other", True, t, other, "#64748b", "m/s^2", "fid-1"),
    ], mode="overlay")
    QCoreApplication.processEvents()

    axis, line = canvas._channel_lines["huge"]
    axis.set_ylim(-10.0, 10.0)
    canvas.set_xlim(1.0, 9.0)
    canvas._flush_pending_refresh()

    _x, displayed_y = line.plot_data_item.getData()
    finite_displayed = np.asarray(displayed_y)[np.isfinite(displayed_y)]

    assert finite_displayed.size
    assert finite_displayed.min() >= -11.0
    assert finite_displayed.max() <= 11.0
    raw = canvas.channel_data["huge"][1]
    assert np.nanmax(raw) > 1000.0, "raw channel_data must remain unclipped"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::test_overlay_refresh_clips_display_envelope_to_visible_y
```

Expected: the displayed finite Y values exceed the visible Y bounds.

- [ ] **Step 3: Apply clipping before `setData`**

In `Renderer._refresh_visible_data()`, after `positions_envelope(...)` returns
and before `line_facade.plot_data_item.setData(...)`, add:

```python
y_bounds = _expanded_y_clip_bounds(axis_facade)
env_s = _clip_envelope_to_visible_y(env_s, y_bounds)
```

The surrounding block should keep existing exception handling:

```python
try:
    env_t, env_s = positions_envelope(
        t, sig,
        xlim=xlim,
        pixel_width=effective_pixel_width,
        is_monotonic=is_monotonic,
    )
except Exception as exc:
    ...

y_bounds = _expanded_y_clip_bounds(axis_facade)
env_s = _clip_envelope_to_visible_y(env_s, y_bounds)
```

Use `pixel_width` for now if Task 3 has not yet introduced
`effective_pixel_width`.

- [ ] **Step 4: Run clipping test**

Run the test from Step 2.

Expected: pass.

- [ ] **Step 5: Run the visible refresh contract test**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSetDataHotPathContract
```

Expected: all tests in the class pass.

---

### Task 3: Add Overlay Point Budget Before Envelope Generation

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write failing overlay budget test**

Append:

```python
def test_overlay_refresh_caps_total_display_points_to_overlay_budget(qapp):
    from PyQt5.QtCore import QCoreApplication

    canvas = _pg_canvas(qapp)
    canvas.resize(1600, 700)
    canvas.show()
    QCoreApplication.processEvents()

    n = 120_000
    t = np.linspace(0.0, 10.0, n, dtype=np.float64)
    rows = []
    for i in range(6):
        sig = (1000.0 * np.sin(2 * np.pi * (30.0 + i) * t)).astype(np.float64)
        rows.append((f"ch{i}", True, t, sig, "#dc2626", "m/s^2", f"fid-{i}"))

    canvas.plot_channels(rows, mode="overlay")
    canvas.set_xlim(0.0, 10.0)
    canvas._flush_pending_refresh()
    QCoreApplication.processEvents()

    total = 0
    for _name, (_axis, line) in canvas._channel_lines.items():
        x, _y = line.plot_data_item.getData()
        total += 0 if x is None else len(x)

    assert total <= canvas._AA_OVERLAY_SEGMENT_OFF
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::test_overlay_refresh_caps_total_display_points_to_overlay_budget
```

Expected: total displayed points exceed `canvas._AA_OVERLAY_SEGMENT_OFF`.

- [ ] **Step 3: Implement effective pixel width helper**

Add this method to `Renderer`:

```python
def _effective_envelope_pixel_width(self, pixel_width: int) -> int:
    """Cap per-curve envelope buckets in overlay mode."""
    pixel_width = max(1, int(pixel_width or 1))
    if not getattr(self, "_overlay_mode", False):
        return pixel_width
    curve_count = max(1, len(getattr(self, "_channel_lines", {}) or {}))
    budget = max(1, int(getattr(self, "_AA_OVERLAY_SEGMENT_OFF", pixel_width)))
    capped = budget // max(1, 2 * curve_count)
    return max(1, min(pixel_width, capped))
```

In `_refresh_visible_data()`, compute once after `pixel_width`:

```python
effective_pixel_width = self._effective_envelope_pixel_width(pixel_width)
```

Pass `effective_pixel_width` into `positions_envelope(...)`.

- [ ] **Step 4: Include effective width in the range key**

Change:

```python
range_key = _quantize_range_key(name, xlim, pixel_width)
```

to:

```python
range_key = _quantize_range_key(name, xlim, effective_pixel_width)
```

This prevents a stale full-width envelope from surviving after overlay point
budget changes.

- [ ] **Step 5: Run budget and density tests**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::test_overlay_refresh_caps_total_display_points_to_overlay_budget tests\ui\test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGQuality
```

Expected: the new budget test passes; existing quality tests pass.

---

### Task 4: Make Y Range Part of the Refresh Key

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write failing Y-cache-key test**

Append:

```python
def test_y_range_change_invalidates_visible_envelope_cache(qapp):
    from PyQt5.QtCore import QCoreApplication

    canvas = _pg_canvas(qapp)
    n = 40_000
    t = np.linspace(0.0, 4.0, n, dtype=np.float64)
    sig = (1000.0 * np.sin(2 * np.pi * 60.0 * t)).astype(np.float64)

    canvas.plot_channels([
        ("a", True, t, sig, "#dc2626", "m/s^2", "fid-1"),
        ("b", True, t, sig * 0.5, "#64748b", "m/s^2", "fid-1"),
    ], mode="overlay")
    canvas.set_xlim(0.0, 4.0)
    canvas._flush_pending_refresh()
    QCoreApplication.processEvents()

    axis, line = canvas._channel_lines["a"]
    _x0, y0 = line.plot_data_item.getData()

    axis.set_ylim(-5.0, 5.0)
    canvas._schedule_visible_data_refresh()
    canvas._flush_pending_refresh()
    QCoreApplication.processEvents()

    _x1, y1 = line.plot_data_item.getData()
    finite_y1 = np.asarray(y1)[np.isfinite(y1)]

    assert not np.array_equal(np.asarray(y0), np.asarray(y1))
    assert finite_y1.min() >= -6.0
    assert finite_y1.max() <= 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::test_y_range_change_invalidates_visible_envelope_cache
```

Expected: either `_schedule_visible_data_refresh` is missing or the displayed Y
data remains equal because the old cache key ignores Y range.

- [ ] **Step 3: Add a Y range key helper**

In `renderer.py`, add:

```python
def _quantize_y_range_key(axis_facade):
    try:
        lo, hi = axis_facade.get_ylim()
        lo = float(lo)
        hi = float(hi)
    except Exception:
        return None
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if not (np.isfinite(lo) and np.isfinite(hi) and span > 0):
        return None
    height = 1.0
    vb = getattr(axis_facade, "view_box", None)
    if vb is not None:
        try:
            height = max(float(vb.sceneBoundingRect().height()), 1.0)
        except Exception:
            height = 1.0
    quantum = span / height
    if not (np.isfinite(quantum) and quantum > 0):
        quantum = 1.0
    return (int(round(lo / quantum)), int(round(hi / quantum)), int(round(height)))
```

- [ ] **Step 4: Use the Y key in `_refresh_visible_data`**

Change range key construction to:

```python
x_key = _quantize_range_key(name, xlim, effective_pixel_width)
y_key = _quantize_y_range_key(axis_facade)
range_key = (x_key, y_key)
```

Keep `_last_range_key[name] = range_key` unchanged.

- [ ] **Step 5: Run Y-cache-key test**

Run the test from Step 2.

Expected: pass.

---

### Task 5: Schedule Visible Refreshes After Overlay Y Changes

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Add canvas refresh scheduler**

In `TimeDomainCanvasPG`, near `_flush_pending_refresh`, add:

```python
def _schedule_visible_data_refresh(self):
    """Debounce a visible envelope refresh after X or Y range changes."""
    self.disable_interactive_quality()
    self._refresh = True
    if self._refresh_pending:
        return
    self._refresh_pending = True
    try:
        self._refresh_timer.start()
    except Exception:
        self._refresh_pending = False
```

- [ ] **Step 2: Refactor X-range scheduling to use the helper**

In `_on_xrange_changed`, replace the manual pending/timer block:

```python
if self._refresh_pending:
    return
self._refresh_pending = True
self._refresh_timer.start()
```

with:

```python
self._schedule_visible_data_refresh()
```

Keep `_propagate_xlim_to_siblings(source=source_handle)` before scheduling.

- [ ] **Step 3: Add overlay Y scheduling calls**

In `overlay_axes.py`, create a local helper method on `OverlayAxisManager`:

```python
def _schedule_overlay_visible_refresh(self):
    scheduler = getattr(self, "_schedule_visible_data_refresh", None)
    if callable(scheduler):
        scheduler()
    else:
        self._refresh = True
        self.draw_idle()
```

Call `_schedule_overlay_visible_refresh()` after successful `set_ylim(...)` in:

- `_apply_overlay_y_drag_at`
- `_handle_wheel_dispatch` overlay branch
- `_handle_wheel_dispatch` non-overlay Y branch after `target.set_ylim`
- `_apply_overlay_box_zoom_y`
- `_snap_overlay_channel_to_grid`
- `_animate_overlay_snap` value and finished callbacks

Do not remove `visible_range_changed.emit()` calls.

- [ ] **Step 4: Write scheduling smoke test**

Append:

```python
def test_overlay_y_wheel_schedules_visible_refresh(qapp, monkeypatch):
    from PyQt5.QtCore import Qt

    canvas = _pg_canvas(qapp)
    t = np.linspace(0.0, 1.0, 5000, dtype=np.float64)
    sig = np.sin(2 * np.pi * 20.0 * t).astype(np.float64)
    canvas.plot_channels([
        ("a", True, t, sig, "#dc2626", "u", "fid-1"),
        ("b", True, t, sig * 2.0, "#64748b", "u", "fid-1"),
    ], mode="overlay")
    canvas.select_overlay_channel("a")

    calls = []
    monkeypatch.setattr(canvas, "_schedule_visible_data_refresh", lambda: calls.append(True))

    handled = canvas._handle_wheel_dispatch(
        delta=120,
        modifiers=Qt.ShiftModifier,
        x_pos=0.5,
        y_pos=0.0,
    )

    assert handled is True
    assert calls, "overlay Y wheel must schedule visible-data refresh"
```

- [ ] **Step 5: Run scheduling tests**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py::test_overlay_y_wheel_schedules_visible_refresh tests\ui\test_pg_timedomain_canvas.py::test_y_range_change_invalidates_visible_envelope_cache
```

Expected: both pass.

---

### Task 6: Add Opt-In Dense Overlay Y-Zoom Benchmark

**Files:**
- Modify: `tests/perf/test_timedomain_pan_perf.py`

- [ ] **Step 1: Add benchmark helper**

In `tests/perf/test_timedomain_pan_perf.py`, add a helper:

```python
def _make_spiky_overlay_channels(n_channels: int, n_samples: int):
    rng = np.random.default_rng(123)
    t = np.linspace(0.0, 8.0, n_samples, dtype=np.float64)
    rows = []
    palette = ["#dc2626", "#f97316", "#0891b2", "#7c3aed", "#be123c", "#64748b"]
    for i in range(n_channels):
        carrier = np.sin(2 * np.pi * (45.0 + i * 7.0) * t)
        bursts = (rng.random(n_samples) > 0.997).astype(np.float64)
        sig = (900.0 * carrier + 3500.0 * bursts * np.sign(carrier)).astype(np.float64)
        rows.append((f"[260417-CLUNK-P-24x] ch{i}", True, t, sig, palette[i % len(palette)], "m/s^2", f"fid-{i}"))
    return rows
```

- [ ] **Step 2: Add slow benchmark**

Add:

```python
def test_timedomain_dense_overlay_narrow_y_refresh_perf():
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    _qapp_or_skip()

    cv = TimeDomainCanvasPG()
    cv.resize(1600, 800)
    cv.show()
    QCoreApplication.processEvents()

    rows = _make_spiky_overlay_channels(6, 200_000)
    cv.plot_channels(rows, mode="overlay")
    QCoreApplication.processEvents()

    first_axis = cv._channel_lines[rows[0][0]][0]
    first_axis.set_ylim(-10.0, 10.0)
    cv.set_xlim(1.0, 7.0)
    cv._flush_pending_refresh()

    samples_ms = []
    starts = np.linspace(1.0, 2.0, 20)
    for s in starts:
        t0 = time.perf_counter()
        cv.set_xlim(float(s), float(s) + 5.0)
        cv._flush_pending_refresh()
        QCoreApplication.processEvents()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)

    print(
        "TIMEDOMAIN_DENSE_OVERLAY_NARROW_Y "
        f"n={len(samples_ms)} "
        f"p50_ms={_percentile(samples_ms, 50):.3f} "
        f"p95_ms={_percentile(samples_ms, 95):.3f} "
        f"mean_ms={statistics.mean(samples_ms):.3f} "
        f"max_ms={max(samples_ms):.3f}"
    )
```

The module already has `pytestmark = pytest.mark.slow`, so this remains opt-in.

- [ ] **Step 3: Run benchmark manually**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\perf\test_timedomain_pan_perf.py -m slow -s
```

Expected: benchmark prints `TIMEDOMAIN_DENSE_OVERLAY_NARROW_Y ...` and exits 0.

---

### Task 7: Final Verification

**Files:**
- Verify: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Verify: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Verify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- Verify: `tests/ui/test_pg_timedomain_canvas.py`
- Verify: `tests/perf/test_timedomain_pan_perf.py`

- [ ] **Step 1: Run focused UI tests**

Run:

```powershell
New-Item -ItemType Directory -Force -Path ".state\pytest-tmp" | Out-Null
$tmp=(Resolve-Path ".state\pytest-tmp").Path
$env:TEMP=$tmp
$env:TMP=$tmp
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py
```

Expected: all tests in `tests/ui/test_pg_timedomain_canvas.py` pass.

- [ ] **Step 2: Run hot-path tests**

Run:

```powershell
$env:TEMP=(Resolve-Path ".state\pytest-tmp").Path
$env:TMP=$env:TEMP
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_timedomain_hotpath_perf.py
```

Expected: all tests pass.

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: exit 0. CRLF warnings are acceptable on this repository; whitespace
errors are not.

- [ ] **Step 4: Inspect changed-file scope**

Run:

```powershell
git status --short
git diff --stat
git diff --name-status
```

Expected: changed files are limited to the renderer/canvas/overlay implementation,
targeted tests, and this plan/spec if they are committed together.

- [ ] **Step 5: Commit**

Use a single implementation commit after tests pass:

```powershell
git add mf4_analyzer/ui/pg_canvas/renderer.py mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/overlay_axes.py tests/ui/test_pg_timedomain_canvas.py tests/perf/test_timedomain_pan_perf.py docs/analyzer/specs/2026-06-22-timedomain-overlay-dense-y-zoom-perf-design.md docs/analyzer/plans/2026-06-22-timedomain-overlay-dense-y-zoom-perf.md
git commit -m "perf: optimize dense overlay y zoom rendering"
```
