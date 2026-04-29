# Inspector Axis B Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the existing FFT Time and Order Inspector axis controls using option B: correct FFT Time axis semantics, reduce automatic-range clutter, remove spinbox steppers, and neutralize the Order background.

**Architecture:** Keep the existing `Inspector` contextual stack unchanged. Update the shared axis-row helper in `mf4_analyzer/ui/inspector_sections.py` so both FFT Time and Order use the same automatic/manual row behavior. Route FFT Time X-time limits through `MainWindow._render_fft_time` into `SpectrogramCanvas.plot_result`; keep legacy `freq_*` aliases mapped to the Y-frequency row for compatibility.

**Tech Stack:** PyQt5 widgets/QSS, Matplotlib embedded canvases, pytest/pytest-qt.

---

### Task 1: Lock The Intended UI Contracts With Failing Tests

**Files:**
- Modify: `tests/ui/test_inspector.py`
- Modify: `tests/ui/test_fft_time_canvas.py` or nearest existing canvas test file if present

- [ ] Add a test asserting `FFTTimeContextual` axis row labels include `时间 (X)` and `频率 (Y)`.
- [ ] Add a test asserting `ctx.chk_freq_auto is ctx.chk_y_auto`, `spin_freq_min is spin_y_min`, and `spin_freq_max is spin_y_max`.
- [ ] Add a test asserting automatic rows show a summary label and hide min/max spin boxes; toggling auto off reveals enabled spin boxes.
- [ ] Add a test asserting Inspector/contextual spin boxes use `QAbstractSpinBox.NoButtons`.
- [ ] Add a canvas test asserting `SpectrogramCanvas.plot_result(..., x_auto=False, x_min=1, x_max=2)` applies `set_xlim(1, 2)`.
- [ ] Add a QSS test asserting `QWidget#orderContextual` no longer uses the old tinted background `#fff5e8`.
- [ ] Run the targeted tests and confirm the new tests fail for the expected reasons.

### Task 2: Update Shared Axis Row Construction

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] Import `QAbstractSpinBox`.
- [ ] Add a helper to set all inspector `QSpinBox` / `QDoubleSpinBox` widgets to `NoButtons`.
- [ ] Update `_build_axis_row` to store row label widgets and create per-row summary labels.
- [ ] Update `_sync_axis_enabled` for `OrderContextual` and `FFTTimeContextual` so auto state hides spin boxes and shows summaries; manual state shows enabled spin boxes and hides summaries.
- [ ] Keep combo boxes unchanged so color map and unit dropdown arrows remain visible.

### Task 3: Correct FFT Time Axis Semantics

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `mf4_analyzer/ui/canvases.py`

- [ ] Change FFT Time axis group labels/defaults to `X 时间`, `Y 频率`, `色阶`.
- [ ] Repoint `chk_freq_auto`, `spin_freq_min`, and `spin_freq_max` aliases to the Y-frequency row.
- [ ] Update `get_params`, `_collect_preset`, and `_apply_preset` so legacy `freq_*` keys read/write Y-frequency controls.
- [ ] Preserve `x_auto/x_min/x_max` as real time-axis display controls.
- [ ] Extend `SpectrogramCanvas.plot_result` to accept `x_auto/x_min/x_max` and apply manual `set_xlim` after rendering.
- [ ] Pass FFT Time X controls from `MainWindow._render_fft_time` into `SpectrogramCanvas.plot_result`.

### Task 4: Remove Order Contextual Tint

**Files:**
- Modify: `mf4_analyzer/ui/style.qss`

- [ ] Change `QWidget#orderContextual` to a neutral/transparent background while preserving readable borders.
- [ ] Add or retain QSS that hides spinbox steppers only where necessary if widget-level `NoButtons` is insufficient visually.

### Task 5: Verify And Review

**Files:**
- No new files expected.

- [ ] Run targeted UI tests for Inspector and FFT Time canvas behavior.
- [ ] Run the broader UI test file if feasible.
- [ ] Inspect changed code for backward compatibility with existing preset keys.
- [ ] Summarize changed files, tests run, and any residual risk.

