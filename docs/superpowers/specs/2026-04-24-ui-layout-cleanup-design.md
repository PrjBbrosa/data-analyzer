# UI Layout Cleanup — Design Spec

**Date:** 2026-04-24
**Author:** collaborative brainstorm with user
**Scope:** Fix a regression, relocate two control groups, slim the top
toolbar and the splitter handle, and make tight-layout the default for all
matplotlib figures.

## 1. Problems to Solve

Observed from screenshots and user testing:

1. **Regression — time-domain canvas blanks after switching FFT → time.**
   The plot is torn down and redrawn while `QStackedWidget` has not yet
   finished laying out the newly-visible canvas, so the drawn frame is
   lost.
2. **Top toolbar is too tall.** Current margins (10, 7, 10, 7) + button
   padding eat vertical space that should belong to the chart.
3. **"绘图模式" and "游标" groups sit in the Inspector** and burn
   right-pane space even though they are chart-level controls.
4. **"刻度" group is collapsible via a checkbox.** User wants the tick
   controls always visible and active by default — no checkbox to flip.
5. **Matplotlib subplot-config button exposes a Borders/Spacings dialog.**
   User wants `tight_layout` to be the default, and this dialog to
   disappear.
6. **Inspector↔Chart splitter handle is too wide.** User wants a narrower
   handle that still remains visible as a drag affordance.
7. **Cursor default is `single`.** User wants default `off`.

## 2. Non-Goals

- No new analysis features.
- No rework of FFT / Order contextual panels beyond the tick group.
- No changes to file navigator, stats strip, cursor pill, axis-lock
  popover, or rebuild-time popover.
- No changes to signal/order math.

## 3. Target Layout

### 3.1 Top toolbar (main `Toolbar`)

```
[添加文件 · 编辑通道 · 导出]   [时域 · FFT · 阶次]   [游标重置 · 轴锁定]
```

- Outer layout margins: `(10, 3, 10, 3)` (was `(10, 7, 10, 7)`).
- Button padding reduced in qss so button height does not re-inflate the
  bar.
- Segmentation (left / mode / right) unchanged.

### 3.2 Per-chart toolbar (`_ChartCard` in `chart_stack.py`)

Time-domain chart only:

```
[home back forward pan zoom save]  ║  [Subplot · Overlay]  ║  [Off · Single · Dual]
```

- The matplotlib `NavigationToolbar2QT` "Configure subplots" button is
  removed (since tight_layout is the new default).
- A `QFrame.VLine` separator sits between the native button group, the
  plot-mode group, and the cursor-mode group.
- Cursor mode default: **Off**.
- FFT and Order cards keep the bare native toolbar — the Subplot/Overlay
  and cursor controls do not appear there (time-domain specific).

### 3.3 Inspector (`inspector_sections.py`)

**Removed from `TimeContextual`:**
- `绘图模式` GroupBox (Subplot/Overlay buttons).
- `游标` GroupBox (Off/Single/Dual buttons).

**Kept in `TimeContextual`:**
- `绘图` button (`btn_plot`) — user confirmed this stays; channel-tick
  auto-plots most of the time, but a manual replot button is still
  valuable when the user wants to force a refresh after config changes.

**PersistentTop `刻度` GroupBox:**
- Remove `setCheckable(True)` / `setChecked(False)` and the
  `_toggle_ticks` helper.
- Spin-boxes for X / Y tick count always visible, default 10 / 6.

No changes to `FFTContextual` / `OrderContextual`.

### 3.4 Splitter

```python
splitter.setHandleWidth(3)  # was the default ~5-7 px
```

Plus a subtle qss rule on the splitter handle so it remains visible
(light gray) — a visible drag affordance but not visually heavy.

## 4. Signal / Slot Re-wiring

### 4.1 New owner of plot-mode and cursor-mode

The two enums now live on a new widget inside the time-domain chart card.
Option chosen: **promote `_ChartCard` for the time canvas to a named
subclass `TimeChartCard`** that inherits the native nav toolbar layout
and appends the two segmented groups.

`TimeChartCard` public interface:

```python
class TimeChartCard(_ChartCard):
    plot_mode_changed = pyqtSignal(str)    # 'subplot' | 'overlay'
    cursor_mode_changed = pyqtSignal(str)  # 'off' | 'single' | 'dual'

    def plot_mode(self) -> str: ...
    def set_plot_mode(self, mode: str) -> None: ...
    def cursor_mode(self) -> str: ...
    def set_cursor_mode(self, mode: str) -> None: ...
```

### 4.2 `ChartStack` relays

`ChartStack` exposes `plot_mode_changed` and `cursor_mode_changed`
signals that forward from its owned `TimeChartCard`. Also exposes
`plot_mode()` / `cursor_mode()` getters so `MainWindow` can query
current state when plotting.

### 4.3 `MainWindow._connect` diff (conceptual)

Before:
```python
self.inspector.plot_mode_changed.connect(self._on_plot_mode_changed)
self.inspector.cursor_mode_changed.connect(self._on_cursor_mode_changed)
```

After:
```python
self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)
self.chart_stack.cursor_mode_changed.connect(self._on_cursor_mode_changed)
```

And in `plot_time()`:

Before:
```python
mode = self.inspector.time_ctx.plot_mode()
```

After:
```python
mode = self.chart_stack.plot_mode()
```

### 4.4 Inspector cleanup

- `TimeContextual.plot_mode_changed`, `cursor_mode_changed` signals:
  **deleted**.
- `TimeContextual.set_cursor_mode` / `set_plot_mode` / `cursor_mode` /
  `plot_mode`: **deleted**.
- `Inspector.plot_mode_changed`, `cursor_mode_changed`: **deleted**.
- `_reset_plot_state` called `self.inspector.time_ctx.set_cursor_mode('single')`
  to reset cursor on file close — rewrite to
  `self.chart_stack.set_cursor_mode('off')`.

## 5. Regression Fix

`MainWindow._on_mode_changed`:

```python
def _on_mode_changed(self, mode):
    self.chart_stack.set_mode(mode)
    self.inspector.set_mode(mode)
    self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
    if mode == 'time' and self.files and self.navigator.get_checked_channels():
        QTimer.singleShot(0, self.plot_time)  # was: self.plot_time()
```

Root cause: when `QStackedWidget.setCurrentIndex` swaps to the time
card, the canvas has not yet received the resize/show events. Calling
`canvas.draw()` in the same tick paints onto a stale backing store
that is discarded once Qt lays the widget out. Deferring by one tick
with `QTimer.singleShot(0, ...)` lets the layout pass complete before
we redraw — same pattern already used in `_load_one`.

## 6. `tight_layout` Default

Targets (all in `canvases.py` or `main_window.py`):

- `TimeDomainCanvas.plot_channels` — each of the three branches currently
  calls `fig.subplots_adjust(...)`. Replace with `fig.tight_layout()`.
- `MainWindow.do_fft` — replace `fig.subplots_adjust(left=0.11, right=0.98,
  top=0.91, bottom=0.09, hspace=0.42)` with `fig.tight_layout()`.
- `MainWindow.do_order_time`, `do_order_rpm`, `do_order_track` already
  use `tight_layout` — no change.

Removal of the "Configure subplots" button happens in `_ChartCard`:

```python
tb = NavigationToolbar(canvas, self)
for act in tb.actions():
    if act.text() == 'Subplots':
        tb.removeAction(act)
        break
```

(The label is backend-dependent. A fallback check against
`tb._actions['configure_subplots']` exists on Qt5Agg and is the real
lookup key; use both.)

## 7. File-by-File Changes

| File | Change |
|------|--------|
| `mf4_analyzer/ui/main_window.py` | `_on_mode_changed` uses `QTimer.singleShot(0, self.plot_time)`. `_connect` routes plot/cursor signals to `chart_stack`. `plot_time` reads plot mode from `chart_stack`. `_reset_plot_state` calls `chart_stack.set_cursor_mode('off')`. `do_fft` uses `tight_layout`. |
| `mf4_analyzer/ui/toolbar.py` | Margins 7 → 3; internal spacing tightened. |
| `mf4_analyzer/ui/chart_stack.py` | New `TimeChartCard` subclass; strip Subplots action from nav toolbar; expose `plot_mode_changed`/`cursor_mode_changed` signals and `plot_mode()`/`set_plot_mode()`/`cursor_mode()`/`set_cursor_mode()`. |
| `mf4_analyzer/ui/inspector.py` | Remove `plot_mode_changed` and `cursor_mode_changed` signals. |
| `mf4_analyzer/ui/inspector_sections.py` | `TimeContextual`: drop plot-mode and cursor GroupBoxes and related state. `PersistentTop`: remove checkable behavior from 刻度 GroupBox. |
| `mf4_analyzer/ui/canvases.py` | `plot_channels`: replace `subplots_adjust` with `tight_layout` in all three branches. |
| `MF4 Data Analyzer V1.py` (qss) | Splitter handle 3px + light color; tighter button padding in main toolbar; `.chartToolbar` styling for segmented buttons and separators inside the chart toolbar. |

## 8. UX Defaults After Change

| Control | Old default | New default |
|---------|-------------|-------------|
| 游标 (cursor mode) | single | **off** |
| 绘图模式 (plot mode) | subplot | subplot (unchanged) |
| 刻度 GroupBox | collapsed via checkbox | **always visible** |
| Figure layout | hardcoded subplots_adjust | **tight_layout** |
| Subplots config button | visible | **removed** |
| Splitter handle | ~5-7px | **3px, visible** |
| Toolbar vertical padding | 7px | **3px** |

## 9. Testing Plan

Because the app is PyQt GUI, most changes are verified by running and
interacting. Minimal automated check:

- Unit test (headless): import `mf4_analyzer.ui.chart_stack` and confirm
  `TimeChartCard` exposes the four new methods and two new signals.
- Unit test: `Inspector` no longer exposes `plot_mode_changed` or
  `cursor_mode_changed` attributes.

Manual test checklist:

1. Launch app, load an MF4; verify time-domain chart toolbar shows native
   buttons + Subplot/Overlay + Off/Single/Dual. FFT/Order toolbars do not
   show those extras.
2. Click Overlay → plot re-draws in overlay mode. Click Subplot → back to
   subplot.
3. Click Single → move mouse over canvas, cursor pill shows x/value.
   Click Off → pill disappears.
4. Switch FFT → back to 时域 → **plot is still visible** (regression
   verified).
5. Open any subplot on FFT page — no "Configure subplots" button in the
   toolbar.
6. `刻度` group shows X / Y spins without a checkbox; changing values
   updates tick density immediately.
7. Drag the splitter between Inspector and chart — handle is narrow but
   still mouse-grabbable.
8. All three figure types fill their canvas naturally (no clipped labels
   on the left; no wasted whitespace at top/bottom).

## 10. Rollout Order

Stage the work so each commit is a reviewable unit:

1. **Commit 1 — Regression fix.** Single-line change to
   `_on_mode_changed`. Verified by the FFT → time toggle test.
2. **Commit 2 — Promote controls into `TimeChartCard`.** New subclass,
   new signals, rewire `MainWindow`, delete from Inspector. Biggest
   diff.
3. **Commit 3 — 刻度 GroupBox always-on + 主工具栏变薄 + splitter 变窄.**
   Cosmetic clean-up.
4. **Commit 4 — `tight_layout` + strip Subplots button.** Touches
   `canvases.py`, `main_window.py` (do_fft), `chart_stack.py`.

Each commit runs the manual checklist subset relevant to its scope
before moving on.
