# Pyqtgraph Subplot Zero-Active Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every zero-active time-domain subplot transition enter a canonical empty state and rebuild safely, while preserving non-empty row reuse and rejecting any reused layout whose realized scene geometry is collapsed.

**Architecture:** `TimeDomainCanvasPG` refuses an empty ordinary-subplot delta before mutation, and the existing `MainWindow` owner converts that failure into canonical empty via whichever branch owns the trigger — `clear()` when nothing is checked, `show_empty_hint()` when everything checked is hidden. Compatible non-empty deltas remain in place, but they settle one centralized subplot layout seam and must pass a viewport-relative `ViewBox.sceneBoundingRect()` postcondition before publishing success; measured-and-collapsed geometry is synchronously cleared and routed to the existing full rebuild, while geometry that cannot be measured at all (hidden canvas) keeps the warm path.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, NumPy, pytest, pytest-qt, repository ViewState/MainWindow rendering flow.

**Design spec:** `docs/superpowers/specs/2026-07-30-pg-subplot-zero-active-hardening-design.md`

**Revision 2026-07-30 (post-review):** verified against the current sources and
corrected. The settle seam no longer short-circuits on `_subplot_label_specs`,
keeps `_repin_overlay_channel_ticks()`, reuses the existing `_settle_layout()`,
and commits to the full build's bottom-then-left unifier order (Task 2 Step 4).
The geometry postcondition is split into observability and measurement — a
non-observable canvas keeps the warm path instead of failing closed (Task 2
Steps 2/5/6). The all-unchecked owner branch uses `clear()`, not
`show_empty_hint()` (Task 3 Step 5). Existing successful-subplot-delta tests
must get an event pump before the delta (Task 2 Step 1), and the Task 3 Step 6
`-k` filter no longer silently drops the overlay guard test.

**Execution amendment 2026-07-30:** The real owner matrix found two additional
source obligations. Empty owner renders must not overwrite saved X/Y ranges
with the cleared canvas fallback, so checkbox changes capture ranges before
replot and the View bridge skips range capture when a canvas explicitly has no
primary X owner. Warm subplot deltas must also reconcile dual-cursor items by
exact ordered `ViewBox` identity (including equal-count replace transitions)
and remove stale items through their recorded owner. The Task 4 overlay
identity test now explicitly selects overlay mode before building the
selection model; its previous default-subplot setup conflicted with the new
one-row zero-active boundary.

## Global Constraints

- A zero active subplot request must return the exact reason `subplot-empty-selection-reset` before mutating a valid retained subplot model.
- A failed non-empty realized-geometry postcondition must return the exact reason `subplot-realized-geometry-invalid` after synchronously clearing the invalid render model.
- `subplot-object-reuse` is legal only when the requested active set is non-empty and realized geometry either passed validation or was not observable.
- A canvas whose geometry is not observable (hidden canvas/`_glw`, or non-positive viewport) must SKIP the postcondition and keep the warm path. Failing closed there would downgrade every later delta on an off-screen pane to a permanent full rebuild while the fallback rebuild is equally unrealized.
- Compatible non-empty-to-non-empty subset changes must preserve unchanged `PlotDataItem`, `PlotItem`, and `ViewBox` identity.
- Append-only compatible subplot additions must create exactly one new row and must not rebuild existing rows.
- Overlay visibility-only behavior and its zero-selection identity fast path must remain unchanged.
- Semantic View state—checked/hidden channels, X range, per-channel Y ranges, plot mode, tick density, and cursor placement—must survive the zero-active structural reset.
- A successful warm delta must leave dual A/B cursor items owned one-to-one by the exact ordered active `ViewBox` set, with replaced items detached from their former scene.
- Production code must not resize a canvas, viewport, parent, or window to recover geometry.
- Production code must not add delayed resize work, event-pump loops, dependency pins, pyqtgraph version checks, or repaint retries.
- Geometry acceptance must use realized `ViewBox.sceneBoundingRect()` values relative to the current viewport, not only visibility flags or `PlotItem` height constraints.
- Tests must use shown widgets and must assert restored geometry before any explicit resize.
- Every existing test that asserts a successful subplot delta must have a realized layout before the delta, so a failure means collapsed geometry and never an un-pumped Qt event queue.
- `MainWindow` reaches canonical empty through two different branches: `canvas.clear()` when nothing is checked, `canvas.show_empty_hint(...)` when everything checked is hidden. Assert `_empty_hint_item`/`_empty_hint_text` only for the all-hidden trigger.
- Use `\.\.venv\Scripts\python.exe` for repository Python checks in this Windows-native workspace.

**Anchoring note:** the `file:line` ranges below are from the pre-change tree and
drift as earlier tasks insert code. Locate every edit site by symbol name
(`_try_apply_subplot_selection_delta`, `_unify_subplot_left_axis_widths`, the
end-of-build tick-density tail, the target test/class names) rather than by line
number.

---

## File map

- Modify `mf4_analyzer/ui/pg_canvas/canvas.py`: define the zero-active selection boundary, centralize subplot settle, validate realized geometry, and fail closed.
- Modify `mf4_analyzer/ui/pg_canvas/cursor.py`: reconcile cursor items by ordered `ViewBox` ownership and remove stale items through the actual owner.
- Modify `mf4_analyzer/ui/main_window/window.py`: capture live ranges before checkbox-driven owner replots.
- Modify `mf4_analyzer/ui/view_bridge.py`: do not capture fallback ranges from an explicitly empty time-domain canvas.
- Modify `tests/ui/test_pg_timedomain_canvas.py`: direct selection-delta state-machine tests, raw scene-geometry assertions, and injected invalid-geometry recovery.
- Modify `tests/ui/test_view_switch_integration.py`: exact populated View → empty View → populated View regression.
- Modify `tests/ui/test_main_window_smoke.py`: all-unchecked and all-eyes-hidden round trips, including one-row subplot coverage and semantic state restoration.
- Modify `tests/ui/test_timedomain_hotpath_perf.py`: make the preserved overlay zero-selection identity contract select overlay mode explicitly.
- Modify `docs/analyzer/specs/2026-07-26-plot-performance-standards.md`: make the non-empty warm-reuse boundary normative and add the zero-active correctness gate.
- Modify `docs/analyzer/plans/2026-07-26-hdf-timedomain-performance-implementation.md`: add a dated supersession note to the former empty-selection delta-hide decision.
- Modify `docs/analyzer/reviews/2026-07-26-hdf-timedomain-performance-regression-report.md`: qualify the retained-row recommendation with the zero-active exception.
- Verify `docs/lessons-learned/codex-pg-subplot-reuse-needs-realized-geometry.md`: keep the existing promoted lesson aligned; do not create a duplicate lesson.

### Task 1: Make zero active subplot rows a structural boundary

**Files:**

- Modify: `tests/ui/test_pg_timedomain_canvas.py:5175-5334`
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py:1212-1256`

**Interfaces:**

- Consumes: `TimeDomainCanvasPG.try_apply_selection_delta(rows, *, mode, render_context_key=None) -> dict`
- Produces: exact failure result `{"applied": False, "reason": "subplot-empty-selection-reset"}` for an empty ordinary-subplot request with a retained model
- Preserves: the existing `None` return from `_try_apply_subplot_selection_delta()` for legacy/non-retained subplot handling

- [ ] **Step 1: Add a shown-canvas helper that independently measures raw active geometry**

Place this near `_pg_canvas()` in `tests/ui/test_pg_timedomain_canvas.py`. It must not call the production geometry validator.

```python
def _active_subplot_scene_sizes(canvas):
    return [
        (
            float(handle.view_box.sceneBoundingRect().width()),
            float(handle.view_box.sceneBoundingRect().height()),
        )
        for handle in canvas.axes_list
    ]
```

- [ ] **Step 2: Write the failing zero-active no-mutation test**

Add this test to `TestTimeDomainCanvasPGSelectionDelta`:

```python
@pytest.mark.parametrize("row_count", [1, 2])
def test_subplot_zero_active_requires_structural_reset_without_mutation(
    self, qapp, row_count,
):
    canvas = _pg_canvas(qapp)
    t = np.linspace(0.0, 10.0, 2000, dtype=np.float64)
    rows = [
        self._row("a", t, np.sin(t)),
        self._row("b", t, np.cos(t)),
    ][:row_count]
    context = ("time", False, None, (False,))
    canvas.plot_channels(rows, mode="subplot", render_context_key=context)
    qapp.processEvents()

    active_before = set(canvas._selection_active_keys)
    plot_items = [handle.plot_item for handle in canvas.axes_list]
    constraints_before = [
        (float(item.minimumHeight()), float(item.maximumHeight()))
        for item in plot_items
    ]
    geometry_before = _active_subplot_scene_sizes(canvas)

    result = canvas.try_apply_selection_delta(
        [], mode="subplot", render_context_key=context
    )

    assert result == {
        "applied": False,
        "reason": "subplot-empty-selection-reset",
    }
    assert canvas._selection_active_keys == active_before
    assert canvas.axes_list
    assert all(item.isVisible() for item in plot_items)
    assert [
        (float(item.minimumHeight()), float(item.maximumHeight()))
        for item in plot_items
    ] == constraints_before
    assert _active_subplot_scene_sizes(canvas) == pytest.approx(geometry_before)
```

- [ ] **Step 3: Run the new test and verify the current regression path is exposed**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta::test_subplot_zero_active_requires_structural_reset_without_mutation -v
```

Expected before implementation: FAIL because the current code returns `subplot-object-reuse`, empties `axes_list`, hides every row, and sets every retained row height constraint to zero.

- [ ] **Step 4: Add the early boundary before any subplot layout mutation**

In `_try_apply_subplot_selection_delta()`, add the guard after the retained-model check and before topology validation, X-limit capture, row append, visibility, or constraint changes:

```python
requested_order = list(parsed)
requested = set(requested_order)
previous_active = set(self._selection_active_keys)
if not self._subplot_retained_order and self._selection_bound_keys:
    return None
if not requested:
    self._last_selection_delta = {
        "applied": False,
        "reason": "subplot-empty-selection-reset",
    }
    return dict(self._last_selection_delta)
```

Do not add the same guard to the generic overlay visibility path.

- [ ] **Step 5: Run the direct selection-delta class**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta -v
```

Expected: PASS. Existing non-empty remove/restore and append tests must still report `subplot-object-reuse`.

- [ ] **Step 6: Commit the state-boundary change**

```powershell
git add mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(plot): make zero subplot selection structural"
```

### Task 2: Centralize subplot settle and fail closed on collapsed realized geometry

**Files:**

- Modify: `tests/ui/test_pg_timedomain_canvas.py` — `test_subplot_remove_restore_reuses_plot_items_and_viewboxes`, `test_subplot_append_adds_one_row_without_rebuilding_existing_rows`, plus two new tests in `TestTimeDomainCanvasPGSelectionDelta`
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py` — the `from math import ceil` import line
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py` — the end-of-`plot_channels` tick-density / overlay-repin / subplot-unifier tail (`canvas.py:1001-1008` pre-change)
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py` — `_try_apply_subplot_selection_delta()` commit sequence (`canvas.py:1297-1397` pre-change)
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py` — new methods immediately before `_unify_subplot_left_axis_widths()` (`canvas.py:3731` pre-change)
- Do NOT modify: the early `_unify_subplot_left_axis_widths()` inside initial subplot construction (`canvas.py:812` pre-change)

**Interfaces:**

- Produces: `TimeDomainCanvasPG._settle_subplot_layout() -> None`
- Produces: `TimeDomainCanvasPG._subplot_geometry_is_observable() -> bool`
- Produces: `TimeDomainCanvasPG._subplot_realized_geometry_is_usable() -> bool`
- Produces: exact failure result `{"applied": False, "reason": "subplot-realized-geometry-invalid"}` with canonical cleared state
- Consumes: existing `_settle_layout()`, `_subplot_label_specs`, `axes_list`, `_glw.viewport().rect()`, and each active `ViewBox.sceneBoundingRect()`
- Preserves: the overlay/single end-of-build tail, including `_repin_overlay_channel_ticks()`

- [ ] **Step 1: Strengthen the existing non-empty remove/restore test with raw geometry assertions**

In `test_subplot_remove_restore_reuses_plot_items_and_viewboxes`, process events after the initial plot so the shown fixture is realized. After each partial removal/restoration delta, run the independent viewport-relative assertion once immediately—before another `processEvents()`—then process events and assert it again. This proves the synchronous settle is sufficient and that a later Qt pass does not collapse it:

```python
def assert_geometry_is_material():
    viewport = canvas._glw.viewport().rect()
    sizes = _active_subplot_scene_sizes(canvas)
    assert sizes
    assert all(width >= max(1.0, viewport.width() * 0.25)
               for width, _height in sizes)
    assert all(height >= max(1.0, viewport.height() * 0.10 / len(sizes))
               for _width, height in sizes)

assert_geometry_is_material()
qapp.processEvents()
assert_geometry_is_material()
```

Call `assert_geometry_is_material()` at all three checkpoints. Do not call `canvas.resize()`, `window.resize()`, or post a resize event between the delta and the assertion.

Then audit every OTHER existing test that asserts a successful subplot delta, because the new postcondition makes them geometry-sensitive — an unrealized layout would otherwise be indistinguishable from a collapsed one and the test would fail for the wrong reason:

```powershell
rg -n "subplot-object-reuse" tests/
```

At minimum `test_subplot_append_adds_one_row_without_rebuilding_existing_rows` needs a `qapp.processEvents()` between its `plot_channels([a], mode="subplot")` and its delta; today it sends the delta with no event pump. Add the pump; do not weaken its `len(created) == 1` assertion.

- [ ] **Step 2: Write the failing fail-closed test**

Add this test to `TestTimeDomainCanvasPGSelectionDelta`:

```python
def test_subplot_invalid_realized_geometry_clears_and_requests_rebuild(
    self, qapp, monkeypatch,
):
    canvas = _pg_canvas(qapp)
    t = np.linspace(0.0, 10.0, 2000, dtype=np.float64)
    a = self._row("a", t, np.sin(t))
    b = self._row("b", t, np.cos(t))
    context = ("time", False, None, (False,))
    canvas.plot_channels([a, b], mode="subplot", render_context_key=context)
    rebuilt = []
    canvas.chart_rebuilt.connect(lambda: rebuilt.append(True))
    monkeypatch.setattr(
        canvas, "_subplot_realized_geometry_is_usable", lambda: False
    )

    result = canvas.try_apply_selection_delta(
        [a], mode="subplot", render_context_key=context
    )

    assert result == {
        "applied": False,
        "reason": "subplot-realized-geometry-invalid",
    }
    assert canvas._last_selection_delta == result
    assert canvas.axes_list == []
    assert canvas._selection_bound_keys == set()
    assert canvas._selection_active_keys == set()
    assert canvas._subplot_retained_order == []
    assert canvas._subplot_retained_handles == {}
    assert canvas._primary_xaxis_ax is None
    assert rebuilt == []
```

Then pin the non-observable decision in the same class, so "skip, do not fail" is asserted rather than assumed:

```python
def test_subplot_hidden_canvas_keeps_warm_path_without_geometry_check(
    self, qapp, monkeypatch,
):
    canvas = _pg_canvas(qapp)
    t = np.linspace(0.0, 10.0, 2000, dtype=np.float64)
    a = self._row("a", t, np.sin(t))
    b = self._row("b", t, np.cos(t))
    context = ("time", False, None, (False,))
    canvas.plot_channels([a, b], mode="subplot", render_context_key=context)
    qapp.processEvents()
    a_vb = canvas._channel_lines["a"][0].view_box
    canvas.hide()
    qapp.processEvents()
    assert canvas._subplot_geometry_is_observable() is False
    monkeypatch.setattr(
        canvas, "_subplot_realized_geometry_is_usable", lambda: False
    )

    result = canvas.try_apply_selection_delta(
        [a], mode="subplot", render_context_key=context
    )

    assert result == {"applied": True, "reason": "subplot-object-reuse"}
    assert canvas._channel_lines["a"][0].view_box is a_vb
    assert canvas._selection_active_keys == {"a"}
```

- [ ] **Step 3: Run the fail-closed test and verify the missing interface**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta -k "invalid_realized_geometry or hidden_canvas_keeps_warm_path" -v
```

Expected before implementation: both FAIL because `_subplot_realized_geometry_is_usable` / `_subplot_geometry_is_observable` do not exist (the hidden-canvas test fails on `monkeypatch.setattr` for a missing attribute) and successful deltas do not validate realized geometry.

- [ ] **Step 4: Implement the centralized settle seam**

Place this method immediately before `_unify_subplot_left_axis_widths()`. Only the label-placement step may be skipped: `active_specs` can legally be empty while active rows exist (a spec entry is appended only when `channel_data` still holds the row), and a seam that then skipped tick density and layout activation would fail the postcondition for a reason unrelated to this defect.

```python
def _settle_subplot_layout(self):
    """Finalize active subplot axes before geometry is observed or painted.

    Single end-of-projection seam for subplot full builds AND in-place
    selection deltas. Ordered so each step measures the previous step's
    geometry: the left unifier reads tick-label text width, whose tick set
    depends on the row heights the bottom unifier just assigned, so left
    runs last. Always ends in a layout activation so the realized-geometry
    postcondition never depends on an inner unifier's early return
    (``_unify_subplot_left_axis_widths`` returns early below two axes).
    """
    if not self.axes_list:
        return
    if self._subplot_label_specs:
        self._recheck_subplot_label_placement()
    self._tick_density_controller._apply_tick_density_to_all_axes()
    self._unify_subplot_bottom_axis_heights()
    self._unify_subplot_left_axis_widths()
    self._settle_layout()
```

Reuse the existing `_settle_layout()` (it already is exactly the guarded
`_glw.ci.layout` invalidate/activate block); do not re-inline it.

At the end of the full build, replace the tick-density/repin/unifier tail with:

```python
if self._subplot_label_specs:
    self._settle_subplot_layout()
else:
    self._tick_density_controller._apply_tick_density_to_all_axes()
    if self._overlay_mode:
        self._repin_overlay_channel_ticks()
```

Two things this must get right:

- `_repin_overlay_channel_ticks()` stays in the non-subplot branch. Dropping it would silently regress overlay tick pinning.
- The two subplot unifiers may be dropped from the non-subplot branch **only** because both short-circuit on an empty `_subplot_label_specs`, which is their documented non-subplot marker, and `plot_channels()` clears that list on every build. Verify that short-circuit before deleting the calls.

Note that this makes the full build's existing bottom-then-left order authoritative and changes the delta path's current left-then-bottom order. That is deliberate consolidation onto one verified order; Step 1's geometry assertions plus `test_subplot_x_grid_geometry_is_aligned_before_first_frame` cover it.

Do NOT remove the earlier `_unify_subplot_left_axis_widths()` call inside initial subplot construction. It runs before per-row binding measures pixel width for dense-decimation decisions, it is idempotent, and no test covers the decimation effect of removing it.

- [ ] **Step 5: Implement observability and the viewport-relative geometry predicate**

Two methods next to `_settle_subplot_layout()`. Keep them separate: "cannot be measured" and "measured and collapsed" must not share an outcome.

```python
def _subplot_geometry_is_observable(self):
    """Return whether realized subplot geometry can be measured at all.

    A hidden canvas or zero-size viewport has no Qt-realized layout, so it
    can neither prove nor disprove the postcondition. Callers SKIP the
    check in that case rather than failing closed: the fallback would be a
    full rebuild that is equally unrealized, permanently downgrading every
    later delta on an off-screen pane. A hide->show transition delivers a
    resize event, and the existing resize settle path re-measures then.
    """
    if not self.axes_list or not self.isVisible() or not self._glw.isVisible():
        return False
    viewport = self._glw.viewport().rect()
    return viewport.width() > 0 and viewport.height() > 0


def _subplot_realized_geometry_is_usable(self):
    """Return whether active subplot ViewBoxes materially occupy the viewport.

    Only meaningful when ``_subplot_geometry_is_observable()`` is True.
    """
    if not self.axes_list:
        return False
    viewport = self._glw.viewport().rect()
    viewport_width = float(viewport.width())
    viewport_height = float(viewport.height())
    if viewport_width <= 0.0 or viewport_height <= 0.0:
        return False

    active_count = len(self.axes_list)
    min_width = max(1.0, viewport_width * 0.25)
    min_row_height = max(
        1.0, viewport_height * 0.10 / max(1, active_count)
    )
    tops = []
    bottoms = []
    for handle in self.axes_list:
        plot_item = getattr(handle, "plot_item", None)
        view_box = getattr(handle, "view_box", None)
        if plot_item is None or view_box is None or not plot_item.isVisible():
            return False
        rect = view_box.sceneBoundingRect()
        width = float(rect.width())
        height = float(rect.height())
        top = float(rect.top())
        bottom = float(rect.bottom())
        if not all(
            isfinite(value) for value in (width, height, top, bottom)
        ):
            return False
        if width < min_width or height < min_row_height:
            return False
        tops.append(top)
        bottoms.append(bottom)

    combined_height = max(bottoms) - min(tops)
    return combined_height >= max(1.0, viewport_height * 0.25)
```

Do not substitute constraint values such as `maximumHeight()` for the scene rectangles. Use `isfinite` on the four scalars — this runs per active row on every warm delta, so it must not allocate a NumPy array per row in the latency-critical path. `canvas.py` already has `from math import ceil`; extend it to `from math import ceil, isfinite` rather than importing the `math` module.

- [ ] **Step 6: Validate before publishing a successful non-empty delta**

In `_try_apply_subplot_selection_delta()`, use this order after `active_specs` is built:

```python
self._teardown_inside_labels()
self._subplot_label_specs = active_specs
self._settle_subplot_layout()
if (
    self._subplot_geometry_is_observable()
    and not self._subplot_realized_geometry_is_usable()
):
    failure = {
        "applied": False,
        "reason": "subplot-realized-geometry-invalid",
    }
    self.clear()
    self._last_selection_delta = dict(failure)
    return failure
```

The `and` ordering is the contract, not a micro-optimization: an unobservable canvas must never reach the measurement.

Move `_selection_active_keys` assignment, data-union cache invalidation, `_last_selection_delta` success recording, dense-raster synchronization, quality scheduling, `chart_rebuilt.emit()`, and `draw_idle()` after this guard. Remove the later duplicate tick-density call (the seam now owns it) and the now-superseded `if active_specs:` label/unifier block that the seam replaces.

- [ ] **Step 7: Run direct layout and first-frame regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode::test_subplot_x_grid_geometry_is_aligned_before_first_frame -v
```

Expected: PASS. The first-frame grid test proves the final tick-density/axis work still settles before geometry is observed.

- [ ] **Step 8: Commit the geometry invariant**

```powershell
git add mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(plot): fail closed on collapsed subplot geometry"
```

### Task 3: Cover every owner-level zero-active trigger without a resize repair

**Files:**

- Modify: `tests/ui/test_view_switch_integration.py:1-15,104-127`
- Modify: `tests/ui/test_main_window_smoke.py:1538-1635`
- Modify (execution amendment): `mf4_analyzer/ui/main_window/window.py`, `mf4_analyzer/ui/view_bridge.py`, `mf4_analyzer/ui/pg_canvas/canvas.py`, `mf4_analyzer/ui/pg_canvas/cursor.py`, and direct cursor-owner coverage in `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**

- Consumes: `MainWindow._plot_time_on_canvas()`, `_render_view_to_canvas()`, both owner empty branches (`canvas.clear()` and `canvas.show_empty_hint()`), and `canvas._last_full_rebuild_reason`
- Verifies: View-tab, checkbox, and eye-toggle sources converge on the same canonical empty → `no-render-model` rebuild flow, each through its own owner branch
- Verifies: outer `MainWindow.size()` is unchanged throughout recovery
- Preserves: saved X/Y/cursor state across the canonical empty interval and exact A/B cursor ownership after later warm row-topology changes

- [ ] **Step 1: Add an independent MainWindow geometry assertion helper**

Add a local helper to both integration test files. Do not import or call the production predicate.

```python
def _assert_subplot_materially_fills_viewport(canvas, expected_rows):
    assert len(canvas.axes_list) == expected_rows
    viewport = canvas._glw.viewport().rect()
    rects = [handle.view_box.sceneBoundingRect() for handle in canvas.axes_list]
    assert all(rect.width() >= max(1.0, viewport.width() * 0.25)
               for rect in rects)
    assert all(rect.height() >= max(1.0, viewport.height() * 0.10 / expected_rows)
               for rect in rects)
    combined_height = max(rect.bottom() for rect in rects) - min(
        rect.top() for rect in rects
    )
    assert combined_height >= max(1.0, viewport.height() * 0.25)
```

- [ ] **Step 2: Add the exact empty-View round-trip regression**

Add to `tests/ui/test_view_switch_integration.py`:

```python
def test_subplot_empty_view_round_trip_rebuilds_full_canvas_geometry(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    w.chart_stack.set_plot_mode("subplot")
    _set_checked(w, "speed", "torque")
    w.plot_time()
    qapp.processEvents()
    _assert_subplot_materially_fills_viewport(w.canvas_time, 2)
    old_view_boxes = [handle.view_box for handle in w.canvas_time.axes_list]
    outer_size = w.size()
    saved_xlim = _narrow_xlim(w, 0.20, 0.65)
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()

    assert w.size() == outer_size
    assert w.canvas_time.axes_list == []
    assert w.canvas_time._selection_bound_keys == set()
    assert w.canvas_time._subplot_retained_order == []

    w._switch_view(0)
    qapp.processEvents()

    assert w.size() == outer_size
    assert w.canvas_time._last_full_rebuild_reason == "no-render-model"
    assert all(
        all(handle.view_box is not old for old in old_view_boxes)
        for handle in w.canvas_time.axes_list
    )
    assert w.canvas_time.get_visible_xlim() == pytest.approx(saved_xlim)
    _assert_subplot_materially_fills_viewport(w.canvas_time, 2)
```

- [ ] **Step 3: Run the View-switch regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_switch_integration.py::test_subplot_empty_view_round_trip_rebuilds_full_canvas_geometry -v
```

Expected after Tasks 1–2: PASS without resizing the window after construction. Reverting the zero-active guard must reproduce the tiny-scene failure.

- [ ] **Step 4: Add the all-eyes-hidden round trip, parameterized for one and two rows**

Add `import pytest` at module scope in `tests/ui/test_main_window_smoke.py`, then add:

```python
@pytest.mark.parametrize("checked_names", [("speed",), ("speed", "torque")])
def test_all_subplot_eyes_hidden_then_reopened_rebuilds_full_geometry(
    qapp, qtbot, loaded_csv, checked_names,
):
    w, fid = _load_time_window_with_checked(
        qapp, qtbot, loaded_csv, checked_names
    )
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    qapp.processEvents()
    w.canvas_time.set_xlim(0.20, 0.65)
    saved_xlim = w.canvas_time.get_visible_xlim()
    current_ylims = w.canvas_time.get_visible_ylims()
    saved_ylims = {}
    for key, (lo, hi) in current_ylims.items():
        span = float(hi) - float(lo)
        if span <= 0.0:
            span = 1.0
        saved_ylims[key] = (
            float(lo) + span * 0.10,
            float(hi) - span * 0.10,
        )
    w.canvas_time.restore_visible_ylims(saved_ylims)
    w._capture_canvas_ranges_for_bound_view(w.canvas_time)
    # Dual mode through the public API: plot_channels only re-creates cursor
    # graphics items when the cursor is visible AND dual, so this makes the
    # round trip actually rebuild them instead of trivially leaving a value
    # nothing in the path would have touched.
    w.canvas_time.set_cursor_visible(True)
    w.canvas_time.set_dual_cursor_mode(True)
    w.canvas_time._cursor.ax = 0.40
    w.canvas_time._cursor.bx = 0.55
    old_view_boxes = [handle.view_box for handle in w.canvas_time.axes_list]
    outer_size = w.size()

    for channel in checked_names:
        assert w.navigator.set_channel_visible(fid, channel, False)
        qapp.processEvents()

    assert w.canvas_time.axes_list == []
    assert w.canvas_time._selection_bound_keys == set()
    assert w.canvas_time._empty_hint_item is not None

    for channel in checked_names:
        assert w.navigator.set_channel_visible(fid, channel, True)
        qapp.processEvents()

    assert w.size() == outer_size
    assert w.canvas_time._last_full_rebuild_reason == "no-render-model"
    assert all(
        all(handle.view_box is not old for old in old_view_boxes)
        for handle in w.canvas_time.axes_list
    )
    assert w.canvas_time.get_visible_xlim() == pytest.approx(saved_xlim)
    restored_ylims = w.canvas_time.get_visible_ylims()
    assert set(restored_ylims) == set(saved_ylims)
    for key, expected in saved_ylims.items():
        assert restored_ylims[key] == pytest.approx(expected)
    assert w.canvas_time._cursor.ax == pytest.approx(0.40)
    assert w.canvas_time._cursor.bx == pytest.approx(0.55)
    assert w.canvas_time._cursor._cursor_a_items
    assert len(w.canvas_time._cursor._cursor_a_items) == len(checked_names)
    _assert_subplot_materially_fills_viewport(
        w.canvas_time, len(checked_names)
    )
```

If `set_cursor_visible` / `set_dual_cursor_mode` do not survive `apply_controls_from_state` (the bridge projects `state.cursor_mode` on every render), drive the mode through `chart_stack.set_cursor_mode(...)` instead so the ViewState round trip carries it, and keep the item-count assertion.

- [ ] **Step 5: Add the all-unchecked round trip using real channel items**

Add a two-row test beside the eye test. Use the channel tree items so `channels_changed` and View capture follow the real user path.

Two things to keep straight here:

- This trigger lands in the owner's `not all_checked` branch, which calls `canvas.clear()` + `canvas.draw()` and installs **no** empty hint. Assert `axes_list == []` / `_selection_bound_keys == set()`, never `_empty_hint_item`. (The eye test in Step 4 is the one that gets the hint.)
- Unlike `_load_time_window_with_checked`, this test does not set `channel_list._updating`, so it relies on `setCheckState` itself driving `channels_changed`. That is intentional — it is the real user path — but verify the signal actually fires, otherwise the "empty" assertions would pass for the wrong reason (nothing replotted at all). A quick check: assert `w.canvas_time._last_full_rebuild_reason` or `_selection_bound_keys` changed between the uncheck loop and the recheck loop.

```python
def test_all_subplots_unchecked_then_rechecked_rebuilds_full_geometry(
    qapp, qtbot, loaded_csv,
):
    from PyQt5.QtCore import Qt

    w, fid = _load_time_window_with_checked(
        qapp, qtbot, loaded_csv, ("speed", "torque")
    )
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    qapp.processEvents()
    w.canvas_time.set_xlim(0.20, 0.65)
    saved_xlim = w.canvas_time.get_visible_xlim()
    outer_size = w.size()
    file_item = w.channel_list._file_items[fid]
    items = {}

    def collect_channel_items(parent):
        for index in range(parent.childCount()):
            item = parent.child(index)
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "channel":
                items[data[2]] = item
            collect_channel_items(item)

    collect_channel_items(file_item)
    assert {"speed", "torque"}.issubset(items)

    for channel in ("speed", "torque"):
        items[channel].setCheckState(0, Qt.Unchecked)
        qapp.processEvents()

    assert w.canvas_time.axes_list == []
    assert w.canvas_time._selection_bound_keys == set()

    for channel in ("speed", "torque"):
        items[channel].setCheckState(0, Qt.Checked)
        qapp.processEvents()

    assert w.size() == outer_size
    assert w.canvas_time._last_full_rebuild_reason == "no-render-model"
    assert w.canvas_time.get_visible_xlim() == pytest.approx(saved_xlim)
    _assert_subplot_materially_fills_viewport(w.canvas_time, 2)
```

- [ ] **Step 6: Run the complete owner-level trigger matrix**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_switch_integration.py tests/ui/test_main_window_smoke.py -k "subplot_empty_view_round_trip or subplot_eyes_hidden or subplots_unchecked_then_rechecked or hiding_checked_channel_collapses_subplot or all_checked_channels_hidden" -v
```

Do not use a `subplot and (...)` conjunction here: `test_all_checked_channels_hidden_shows_hint_but_keeps_statistics` has no `subplot` in its name and would be silently dropped from a matrix that claims to cover it. That test is overlay-mode and must keep passing unchanged — it is the regression guard for the overlay zero-selection outcome this change does not touch.

Expected: PASS. The tests must not call `resize()` after the initial fixture/window setup.

- [ ] **Step 7: Commit the integration regressions**

```powershell
git add tests/ui/test_view_switch_integration.py tests/ui/test_main_window_smoke.py
git commit -m "test(plot): cover zero-active subplot trigger matrix"
```

### Task 4: Correct the performance contract and supersede the dangerous historical instruction

**Files:**

- Modify: `docs/analyzer/specs/2026-07-26-plot-performance-standards.md:41-50`
- Modify: `docs/analyzer/plans/2026-07-26-hdf-timedomain-performance-implementation.md:92-107`
- Modify: `docs/analyzer/reviews/2026-07-26-hdf-timedomain-performance-regression-report.md:128-139`
- Verify: `tests/ui/test_timedomain_hotpath_perf.py:439-501`

**Interfaces:**

- Produces: a normative performance contract that distinguishes non-empty warm reuse from zero-active structural reset
- Preserves: overlay CRC uncheck/recheck and eye-toggle identity test behavior

- [ ] **Step 1: Amend the normative deterministic gates**

In `2026-07-26-plot-performance-standards.md`, replace the unqualified subplot hide/restore gates with this meaning:

```markdown
4. 普通 subplot 的非空→非空 warm hide/restore（变更前后至少一行 active）不创建或销毁未变化的 PlotItem/ViewBox；
5. append 一个兼容通道只新增一个 PlotItem/ViewBox；
6. 非空→非空时，hidden row 高度为 0，re-show 复用原 PDI、ViewBox、颜色和 X/cursor state；
7. 普通 subplot 进入 zero-active 时必须转为 canonical empty render model；下一次 non-empty 必须 full rebuild，并在不改变外层窗口尺寸的前提下通过 shown-canvas sceneBoundingRect 几何门禁（`test_subplot_empty_view_round_trip_rebuilds_full_canvas_geometry`、`test_all_subplot_eyes_hidden_then_reopened_rebuilds_full_geometry`、`test_all_subplots_unchecked_then_rechecked_rebuilds_full_geometry`）；
8. 几何不可观测（canvas 未 shown 或 viewport 尺寸非正）时跳过该门禁并保留 warm path，不得降级为永久 full rebuild（`test_subplot_hidden_canvas_keeps_warm_path_without_geometry_check`）；
```

Renumber later items consistently. Every other gate in this list names its enforcing behavior, so these two must name their tests — a normative gate with no CI-checkable anchor is documentation, not a gate.

- [ ] **Step 2: Add a dated supersession note to the historical implementation plan**

Immediately below the Stage 3 retained-row list in `2026-07-26-hdf-timedomain-performance-implementation.md`, add:

```markdown
> **2026-07-30 zero-active 加固修订：** 上述 retained-row 规则仅适用于变更前后至少一行 active 的非空→非空 transition。第 5 条“空选择优先 delta-hide”已被 `docs/superpowers/specs/2026-07-30-pg-subplot-zero-active-hardening-design.md` 取代：zero-active 必须 canonical clear，恢复 non-empty 时 full rebuild；不得继续要求跨 zero-active 保留 PlotItem/ViewBox identity。
```

Do not rewrite the rest of the historical plan as though it had originally used the new rule.

- [ ] **Step 3: Qualify the historical regression-report recommendation**

After the retained-row recommendation in `2026-07-26-hdf-timedomain-performance-regression-report.md`, add:

```markdown
> **2026-07-30 后续边界：** retained rows 只覆盖 active count 始终大于 0 的普通 subplot transition。zero-active 是结构重置边界，恢复时重建并验证 realized scene geometry；详见 `docs/superpowers/specs/2026-07-30-pg-subplot-zero-active-hardening-design.md`。
```

- [ ] **Step 4: Search for stale unqualified zero-active requirements**

Run:

```powershell
rg -n "空选择优先 delta-hide|zero-active|warm hide/restore|hidden row 高度为 0|PlotItem/ViewBox identity" docs/analyzer docs/superpowers docs/lessons-learned
```

Expected: every empty-selection delta-hide occurrence is either removed from the normative standard or directly followed by the dated supersession note. Non-empty warm-reuse requirements remain.

- [ ] **Step 5: Re-run the overlay fast-path contract**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_mainwindow_crc_uncheck_recheck_and_eye_toggle_use_selection_delta -v
```

Expected: PASS. The new subplot boundary must not change overlay object identity or X-range retention.

- [ ] **Step 6: Commit the corrected contract**

```powershell
git add docs/analyzer/specs/2026-07-26-plot-performance-standards.md docs/analyzer/plans/2026-07-26-hdf-timedomain-performance-implementation.md docs/analyzer/reviews/2026-07-26-hdf-timedomain-performance-regression-report.md
git commit -m "docs(plot): define zero-active subplot rebuild boundary"
```

### Task 5: Run the complete verification and lessons completion gate

**Files:**

- Verify: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Verify: `tests/ui/test_pg_timedomain_canvas.py`
- Verify: `tests/ui/test_view_switch_integration.py`
- Verify: `tests/ui/test_main_window_smoke.py`
- Verify: `tests/ui/test_timedomain_hotpath_perf.py`
- Verify: `docs/lessons-learned/codex-pg-subplot-reuse-needs-realized-geometry.md`

**Interfaces:**

- Verifies: every acceptance criterion in the design spec
- Produces: no new interface; this is the completion gate

- [ ] **Step 1: Run focused canvas and geometry tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode::test_subplot_x_grid_geometry_is_aligned_before_first_frame -v
```

Expected: PASS.

- [ ] **Step 2: Run complete owner-flow test files**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_switch_integration.py tests/ui/test_main_window_smoke.py tests/ui/test_timedomain_hotpath_perf.py -v
```

Expected: PASS.

- [ ] **Step 3: Run the complete pyqtgraph time-domain canvas file**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py -v
```

Expected: PASS.

- [ ] **Step 4: Verify forbidden recovery mechanisms and stable diagnostics**

```powershell
rg -n "subplot-empty-selection-reset|subplot-realized-geometry-invalid|subplot-object-reuse|sceneBoundingRect" mf4_analyzer/ui/pg_canvas tests/ui docs
rg -n "_settle_subplot_layout|_subplot_geometry_is_observable|_subplot_realized_geometry_is_usable|_repin_overlay_channel_ticks" mf4_analyzer/ui/pg_canvas/canvas.py
rg -n "singleShot|processEvents|\.resize\(" mf4_analyzer/ui/pg_canvas/canvas.py
```

Expected: the new reasons appear at the designed seams; `_repin_overlay_channel_ticks` is still called from the non-subplot end-of-build branch; the settle seam is called from exactly two places (full build tail + delta commit); no new resize/timer/event-loop recovery is present in the implementation diff. Pre-existing unrelated resize/event handling may still appear and must be distinguished with `git diff`.

- [ ] **Step 5: Review only the implementation diff for accidental resize or dependency changes**

```powershell
git diff -- mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_view_switch_integration.py tests/ui/test_main_window_smoke.py tests/ui/test_timedomain_hotpath_perf.py docs/analyzer docs/lessons-learned
git diff --check
```

Expected: no dependency file changes, no synthetic resize repair, no whitespace errors, and no unrelated user edits reverted.

- [ ] **Step 6: Run the lessons completion check with the Windows venv**

The durable lesson already exists at `docs/lessons-learned/codex-pg-subplot-reuse-needs-realized-geometry.md`. Do not promote a duplicate.

```powershell
.\.venv\Scripts\python.exe scripts\lessons\check.py --doctor --verbose
.\.venv\Scripts\python.exe scripts\lessons\check.py --clear
```

Expected: doctor passes; the completion requirement is clear because the promoted lesson and its index entry are present.

- [ ] **Step 7: Commit any verification-only documentation alignment**

Skip this step when verification caused no file changes. If the existing lesson required wording alignment to match the exact final reason strings, commit only that alignment:

```powershell
git add docs/lessons-learned/codex-pg-subplot-reuse-needs-realized-geometry.md docs/lessons-learned/INDEX.md
git commit -m "docs(lessons): pin subplot realized geometry gate"
```

Do not commit unrelated pre-existing workspace changes.
