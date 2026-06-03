# Pyqtgraph TimeDomain Overlay/Toolbar Five-Fix Design

## Source And Verdict

Source: user bug report (2026-05-29, zh) against the live pyqtgraph TimeDomain
renderer (`TimeDomainCanvasPG`) on branch `plan/pyqtgraph-timedomain-migration`,
with two screenshots (overlay mode + 6-row subplot mode). Five defects, all in
the pyqtgraph canvas/toolbar **surface** (axis-label geometry, GraphicsScene
item teardown, ViewBox mouse-mode wiring, Y-extent restore, scene-pos
hit-testing). None touch DSP/raw-data/statistics paths.

Root causes were confirmed from source before this design (file:line below) and
re-reviewed by `squad-orchestrator` (no errors found; two reinforcements noted).

## Confirmed Root Causes

- **Bug 1 — overlay y-axis label overlaps tick numbers.** Overlay gives each
  channel its own Y axis (ch1 left, ch2 right, ch3+ appended right axis via
  `primary_plot.layout.addItem(axis_item, 2, 2+index)`,
  `mf4_analyzer/ui/pg_canvases.py:534-539`). Label built by
  `_compact_axis_label(name, unit, max_chars=20)` (`pg_canvases.py:664`); for
  `"[prefix] longname"` a `\n` is inserted (`canvases.py:233-235`) but pyqtgraph
  `AxisItem.setLabel` renders text as HTML and ignores `\n` → one long rotated
  label; plus `autoSIPrefix` adds `(x0.001)`. Overlay has **no** axis
  width/offset/spacing management (subplot has `_unify_subplot_left_axis_widths`
  + inside-label flip; overlay has none).

- **Bug 2 — overlay curves persist after split↔overlay switch.** Aux ViewBoxes
  are added top-level via `primary_plot.scene().addItem(aux_vb)`
  (`pg_canvases.py:545`); curves are children of aux ViewBoxes. `clear()`
  (`pg_canvases.py:804-843`) only calls `self._glw.clear()` (removes layout
  PlotItems) then sets `_overlay_aux_viewboxes=[]` **without** `scene.removeItem`
  on them, so aux VBs + their curves + ch3+ appended right `AxisItem`s leak as
  ghosts. Same scene-leak class already solved for inside-label `TextItem`s by
  `_teardown_inside_labels` (`pg_canvases.py:2294`).

- **Bug 3 — toolbar box-zoom only works on the first subplot row; overlay
  box-zoom dead.** (A) `_set_all_mouse_modes` is only called from
  `pan()`/`zoom()` (`chart_stack.py:465-491`); `plot_channels` builds **new**
  ViewBoxes (default PanMode) but the toolbar `mode` stays `'zoom'` and nobody
  re-applies RectMode after a replot/mode-switch → box-zoom silently dead while
  the button still looks active. (B) overlay: `_view_boxes()`
  (`chart_stack.py:355-365`) returns only the aux VBs (all
  `setMouseEnabled(False)`); the real mouse-capture surface is the x_master
  ViewBox, which is NOT in that list and stays PanMode → overlay box-zoom never
  works. `test_chart_stack.py:213` only proves RectMode at toggle time on fresh
  state.

- **Bug 4 — Home restores X only, Y stuck at previous step.** `home()` →
  `reset_view_to_data_extents()` (`chart_stack.py:417` / `pg_canvases.py:746-758`)
  calls `vb.autoRange()` per VB, but in the hot path the `PlotDataItem` holds
  ONLY the current-viewport envelope (`_refresh_visible_data` `setData` with
  xlim-clipped `positions_envelope`, `pg_canvases.py:1784-1800`) → autoRange
  computes Y from clipped data; `_set_xrange_to_data_union` widens X afterward
  but Y is never re-autoscaled → X global, Y stuck at last window.

- **Bug 5 — overlay blank click cannot deselect.**
  `_select_overlay_channel_from_scene_pos` (`pg_canvases.py:1070-1151`) has an
  axis-hit fallback via `_axis_handle_at_scene_pos` using
  `vb.sceneBoundingRect().contains()` (`pg_canvases.py:1479-1503`), but overlay
  aux ViewBoxes all have geometry == the primary's FULL plot rect
  (`_sync_overlay_aux_viewboxes`, `pg_canvases.py:1513-1532`), so ANY in-plot
  point is contained by every aux VB → always returns channel 1 → blank click
  never returns `None` → never deselects (`pg_canvases.py:1216-1224`). The
  existing test passes only because it clicks ABOVE the plot area (outside the
  rect).

## Goals

1. Fix all five overlay/toolbar defects in the live pyqtgraph TimeDomain
   renderer with narrow, test-first changes (one RED test per behavior).
2. Preserve the W0 contract: signals, methods, and attribute surface of
   `TimeDomainCanvasPG` unchanged.
3. Keep raw data / statistics / cursor calculations untouched.
4. Strengthen the two tests that currently pass for the wrong reason (bugs 3 and
   5) so they exercise the real failure.

## Non-Goals

- No DSP / envelope-algorithm changes.
- No rubber-band box-zoom that spans multiple subplots (per-ViewBox rubber band
  is a pyqtgraph design limit; out of scope).
- No matplotlib API reintroduction on the PG widget (cite
  `2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`).
- No pixel-perfect label typography; bug 1 targets "labels do not collide with
  ticks or adjacent axes", not a specific font metric.

## Behavioral Requirements

### R1: Overlay axis labels do not collide

In overlay mode every channel's rotated Y-axis label must be readable and must
not overlap its own tick numbers or the adjacent axis. Measures: replace the
`\n` with `<br>` (or drop the newline), ellipsize/compact long names (or move
the long identity to a top horizontal chip), disable or relocate `autoSIPrefix`,
and add overlay axis width/offset/spacing management. Acceptance is visual
(screenshot) plus a unit assertion that the overlay label string contains no raw
`\n` and that each overlay `AxisItem` reserves a non-zero width.

### R2: Mode switch leaves no ghost curves

After switching overlay→split (or split→overlay), `clear()` must remove every
aux ViewBox, its child curves, and ch3+ appended right `AxisItem`s from the
scene. Test: after an overlay build then a subplot rebuild, `scene().items()`
contains none of the prior aux ViewBoxes / their `PlotDataItem`s. Mirror
`_teardown_inside_labels`.

### R3: Box-zoom works on every subplot row and in overlay

The toolbar's current mouse mode (`pan`/`zoom`) must be re-applied to freshly
built ViewBoxes after any `plot_channels` rebuild, so a `zoom`-active toolbar
yields RectMode on all subplot rows. In overlay mode the Rect/Pan mode must
reach the x_master ViewBox (the actual mouse-capture surface). Tests assert
RectMode on all subplot VBs *after a replot* and on the overlay x_master VB.

### R4: Home restores global X and Y in one click

`reset_view_to_data_extents()` must set each axis Y range from the RAW full
`channel_data` arrays (not from the viewport-clipped `PlotDataItem`), and X to
the union of all raw time ranges. Ordering must honor
`2026-04-25-flush-after-axis-mutation-not-before.md`: set X union → flush pending
refresh → set Y from raw, with a try/finally tail flush covering all return
paths. Test: zoom into a small X+Y window, drive the envelope refresh, call
`home()`, assert both X and Y equal the global data extents.

### R5: Overlay blank in-plot click deselects

In overlay mode, a left press on genuinely blank in-plot space (no curve within
`_overlay_pick_radius_px`) must deselect (selection → `None`,
`overlay_channel_selected(None)` emitted). The ViewBox-rect axis-hit fallback
must be dropped or replaced with a real `AxisItem.sceneBoundingRect()` gutter
test, because aux ViewBox rects span the whole plot in overlay. The existing
blank-click test must be tightened to click *inside* the plot area, away from
all curves.

## Verification

Targeted gates (Windows venv):

```
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py -q
.venv\Scripts\python.exe -m pytest tests/ui/test_chart_stack.py tests/ui/test_axis_handle.py tests/ui/test_dialogs.py -q
git diff --check
```

(Equivalent bash: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest ...`.)

Live GUI gate (REQUIRED — offscreen tests for bugs 3 and 5 historically passed
for the wrong reason):

- Overlay: axis labels do not collide with ticks/adjacent axes (R1); blank
  in-plot click deselects (R5); box-zoom works (R3).
- Subplot: box-zoom rubber band works on every row, including after a replot
  (R3); Home restores both X and Y to global in one click (R4).
- Switch overlay↔split repeatedly: no ghost curves remain (R2).
