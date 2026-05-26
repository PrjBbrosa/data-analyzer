# TimeDomain State Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve TimeDomain visual state across non-semantic UI operations and keep curve styling coherent.

**Architecture:** Reuse the existing `MainWindow` xlim capture/restore helpers for compatible replots. Keep Matplotlib-specific styling updates inside the chart/dialog layer, and keep toolbar mode policy inside `TimeChartCard`.

**Tech Stack:** Python, PyQt5, Matplotlib, pytest-qt.

---

### Task 1: Regression Tests

**Files:**
- Modify: `tests/ui/test_dialogs.py`
- Modify: `tests/ui/test_canvases.py`
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `tests/ui/test_main_window_smoke.py`

- [ ] Add a dialog test that plots two TimeDomain series, opens
  `ChartOptionsDialog` for one axis, changes `edit_curve_color`, calls
  `_apply_appearance()`, and asserts the line, Y label, Y tick labels, Y spine,
  and matching inside label use the new color.

- [ ] Update the existing inside-label test so it asserts full channel names are
  present and no ellipsis is inserted.

- [ ] Update the overlay drag test so it asserts pan is active again after
  release and X limits are unchanged.

- [ ] Add MainWindow smoke coverage for `_ch_changed()` and
  `_apply_channel_edits()` preserving the visible X limit when the new plot
  extent overlaps the captured window.

- [ ] Run the focused tests and confirm the new assertions fail before
  implementation:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/ui/test_dialogs.py tests/ui/test_canvases.py::test_timedomain_subplot_long_ylabel_switches_to_inside_labels tests/ui/test_chart_stack.py::test_overlay_curve_drag_returns_to_pan_after_y_move tests/ui/test_main_window_smoke.py::test_plot_mode_toggle_preserves_xlim_overlay_to_subplot -q
```

### Task 2: Styling And Label Implementation

**Files:**
- Modify: `mf4_analyzer/ui/dialogs.py`
- Modify: `mf4_analyzer/ui/canvases.py`

- [ ] Add a helper in `ChartOptionsDialog` to synchronize Y-axis styling for
  the current line's axis.

- [ ] Update `TimeDomainCanvas._apply_inside_channel_labels()` to show full
  channel names, wrapping prefixed labels when possible instead of applying
  `_middle_ellipsis()`.

- [ ] Run the dialog and canvas focused tests.

### Task 3: X-Limit Preservation

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `tests/ui/test_main_window_smoke.py`

- [ ] Add a small wrapper around `plot_time()` that captures the current
  primary TimeDomain X limit, runs the replot, and restores the limit when the
  new extent overlaps.

- [ ] Use the wrapper from `_ch_changed()`, `_apply_channel_edits()`, and the
  TimeDomain branch of `_on_mode_changed()`.

- [ ] Do not use the wrapper for custom X-axis application, time-axis rebuild,
  file close, or empty-selection clears.

- [ ] Run the MainWindow focused tests.

### Task 4: Toolbar Mode Policy

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `tests/ui/test_chart_stack.py`

- [ ] Change overlay curve selection so it no longer leaves the toolbar in idle
  after a selection or Y drag.

- [ ] Preserve explicit zoom mode; otherwise return to pan.

- [ ] Run the ChartStack focused tests.

### Task 5: Final Verification

**Files:**
- No production edits unless failures identify a defect.

- [ ] Run the combined focused suite:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/ui/test_dialogs.py tests/ui/test_canvases.py tests/ui/test_chart_stack.py tests/ui/test_main_window_smoke.py -q
```

- [ ] Run the lessons gate and create a lesson only if a new durable project
  rule is needed.

- [ ] No git commit in this execution because the worktree already contains
  unrelated uncommitted changes.
