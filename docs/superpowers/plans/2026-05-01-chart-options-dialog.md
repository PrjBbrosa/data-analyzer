# Chart Options Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rough Matplotlib-style figure options path with an Inspector-styled Chinese `图表选项` dialog that opens from both chart double-click and toolbar button.

**Architecture:** Add a focused `ChartOptionsDialog` in `mf4_analyzer/ui/dialogs.py`, route axes selection through `mf4_analyzer/ui/_axis_interaction.py`, and expose `open_chart_options_dialog()` on each canvas class. `_ChartCard` owns the toolbar icon button and delegates to the active canvas, so multi-card routing stays local to the selected chart card.

**Tech Stack:** PyQt5 widgets, Matplotlib `Axes`, existing `CompactDoubleSpinBox`, existing `NavigationToolbar2QT`, pytest/pytest-qt.

---

## File Structure

- Modify `mf4_analyzer/ui/dialogs.py`
  - Add `ChartOptionsDialog`.
  - Keep `AxisEditDialog` available for compatibility, but stop using it for new chart-option entry points.
- Modify `mf4_analyzer/ui/_axis_interaction.py`
  - Add `target_axes_for_event(fig, event, margin)`.
  - Add `edit_chart_options_dialog(parent_widget, ax)`.
- Modify `mf4_analyzer/ui/canvases.py`
  - Add shared private helpers for default axes selection and dialog opening.
  - Update `TimeDomainCanvas`, `SpectrogramCanvas`, and `PlotCanvas` double-click paths to open chart options for graph-face or gutter target axes.
- Modify `mf4_analyzer/ui/chart_stack.py`
  - Add one icon-only `图表选项` toolbar button to every `_ChartCard`.
  - Button delegates to `canvas.open_chart_options_dialog()`.
- Modify `mf4_analyzer/ui/style.qss`
  - Add small styling block for `QDialog#ChartOptionsDialog`.
- Modify tests:
  - `tests/ui/test_dialogs.py`
  - `tests/ui/test_axis_interaction.py`
  - `tests/ui/test_chart_stack.py`

## Task 1: Dialog Contract

**Files:**
- Modify: `tests/ui/test_dialogs.py`
- Modify: `mf4_analyzer/ui/dialogs.py`

- [x] **Step 1: Write failing dialog tests**

Add tests asserting that `ChartOptionsDialog` reads an axes title, X/Y labels,
limits and scales; exposes Chinese labels; applies changed values; and reset
restores initial field values.

- [x] **Step 2: Run red test**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py -q -k chart_options
```

Expected: FAIL because `ChartOptionsDialog` does not exist.

- [x] **Step 3: Implement `ChartOptionsDialog`**

Implement a QDialog with object name `ChartOptionsDialog`, Chinese labels,
`CompactDoubleSpinBox` range fields, scale combos (`线性` / `对数`), grid and
legend checkboxes, and `重置 / 取消 / 应用 / 确定` buttons.

- [x] **Step 4: Run green dialog test**

Run the same command and expect PASS.

## Task 2: Axes Targeting and Canvas Double-Click

**Files:**
- Modify: `tests/ui/test_axis_interaction.py`
- Modify: `mf4_analyzer/ui/_axis_interaction.py`
- Modify: `mf4_analyzer/ui/canvases.py`

- [x] **Step 1: Write failing targeting tests**

Add tests for:

- Double-click inside a `PlotCanvas` axes calls `edit_chart_options_dialog`
  with `event.inaxes`.
- Double-click inside `SpectrogramCanvas._ax_slice` targets the slice axes,
  not the main spectrogram axes.

- [x] **Step 2: Run red targeting tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_axis_interaction.py -q -k "chart_options or dblclick"
```

Expected: new chart-options tests FAIL because current code only opens the old
axis dialog on gutter hit.

- [x] **Step 3: Implement targeting helper and canvas hooks**

Add:

- `target_axes_for_event(fig, event, margin)`
- `edit_chart_options_dialog(parent_widget, ax)`
- per-canvas `open_chart_options_dialog(ax=None)`
- per-canvas double-click logic that resolves `event.inaxes` first, then
  gutter hit via `find_axis_for_dblclick`.

- [x] **Step 4: Run green targeting tests**

Run the same command and expect PASS.

## Task 3: Toolbar Entry

**Files:**
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `mf4_analyzer/ui/style.qss`

- [x] **Step 1: Write failing toolbar tests**

Add tests asserting each chart card owns `_options_btn` with tooltip
`图表选项`, and clicking it calls the current canvas `open_chart_options_dialog()`.

- [x] **Step 2: Run red toolbar tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q -k chart_options
```

Expected: FAIL because `_options_btn` is not installed.

- [x] **Step 3: Implement toolbar button**

Add an icon-only `QToolButton` near copy/save controls with tooltip `图表选项`,
object name `chartOptionsButton`, and connect it to `canvas.open_chart_options_dialog`.

- [x] **Step 4: Run green toolbar tests**

Run the same command and expect PASS.

## Task 4: Focused Regression Suite and Review

**Files:**
- Create: `docs/code-reviews/2026-05-01-chart-options-dialog-review.md`

- [x] **Step 1: Run focused suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_dialogs.py \
  tests/ui/test_axis_interaction.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_canvases.py \
  tests/ui/test_inspector.py -q
```

Expected: PASS, with only pre-existing DejaVu Sans CJK glyph warnings if any.

- [x] **Step 2: Run static checks**

Run:

```bash
git diff --check -- \
  mf4_analyzer/ui/dialogs.py \
  mf4_analyzer/ui/_axis_interaction.py \
  mf4_analyzer/ui/canvases.py \
  mf4_analyzer/ui/chart_stack.py \
  mf4_analyzer/ui/style.qss \
  tests/ui/test_dialogs.py \
  tests/ui/test_axis_interaction.py \
  tests/ui/test_chart_stack.py
```

Expected: no output.

- [x] **Step 3: Write review report**

Create `docs/code-reviews/2026-05-01-chart-options-dialog-review.md` with:

- Verdict
- Scope reviewed
- Findings, ordered by severity
- Evidence with exact file:line references
- Tests run
- Residual risks

- [x] **Step 4: Lessons gate**

Run:

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

If `lesson_required: True`, promote a lesson before final response.
