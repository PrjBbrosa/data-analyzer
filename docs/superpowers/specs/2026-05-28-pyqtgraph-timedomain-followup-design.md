# Pyqtgraph TimeDomain Followup Fixes Design

## Source And Verdict

Source report: `docs/analyzer/reviews/2026-05-28-pyqtgraph-timedomain-followup-verify.html`.

The followup report is accepted as direction, with these source-confirmed
adjustments:

- Label drift is a P0 regression. Current PG inside labels are placed once at
  data coordinates from `ViewBox.viewRange()` (`mf4_analyzer/ui/pg_canvases.py:1817-1822`),
  while the original matplotlib labels used axes coordinates
  (`mf4_analyzer/ui/canvases.py:974-977`).
- Overlay single-Y-axis behavior is a real parity gap. Current PG overlay uses
  one `PlotItem`/`ViewBox` for all channels (`mf4_analyzer/ui/pg_canvases.py:394-403`);
  original matplotlib overlay used one axis per channel via `twinx()`
  (`mf4_analyzer/ui/canvases.py:702-733`).
- Chart options has PG-dead or PG-partial controls because the dialog still
  reads `self.ax` for grid, scale, legend, and axis color sync
  (`mf4_analyzer/ui/dialogs.py:557-573`, `649-659`, `794-803`), while
  `PgAxisHandle` exposes no matplotlib `.axes` escape hatch
  (`mf4_analyzer/ui/_axis_handle.py:516-527`).
- Tick density is currently a no-op in the PG time canvas
  (`mf4_analyzer/ui/pg_canvases.py:857-862`) despite the inspector/main-window
  call chain being live (`mf4_analyzer/ui/main_window.py:458-459`, `1001-1004`).
- The old `QPainterPath`/`QPixmap` cache is now hot-path waste: visible PG
  rendering is `PlotDataItem.setData()` (`mf4_analyzer/ui/pg_canvases.py:1271`),
  but path/pixmap are still built and cached first (`mf4_analyzer/ui/pg_canvases.py:1258-1264`).
- Cursor hover currently consumes every successful `MouseMove`
  (`mf4_analyzer/ui/pg_canvases.py:952-957`), including left-button drag.
- `PgNavigationToolbar.home()` calls `autoRange()` per axis
  (`mf4_analyzer/ui/chart_stack.py:396-414`); this needs an explicit shared-X
  policy after reset.
- Custom plot titles and inside channel labels can be shown together unless the
  PG canvas enforces a single top identity label.

## Goals

1. Restore original TimeDomain behavior for subplot labels, overlay Y axes,
   chart options, tick density, cursor drag coexistence, Home reset, and visual
   readability.
2. Keep current raw data/statistics/cursor calculations unchanged.
3. Keep fixes narrow and test-first. Every behavior change gets a RED test
   before production code.
4. Preserve the already-green UI gap fixes from
   `2026-05-28-pyqtgraph-timedomain-ui-gap-fixes.md`.

## Non-Goals

- No live hardware/Windows/frozen-build validation in this task.
- No broad renderer abstraction rewrite beyond the handle methods needed by
  `ChartOptionsDialog` and PG overlay axes.
- No custom pixmap renderer. The visible render truth remains
  `positions_envelope -> PlotDataItem.setData` until a correctly transformed
  custom pyqtgraph item is designed separately.
- No pixel-perfect recreation of every matplotlib tick locator. PG tick density
  must respond to the inspector and stay stable, but exact `MaxNLocator`
  geometry is not promised.

## Behavioral Requirements

### R1: Inside Labels Stay Anchored

Subplot inside channel labels must remain visually pinned near the ViewBox
top-left after x/y pan or zoom. Tests compare the label scene position relative
to the owning `ViewBox.sceneBoundingRect()`, not the data-space `TextItem.pos()`.

### R2: Overlay Uses Independent Y Axes

Overlay mode with N visible channels must create N logical `PgAxisHandle`s and
N `ViewBox` Y ranges:

- channel 1 uses the primary `PlotItem` left axis;
- channel 2 uses the built-in right axis linked to an auxiliary `ViewBox`;
- channel 3+ use added right-side `AxisItem`s and auxiliary `ViewBox`es;
- all overlay ViewBoxes share the same X range;
- each channel's label/color and Y drag belong to its own axis.

Implementation follows the local pyqtgraph example
`.venv/lib/python3.12/site-packages/pyqtgraph/examples/MultiplePlotAxes.py`.

### R3: Chart Options Uses AxisHandle State

`ChartOptionsDialog` must not make PG controls dead because `self.ax is None`.
Renderer-agnostic handle methods must provide:

- grid initial state;
- x/y scale initial state;
- idempotent legend rebuild/toggle;
- curve color -> owning axis color sync.

Matplotlib behavior must remain compatible with the existing tests.

### R4: Tick Density Applies

`TimeDomainCanvasPG.set_tick_density(x, y)` must update current axes and be
reapplied to future axes after `plot_channels()`. Non-bottom subplot X labels
must remain hidden after density changes.

### R5: Cursor Hover Does Not Block Drag

Cursor hover may consume no-button mouse moves to update cursor lines and HTML,
but left-button moves must be allowed through so ViewBox pan/zoom drag remains
usable while cursor mode is on.

### R6: Visual And Perf Cleanup

Default PG curve widths must be readable on high-DPI screens. Overlay emphasis
widths must be raised proportionally. The visible path must avoid building
unused `QPainterPath`/`QPixmap` cache entries on refresh.

### R7: Home Keeps Shared X

Toolbar Home must reset Y ranges per axis while ending with one deterministic
shared X range across subplots and overlay axes. The policy for this repair is
the union of all live channel raw time ranges.

### R8: One Top Identity Label

In inside-label mode, applying a custom title must not display both a PlotItem
title and an inside channel label for the same subplot. The custom title wins:
the axis keeps its inside channel badge hidden while the title is non-empty.

## Verification

Targeted gates:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_axis_handle.py tests/ui/test_chart_stack.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py::test_timedomain_pan_refresh_pg_canvas -q -s
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

Visual gate:

- Render at least one subplot screenshot with long inside labels after pan/zoom.
- Render or inspect one overlay screenshot with multiple visible colored axes.

