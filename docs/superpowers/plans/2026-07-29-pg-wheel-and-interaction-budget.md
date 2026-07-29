# Pyqtgraph Wheel And Interaction Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make precision-touchpad modifier zoom work in every pyqtgraph analysis canvas, enforce the TimeDomain coarse-refresh 10 Hz ceiling, and prevent dense overlays from re-enabling native AA because of envelope rounding.

**Architecture:** Reuse the existing owner-scoped raw-wheel bridge at the Qt viewport boundary, add a monotonic elapsed-time guard at the coarse timeout boundary, and add a read-only raw-density pressure gate beside the existing displayed-point AA hysteresis. Keep the three fixes independent and execute them sequentially because the latter two share the TimeDomain test file.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, NumPy, pytest, pytest-qt.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-29-pg-wheel-and-interaction-budget-design.md` exactly.
- Use the repository virtual environment: `.\.venv\Scripts\python.exe -m pytest`.
- Use a unique writable `--basetemp D:\tmp\...` for every pytest command.
- Isolate Qt settings through the repository UI fixtures; do not write real `QSettings` keys.
- Preserve angle-delta mouse behavior, plain-wheel native behavior, zoom factors, cursor anchoring, and axis-lock semantics.
- Preserve generation checks, settle coalescing, HDF raw-X caching, selection-delta object identity, dense-discrete raster behavior, and export fidelity.
- Do not lower `_AA_OVERLAY_SEGMENT_OFF`, increase envelope buckets to manipulate AA, or add a second wheel parser.
- Preserve unrelated worktree changes and do not use destructive git commands.
- Every production change follows RED → GREEN → focused regression.

---

## File Structure

- `mf4_analyzer/ui/pg_canvas/viewbox.py`: existing raw wheel-delta bridge and scene-level fallback interface; Task 1 consumes it without duplicating parsing.
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`: host selection for FFT and its time preview.
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`: host selection for FFT-vs-Time, Order, and optional slice plot.
- `mf4_analyzer/ui/pg_canvas/canvas.py`: TimeDomain coarse timer scheduling and timeout enforcement.
- `mf4_analyzer/ui/pg_canvas/renderer.py`: owner of the shared dense decimation ratio constant.
- `mf4_analyzer/ui/pg_canvas/quality.py`: native-AA affordability and reader-facing block status.
- `tests/ui/test_pg_line_canvas.py`: real viewport wheel routing for both FFT rows.
- `tests/ui/test_pg_heatmap_canvas.py`: real viewport wheel routing for main and slice heatmap rows.
- `tests/ui/test_pg_timedomain_canvas.py`: coarse scheduler and overlay AA policy regression coverage.
- `tests/ui/test_timedomain_hotpath_perf.py`: unchanged HDF consumer-budget regression gate.

### Task 1: Route Precision Wheel Delta Through FFT And Heatmap Hosts

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py:56,164`
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:58,816`
- Test: `tests/ui/test_pg_line_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

**Interfaces:**
- Consumes: `_WheelDeltaGraphicsLayoutWidget(*args, owner_canvas=None, **kwargs)` and `_ModifierWheelViewBox(owner_canvas=None)` from `mf4_analyzer.ui.pg_canvas.viewbox`.
- Produces: `PgLineCanvas._glw` and `PgHeatmapCanvas._glw` that preserve the signed raw delta only during routing of the current Qt wheel event.

- [ ] **Step 1: Add a shared real-viewport wheel event helper to both test modules**

Use the existing Qt imports and add this module-level helper, parameterized by the canvas and target ViewBox:

```python
def _send_viewport_wheel(canvas, view_box, *, pixel_y=0, angle_y=0,
                         modifiers=Qt.NoModifier):
    scene_pos = view_box.mapViewToScene(QPointF(1.0, 1.0))
    pos = QPointF(canvas._glw.mapFromScene(scene_pos))
    global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
    event = QWheelEvent(
        pos,
        global_pos,
        QPoint(0, pixel_y),
        QPoint(0, angle_y),
        Qt.NoButton,
        modifiers,
        Qt.ScrollUpdate,
        False,
    )
    return QApplication.sendEvent(canvas._glw.viewport(), event)
```

- [ ] **Step 2: Add failing pixel-only tests for every owned ViewBox**

In `test_pg_line_canvas.py`, parameterize over `"_plot_amp"` and `"_plot_time"`, Ctrl/Shift, and `(15, True), (-15, False)`. In `test_pg_heatmap_canvas.py`, construct `PgHeatmapCanvas(with_slice=True)` and parameterize over `"_plot"` and `"_slice_plot"` with the same modifier/delta matrix. For each case:

```python
view_box.setXRange(0.0, 100.0, padding=0)
view_box.setYRange(0.0, 50.0, padding=0)
qapp.processEvents()
before = view_box.viewRange()
assert _send_viewport_wheel(
    canvas, view_box, pixel_y=pixel_delta, modifiers=modifier,
)
qapp.processEvents()
after = view_box.viewRange()
axis_index = 0 if modifier == Qt.ControlModifier else 1
other_index = 1 - axis_index
before_span = before[axis_index][1] - before[axis_index][0]
after_span = after[axis_index][1] - after[axis_index][0]
assert after[other_index] == pytest.approx(before[other_index])
assert (after_span < before_span) is expect_zoom_in
```

Name the tests:

- `test_pixel_only_modifier_wheel_zooms_each_fft_viewbox`
- `test_pixel_only_modifier_wheel_zooms_each_heatmap_viewbox`

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ui/test_pg_line_canvas.py::test_pixel_only_modifier_wheel_zooms_each_fft_viewbox `
  tests/ui/test_pg_heatmap_canvas.py::test_pixel_only_modifier_wheel_zooms_each_heatmap_viewbox `
  --basetemp D:\tmp\pytest-wheel-red
```

Expected: the events are delivered, but the intended range span remains unchanged because both canvases still use plain `GraphicsLayoutWidget`.

- [ ] **Step 4: Replace only the two host widget constructors**

In `line_canvas.py` import both shared classes and construct:

```python
from .viewbox import _ModifierWheelViewBox, _WheelDeltaGraphicsLayoutWidget

self._glw = _WheelDeltaGraphicsLayoutWidget(self, owner_canvas=self)
```

In `heatmap_canvas.py` use the same two-class import from its current absolute module path and the same constructor. Do not alter `_handle_wheel_dispatch`, zoom factors, or ViewBox creation.

- [ ] **Step 5: Verify GREEN and compatibility**

Run the two new tests again with `--basetemp D:\tmp\pytest-wheel-green`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ui/test_pg_line_canvas.py::test_viewport_ctrl_wheel_zooms_fft_line_canvas_x_only `
  tests/ui/test_pg_heatmap_canvas.py::test_viewport_shift_wheel_zooms_heatmap_y_only `
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSetDataHotPathContract::test_real_viewport_shift_pixel_wheel_zooms_overlay_y `
  --basetemp D:\tmp\pytest-wheel-compat
```

Expected: all cases pass, including both TimeDomain pixel-delta parameters.

- [ ] **Step 6: Prove owner state does not leak between events**

Add one test in `test_pg_line_canvas.py` that sends a pixel-only modifier event, asserts `getattr(canvas, "_raw_wheel_delta", None) is None` afterward, then sends an angle-only event of the opposite sign and verifies the angle event controls the new range change. Run that test with a new `--basetemp` and confirm it passes.

- [ ] **Step 7: Review and commit Task 1**

Run `git diff --check`, inspect only the four Task 1 files, and commit:

```powershell
git add mf4_analyzer/ui/pg_canvas/line_canvas.py `
        mf4_analyzer/ui/pg_canvas/heatmap_canvas.py `
        tests/ui/test_pg_line_canvas.py `
        tests/ui/test_pg_heatmap_canvas.py
git commit -m "fix(plot): route precision wheel events across analysis canvases"
```

### Task 2: Enforce The Coarse Refresh Interval At Timeout

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py:63,3209-3268`
- Test: `tests/ui/test_pg_timedomain_canvas.py:4768-4800`

**Interfaces:**
- Consumes: `TimeDomainCanvasPG._COARSE_REFRESH_MS`, `_last_coarse_refresh_at`, `_coarse_timer`, and the imported `monotonic` clock.
- Produces: `TimeDomainCanvasPG._remaining_coarse_refresh_ms(now=None) -> int`, returning zero when refresh is allowed and a positive upward-rounded delay when it must be deferred.

- [ ] **Step 1: Add deterministic RED tests for the desired helper and timeout behavior**

Add tests under `TestTimeDomainCanvasPGSetDataHotPathContract`:

```python
def test_coarse_refresh_remaining_delay_rounds_up(self, qapp, monkeypatch):
    canvas, _pdi = self._canvas_and_pdi(qapp)
    canvas._last_coarse_refresh_at = 10.0
    monkeypatch.setattr("mf4_analyzer.ui.pg_canvas.canvas.monotonic", lambda: 10.0991)
    assert canvas._remaining_coarse_refresh_ms() == 1

def test_early_coarse_timeout_reschedules_without_setdata(
    self, qapp, monkeypatch,
):
    from unittest.mock import patch

    canvas, pdi = self._canvas_and_pdi(qapp)
    canvas._begin_view_interaction()
    canvas._pending_coarse_xlim = (6.0, 8.0)
    canvas._last_coarse_refresh_at = 10.0
    monkeypatch.setattr("mf4_analyzer.ui.pg_canvas.canvas.monotonic", lambda: 10.050)
    with patch.object(pdi, "setData", wraps=pdi.setData) as spy:
        assert canvas._run_coarse_refresh(canvas._interaction_generation) is False
        assert spy.call_count == 0
    assert canvas._pending_coarse_xlim == pytest.approx((6.0, 8.0))
    assert canvas._coarse_timer.isActive()
    assert canvas._coarse_timer.remainingTime() > 0
```

- [ ] **Step 2: Run the two tests and verify RED**

Run both exact node IDs with `--basetemp D:\tmp\pytest-coarse-red`.

Expected: the helper is absent and the early timeout consumes the pending viewport or calls `setData()`.

- [ ] **Step 3: Implement upward-rounded scheduling and timeout recheck**

Import `ceil` from `math`. Add:

```python
def _remaining_coarse_refresh_ms(self, now=None):
    if self._last_coarse_refresh_at <= 0.0:
        return int(self._COARSE_REFRESH_MS)
    current = monotonic() if now is None else float(now)
    elapsed_ms = (current - self._last_coarse_refresh_at) * 1000.0
    remaining_ms = float(self._COARSE_REFRESH_MS) - elapsed_ms
    return 0 if remaining_ms <= 0.0 else max(1, int(ceil(remaining_ms)))
```

Use this helper in `_schedule_coarse_refresh_if_needed`. At the beginning of `_run_coarse_refresh`, after generation validation and before consuming `_pending_coarse_xlim`, perform the elapsed guard only when `_last_coarse_refresh_at > 0.0`:

```python
remaining_ms = self._remaining_coarse_refresh_ms()
if remaining_ms > 0:
    self._coarse_timer.start(remaining_ms)
    return False
```

Keep the first-frame full delay in the scheduling method. Do not clear the pending viewport on deferral.

- [ ] **Step 4: Verify deterministic GREEN**

Run the two new tests with `--basetemp D:\tmp\pytest-coarse-green`. Confirm the early callback produces zero `setData()` calls and preserves the pending viewport.

- [ ] **Step 5: Strengthen the real integration assertion**

In `test_drag_leaving_buffer_gets_rate_limited_coarse_coverage`, record `monotonic()` whenever `pdi.setData` is called during the held gesture. Assert adjacent coarse timestamps differ by at least `(canvas._COARSE_REFRESH_MS - 2) / 1000.0`. Retain the final release assertion separately so the settled frame is not treated as coarse.

Run this integration test eight times from PowerShell, each with a unique base temp, and require eight passes:

```powershell
1..8 | ForEach-Object {
  .\.venv\Scripts\python.exe -m pytest -q `
    tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSetDataHotPathContract::test_drag_leaving_buffer_gets_rate_limited_coarse_coverage `
    --basetemp ("D:\tmp\pytest-coarse-repeat-" + $_)
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

- [ ] **Step 6: Run scheduler and HDF consumer regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ui/test_timedomain_hotpath_perf.py `
  tests/ui/test_pg_timedomain_canvas.py -k "coarse or settle or interaction or buffer or resize" `
  --basetemp D:\tmp\pytest-coarse-regression
```

Expected: all selected tests pass; do not weaken a failed count or timing assertion.

- [ ] **Step 7: Review and commit Task 2**

Run `git diff --check`, inspect the Task 2 hunks, and commit only its two files:

```powershell
git add mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(plot): enforce coarse refresh interval at timeout"
```

### Task 3: Decouple Dense Overlay AA Pressure From Envelope Point Count

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/quality.py:23-41,231-283,285-428`
- Read only unless a constant export is needed: `mf4_analyzer/ui/pg_canvas/renderer.py:76-94`
- Test: `tests/ui/test_pg_timedomain_canvas.py:312-435`

**Interfaces:**
- Consumes: `renderer._SUBPLOT_DENSE_DECIMATION`, `channel_data.get(composite_key)`, `_channel_lines.composite_items()`, and `_current_pixel_width()`.
- Produces: `QualityManager._overlay_density_pressure_status() -> dict` with `blocked: bool`, `count: int`, and `labels: tuple[str, ...]`.

- [ ] **Step 1: Replace the brittle displayed-count contract with RED behavior tests**

Keep the existing bucket-cap formula test for six curves. Replace the N=2 assertion that every displayed total must exceed 7,000 with assertions that envelope output remains bounded and the AA decision comes from explicit pressure. Add:

```python
def test_dense_two_curve_overlay_blocks_native_aa_below_display_budget(self, qapp):
    canvas = self._make_overlay(qapp, 2)
    canvas._flush_pending_refresh()
    density = canvas._quality._density_status()
    pressure = canvas._quality._overlay_density_pressure_status()
    assert density["metric"] <= density["off_budget"]
    assert pressure == {
        "blocked": True,
        "count": 2,
        "labels": ("ch0", "ch1"),
    }
    assert canvas._quality._idle_aa_density_ok() is False
    status = canvas.quality_status()
    assert status["block_reason"] == "overlay-density-pressure"
```

Add tests that hide one PDI, use two 100-sample rows, and use subplot mode. In each case assert `blocked is False`. Add a composite-identity case with two same display names and different source IDs, asserting `count == 2`.

- [ ] **Step 2: Run the new AA tests and verify RED**

Run the exact new node IDs with `--basetemp D:\tmp\pytest-aa-red`.

Expected: `_overlay_density_pressure_status` does not exist and the dense two-curve case remains eligible for AA.

- [ ] **Step 3: Implement the read-only pressure status**

Import the existing ratio constant without copying its value:

```python
from .renderer import _SUBPLOT_DENSE_DECIMATION
```

Add a method that returns unblocked outside overlay mode, returns unblocked for invalid/non-positive pixel width, and otherwise walks `self._channel_lines.composite_items()`. Skip invisible PDIs. Resolve raw data with `self.channel_data.get(composite_key)`, use `len(row[1])` as the raw visible sample count, and count the curve when `sample_count / pixel_width >= _SUBPLOT_DENSE_DECIMATION`. Set `blocked` only when at least two curves qualify. Catch identity/length errors per curve and continue.

- [ ] **Step 4: Integrate the pressure decision into all native-AA gates**

In `_idle_aa_density_ok`, after the dense-discrete and Y-overflow hard gates but before displayed-point hysteresis, set `density_allowed = False` and return `False` when overlay pressure is blocked.

In `_export_aa_affordable`, return `False` for the same pressure before reading `_density_status`.

In `quality_status`, compute pressure once. Preserve dense-raster/high-raster precedence. Before the existing displayed-metric red branch, return a red state with:

```python
{
    **base,
    "state": "red",
    "render_path": "native-non-aa",
    "block_reason": "overlay-density-pressure",
    "overlay_dense_curve_count": pressure["count"],
    "tooltip": "抗锯齿未激活：叠加高密度曲线达到性能门禁",
}
```

Do not alter `density["metric"]`, envelope arrays, or renderer bucket width.

- [ ] **Step 5: Verify GREEN and export behavior**

Run all `TestOverlayBucketCap` tests and the new focused pressure tests with `--basetemp D:\tmp\pytest-aa-green`. Add an export-affordability assertion for blocked and unblocked cases, then rerun it.

- [ ] **Step 6: Run quality, dense-raster, and HDF regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ui/test_pg_timedomain_canvas.py -k "OverlayBucketCap or AutoIdleAA or quality or antialias" `
  tests/ui/test_pg_dense_raster.py `
  tests/ui/test_timedomain_hotpath_perf.py `
  --basetemp D:\tmp\pytest-aa-regression
```

Expected: all selected tests pass and envelope data assertions are unchanged except the intentionally replaced brittle `metric > 7000` contract.

- [ ] **Step 7: Review and commit Task 3**

Run `git diff --check`, inspect the Task 3 hunks, and commit:

```powershell
git add mf4_analyzer/ui/pg_canvas/quality.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(plot): gate dense overlay antialiasing by raw pressure"
```

### Task 4: Combined Verification And Lessons Gate

**Files:**
- Verify: all files changed by Tasks 1-3
- Modify only if required: `docs/lessons-learned/INDEX.md`
- Modify only if a new uncovered durable rule exists: one focused lesson file

**Interfaces:**
- Consumes: the three task commits and the acceptance criteria in the design spec.
- Produces: fresh verification evidence and a clean lessons requirement state.

- [ ] **Step 1: Run the complete affected canvas suites**

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ui/test_pg_line_canvas.py `
  tests/ui/test_pg_heatmap_canvas.py `
  tests/ui/test_pg_dense_raster.py `
  tests/ui/test_timedomain_hotpath_perf.py `
  tests/ui/test_pg_timedomain_canvas.py `
  --basetemp D:\tmp\pytest-pg-interaction-final
```

Read the full output and report the live pass/fail/skip totals. Do not replace this with earlier focused counts.

- [ ] **Step 2: Run structural checks**

```powershell
git diff --check
rg -n "pg\.GraphicsLayoutWidget\(self\)|_WheelDeltaGraphicsLayoutWidget" `
  mf4_analyzer/ui/pg_canvas/canvas.py `
  mf4_analyzer/ui/pg_canvas/line_canvas.py `
  mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
rg -n "_remaining_coarse_refresh_ms|overlay-density-pressure|_SUBPLOT_DENSE_DECIMATION" `
  mf4_analyzer/ui/pg_canvas tests/ui
```

Expected: all three production canvases use the shared wheel host; the timer and pressure seams each have production and test consumers.

- [ ] **Step 3: Inspect the aggregate diff and commit history**

Run `git status --short`, `git diff HEAD~3 --stat`, and `git log -5 --oneline`. Verify no unrelated files or user changes were included.

- [ ] **Step 4: Complete the lessons gate**

The wheel-route and timeout-time rules already have active lessons. Do not create duplicates. Run:

```powershell
.\.venv\Scripts\python.exe scripts\lessons\check.py --status
```

If Task 3 uncovers a distinct repeatable policy risk not covered by an existing lesson, require and promote one focused lesson. Otherwise clear only a requirement created during this implementation and record that the existing two lessons cover the durable risks.
