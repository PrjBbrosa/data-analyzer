# Overlay Risk Warnings And Bottom Compute Progress Design

Date: 2026-06-26
Status: Draft for implementation
Owner: Codex

## Summary

Add two related UI safeguards for expensive chart operations:

1. In Time Domain overlay mode, estimate the post-range data volume before plotting and surface a red warning when the selected data is large enough to risk UI stalls.
2. Add a compact bottom status-bar progress indicator for expensive chart computations, with determinate progress where the compute backend already exposes progress and indeterminate busy feedback where it does not.

The first implementation keeps the chart rendering architecture intact. It adds lightweight risk estimation, UI warnings, and progress plumbing around existing compute entry points.

## Problem

Time Domain overlay mode can become slow or visually crowded when many channels or dense traces are selected. The current warning is count-only:

- `mf4_analyzer/ui/main_window/window.py` prompts only when overlay has more than five checked channels.
- It does not account for selected time range, sample counts, filtered companion traces, or filter cost.
- It does not provide the requested red large-data warning near the workflow.

Several analysis paths also do non-trivial synchronous or threaded work without visible progress in the main window:

- Time Domain builds masked channel arrays and may apply filters synchronously.
- FFT computes synchronously.
- FFT vs Time already computes in workers and emits progress, but the connected handler is currently a no-op.
- Order computation already supports progress callbacks in the analyzer, but the UI dispatch path does not pass one through.

Users currently cannot tell whether the UI is working, blocked, or safe to interrupt during those operations.

## Goals

- Warn before or during overlay plotting when selected data is likely to be expensive.
- Make the most severe overlay warning visually red.
- Preserve the existing simple overlay crowded-axis protection, but replace it with a richer risk model.
- Show a bottom status-bar progress indicator for expensive chart computations.
- Use determinate progress for FFT vs Time and Order, because those backends already expose frame progress.
- Use indeterminate busy feedback for Time Domain and FFT until those paths are moved to workers.
- Keep the implementation narrow and compatible with current PyQt widgets and tests.
- Provide focused unit/UI tests for risk estimation, warning behavior, and progress plumbing.

## Non-Goals

- Moving Time Domain plotting into a worker thread in this change.
- Moving FFT computation into a worker thread in this change.
- Adding a cancel button to the new progress widget.
- Adding user-editable threshold settings.
- Changing the batch-processing task list UI.
- Reworking pyqtgraph rendering budgets or downsampling behavior.

## Current Architecture Anchors

### Verified Data Shapes (checked against code 2026-06-26)

These were confirmed against the current tree before implementation. The risk
estimator MUST be written against these real shapes, not against simplified
stand-ins, or it will silently no-op in production while passing unit tests.

- Selected channels are **`(fid, ch, color)` tuples**, not bare names.
  `FileNavigator.get_checked_channels()` returns
  `[(fid, ch, color), ...]` (`mf4_analyzer/ui/widgets/__init__.py:560-573`,
  consumed as `for fid, ch, color in checked` in
  `mf4_analyzer/ui/main_window/window.py:2014`).
- `FileData.channels` is a **list of channel-name strings**
  (`chs = list(df.columns)` in `mf4_analyzer/io/loader.py:591,599`;
  `self.channels = chs` in `mf4_analyzer/io/file_data.py:85`). It is **not** a
  `name -> array` mapping.
- Channel **data** lives in `FileData.data`, a pandas `DataFrame`.
  Membership is tested as `ch in fd.data.columns`
  (`window.py:2016`); arrays are read as `fd.data[ch].to_numpy()`
  (`window.py:2025`). `len(fd.data) == len(fd.time_array)`.
- The loaded-file container is `MainWindow.files`, an `OrderedDict`
  keyed by `fid` with `FileData` values (`window.py:67`).
- `time_array` is the acquisition-time numpy array used for range masks even
  when a custom X axis is displayed (`window.py:2018-2032`).

Consequence: the estimator iterates the checked `(fid, ch)` pairs, looks each up
in `files[fid]`, tests presence via `fd.data.columns`, and derives per-channel
sample counts from `len(fd.time_array)` within the range. It never indexes
`FileData.channels` as a mapping and never copies channel arrays.

### Overlay Mode Entry Points

- `mf4_analyzer/ui/chart_stack/cards.py`
  - `TimeChartCard` creates `btn_subplot` and `btn_overlay`.
  - `btn_overlay.clicked.connect(lambda: self.set_plot_mode('overlay'))`.
  - `TimeChartCard.set_plot_mode()` emits `plot_mode_changed`.
- `mf4_analyzer/ui/chart_stack/stack.py`
  - `_time_card.plot_mode_changed.connect(self._on_shared_plot_mode_changed)`.
  - `ChartStack.set_plot_mode(...)` applies mode to visible cards.
  - `_on_shared_plot_mode_changed(...)` emits `plot_mode_changed`.
- `mf4_analyzer/ui/main_window/window.py`
  - `self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)`.
  - `_on_plot_mode_changed(...)` routes mode changes.
  - `plot_time(...)` and `_plot_time_on_canvas(...)` perform Time Domain plotting.
  - `_build_time_plot_data(...)` masks range and applies filters.

### Existing Overlay Prompt

`mf4_analyzer/ui/main_window/window.py` currently prompts inside `_plot_time_on_canvas(...)` when:

- `mode == 'overlay'`
- plotting is primary/user initiated
- `len(checked) > 5`

This warning should be replaced by the new risk decision, while still including channel-count crowding as one reason.

### Rendering Density Context

`mf4_analyzer/ui/pg_canvas/canvas.py` and `mf4_analyzer/ui/pg_canvas/quality.py` already contain overlay density budget logic for antialiasing. That logic acts after rendering decisions and should not be used as the only user warning. The new risk estimator runs before expensive Time Domain data preparation/rendering and uses data-volume inputs.

### Status Bar

`mf4_analyzer/ui/main_window/window.py` creates:

- `SurfaceStatusBar`
- `self.statusBar = SurfaceStatusBar(self)`
- `_install_status_hint_bar(...)`

The new progress/risk widgets should live in the status bar so they are visible across modes and do not compete with chart content.

### Compute Progress Already Available

- `mf4_analyzer/ui/analysis_worker.py`
  - `AnalysisComputeWorker.progress = pyqtSignal(int, int)`.
- `mf4_analyzer/signal/spectrogram.py`
  - `SpectrogramAnalyzer.compute(..., progress_callback=None, cancel_token=None)`.
  - Emits throttled `(current, total)` progress and a final `(total, total)`.
- `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
  - Connects `worker.progress` to `_on_fft_time_progress(...)`.
  - `_on_fft_time_progress(...)` is currently intentionally empty.
- `mf4_analyzer/signal/order_cot.py`
  - `COTOrderAnalyzer.compute(..., progress_callback=None, cancel_token=None)`.
  - Supports per-frame progress callbacks and final completion.
- `mf4_analyzer/ui/main_window/_order_mixin.py`
  - Dispatches Order worker jobs but does not currently pass `progress_callback`.

## Overlay Risk Model

### New Helper

Add a small pure helper module:

`mf4_analyzer/ui/plot_risk.py`

Suggested public shape:

```python
from dataclasses import dataclass
from enum import Enum


class PlotRiskLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    DANGER = "danger"


@dataclass(frozen=True)
class PlotRisk:
    level: PlotRiskLevel
    channel_count: int
    series_count: int
    sample_total: int
    max_channel_samples: int
    filter_enabled: bool
    reasons: tuple[str, ...]

    @property
    def is_warning(self) -> bool:
        return self.level in {PlotRiskLevel.WARNING, PlotRiskLevel.DANGER}
```

The helper should be UI-independent enough to test without creating a `QApplication`.

### Inputs

Risk estimation should use:

- Selected channels as `(fid, ch, ...)` tuples (only `fid` and `ch` are read).
- The `MainWindow.files` mapping (`fid -> FileData`).
- Current Time Domain range settings.
- Current Time Domain *effective* filter state (see below).
- Current plot mode.
- Whether filtered companion traces are shown.
- Whether original traces are shown together with filtered traces.

For each selected `(fid, ch)`: skip when `files.get(fid)` is missing or
`ch not in fd.data.columns`; otherwise count one channel and add
`len(fd.time_array)` (after the range mask) to the sample total. The estimator
counts samples from acquisition time (`FileData.time_array`) after applying the
selected time range. This matches the existing custom-X behavior: custom X can
change the displayed X values, but range filtering is still based on acquisition
time. The estimator must not allocate or copy channel arrays — sample counts
come from time-array length and the range mask only.

**Effective filter**: `filter_enabled` passed to the estimator must mirror the
plotting path, not the panel's raw enabled flag. `_build_time_plot_data`
(`window.py:2002-2006`) treats the filter as active only when
`spec.cutoff > 0` or `(spec.cutoff_lo > 0 and spec.cutoff_hi > 0)`. A panel that
is enabled with zero cutoffs produces no extra curve, so it must not inflate the
series count.

### Series Count

Base series count is the number of selected `(fid, ch)` pairs whose channel is
present in `fd.data.columns`.

When the *effective* filter is enabled:

- If filtered traces are shown, count one filtered series per selected channel.
- If original traces are also shown, count one original series per selected channel.
- If only original traces are shown, count one original series per selected channel.

This keeps warnings aligned with the actual number of curves the canvas may draw.

### Initial Thresholds

Use conservative named constants so tests can assert behavior and future tuning is localized:

```python
OVERLAY_WARN_CHANNELS = 4
OVERLAY_DANGER_CHANNELS = 8
OVERLAY_WARN_SERIES = 6
OVERLAY_DANGER_SERIES = 10
OVERLAY_WARN_SAMPLES = 1_000_000
OVERLAY_DANGER_SAMPLES = 5_000_000
FILTER_WARN_SAMPLES = 750_000
FILTER_DANGER_SAMPLES = 2_000_000
```

Risk level should be the maximum severity triggered by any reason:

- `WARNING`
  - Overlay channel count exceeds `OVERLAY_WARN_CHANNELS`.
  - Overlay drawn series exceeds `OVERLAY_WARN_SERIES`.
  - Post-range sample total exceeds `OVERLAY_WARN_SAMPLES`.
  - Filter is enabled and post-range sample total exceeds `FILTER_WARN_SAMPLES`.
- `DANGER`
  - Overlay channel count exceeds `OVERLAY_DANGER_CHANNELS`.
  - Overlay drawn series exceeds `OVERLAY_DANGER_SERIES`.
  - Post-range sample total exceeds `OVERLAY_DANGER_SAMPLES`.
  - Filter is enabled and post-range sample total exceeds `FILTER_DANGER_SAMPLES`.

The warning copy should include the actual counts so the user can make a decision.

### Warning Behavior

The risk label and the confirmation prompt apply only to **primary /
user-initiated** plots. `_plot_time_on_canvas(...)` also runs for secondary
canvases and non-user replots; mirror the existing guard
(`update_primary_ui or user_initiated`, `window.py:1823`) so the label is not
re-written by background redraws. Risk is still computed cheaply, but the
status-bar label is only shown/cleared on the primary path.

For `WARNING`:

- Do not block plotting.
- Show a status-bar risk message using warning color.
- Update overlay-button tooltip with the concise risk summary when the active
  `TimeChartCard` is reachable; otherwise leave the tooltip unchanged (no
  brittle widget-tree search).

For `DANGER`:

- Show a red status-bar risk message.
- Ask for confirmation before continuing a user-initiated overlay plot.
- If the user cancels, do not call `canvas.plot_channels(...)`. Show a status
  message and return — matching the current count-only cancel path, which also
  returns without plotting (`window.py:1828-1830`).
- Restoring the previous (non-overlay) plot mode on cancel is **best-effort and
  optional in v1**. There is no silent plot-mode setter today, and the
  confirmation runs inside the replot triggered by the `plot_mode_changed`
  signal chain (`cards -> stack -> window`), so a naive restore re-enters
  `_on_plot_mode_changed` and recurses. If restore is attempted it MUST use a
  re-entrancy guard (e.g. `self._restoring_plot_mode`) and capture the previous
  mode before `self._last_plot_mode` is reassigned. If the guard proves fragile,
  ship without restore: the toolbar already tolerates this minor inconsistency
  in the existing count-only path.
- If the user continues, perform the plot and leave the red risk label visible until the next low-risk plot or mode change.

The confirmation dialog should be reserved for danger-level risk to avoid adding friction to normal overlay use.

### Copy

Status-bar warning examples:

- `叠加模式：6 个通道 / 6 条曲线 / 120 万点，可能卡顿`
- `叠加模式：12 个通道 / 24 条曲线 / 680 万点，风险较高`
- `滤波 + 叠加：24 条曲线 / 320 万点，计算可能较慢`

Danger confirmation body:

```text
叠加模式将绘制 12 个通道、24 条曲线，约 680 万个点。
这可能导致明显卡顿。是否继续？
```

When filters contribute to the risk, append:

```text
当前还启用了滤波，会额外增加计算时间。
```

## Bottom Progress Indicator

### Widget Placement

Add a compact progress widget to `SurfaceStatusBar` as a permanent widget:

- Hidden when idle.
- Label text on the left, progress bar on the right.
- Fixed or bounded progress width so help/update buttons do not jump.
- Determinate mode with `setRange(0, total)`.
- Indeterminate mode with `setRange(0, 0)`.

The widget should not replace the existing hint/status text. It should coexist with the help/update controls.

### Suggested Helper

Add:

`mf4_analyzer/ui/compute_progress.py`

Suggested public shape:

```python
class ComputeProgressWidget(QWidget):
    def begin(self, label: str, total: int | None = None) -> None: ...
    def set_progress(self, current: int, total: int, label: str | None = None) -> None: ...
    def finish(self, label: str | None = None) -> None: ...
```

Do not name the update method `update`: `QWidget.update()` is an existing
no-arg repaint method, and shadowing it with a required-argument signature is a
trap (any no-arg `widget.update()` call would raise). Use `set_progress`.

MainWindow can wrap it with convenience methods:

```python
def _begin_compute_progress(self, label: str, total: int | None = None) -> None: ...
def _update_compute_progress(self, current: int, total: int, label: str | None = None) -> None: ...
def _finish_compute_progress(self, label: str | None = None) -> None: ...
```

These wrappers make mixin usage simple and keep tests from depending on widget internals.

### Time Domain Progress

Time Domain currently prepares data and renders synchronously:

- `_plot_time_on_canvas(...)`
- `_build_time_plot_data(...)`
- `canvas.plot_channels(...)`

Use indeterminate progress:

- Begin before `_build_time_plot_data(...)` for user-visible plots.
- Label: `时间域绘制中`
- Finish in `finally` after `canvas.plot_channels(...)` or after an early cancel/error.
- Call `QApplication.processEvents()` immediately after begin so the status bar paints before the synchronous work starts.

This does not make Time Domain cancelable or truly progressive. It gives immediate busy feedback during expensive synchronous work.

### FFT Progress

FFT currently computes synchronously in `_fft_mixin.py`.

Use indeterminate progress:

- Begin before FFT array computation.
- Label: `FFT 计算中`
- Finish in `finally`.
- Keep existing compute-feedback messages.

### FFT vs Time Progress

FFT vs Time already runs through `AnalysisComputeWorker` and `SpectrogramAnalyzer.compute(...)` with progress callbacks.

Use determinate progress:

- Begin when the worker queue is dispatched. The `worker.progress` signal is
  **already connected** to `_on_fft_time_progress(...)`
  (`_fft_time_mixin.py:583`); the handler is currently an intentional no-op
  (`_fft_time_mixin.py:729`). Implement it to update the status-bar progress.
- **Job count is the queued (cache-miss) panes, not the pane total.** Cache-hit
  panes render synchronously and are never enqueued
  (`_fft_time_mixin.py:311-356`). Use `total_jobs = len(self._fft_time_queue)`.
  If the queue is empty, do not begin progress at all.
- Jobs run sequentially (one worker at a time, advanced by
  `_on_fft_time_thread_done`). Aggregate across jobs:
  - Completed jobs count as `1.0`.
  - Current job contributes `current / total`.
  - Overall progress is `(completed_jobs + current_fraction) / total_jobs`.
- Increment `completed_jobs` and decide finish in the **single funnel**
  `_on_fft_time_thread_done` (`_fft_time_mixin.py:741`), which fires once per job
  on success, failure, and cancel — so finish/finish-detection is not duplicated
  across the separate finished/failed handlers.
- Finish when the last queued job has terminated.

Suggested label:

- `FFT-时间 1/2`
- `FFT-时间 2/2`

### Order Progress

Order computation already supports `progress_callback` in `COTOrderAnalyzer.compute(...)`.

Use determinate progress:

- Unlike FFT vs Time, Order does **not** currently connect `worker.progress` and
  does **not** pass `progress_callback`. The dispatch calls
  `COTOrderAnalyzer.compute(_sig, _rpm, _t, _p, cancel_token=worker.cancelled)`
  (`_order_mixin.py:461-463`). This change adds both: a new
  `worker.progress.connect(self._on_order_progress)` before the worker starts,
  and `progress_callback=worker.progress.emit` on the compute call.
- Job count is the queued (cache-miss) panes: `total_jobs = len(self._order_queue)`
  (`_order_mixin.py:341-352`). If the queue is empty, do not begin progress.
- Aggregate progress across queued pane jobs the same way as FFT vs Time, and
  increment/finish in the single funnel `_on_order_thread_done`
  (`_order_mixin.py:655`).
- Finish when the last queued Order job has terminated.

Suggested label:

- `阶次 1/2`
- `阶次 2/2`

## Error, Cancel, And Re-Entry Rules

- Progress must finish or hide on success, error, cancel, and early return.
  Drive finish from the single per-job funnel (`_on_*_thread_done`) so the
  cancel and failure paths are covered without duplicate finish calls.
- Danger overlay cancel must not call `canvas.plot_channels(...)`. Restoring the
  previous plot mode is best-effort (see Warning Behavior).
- If a new compute starts while progress is visible, the new compute owns the progress widget and updates the label.
- Worker completion handlers should tolerate late progress signals after completion by ignoring updates when no active token matches.
- Existing `_emit_compute_feedback(...)` messages remain; the progress widget
  adds visible duration feedback but does not replace result/error feedback.
  Note its real signature is
  `_emit_compute_feedback(outcome, *, busy=False, section_label="计算")`
  (`_analysis_mixin.py:35`) — it takes a compute *outcome*, not a free-form
  string, and has **no** `level=` parameter. For plain cancel/info status text
  use `self.statusBar.showMessage(...)` instead.

## Styling

Add QSS object names/properties rather than hard-coded palettes where practical:

- `computeProgressWidget`
- `computeProgressLabel`
- `computeProgressBar`
- `plotRiskLabel`
- `riskLevel="warning"` or `riskLevel="danger"`

Danger label should be red and readable on the current surface.

Warning label can use existing accent/warning color if available; otherwise use a muted amber/orange that does not dominate the status bar.

## Testing Strategy

### Pure Unit Tests

Add `tests/ui/test_plot_risk.py`:

- Low-risk overlay with small data returns `OK`.
- More than warning channel threshold returns `WARNING`.
- More than danger channel threshold returns `DANGER`.
- Filtered companion traces increase series count.
- Range filtering uses `FileData.time_array` and not custom X data.
- Filter-enabled sample thresholds can raise risk even with fewer channels.

### MainWindow/UI Tests

Add or extend focused UI tests:

- Danger overlay risk shows red risk label and confirmation prompt.
- Canceling danger overlay restores previous plot mode and avoids canvas plotting.
- Warning overlay risk shows status warning and does not prompt.
- Low-risk mode change clears the risk label.
- Time Domain plotting starts and finishes indeterminate progress, including error paths.

### Worker Progress Tests

Add or extend tests for:

- `_on_fft_time_progress(...)` updates the bottom progress wrapper.
- FFT-vs-Time completion hides progress after the final queued job.
- Order dispatch passes `progress_callback` to `COTOrderAnalyzer.compute(...)`.
- `_on_order_progress(...)` updates the bottom progress wrapper.
- Order completion hides progress after the final queued job.

### Visual Verification

Use offscreen Qt or Playwright-supported screenshot tooling already used in the repository to capture:

- Time Domain overlay warning in warning state.
- Time Domain overlay warning in red danger state.
- Bottom progress bar visible during an indeterminate Time Domain plot.
- Bottom progress bar visible during determinate FFT-vs-Time or Order progress.

## Implementation Risks

- Synchronous Time Domain and FFT work can still block repaints after the initial progress paint. The design calls `QApplication.processEvents()` immediately after showing the progress widget, but long synchronous sections will not animate smoothly.
- Danger confirmation must not recurse through plot-mode signals when restoring the previous mode. The implementation should use an existing silent setter if available, or guard the restore path.
- Risk estimation can add overhead if it scans full arrays repeatedly. It should use boolean masks or `searchsorted` on monotonic time arrays, and only inspect selected channels.
- Multi-pane worker aggregation needs a small active-token guard so stale worker signals do not overwrite a newer progress label.

## Acceptance Criteria

- Overlay mode still works for normal small selections with no modal prompt.
- Large overlay selections show a red status-bar warning before plotting.
- Danger-level overlay selections ask for confirmation on user-initiated plots.
- Canceling the danger prompt prevents the expensive overlay plot (does not call
  `canvas.plot_channels(...)`). Restoring the prior plot mode is best-effort.
- The estimator returns a non-OK level when fed **real** inputs: `(fid, ch, ...)`
  tuples plus `FileData`-shaped objects (`.data.columns`, `.time_array`). At
  least one test must exercise this production shape, not only mapping-style
  fakes, so a green suite cannot hide a production no-op.
- Time Domain and FFT show bottom indeterminate progress while computing.
- FFT vs Time and Order show bottom determinate progress with visible percentage movement.
- Progress hides on success, failure, cancel, and early returns.
- Focused tests for risk estimation and progress plumbing pass.
- Offscreen screenshots confirm that red warning and bottom progress bar are visible and not clipped.
