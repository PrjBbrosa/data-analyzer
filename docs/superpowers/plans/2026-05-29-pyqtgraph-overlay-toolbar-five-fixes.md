# PyQtGraph TimeDomain Overlay/Toolbar Five-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans
> (or subagent-driven-development) to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax. ONE commit per bug fix, six tasks total (5 fixes +
> verify). All work is pure UI/PyQt — do NOT touch DSP/raw-data paths. Preserve
> the W0 contract (signals/methods/attributes of `TimeDomainCanvasPG`).

**Goal:** Fix the five overlay/toolbar defects in the live pyqtgraph TimeDomain
renderer (`TimeDomainCanvasPG`) reported 2026-05-29.

**Spec:** `docs/superpowers/specs/2026-05-29-pyqtgraph-overlay-toolbar-five-fixes-design.md`
(root causes + behavioral requirements R1–R5).

**Tech stack:** Python 3.12, PyQt5, pyqtgraph 0.14.0, pytest. Windows venv.

**Run tests with (bash):**
```
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest <target> -q
```

**Files in play:**
- `mf4_analyzer/ui/pg_canvases.py` — bugs 1, 2, 4, 5 (and the canvas side of 3).
- `mf4_analyzer/ui/chart_stack.py` — bug 3 (toolbar mouse-mode reapply).
- `tests/ui/test_pg_timedomain_canvas.py`, `tests/ui/test_chart_stack.py` — tests.

**Ordering rationale:** lowest-risk / clearest-template first (bug 2), visual
tuning last (bug 1). Bug 3 carries a runtime-confirm step.

**Lessons to honor:**
- `2026-04-25-flush-after-axis-mutation-not-before.md` → bug 4 ordering.
- `2026-04-25-matplotlib-axes-callbacks-lifecycle.md` → disconnect listeners
  before teardown / reconnect against fresh objects (bugs 2, 3).
- `2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md` → no matplotlib
  APIs on the PG widget; simulate via Qt-native events.
- `2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` → report
  `symbols_touched`, not just files.

---

## Task 1 (Bug 2): Tear down overlay aux ViewBoxes on rebuild

**Files:** Modify `mf4_analyzer/ui/pg_canvases.py`; test
`tests/ui/test_pg_timedomain_canvas.py`.

- [ ] **Step 1 — failing test.** Build overlay (≥3 channels so ch3+ append a
  right axis), capture the aux ViewBoxes, rebuild as subplot, assert none of the
  old aux ViewBoxes nor their `PlotDataItem`s remain in `canvas._glw.scene().items()`.

```python
def test_overlay_aux_viewboxes_removed_on_mode_switch(qtbot):
    import numpy as np, pyqtgraph as pg
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    canvas = TimeDomainCanvasPG(); qtbot.addWidget(canvas)
    t = np.linspace(0.0, 10.0, 2000)
    rows = [(f"ch{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid") for i in range(3)]
    canvas.plot_channels(rows, mode="overlay")
    old_aux = list(canvas._overlay_aux_viewboxes)
    assert old_aux  # sanity: overlay built aux VBs
    canvas.plot_channels(rows, mode="subplot")
    scene_items = set(canvas._glw.scene().items())
    for vb in old_aux:
        assert vb not in scene_items, "ghost aux ViewBox leaked after mode switch"
        for child in vb.allChildItems():
            assert child not in scene_items, "ghost overlay curve leaked"
```

- [ ] **Step 2 — run, expect FAIL** (old aux VBs still in scene).

- [ ] **Step 3 — implement.** Add `_teardown_overlay_aux_viewboxes()` mirroring
  `_teardown_inside_labels` (`pg_canvases.py:2294`): for each `aux_vb` in
  `_overlay_aux_viewboxes`, `scene = aux_vb.scene(); scene.removeItem(aux_vb)`
  (try/except); for each appended axis in `_overlay_aux_axes`, remove it from the
  PlotItem layout / scene (`x_master.plot_item.layout.removeItem(ax)` and/or
  `scene.removeItem(ax)`), guarded. Call it in `clear()` (`pg_canvases.py:804`)
  **before** the lines that zero `_overlay_aux_viewboxes`/`_overlay_aux_axes`
  (`pg_canvases.py:838-839`). Keep the existing
  `_disconnect_overlay_view_sync()` call. Do not zero the lists twice — let the
  new helper own them or null them right after. Note ch1/ch2 use the PlotItem's
  built-in left/right axes (removed with the PlotItem by `_glw.clear()`); only
  ch3+ appended axes + all aux VBs need explicit removal.

- [ ] **Step 4 — run, expect PASS.**

- [ ] **Step 5 — commit:** `fix(ui): tear down overlay aux viewboxes on rebuild (ghost curves)`

---

## Task 2 (Bug 5): Overlay blank in-plot click deselects

**Files:** Modify `mf4_analyzer/ui/pg_canvases.py`; tests
`tests/ui/test_pg_timedomain_canvas.py`.

- [ ] **Step 1 — failing test.** Select a channel, then press at an in-plot
  point that is inside the plot rect but far (> `_overlay_pick_radius_px`) from
  every curve sample; assert selection becomes `None` and the last emission is
  `None`. Reuse the `_overlay_canvas` / `_press` / `_viewport_point_for_data`
  helpers already in the file. Crucially the point must map INSIDE the plot rect
  (unlike `test_blank_click_deselects_and_emits_none` which clicks above it).
  Pick a data y near mid-range but an x where the curve is far in pixels, or a
  region between two sparse channels — verify the mapped viewport point is inside
  `x_master.view_box.sceneBoundingRect()`.

- [ ] **Step 2 — run, expect FAIL** (selection stays on channel 1 via the axis
  fallback; no `None` emission).

- [ ] **Step 3 — implement.** In `_select_overlay_channel_from_scene_pos`
  (`pg_canvases.py:1070-1151`) remove the ViewBox-rect axis-hit fallback: the
  `_axis_handle_at_scene_pos` baseline (`axis_name`) is meaningless in overlay
  because every aux VB rect spans the full plot. Return the nearest-curve match
  only when within `_overlay_pick_radius_px`, else `None`. If "click the axis
  gutter to select" must be preserved, gate it on the real
  `AxisItem.sceneBoundingRect()` (the y-axis item, `handle.y_axis_item()`), not
  the ViewBox rect. Leave `_handle_overlay_mouse_press` deselect branch
  (`pg_canvases.py:1216-1224`) unchanged — it already calls
  `select_overlay_channel(None)` when `name is None`.

- [ ] **Step 4 — run, expect PASS.** Also re-run the existing
  `test_blank_click_deselects_and_emits_none` and tighten it to click an in-plot
  blank point (it previously clicked outside the rect).

- [ ] **Step 5 — commit:** `fix(ui): overlay blank in-plot click deselects curve`

---

## Task 3 (Bug 4): Home restores global X and Y in one click

**Files:** Modify `mf4_analyzer/ui/pg_canvases.py`
(`reset_view_to_data_extents`); test `tests/ui/test_chart_stack.py` (and/or
`test_pg_timedomain_canvas.py`).

- [ ] **Step 1 — failing test.** Build subplot, drive a real envelope refresh on
  a zoomed window so each `PlotDataItem` holds only the clipped envelope (set a
  narrow xlim + `_flush_pending_refresh()`), then also set a narrow ylim, then
  call the toolbar `home()` (or `reset_view_to_data_extents()`), then assert each
  axis Y range ≈ that channel's RAW full min/max (with pyqtgraph default Y
  padding tolerance) and X ≈ the raw union. The key is that Y must come from raw
  data, not the clipped envelope.

```python
# sketch — adapt to existing helpers in test_chart_stack.py
cs.canvas_time.plot_channels(rows, mode="subplot")
h = cs.canvas_time.axes_list[0]
h.set_xlim(4.0, 4.5); cs.canvas_time._flush_pending_refresh()
h.set_ylim(0.0, 0.01)                     # tiny window, far from data extents
cs._time_card.toolbar.home()
raw_t, raw_s, *_ = cs.canvas_time.channel_data[name0]
ylo, yhi = h.get_ylim()
assert ylo <= float(raw_s.min()) and yhi >= float(raw_s.max())
```

- [ ] **Step 2 — run, expect FAIL** (Y stuck near the clipped window).

- [ ] **Step 3 — implement.** Rewrite `reset_view_to_data_extents`
  (`pg_canvases.py:746-758`): (1) set X on all handles to `_data_x_union()`
  first; (2) `_flush_pending_refresh()` so the envelope repopulates for the
  global window (honors `flush-after-axis-mutation-not-before`); (3) for each
  channel, compute Y min/max from the RAW `channel_data` array (full, finite
  only) and `set_ylim` on its handle — do NOT call `vb.autoRange()`. In overlay
  mode, Y is per-channel (each on its own aux handle); in subplot/single mode,
  one channel per handle. Wrap the body so a tail `_flush_pending_refresh()` runs
  via try/finally. Keep `_set_xrange_to_data_union` for the X step (it already
  seeds the x_master too). Verify the existing
  `test_pg_toolbar_home_keeps_subplot_x_ranges_identical_after_auto_range`
  (`test_chart_stack.py:253`) still passes.

- [ ] **Step 4 — run, expect PASS.**

- [ ] **Step 5 — commit:** `fix(ui): home restores global X and Y from raw data`

---

## Task 4 (Bug 3): Box-zoom works on every subplot row + overlay

**Files:** Modify `mf4_analyzer/ui/chart_stack.py` (and possibly
`pg_canvases.py` for an overlay VB accessor); tests `tests/ui/test_chart_stack.py`.

- [ ] **Step 0 — runtime confirm (REQUIRED before coding).** Reproduce the
  "only first row" symptom. Strong hypothesis: after a `plot_channels` rebuild
  the toolbar still shows `zoom` but the new ViewBoxes are PanMode because
  `_set_all_mouse_modes` is only called from `pan()`/`zoom()`
  (`chart_stack.py:465-491`). Confirm whether a replot drops RectMode; note the
  finding in the work report.

- [ ] **Step 1 — failing test(s).**
  - Subplot: toggle `zoom`, then `plot_channels(...)` again (replot), assert all
    subplot ViewBoxes are `pg.ViewBox.RectMode` (extends `test_chart_stack.py:213`
    to cover the post-replot reapply).
  - Overlay: toggle `zoom`, assert the x_master ViewBox
    (`canvas._x_master_handle.view_box`) is `RectMode` (currently it stays
    PanMode because `_view_boxes()` excludes it).

- [ ] **Step 2 — run, expect FAIL.**

- [ ] **Step 3 — implement.**
  - Reapply mouse mode after rebuild: have `_ChartCard`/canvas re-invoke the
    toolbar's current mode on the fresh ViewBoxes. Cleanest: add a small
    `apply_current_mouse_mode()` on `PgNavigationToolbar` that calls
    `_set_all_mouse_modes(RectMode if self.mode=='zoom' else PanMode)`, and call
    it at the end of `plot_channels` (via a canvas hook the card connects) or
    from the card after it triggers a replot. Keep it idempotent and guarded.
  - Overlay x_master: make `_view_boxes()` include the x_master ViewBox in
    overlay mode (e.g. append `canvas._x_master_handle.view_box` when present),
    so Rect/Pan reaches the actual mouse-capture surface. The aux VBs stay
    mouse-disabled by design.

- [ ] **Step 4 — run, expect PASS.**

- [ ] **Step 5 — commit:** `fix(ui): reapply toolbar zoom mode after replot and to overlay x-master`

---

## Task 5 (Bug 1): Overlay axis labels do not collide with ticks

**Files:** Modify `mf4_analyzer/ui/pg_canvases.py`
(`_bind_channel` label path + overlay axis setup); test
`tests/ui/test_pg_timedomain_canvas.py`. This is visual tuning — iterate with a
screenshot; keep the unit assertions minimal and robust.

- [ ] **Step 1 — failing test.** Assert the overlay label string set on an axis
  contains no raw `\n` (pyqtgraph ignores it → long unbroken label), and that
  each overlay `AxisItem` reserves a non-zero width. e.g. build overlay with a
  long prefixed name, read `handle.get_ylabel()` / the axis `labelText`, assert
  `"\n" not in label`.

- [ ] **Step 2 — run, expect FAIL** (label currently carries `\n`).

- [ ] **Step 3 — implement.** In `_bind_channel` (`pg_canvases.py:611-674`) for
  the overlay label path: replace the `\n` from `_compact_axis_label` with
  `<br>` (pyqtgraph honors HTML `<br>`) OR drop the newline and ellipsize via
  `_middle_ellipsis` (`canvases.py:239`) to a sane length so the rotated label
  fits the axis height. Disable `autoSIPrefix` on overlay y-axes
  (`axis.enableAutoSIPrefix(False)`) or fold the scale into the label. Add
  overlay axis width/offset management: set a small label offset and/or pin a
  minimum width on each overlay `AxisItem` so the rotated label clears the tick
  numbers and adjacent axes (analogous to `_unify_subplot_left_axis_widths` but
  for the overlay right-axis stack). Tune against the screenshot.

- [ ] **Step 4 — run, expect PASS.**

- [ ] **Step 5 — commit:** `fix(ui): overlay y-axis labels no longer collide with ticks`

---

## Task 6: Full regression sweep + live GUI verification

**Files:** none (verification only; tighten a test only if it is green for the
wrong reason).

- [ ] **Step 1 — canvas + toolbar suites (offscreen).**
```
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_chart_stack.py -q
```
- [ ] **Step 2 — adjacent UI suites.**
```
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_axis_handle.py tests/ui/test_dialogs.py tests/ui/test_main_window_smoke.py -q
```
- [ ] **Step 3 — `git diff --check`** (whitespace/conflict markers).
- [ ] **Step 4 — LIVE GUI verification (REQUIRED).** Launch the app, load a
  multi-channel file, and confirm by hand (offscreen does NOT prove bugs 3/5):
  1. Overlay: labels clear of ticks/adjacent axes (R1); blank in-plot click
     deselects (R5); box-zoom works (R3).
  2. Subplot: box-zoom works on every row, including after toggling channels
     (replot) (R3); Home restores both X and Y to global in one click (R4).
  3. Switch overlay↔split repeatedly: no ghost curves remain (R2).
- [ ] **Step 5 — report** `ui_verified`, `tests_run`, `tests_before`,
  `tests_after`, `files_changed`, `symbols_touched`, and any `flagged{from,for,issue}`.

---

## Self-Review

- **Spec coverage:** R2→Task1, R5→Task2, R4→Task3, R3→Task4, R1→Task5,
  verification→Task6.
- **Wrong-reason tests:** bug 5 test (clicks outside rect) tightened in Task 2
  Step 4; bug 3 test (fresh-state only) extended in Task 4 Step 1.
- **Lesson compliance:** bug 4 ordering follows flush-after-mutation; bugs 2/3
  disconnect/rebuild listeners against fresh objects; no matplotlib APIs added.
- **Contract:** no signal/method/attribute removals; new helpers are private
  (`_teardown_overlay_aux_viewboxes`, optional `apply_current_mouse_mode`).
