# Overlay Risk Warnings And Bottom Compute Progress Implementation Plan

> **For implementer:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan step-by-step.

Date: 2026-06-26
Spec: `docs/superpowers/specs/2026-06-26-overlay-risk-progress-design.md`

## Goal

Add data-aware overlay-mode risk warnings and a bottom status-bar progress indicator for expensive chart computations.

## Scope

In scope:

- Time Domain overlay risk estimation.
- Red status-bar warning for danger-level overlay selections.
- Danger confirmation dialog for user-initiated expensive overlay plots.
- Bottom status-bar progress widget.
- Indeterminate progress for Time Domain and FFT.
- Determinate progress for FFT vs Time and Order.
- Focused tests and offscreen UI screenshot verification.

Out of scope:

- Moving Time Domain or FFT to worker threads.
- Adding cancel controls to the progress widget.
- Adding user-editable threshold settings.
- Changing batch dialog progress UI.

## Architecture Summary

New files:

- `mf4_analyzer/ui/plot_risk.py`
- `mf4_analyzer/ui/compute_progress.py`
- `tests/ui/test_plot_risk.py`
- `tests/ui/test_compute_progress.py`
- `tests/ui/test_main_window_overlay_risk.py`

Modified files:

- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/main_window/_fft_mixin.py`
- `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- `mf4_analyzer/ui/main_window/_order_mixin.py`
- `mf4_analyzer/ui/analysis_worker.py` only if a token helper is needed; prefer avoiding this.
- Existing QSS file if status-bar styling is centralized there.

Primary implementation points:

- `MainWindow._on_plot_mode_changed(...)`
- `MainWindow._plot_time_on_canvas(...)`
- `MainWindow._build_time_plot_data(...)`
- `MainWindow._begin_compute_progress(...)`
- `MainWindow._update_compute_progress(...)`
- `MainWindow._finish_compute_progress(...)`
- `MainWindow._on_fft_time_progress(...)`
- new `MainWindow._on_order_progress(...)`

## Verification Commands

Run these frequently:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_plot_risk.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_compute_progress.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_overlay_risk.py -q
```

Final focused verification:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_plot_risk.py \
  tests/ui/test_compute_progress.py \
  tests/ui/test_main_window_overlay_risk.py \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_channel_axis_groups.py \
  tests/ui/test_channel_widget.py \
  -q
```

Quality gate:

```bash
git diff --check
```

## Task 1: Add Pure Overlay Risk Estimator

Files:

- Create `mf4_analyzer/ui/plot_risk.py`
- Create `tests/ui/test_plot_risk.py`

### 1.1 Write failing tests

Create `tests/ui/test_plot_risk.py` with pure tests that do not require a full `MainWindow`.

Test helper. The fake mirrors the **real** `FileData` shape: channel data lives
behind `.data` with a `.columns` collection, and `checked` items are
`(fid, ch, color)` tuples — not bare names and not a `name -> array` mapping
(`mf4_analyzer/io/file_data.py:84-85`, `mf4_analyzer/io/loader.py:591`,
`mf4_analyzer/ui/widgets/__init__.py:567`). The estimator never reads channel
arrays, so `_file` only allocates `time_array`.

```python
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from mf4_analyzer.ui.plot_risk import (
    PlotRiskLevel,
    estimate_time_overlay_risk,
)


@dataclass
class FakeFrame:
    """Stand-in for the pandas DataFrame held by FileData.data.

    The estimator only needs column membership; sample counts come from
    time_array length, so no channel arrays are stored.
    """

    columns: Sequence[str]


@dataclass
class FakeFileData:
    time_array: np.ndarray
    data: FakeFrame


def _file(length: int, *names: str) -> FakeFileData:
    t = np.linspace(0.0, 10.0, length)
    return FakeFileData(time_array=t, data=FakeFrame(columns=list(names)))


def _checked(fid: str, *names: str):
    return [(fid, name, "#1f77b4") for name in names]
```

Required tests:

```python
def test_small_overlay_is_ok():
    files = {"f": _file(100, "A", "B")}

    risk = estimate_time_overlay_risk(
        checked=_checked("f", "A", "B"),
        files=files,
        mode="overlay",
        time_range=None,
        filter_enabled=False,
        show_original=True,
        show_filtered=False,
    )

    assert risk.level is PlotRiskLevel.OK
    assert risk.channel_count == 2
    assert risk.series_count == 2
    assert risk.sample_total == 200
```

```python
def test_channel_count_can_warn():
    files = {"f": _file(100, "A", "B", "C", "D", "E")}

    risk = estimate_time_overlay_risk(
        checked=_checked("f", "A", "B", "C", "D", "E"),
        files=files,
        mode="overlay",
        time_range=None,
        filter_enabled=False,
        show_original=True,
        show_filtered=False,
    )

    assert risk.level is PlotRiskLevel.WARNING
    assert any("通道" in reason for reason in risk.reasons)
```

```python
def test_danger_sample_volume_uses_post_range_count():
    files = {"f": _file(6_000_000, "A")}

    full = estimate_time_overlay_risk(
        checked=_checked("f", "A"),
        files=files,
        mode="overlay",
        time_range=None,
        filter_enabled=False,
        show_original=True,
        show_filtered=False,
    )
    narrow = estimate_time_overlay_risk(
        checked=_checked("f", "A"),
        files=files,
        mode="overlay",
        time_range=(0.0, 0.001),
        filter_enabled=False,
        show_original=True,
        show_filtered=False,
    )

    assert full.level is PlotRiskLevel.DANGER
    assert narrow.level is PlotRiskLevel.OK
```

```python
def test_filter_companion_trace_increases_series_count():
    files = {"f": _file(100, "A", "B", "C", "D", "E", "F")}

    risk = estimate_time_overlay_risk(
        checked=_checked("f", "A", "B", "C", "D", "E", "F"),
        files=files,
        mode="overlay",
        time_range=None,
        filter_enabled=True,
        show_original=True,
        show_filtered=True,
    )

    assert risk.series_count == 12
    assert risk.level is PlotRiskLevel.DANGER
```

```python
def test_non_overlay_returns_ok_for_overlay_specific_thresholds():
    files = {"f": _file(6_000_000, "A")}

    risk = estimate_time_overlay_risk(
        checked=_checked("f", "A"),
        files=files,
        mode="subplot",
        time_range=None,
        filter_enabled=False,
        show_original=True,
        show_filtered=False,
    )

    assert risk.level is PlotRiskLevel.OK
```

Add an anti-false-green test that uses the **real** `FileData` (pandas-backed),
so a passing suite cannot hide a production no-op caused by a shape mismatch:

```python
def test_real_filedata_shape_is_supported():
    import pandas as pd

    from mf4_analyzer.io.file_data import FileData

    n = 6_000_000
    df = pd.DataFrame({"sig": np.zeros(n, dtype=np.float32)})
    fd = FileData("x.csv", df, list(df.columns), {}, fs=1000.0)
    files = {0: fd}

    risk = estimate_time_overlay_risk(
        checked=[(0, "sig", "#1f77b4")],
        files=files,
        mode="overlay",
        time_range=None,
        filter_enabled=False,
        show_original=True,
        show_filtered=False,
    )

    assert risk.level is PlotRiskLevel.DANGER
    assert risk.channel_count == 1
    assert risk.sample_total == n
```

Expected result:

```text
FAILED tests/ui/test_plot_risk.py
```

### 1.2 Implement `plot_risk.py`

Implement a pure helper with explicit constants.

Required public API:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

import numpy as np


class PlotRiskLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    DANGER = "danger"


OVERLAY_WARN_CHANNELS = 4
OVERLAY_DANGER_CHANNELS = 8
OVERLAY_WARN_SERIES = 6
OVERLAY_DANGER_SERIES = 10
OVERLAY_WARN_SAMPLES = 1_000_000
OVERLAY_DANGER_SAMPLES = 5_000_000
FILTER_WARN_SAMPLES = 750_000
FILTER_DANGER_SAMPLES = 2_000_000


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

Implementation details:

- `checked` is a sequence of `(fid, ch, ...)` tuples (only the first two items
  are read). `files` is a mapping `fid -> FileData`-like with `.data` (whose
  `.columns` lists channel names) and `.time_array`.
- For each `(fid, ch)`: skip when `files.get(fid)` is missing or
  `ch not in _file_columns(fd)`; otherwise count one channel and add the
  post-range sample count of `fd.time_array`.
- Only evaluate overlay-specific thresholds when `mode == "overlay"`; for any
  other mode return `OK` regardless of counts.
- Series count: when the *effective* filter is on, each kept channel contributes
  `(1 if show_filtered else 0) + (1 if show_original else 0)` curves (min 1);
  when the filter is off, one curve per channel.
- Use `np.searchsorted` for range counts when `time_array` is monotonic.
- Fall back to boolean masks when needed.
- Clamp range endpoints so reversed ranges are normalized.
- Do not copy channel arrays; sample count comes from time length and range mask.
- Return localized Chinese reasons, because they are shown in the UI.

Function signature:

```python
def estimate_time_overlay_risk(
    *,
    checked: Sequence[tuple],
    files: Mapping[object, object],
    mode: str,
    time_range: tuple[float, float] | None,
    filter_enabled: bool,
    show_original: bool,
    show_filtered: bool,
) -> PlotRisk:
    ...
```

Suggested helpers:

```python
def _file_columns(file_data: object) -> set[str]:
    # Real FileData stores channel data in a pandas DataFrame at `.data`;
    # membership is tested against `data.columns` (window.py:2016). Keep a
    # mapping/sequence fallback so the helper stays UI- and pandas-agnostic.
    data = getattr(file_data, "data", None)
    cols = getattr(data, "columns", None)
    if cols is not None:
        return set(cols)
    channels = getattr(file_data, "channels", None)
    if isinstance(channels, Mapping):
        return set(channels.keys())
    if isinstance(channels, (list, tuple, set)):
        return set(channels)
    return set()


def _range_count(time_array: object, time_range: tuple[float, float] | None) -> int:
    arr = np.asarray(time_array)
    if arr.size == 0:
        return 0
    if time_range is None:
        return int(arr.size)
    start, end = sorted(time_range)
    if arr.size > 1 and bool(np.all(arr[:-1] <= arr[1:])):
        left = int(np.searchsorted(arr, start, side="left"))
        right = int(np.searchsorted(arr, end, side="right"))
        return max(0, right - left)
    mask = (arr >= start) & (arr <= end)
    return int(np.count_nonzero(mask))
```

### 1.3 Verify Task 1

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_plot_risk.py -q
```

Expected result:

```text
passed
```

## Task 2: Add Status-Bar Risk Label And Overlay Prompt Flow

Files:

- Modify `mf4_analyzer/ui/main_window/window.py`
- Create `tests/ui/test_main_window_overlay_risk.py`
- Modify QSS only if status-bar object names are styled in a central stylesheet.

### 2.1 Write failing UI tests

Create `tests/ui/test_main_window_overlay_risk.py`.

Use the repository's existing `qapp`/window fixtures if available. If fixtures differ, adapt to the local test style from `tests/ui/test_main_window_smoke.py`.

Required test scenarios:

1. Warning risk shows the risk label and does not call `QMessageBox.question`.
2. Danger risk calls `QMessageBox.question`.
3. Canceling danger risk prevents `canvas.plot_channels(...)`.
4. Low-risk mode clears the risk label.

Use monkeypatching to avoid expensive real arrays:

```python
from mf4_analyzer.ui.plot_risk import PlotRisk, PlotRiskLevel


def _risk(level):
    return PlotRisk(
        level=level,
        channel_count=9 if level is PlotRiskLevel.DANGER else 5,
        series_count=9 if level is PlotRiskLevel.DANGER else 5,
        sample_total=6_000_000 if level is PlotRiskLevel.DANGER else 100,
        max_channel_samples=6_000_000 if level is PlotRiskLevel.DANGER else 100,
        filter_enabled=False,
        reasons=("测试风险",),
    )
```

Patch `estimate_time_overlay_risk` at the import site used by `window.py`.

Expected result before implementation:

```text
FAILED tests/ui/test_main_window_overlay_risk.py
```

### 2.2 Install Risk Label

In `MainWindow.__init__` after status bar setup, install a hidden risk label:

```python
def _install_plot_risk_label(self) -> None:
    self._plot_risk_label = QLabel(self)
    self._plot_risk_label.setObjectName("plotRiskLabel")
    self._plot_risk_label.setVisible(False)
    self._plot_risk_label.setMinimumWidth(0)
    self._plot_risk_label.setMaximumWidth(520)
    self._plot_risk_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    self.statusBar.addPermanentWidget(self._plot_risk_label, 0)
```

Add helpers:

```python
def _show_plot_risk(self, risk: PlotRisk) -> None:
    if not getattr(self, "_plot_risk_label", None):
        return
    if risk.level is PlotRiskLevel.OK:
        self._clear_plot_risk()
        return
    self._plot_risk_label.setProperty("riskLevel", risk.level.value)
    self._plot_risk_label.setText(self._format_plot_risk_text(risk))
    self._plot_risk_label.setToolTip("\n".join(risk.reasons))
    self._plot_risk_label.style().unpolish(self._plot_risk_label)
    self._plot_risk_label.style().polish(self._plot_risk_label)
    self._plot_risk_label.setVisible(True)


def _clear_plot_risk(self) -> None:
    if not getattr(self, "_plot_risk_label", None):
        return
    self._plot_risk_label.clear()
    self._plot_risk_label.setToolTip("")
    self._plot_risk_label.setVisible(False)
```

Formatting:

```python
def _format_plot_risk_text(self, risk: PlotRisk) -> str:
    points = self._format_count_zh(risk.sample_total, "点")
    prefix = "叠加模式"
    if risk.filter_enabled:
        prefix = "滤波 + 叠加"
    suffix = "风险较高" if risk.level is PlotRiskLevel.DANGER else "可能卡顿"
    return f"{prefix}：{risk.channel_count} 个通道 / {risk.series_count} 条曲线 / {points}，{suffix}"
```

Use an existing count formatter if one exists. If not, keep a tiny private formatter:

```python
def _format_count_zh(self, value: int, unit: str) -> str:
    if value >= 10_000_000:
        return f"{value / 10_000_000:.1f} 千万{unit}"
    if value >= 10_000:
        return f"{value / 10_000:.1f} 万{unit}"
    return f"{value} {unit}"
```

### 2.3 Estimate Risk From MainWindow State

There are no pre-existing `_selected_channel_names()` /
`_current_time_range_tuple()` / `_current_time_filter_flags()` helpers — do not
invent indirection. Read the same sources `_plot_time_on_canvas` and
`_build_time_plot_data` already use, and pass them straight through.

Add a private helper in `window.py` that takes the already-computed `checked`
list so it does not re-query selection state:

```python
def _estimate_current_time_overlay_risk(self, mode: str, checked) -> PlotRisk:
    # Range: same source as _plot_time_on_canvas (window.py:1846-1847).
    if self.inspector.top.range_enabled():
        time_range = self.inspector.top.range_values()
    else:
        time_range = None

    # Filter: same source/semantics as _build_time_plot_data
    # (window.py:1998-2006). Effective-enabled requires a real cutoff, so an
    # enabled panel with zero cutoffs does not inflate the series count.
    filter_enabled = False
    show_original = True
    show_filtered = False
    fp = getattr(self.inspector, "filter_panel", None)
    if fp is not None and fp.is_enabled():
        spec = fp.filter_spec()
        show_original, show_filtered = fp.show_original(), fp.show_filtered()
        filter_enabled = (spec.cutoff > 0) or (
            spec.cutoff_lo > 0 and spec.cutoff_hi > 0)

    return estimate_time_overlay_risk(
        checked=checked,                 # [(fid, ch, color), ...]
        files=self.files,                # OrderedDict fid -> FileData
        mode=mode,
        time_range=time_range,
        filter_enabled=filter_enabled,
        show_original=show_original,
        show_filtered=show_filtered,
    )
```

Binding rules:

- `checked` is the list already obtained via
  `self.channel_list.get_checked_channels()` in `_plot_time_on_canvas`
  (`window.py:1778`) — pass it in, do not re-query.
- Range comes from `self.inspector.top` (`window.py:1846-1847`).
- Filter comes from `self.inspector.filter_panel` (`window.py:1998-2006`); guard
  with `getattr` because the panel may be absent.
- Do not create a second model of selection/filter state.

### 2.4 Replace Count-Only Overlay Prompt

In `_plot_time_on_canvas(...)`, replace the existing `len(checked) > 5` prompt
(`window.py:1823-1830`) with risk handling. Capture the previous mode **before**
`self._last_plot_mode = mode` (`window.py:1822`) is reassigned, so an optional
restore has something to go back to. Gate the label and prompt to the primary /
user-initiated path, exactly like the prompt it replaces, so secondary canvas
redraws do not re-write or clear the label:

```python
is_primary = update_primary_ui or user_initiated
risk = self._estimate_current_time_overlay_risk(mode, checked)
if is_primary:
    if mode == "overlay":
        self._show_plot_risk(risk)
    else:
        self._clear_plot_risk()

if (
    risk.level is PlotRiskLevel.DANGER
    and is_primary
    and not self._confirm_overlay_risk(risk)
):
    self._restore_previous_time_plot_mode(prev_mode)  # best-effort; may no-op
    self.statusBar.showMessage("已取消高风险叠加绘制", 3000)
    return
```

`_emit_compute_feedback` is for compute outcomes and has no `level=` parameter
(`_analysis_mixin.py:35`); use `self.statusBar.showMessage(...)` for this plain
cancel notice, matching the existing cancel path (`window.py:1829`).

Add:

```python
def _confirm_overlay_risk(self, risk: PlotRisk) -> bool:
    body = (
        f"叠加模式将绘制 {risk.channel_count} 个通道、"
        f"{risk.series_count} 条曲线，约 {self._format_count_zh(risk.sample_total, '点')}。\n"
        "这可能导致明显卡顿。是否继续？"
    )
    if risk.filter_enabled:
        body += "\n当前还启用了滤波，会额外增加计算时间。"
    result = QMessageBox.question(
        self,
        "叠加模式数据量较大",
        body,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return result == QMessageBox.Yes
```

Restore behavior (best-effort, optional in v1):

There is no silent plot-mode setter today, and this code runs inside the replot
triggered by the `plot_mode_changed` chain (`cards -> stack -> window`), so a
naive restore re-enters `_on_plot_mode_changed` and recurses. Implement
`_restore_previous_time_plot_mode(prev_mode)` defensively:

```python
def _restore_previous_time_plot_mode(self, prev_mode) -> None:
    if not prev_mode or prev_mode == "overlay":
        return
    if getattr(self, "_restoring_plot_mode", False):
        return
    self._restoring_plot_mode = True
    try:
        self.chart_stack.set_plot_mode(prev_mode)
    finally:
        self._restoring_plot_mode = False
```

- Add an early `if getattr(self, "_restoring_plot_mode", False): return` guard at
  the top of `_on_plot_mode_changed(...)` so the restore cannot recurse.
- If wiring the guard cleanly proves fragile, **ship without restore**: make
  `_restore_previous_time_plot_mode` a no-op. The cancel still prevents the
  expensive plot, which is the safety-critical behavior; the toolbar already
  tolerates this minor inconsistency in the current count-only path. Restoration
  is not a hard acceptance criterion.

### 2.5 Update Overlay Tooltip

When risk is warning/danger, set the Time Domain overlay button tooltip to the risk summary if there is an accessible path to the active `TimeChartCard`.

If direct card access is awkward, keep this as label-only in the first implementation and leave the tooltip unchanged. Do not add brittle widget tree searches.

### 2.6 Verify Task 2

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_overlay_risk.py tests/ui/test_plot_risk.py -q
```

Expected result:

```text
passed
```

## Task 3: Add Bottom Compute Progress Widget

Files:

- Create `mf4_analyzer/ui/compute_progress.py`
- Create `tests/ui/test_compute_progress.py`
- Modify `mf4_analyzer/ui/main_window/window.py`
- Modify central QSS if needed

### 3.1 Write failing widget tests

Create `tests/ui/test_compute_progress.py`.

Required tests:

```python
def test_progress_widget_is_hidden_when_idle(qapp):
    widget = ComputeProgressWidget()
    assert not widget.isVisible()
```

```python
def test_begin_indeterminate_shows_busy_bar(qapp):
    widget = ComputeProgressWidget()

    widget.begin("时间域绘制中")

    assert widget.isVisible()
    assert widget.label.text() == "时间域绘制中"
    assert widget.bar.minimum() == 0
    assert widget.bar.maximum() == 0
```

```python
def test_update_determinate_sets_value_and_total(qapp):
    widget = ComputeProgressWidget()

    widget.begin("FFT-时间", total=100)
    widget.set_progress(25, 100)

    assert widget.isVisible()
    assert widget.bar.minimum() == 0
    assert widget.bar.maximum() == 100
    assert widget.bar.value() == 25
```

```python
def test_finish_hides_widget(qapp):
    widget = ComputeProgressWidget()

    widget.begin("阶次", total=10)
    widget.finish()

    assert not widget.isVisible()
```

Expected result before implementation:

```text
FAILED tests/ui/test_compute_progress.py
```

### 3.2 Implement Widget

Create `mf4_analyzer/ui/compute_progress.py`.

Implementation requirements:

- Subclass `QWidget`.
- Expose `label` and `bar` attributes for straightforward tests.
- Keep width bounded.
- Hide by default.
- Treat `total is None` or `total <= 0` as indeterminate.
- Clamp current into `[0, total]`.
- Name the progress-update method `set_progress`, not `update`: `QWidget.update`
  is an existing no-arg repaint method and must not be shadowed.

Implementation sketch:

```python
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QSizePolicy, QWidget


class ComputeProgressWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("computeProgressWidget")
        self.label = QLabel(self)
        self.label.setObjectName("computeProgressLabel")
        self.bar = QProgressBar(self)
        self.bar.setObjectName("computeProgressBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(160)
        self.bar.setFixedHeight(8)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setVisible(False)

    def begin(self, label: str, total: int | None = None) -> None:
        self.label.setText(label)
        if total is None or total <= 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, int(total))
            self.bar.setValue(0)
        self.setVisible(True)

    def set_progress(self, current: int, total: int, label: str | None = None) -> None:
        if label is not None:
            self.label.setText(label)
        if total <= 0:
            self.bar.setRange(0, 0)
            self.setVisible(True)
            return
        value = max(0, min(int(current), int(total)))
        self.bar.setRange(0, int(total))
        self.bar.setValue(value)
        self.setVisible(True)

    def finish(self, label: str | None = None) -> None:
        if label is not None:
            self.label.setText(label)
        self.setVisible(False)
```

### 3.3 Install In MainWindow

In `window.py`, import `ComputeProgressWidget`.

Install after the status bar is created:

```python
def _install_compute_progress(self) -> None:
    self._compute_progress = ComputeProgressWidget(self)
    self.statusBar.addPermanentWidget(self._compute_progress, 0)
    self._active_compute_progress_token = None
```

Add wrappers:

```python
def _begin_compute_progress(self, label: str, total: int | None = None, token: object | None = None) -> object:
    token = token or object()
    self._active_compute_progress_token = token
    self._compute_progress.begin(label, total)
    QApplication.processEvents()
    return token


def _update_compute_progress(
    self,
    current: int,
    total: int,
    label: str | None = None,
    token: object | None = None,
) -> None:
    if token is not None and token is not self._active_compute_progress_token:
        return
    self._compute_progress.set_progress(current, total, label)


def _finish_compute_progress(self, label: str | None = None, token: object | None = None) -> None:
    if token is not None and token is not self._active_compute_progress_token:
        return
    self._compute_progress.finish(label)
    self._active_compute_progress_token = None
```

### 3.4 Style Widget

If status bar styling lives in QSS, add object-name styles:

```css
#computeProgressWidget {
    background: transparent;
}

#computeProgressLabel {
    color: #4b5f78;
    font-size: 12px;
}

#computeProgressBar {
    border: 1px solid #c9d8ea;
    border-radius: 4px;
    background: #eef4fb;
}

#computeProgressBar::chunk {
    border-radius: 4px;
    background: #1a7be8;
}

#plotRiskLabel[riskLevel="warning"] {
    color: #b26b00;
}

#plotRiskLabel[riskLevel="danger"] {
    color: #d92d20;
    font-weight: 600;
}
```

Match nearby stylesheet naming and colors if the project already defines tokens.

### 3.5 Verify Task 3

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_compute_progress.py -q
```

Expected result:

```text
passed
```

## Task 4: Wire Indeterminate Progress For Time Domain And FFT

Files:

- Modify `mf4_analyzer/ui/main_window/window.py`
- Modify `mf4_analyzer/ui/main_window/_fft_mixin.py`
- Extend `tests/ui/test_main_window_overlay_risk.py` or add a focused progress test

### 4.1 Time Domain Progress

In `_plot_time_on_canvas(...)`, begin indeterminate progress before expensive Time Domain work:

```python
progress_token = None
if update_primary_ui or user_initiated:
    progress_token = self._begin_compute_progress("时间域绘制中")
try:
    data = self._build_time_plot_data(...)
    canvas.plot_channels(...)
finally:
    if progress_token is not None:
        self._finish_compute_progress(token=progress_token)
```

Placement requirements:

- Run overlay danger confirmation before beginning progress if confirmation itself is the only action.
- Start progress before `_build_time_plot_data(...)`.
- Finish progress on empty data, errors, and successful plot.
- Preserve existing exception handling and status messages.

Test:

- Monkeypatch `_begin_compute_progress` and `_finish_compute_progress`.
- Monkeypatch `_build_time_plot_data` and `canvas.plot_channels`.
- Assert begin happens before build and finish happens after plot.

### 4.2 FFT Progress

In `_fft_mixin.py`, wrap the synchronous FFT compute section:

```python
progress_token = self._begin_compute_progress("FFT 计算中")
try:
    # existing FFT compute and render
finally:
    self._finish_compute_progress(token=progress_token)
```

Placement requirements:

- Begin immediately before the compute path that can stall.
- Do not wrap cheap UI validation-only branches.
- Finish in every branch after begin.

Test:

- Use monkeypatch wrappers around `_begin_compute_progress` and `_finish_compute_progress`.
- Trigger the smallest existing FFT path test if one exists.
- If direct FFT setup is heavy, add a small method-level test around the internal compute entry point already used by tests.

### 4.3 Verify Task 4

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_overlay_risk.py \
  tests/ui/test_main_window_smoke.py \
  -q
```

Expected result:

```text
passed
```

## Task 5: Wire Determinate Progress For FFT vs Time

Files:

- Modify `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- Add or extend focused FFT-vs-Time UI tests

### 5.1 Add Progress State

Add lightweight state on the main window:

```python
self._fft_time_progress_token = None
self._fft_time_progress_total_jobs = 0
self._fft_time_progress_completed_jobs = 0
```

If this mixin already initializes mode-specific state in a helper, put these attributes there.

### 5.2 Begin Progress When Dispatching Jobs

Where FFT-vs-Time worker jobs are queued/dispatched (after `self._fft_time_queue`
is built, `_fft_time_mixin.py:356`). **Count only the queued (cache-miss) jobs** —
cache-hit panes render synchronously and never enter the queue
(`_fft_time_mixin.py:311-356`), so they must not inflate the job count. If the
queue is empty, do not begin progress:

```python
n_jobs = len(self._fft_time_queue)
self._fft_time_progress_token = None
self._fft_time_progress_total_jobs = n_jobs
self._fft_time_progress_completed_jobs = 0
if n_jobs > 0:
    self._fft_time_progress_token = self._begin_compute_progress(
        "FFT-时间 1/%d" % n_jobs,
        total=1000,
    )
```

Use a fixed total of `1000` for aggregated progress. This avoids changing the progress bar total as each worker reports different frame counts.

### 5.3 Implement `_on_fft_time_progress`

Replace the current no-op with:

```python
def _on_fft_time_progress(self, current: int, total: int) -> None:
    if not self._fft_time_progress_token:
        return
    total_jobs = max(1, self._fft_time_progress_total_jobs)
    job_fraction = 0.0
    if total > 0:
        job_fraction = max(0.0, min(1.0, current / total))
    overall = (self._fft_time_progress_completed_jobs + job_fraction) / total_jobs
    value = int(round(overall * 1000))
    label = f"FFT-时间 {min(self._fft_time_progress_completed_jobs + 1, total_jobs)}/{total_jobs}"
    self._update_compute_progress(value, 1000, label=label, token=self._fft_time_progress_token)
```

### 5.4 Finish On Last Job

Increment and finish in the **single per-job funnel** `_on_fft_time_thread_done`
(`_fft_time_mixin.py:741`), which fires once per job on success, failure, and
cancel — so the count is not split across the separate `_on_fft_time_finished`
(`:695`) and `_on_fft_time_failed` (`:721`) handlers and cannot double-count:

```python
if self._fft_time_progress_token is not None:
    self._fft_time_progress_completed_jobs = min(
        self._fft_time_progress_completed_jobs + 1,
        self._fft_time_progress_total_jobs,
    )
    if self._fft_time_progress_completed_jobs >= self._fft_time_progress_total_jobs:
        self._finish_compute_progress(token=self._fft_time_progress_token)
        self._fft_time_progress_token = None
```

Clamping completed jobs to total jobs guards against any duplicate termination
signal.

### 5.5 Tests

Add tests for:

- `_on_fft_time_progress(50, 100)` maps to `500` when there is one job.
- With two jobs and one completed, `_on_fft_time_progress(50, 100)` maps to `750`.
- Completion of the last job hides progress.

Use monkeypatching on `_update_compute_progress` and `_finish_compute_progress` instead of requiring full worker execution.

### 5.6 Verify Task 5

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_overlay_risk.py \
  tests/ui/test_main_window_smoke.py \
  -q
```

Add the exact FFT-vs-Time test file to this command once identified from the existing suite.

## Task 6: Wire Determinate Progress For Order

Files:

- Modify `mf4_analyzer/ui/main_window/_order_mixin.py`
- Add or extend focused Order UI tests

### 6.1 Pass Analyzer Progress Callback

Unlike FFT vs Time, Order is **not** wired for progress yet: `worker.progress` is
not connected and `progress_callback` is not passed. Both are net-new here.

The job closure at `_order_mixin.py:461-463` currently reads:

```python
def job(worker, _sig=sig, _rpm=rpm, _t=t_arr, _p=p):
    return COTOrderAnalyzer.compute(_sig, _rpm, _t, _p,
                                    cancel_token=worker.cancelled)
```

Change the compute call to pass the callback:

```python
def job(worker, _sig=sig, _rpm=rpm, _t=t_arr, _p=p):
    return COTOrderAnalyzer.compute(
        _sig, _rpm, _t, _p,
        progress_callback=worker.progress.emit,
        cancel_token=worker.cancelled,
    )
```

And add `worker.progress.connect(self._on_order_progress)` at the point each
Order worker is created/started (the same place the worker's other signals are
connected), before it starts.

### 6.2 Add Order Progress State

Use the same aggregation pattern as FFT vs Time:

```python
self._order_progress_token = None
self._order_progress_total_jobs = 0
self._order_progress_completed_jobs = 0
```

Begin progress when jobs are queued, counting only the queued (cache-miss) jobs
(`self._order_queue`, `_order_mixin.py:352`) and skipping when the queue is empty:

```python
n_jobs = len(self._order_queue)
self._order_progress_token = None
self._order_progress_total_jobs = n_jobs
self._order_progress_completed_jobs = 0
if n_jobs > 0:
    self._order_progress_token = self._begin_compute_progress(
        "阶次 1/%d" % n_jobs, total=1000)
```

### 6.3 Implement `_on_order_progress`

```python
def _on_order_progress(self, current: int, total: int) -> None:
    if not self._order_progress_token:
        return
    total_jobs = max(1, self._order_progress_total_jobs)
    job_fraction = 0.0
    if total > 0:
        job_fraction = max(0.0, min(1.0, current / total))
    overall = (self._order_progress_completed_jobs + job_fraction) / total_jobs
    value = int(round(overall * 1000))
    label = f"阶次 {min(self._order_progress_completed_jobs + 1, total_jobs)}/{total_jobs}"
    self._update_compute_progress(value, 1000, label=label, token=self._order_progress_token)
```

### 6.4 Finish On Last Job

Increment and finish in the single per-job funnel `_on_order_thread_done`
(`_order_mixin.py:655`), which fires once per job on success, failure, and cancel
(not split across `_on_order_finished` `:612` / `_on_order_failed` `:635`):

```python
if self._order_progress_token is not None:
    self._order_progress_completed_jobs = min(
        self._order_progress_completed_jobs + 1,
        self._order_progress_total_jobs,
    )
    if self._order_progress_completed_jobs >= self._order_progress_total_jobs:
        self._finish_compute_progress(token=self._order_progress_token)
        self._order_progress_token = None
```

### 6.5 Tests

Add tests for:

- `_on_order_progress(25, 100)` maps to `250` for one job.
- Two-job aggregation maps first half of second job to `750`.
- Order dispatch passes a non-`None` `progress_callback` to `COTOrderAnalyzer.compute`.
- Final completion hides progress.

For the callback-passing test, monkeypatch `COTOrderAnalyzer.compute`:

```python
def fake_compute(*args, progress_callback=None, cancel_token=None, **kwargs):
    assert progress_callback is not None
    progress_callback(1, 2)
    return fake_result
```

### 6.6 Verify Task 6

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_overlay_risk.py \
  tests/ui/test_main_window_smoke.py \
  -q
```

Add the exact Order test file to this command once identified from the existing suite.

## Task 7: Visual Verification Screenshots

Files:

- Prefer adding a tiny reusable screenshot probe under an existing test/helper location if the repository already has one.
- If no screenshot helper exists, use a short local script under `.state/` and do not commit it.

### 7.1 Capture Warning And Danger Label

Create a controlled `MainWindow` state with patched risk estimator:

- Warning risk: `PlotRiskLevel.WARNING`
- Danger risk: `PlotRiskLevel.DANGER`

Render offscreen and capture the status-bar area.

Success criteria:

- Warning text is visible.
- Danger text is visible and red.
- Text is not clipped by help/update buttons.
- The status bar height does not jump.

### 7.2 Capture Progress Widget

Use:

```python
window._begin_compute_progress("时间域绘制中")
```

and:

```python
window._begin_compute_progress("FFT-时间 1/2", total=1000)
window._update_compute_progress(500, 1000, label="FFT-时间 1/2")
```

Capture status-bar screenshots.

Success criteria:

- Indeterminate progress bar is visible.
- Determinate progress bar is visible.
- Label text fits at desktop width.
- Help/update buttons remain reachable and not overlapped.

### 7.3 Show Screenshots To User

When implementation is complete, provide Markdown image links with absolute paths:

```markdown
![overlay danger status](/absolute/path/to/overlay-danger.png)
![compute progress](/absolute/path/to/compute-progress.png)
```

## Task 8: Full Focused Verification

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_plot_risk.py \
  tests/ui/test_compute_progress.py \
  tests/ui/test_main_window_overlay_risk.py \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_channel_axis_groups.py \
  tests/ui/test_channel_widget.py \
  -q
```

Run any existing FFT-vs-Time and Order focused tests discovered during Tasks 5 and 6.

Run:

```bash
git diff --check
```

Expected result:

```text
no whitespace errors
focused tests passed
```

## Task 9: Commit Hygiene

Before committing:

```bash
git status --short --branch
git diff --stat
git diff -- docs/superpowers/specs/2026-06-26-overlay-risk-progress-design.md docs/superpowers/plans/2026-06-26-overlay-risk-progress.md
```

Stage only files related to this change.

Commit message:

```text
docs: plan overlay risk warnings and compute progress
```

If implementation is included in the same branch later, use a separate implementation commit such as:

```text
feat: add overlay risk warnings and compute progress
```

## Rollback Plan

If implementation causes UI instability:

- Disable danger confirmation by returning `True` from `_confirm_overlay_risk(...)`.
- Keep the risk label hidden by making `_show_plot_risk(...)` call `_clear_plot_risk()`.
- Keep progress widget installed but hidden by making `_begin_compute_progress(...)` return a token without showing the widget.
- The pure risk helper can remain because it has no side effects.

These are code rollback levers for implementation. They are not part of the default path.

## Open Implementation Notes

- There are no ready-made selection/range/filter getters; read the same sources
  `_plot_time_on_canvas` / `_build_time_plot_data` already use
  (`channel_list.get_checked_channels()`, `inspector.top`, `inspector.filter_panel`)
  and pass `checked` through rather than re-querying or modeling state twice.
- Restoring the previous plot mode on danger-cancel is best-effort: use a
  `_restoring_plot_mode` re-entrancy guard, or ship as a no-op. It is not a hard
  acceptance criterion.
- Keep the risk estimator independent from Qt imports, and feed it the real
  `(fid, ch)` tuples + `FileData` (`.data.columns`, `.time_array`) — not
  mapping-style stand-ins — so green unit tests cannot mask a production no-op.
- Keep progress aggregation token-based so late worker signals cannot update a
  newer compute operation, and count only queued (cache-miss) jobs.
- Keep status-bar widgets compact; avoid moving chart content or changing existing panel layout.
