# Analysis Interaction — Review Fixes (Design Spec)

**Date:** 2026-06-14
**Source:** Review of the last ~10 commits (FFT/heatmap analysis polish batch).
Three issues to fix: A (time-preview drag swallows toolbar mode), B (divider
drag/reset/collapse fight split-pane slice alignment), C (shortcut tests stale +
Alt view-switch is time-only + chart_stack test-isolation cascade).

This spec records root cause, the decided fix, scope, and the verification bar
for each. The companion plan
(`docs/superpowers/plans/2026-06-14-analysis-interaction-review-fixes.md`)
breaks these into TDD tasks.

---

## A. Time-preview left-drag must respect the toolbar Pan/Zoom mode

**Root cause.** `_TimePreviewViewBox.mouseDragEvent`
(`mf4_analyzer/ui/pg_canvas/line_canvas.py`) intercepts **every** left-button
drag (`axis is None`), calls `select_time_region`, and `return`s before
`super()`. The parent `_ModifierWheelViewBox.mouseDragEvent`
(`mf4_analyzer/ui/pg_canvas/viewbox.py:87`) has an explicit box-zoom branch
(`state['mouseMode'] == pg.ViewBox.RectMode`, line 93) that is therefore
**never reached** on the time preview. Consequences:

- Toolbar **Zoom** active → left-drag on the time preview frame-selects instead
  of box-zooming (the spectrum plot box-zooms → inconsistent).
- The `1e5061b` commit message claims *"box-zoom mode keep working"* — false for
  this ViewBox.

**Decision.** Frame-select only when **not** in RectMode; otherwise fall through
to `super()` so the toolbar Zoom still box-zooms. Pan-mode left-drag keeps
frame-selecting (that is the intended replacement for panning the preview).

```python
def mouseDragEvent(self, ev, axis=None):
    is_rect = self.state.get("mouseMode") == pg.ViewBox.RectMode
    if ev.button() == Qt.LeftButton and axis is None and not is_rect:
        ev.accept()
        p0 = self.mapToView(ev.buttonDownPos())
        p1 = self.mapToView(ev.pos())
        self.build_region_from_data(float(p0.x()), float(p1.x()))
        return
    super().mouseDragEvent(ev, axis=axis)
```

**Minor companion fix.** `select_time_region` currently `setVisible(True)`
unconditionally — a near-zero drag (`hi <= lo`) leaves an invisible-width region
shown. Only show when `hi > lo`.

**Verification.** Unit test: in RectMode a left-drag does NOT create/show the
region (box-zoom path owns it); in PanMode a left-drag DOES set the region and
emit `time_preview_range_changed`. Plus the existing region tests stay green.

---

## B. Divider drag / reset / collapse must not run single-pane slice align in split mode

**Root cause.** Slice right-edge alignment is **owned by the page**:
`AnalysisSectionPage` connects each canvas `layout_geometry_changed`
→ `_schedule_heatmap_layout_sync` (`analysis_section_page.py:186`), a debounced
`QTimer.singleShot(0, sync_heatmap_layouts)` that picks single
(`reset_split_layout_alignment`) vs split (`apply_split_layout_alignment`)
by pane count. `PgHeatmapCanvas.resizeEvent`
(`heatmap_canvas.py:1376`) deliberately does NOT call `_align_slice_to_main()`
— the comment says doing so "fights the shared split reserve".

But the divider handlers call it directly and unconditionally:
- `_on_split_drag_finished` (`heatmap_canvas.py:1361`)
- `_on_split_reset` (`heatmap_canvas.py:1372`)
- `_on_collapse_changed` state=='none' (`heatmap_canvas.py:1328`)

In split mode this runs single-pane alignment that races the page's split
alignment → slice time-axis can mis-align after a divider drag/reset/fold.
`_on_split_drag_finished` additionally does **not** emit
`layout_geometry_changed`, so the page never gets told to re-sync after a drag
settles.

**Decision.** A standalone canvas (and every existing canvas unit test) has NO
page listening to `layout_geometry_changed`, so we cannot simply delete the
align — single-pane alignment must still happen locally. Instead, track whether
the **page** is currently driving split alignment, and only self-align when it
is not:

- Add `self._split_aligned = False` in `__init__`.
- `apply_split_layout_alignment(...)` sets `self._split_aligned = True`
  (page is managing split geometry).
- `reset_split_layout_alignment()` sets `self._split_aligned = False`
  (back to single-pane / page not splitting).
- In `_on_split_drag_finished`, `_on_split_reset`, and `_on_collapse_changed`
  (state=='none'): call `_align_slice_to_main()` + `_position_slice_panel()`
  ONLY when `not self._split_aligned`; ALWAYS emit `layout_geometry_changed`
  (drag_finished currently doesn't) so the page re-syncs in split mode.

Net effect:
- Standalone / single pane (`_split_aligned == False`): self-aligns directly
  (unchanged behavior; existing tests stay green).
- Split panes (`_split_aligned == True`): skips the single-pane align; the
  emitted `layout_geometry_changed` drives the page's
  `apply_split_layout_alignment` (no fight).

**Verification.** Unit test on a single-pane heatmap: after
`_on_split_drag_finished()` / `_on_split_reset()`, slice right edge still aligns
to the map (alignment happened via the page path or the single-pane reset).
Existing collapse/restore/drag tests stay green. Real-render check on a split
analysis page (two panes): drag one divider, confirm the slice axes of both
panes stay aligned (no drift band).

---

## C. Keyboard shortcuts: confirm Ctrl top / Alt bottom-view, make Alt global, fix stale tests + isolation

**Confirmed intent (from user).** Top chart shortcuts = **Ctrl**
(`hints.py` `NAV_SHORTCUTS` Ctrl+R/Z/G/B; `TIME_CARD_SHORTCUTS` Ctrl+1..5 for
分屏/叠加/游标关/单游标/双游标). Bottom **view switching = Alt** (Alt+1..6),
and it must work in **every section** (time / fft / fft_time / order).

### C1 — Stale tests assert Alt for the Ctrl top shortcuts

`test_chart_stack.py::test_chart_nav_actions_have_chart_area_shortcuts` and
`::test_time_card_segmented_buttons_have_alt_digit_shortcuts` assert `Alt+R` /
`Alt+1..5`, but the code (correctly) wires Ctrl. Root: commit `9570b95` moved the
code Alt→Ctrl without updating these two tests. **Fix the tests** to assert Ctrl
(top shortcuts are Ctrl by design) and rename the time-card test to
`..._have_ctrl_digit_shortcuts`.

### C2 — Alt+1..6 view switching is time-only; make it section-aware

`MainWindow._install_view_shortcuts` (`main_window.py:611`) wires
`Alt+{1..6}` → `_switch_view`, which switches `self.view_manager` — the **time**
section's manager only. The analysis sections (fft/fft_time/order) have separate
`self.analysis_managers[sec]` driven by `_on_analysis_switch(sec, idx)`
(`main_window.py:752`), reached only through the per-section tab bars, never the
global Alt shortcuts.

**Decision.** Dispatch the Alt shortcut by the current section:

```python
def _switch_view_for_active_section(self, idx):
    mode = self.chart_stack.current_mode()   # 'time'|'fft'|'fft_time'|'order'
    if mode in ('fft', 'fft_time', 'order'):
        self._on_analysis_switch(mode, idx)
    else:
        self._switch_view(idx)
```

Wire `sc.activated.connect(lambda bound=idx: self._switch_view_for_active_section(bound))`.
Both `_switch_view` and `_on_analysis_switch` already guard
`0 <= idx < len(views)` and no-op when `idx == active`, so out-of-range Alt
keys are safe.

### C3 — chart_stack test-isolation cascade

`test_chart_stack.py::test_chart_stack_set_mode` passes in isolation but, run in
module order, errors during TEARDOWN and cascades 7 more teardown errors — an
earlier test leaks global Qt state (a widget/singleton not cleaned up). Scope:
identify the leaking test, add proper teardown (`deleteLater()` +
`processEvents`, or a fixture) so the module runs green. If the root cause is a
deep pre-existing Qt-global issue beyond a localized cleanup, document it in a
lesson and descope to a follow-up rather than over-engineer here.

**Verification (C).** `tests/ui/test_chart_stack.py` runs **green as a module**
(no failures, no teardown errors). New test: with the app on an analysis section,
`Alt+i` switches that section's active view (not the time manager).

---

## Out of scope

- The fragile `getattr(curve, "curve")` AA reach-in (`6b0d0a6`, finding D) —
  acceptable, guarded; no change.
- The full-width divider crossing the colorbar column on heatmaps — accepted
  visually by the user.
- Re-litigating Ctrl-vs-Alt key choice — settled by the user (Ctrl top / Alt
  view).

## Risks / regressions to watch

- A: tests that simulate left-drag on `_plot_time` while a Zoom mode is active
  now box-zoom instead of frame-select; check no existing test asserts the old
  (always-frame-select) behavior.
- B: removing the direct align relies on the page being wired
  (`layout_geometry_changed` connected). Standalone canvas tests (no page) must
  still align via the single-pane path — keep `reset_split_layout_alignment`
  reachable and verify standalone heatmap tests stay green.
- C2: `current_mode()` must return the section key; confirm the mapping
  (`_MODE_TO_INDEX = {'time','fft','fft_time','order'}`).
