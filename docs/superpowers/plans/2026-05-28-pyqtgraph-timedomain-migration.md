# Pyqtgraph TimeDomainCanvas Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve time-domain pan/zoom performance by replacing only the TimeDomainCanvas rendering hot path while preserving current functional logic and UI.

**Architecture:** Freeze the current TimeDomainCanvas contract, introduce adapter seams for axes/dialog/toolbar, add a measured `asammdf.blocks.cutils.positions` envelope wrapper with numpy fallback, build a pyqtgraph-backed time canvas behind tests, then switch ChartStack only after parity and performance evidence. The old matplotlib TimeDomainCanvas remains until a separate cleanup approval.

**Tech Stack:** Python 3.12, PyQt5, pyqtgraph, matplotlib, numpy, asammdf, pytest, pytest-qt.

---

## Guardrails

- Do not change TimeChartCard UI labels, shortcuts, layout, hints, or workflows.
- Do not migrate FFT, Heatmap, Spectrogram, or Order canvases.
- Do not expose a user-facing feature flag or new setting.
- Do not call the migration complete without measured before/after performance.
- Do not delete the old matplotlib TimeDomainCanvas in this plan.

---

## File Map

- Modify: `requirements.txt` to add `pyqtgraph>=0.13.3`.
- Modify: `mf4_analyzer/ui/canvases.py` only for small compatibility helpers such as `reset_cursor_state()`; keep old `TimeDomainCanvas`.
- Create: `mf4_analyzer/ui/pg_canvases.py` for `TimeDomainCanvasPG`, curve-layer cache, pyqtgraph toolbar adapter, and compatibility facades.
- Create: `mf4_analyzer/ui/_axis_handle.py` for dialog/axis adapters.
- Create: `mf4_analyzer/signal/_envelope_cutils.py` for `positions_envelope`.
- Modify: `mf4_analyzer/ui/dialogs.py` to consume `AxisHandle` while keeping the same UI.
- Modify: `mf4_analyzer/ui/_axis_interaction.py` to route matplotlib and pyqtgraph axes.
- Modify: `mf4_analyzer/ui/chart_stack.py` only when switching the production time canvas; keep TimeChartCard controls unchanged.
- Modify: `mf4_analyzer/ui/main_window.py` to call `reset_cursor_state()` instead of mutating time-canvas private cursor fields.
- Create: `tests/ui/test_timedomain_canvas_contract.py`.
- Create: `tests/ui/test_axis_handle.py`.
- Create: `tests/ui/test_pg_timedomain_canvas.py`.
- Create: `tests/perf/test_timedomain_pan_perf.py`.
- Create: `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md` at the end with measurements and verification.

---

### Task 1: Baseline And Dependency Gate

**Files:**
- Modify: `requirements.txt`
- Create: `tests/perf/test_timedomain_pan_perf.py`
- Create: `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md`

- [ ] **Step 1: Add pyqtgraph dependency**

Add one line to `requirements.txt`:

```text
pyqtgraph>=0.13.3
```

- [ ] **Step 2: Verify import surface**

Run:

```bash
.venv/bin/python - <<'PY'
import importlib.util
from asammdf.blocks import cutils
print("pyqtgraph", bool(importlib.util.find_spec("pyqtgraph")))
print("positions", callable(getattr(cutils, "positions", None)))
PY
```

Expected after dependency install: both lines print truthy values. If `pyqtgraph` is still missing, install dependencies into the repo-local venv before continuing.

- [ ] **Step 3: Write baseline perf test**

Create `tests/perf/test_timedomain_pan_perf.py` with a slow-marked helper that constructs 5 channels x 100k samples, calls the current canvas `plot_channels`, then times repeated `set_xlim` plus `_flush_pending_refresh()` calls.

The test should not fail the normal suite by default. Use `@pytest.mark.slow` and skip if Qt cannot initialize offscreen.

- [ ] **Step 4: Run current baseline**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow
```

Expected: prints or records current matplotlib P50/P95. Save the values into the results report.

- [ ] **Step 5: Run current behavior baseline**

Run:

```bash
.venv/bin/python -m pytest tests/ui/test_xlim_refresh.py tests/ui/test_canvases.py tests/ui/test_axis_interaction.py -q
```

Expected: all selected tests pass before migration work begins.

---

### Task 2: Freeze Current Time-Domain Contract

**Files:**
- Create: `tests/ui/test_timedomain_canvas_contract.py`
- Modify: `mf4_analyzer/ui/canvases.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Write contract tests**

Cover:

- four signals exist on the canvas
- public methods exist
- `plot_channels` keeps `channel_data[name] == (t, sig, color, unit)`
- `get_statistics` uses raw channel data
- `plot_time` does not enable always-on span selection
- TimeChartCard labels are exactly `分屏`, `叠加`, `游标关`, `单游标`, `双游标`

- [ ] **Step 2: Add `reset_cursor_state()` to current canvas**

In `TimeDomainCanvas`, add:

```python
def reset_cursor_state(self):
    self._ax = self._bx = None
    self._placing = 'A'
    self._refresh = True
    self.draw_idle()
```

- [ ] **Step 3: Use the helper from MainWindow**

Replace direct mutation in `MainWindow._reset_cursors` with:

```python
reset = getattr(self.canvas_time, "reset_cursor_state", None)
if callable(reset):
    reset()
else:
    self.canvas_time._ax = self.canvas_time._bx = None
    self.canvas_time._placing = 'A'
    self.canvas_time._refresh = True
    self.canvas_time.draw_idle()
```

- [ ] **Step 4: Verify**

Run:

```bash
.venv/bin/python -m pytest tests/ui/test_timedomain_canvas_contract.py tests/ui/test_main_window_smoke.py -q
```

Expected: all pass.

---

### Task 3: AxisHandle Adapter Without Renderer Switch

**Files:**
- Create: `mf4_analyzer/ui/_axis_handle.py`
- Modify: `mf4_analyzer/ui/dialogs.py`
- Modify: `mf4_analyzer/ui/_axis_interaction.py`
- Create: `tests/ui/test_axis_handle.py`

- [ ] **Step 1: Write `MplAxisHandle` tests first**

Tests must prove `get_xlim`, `set_xlim`, `get_ylim`, `set_ylim`, label getters/setters, scale setters, grid, editable lines, and redraw delegation against a matplotlib axis.

- [ ] **Step 2: Implement `AxisHandle` and `MplAxisHandle`**

Keep this module small. The matplotlib implementation should delegate to the existing `Axes` methods.

- [ ] **Step 3: Refactor ChartOptionsDialog internals**

Constructor rule:

```python
if hasattr(axis_or_handle, "get_xlim") and not hasattr(axis_or_handle, "figure"):
    self.handle = axis_or_handle
else:
    self.handle = MplAxisHandle(axis_or_handle)
```

Then replace direct `self.ax.*` calls used by the dialog with `self.handle.*`. Preserve all widget creation and text.

- [ ] **Step 4: Refactor axis interaction**

Keep matplotlib hit detection working. Add a dispatch point for future pyqtgraph canvas/axis handles without changing callers.

- [ ] **Step 5: Verify**

Run:

```bash
.venv/bin/python -m pytest tests/ui/test_axis_handle.py tests/ui/test_axis_interaction.py tests/ui/test_dialog_with_handle.py -q
```

If `test_dialog_with_handle.py` does not exist yet, create it with the minimal apply/reset/log-scale cases before running.

---

### Task 4: Cutils Envelope Wrapper

**Files:**
- Create: `mf4_analyzer/signal/_envelope_cutils.py`
- Create or modify: `tests/ui/test_pg_timedomain_canvas.py`
- Create or modify: `tests/perf/test_timedomain_pan_perf.py`

- [ ] **Step 1: Write parity tests**

Compare `positions_envelope(...)` with `build_envelope(...)` for:

- empty arrays
- normal monotonic timestamps
- reversed xlim
- small arrays where fallback should be used
- non-monotonic timestamps where fallback should be used
- NaN segments
- non-contiguous views

- [ ] **Step 2: Implement wrapper**

Use the same call shape as local asammdf `trim_c`: samples, timestamps, output sample buffer, output timestamp buffer, pos buffer, steps, count, rest, dtype kind, itemsize.

Make fallback explicit:

```python
return build_envelope(t, sig, xlim=xlim, pixel_width=pixel_width, is_monotonic=is_monotonic)
```

- [ ] **Step 3: Add micro-benchmark helper**

The perf test should report `build_envelope` and `positions_envelope` timings separately before testing full canvas pan.

- [ ] **Step 4: Verify**

Run:

```bash
.venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow
```

Expected: parity tests pass; perf report records C path or explicit fallback reason.

---

### Task 5: Build Pyqtgraph TimeDomain Canvas Behind Tests

**Files:**
- Create: `mf4_analyzer/ui/pg_canvases.py`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write single-channel tests**

Cover:

- class exposes the four signals
- `plot_channels` accepts current row shape
- `channel_data` keeps raw arrays
- `axes_list`, `_channel_lines`, `_primary_xaxis_ax` compatibility surfaces exist
- `set_cursor_visible`, `set_dual_cursor_mode`, `reset_cursor_state`, `get_statistics` work

- [ ] **Step 2: Implement skeleton**

Implement `TimeDomainCanvasPG(QWidget)` or a pyqtgraph widget subclass with:

- `GraphicsLayoutWidget`
- one PlotItem/ViewBox
- compatibility axis facade
- raw `channel_data`
- no production switch

- [ ] **Step 3: Implement custom curve layer**

Add a render layer that caches range-keyed pixel-space paths and pixmaps. Do not use plain `PlotDataItem.setData` as the final pan path.

- [ ] **Step 4: Verify**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
```

Expected: pyqtgraph canvas tests pass while production still uses matplotlib.

---

### Task 6: Subplot, Overlay, Cursor, And Scroll Parity

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Add parity tests**

Cover:

- 5-channel subplot plotting
- 5-channel overlay plotting
- overlay channel select and deselect
- selected-channel Y drag
- Ctrl+wheel X zoom
- Shift+wheel Y zoom
- plain wheel Y pan
- single cursor info
- dual cursor info and detail HTML
- span compatibility method is callable but not enabled from `plot_time`
- inside label behavior equivalent to current visual rule

- [ ] **Step 2: Implement behavior**

Implement only behavior needed to satisfy the parity tests. Preserve current raw-data semantics and compatibility facades.

- [ ] **Step 3: Verify**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_canvases.py tests/ui/test_xlim_refresh.py -q
```

Expected: new pyqtgraph tests pass; existing matplotlib behavior tests still pass.

---

### Task 7: Production Switch Without UI Change

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `tests/ui/test_timedomain_canvas_contract.py`

- [ ] **Step 1: Add UI invariant tests**

Before switching, assert current labels, shortcuts, action keys, and copy-image behavior. These tests must pass against the current UI.

- [ ] **Step 2: Switch time canvas construction**

Change only the time-canvas construction/import path in `ChartStack` so `self.canvas_time` uses `TimeDomainCanvasPG`. Keep `TimeChartCard` construction and controls unchanged.

- [ ] **Step 3: Verify focused tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_timedomain_canvas_contract.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_main_window_smoke.py tests/ui/test_axis_interaction.py -q
```

Expected: all pass; no UI invariant test changed.

---

### Task 8: Final Verification And Report

**Files:**
- Create or update: `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md`

- [ ] **Step 1: Run full tests**

Run:

```bash
.venv/bin/python -m pytest tests/ -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 2: Run performance check**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow
```

Expected: report P50/P95. Target is P50 <= 8 ms and P95 <= 15 ms on the C path.

- [ ] **Step 3: Manual smoke**

Run the app and verify:

- one channel time plot
- five channel subplot
- five channel overlay
- subplot/overlay xlim preservation
- Ctrl+wheel, Shift+wheel, plain wheel
- overlay select/deselect and Y drag
- single/dual cursor pill
- ChartOptionsDialog
- copy image includes cursor pill

- [ ] **Step 4: Write results report**

The report must include:

- baseline command and numbers
- final command and numbers
- whether C path or fallback path was used
- exact verification commands
- remaining risks
- confirmation that UI controls/workflows were not intentionally changed

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md`.

Recommended execution: subagent-driven, one task at a time, with review after each task. Do not start Task 7 until Tasks 1-6 have passing evidence.
