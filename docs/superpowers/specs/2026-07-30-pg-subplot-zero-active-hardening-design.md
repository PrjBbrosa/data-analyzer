# Pyqtgraph Subplot Zero-Active Hardening Design

**Status:** Implemented on `codex/pg-subplot-zero-active-hardening`; final verification pending.

**Review target:** This document and its companion implementation plan are intended for an independent Claude review before implementation.

**Revision 2026-07-30 (post-review):** Independent review against the current
`canvas.py` / `window.py` sources corrected four things. (1) The settle seam no
longer short-circuits on `_subplot_label_specs`, keeps the overlay tick repin,
reuses the existing `_settle_layout()`, and commits to one unifier order (§7.2).
(2) The realized-geometry postcondition is split into observability and
measurement, and a non-observable canvas keeps the warm path instead of failing
closed (§7.3, §6, §8). (3) `MainWindow` has two different empty branches —
`clear()` when nothing is checked, `show_empty_hint()` when everything checked
is hidden — so the earlier single-branch description was wrong (§7.4). (4) The
new postcondition makes every existing successful-subplot-delta test
geometry-sensitive; auditing them is now explicit scope (§9.1). Overlay's real
zero-selection outcome is also stated precisely (§4).

**Execution amendment 2026-07-30:** Owner-level regressions exposed two state
edges that the pre-implementation review did not model. First, a canonical
empty canvas has no live X/Y range: checkbox replots now capture ranges before
projecting the changed controls, and `capture_canvas_ranges_into()` refuses to
replace `ViewState` with the empty canvas fallback `(0, 1)` when the canvas
explicitly has no primary X owner. Second, a non-empty warm delta may change
the active `ViewBox` topology without changing its cardinality. Dual-cursor
items are therefore reconciled by exact ordered `ViewBox` identity, and stale
items are removed through their recorded owner so neither missing nor ghost
cursor lines survive a delta. The explicit overlay identity contract also sets
overlay mode before constructing its selection model; one-row subplot
zero-active behavior remains structural.

## 1. Summary

The time-domain subplot selection-delta optimization must stop treating “zero active subplot rows” as an ordinary warm-hide state. A subplot canvas may retain dormant rows only while at least one row remains active. Crossing from one-or-more active rows to zero is a structural boundary: the canvas refuses the delta without mutating the live layout, `MainWindow` enters its existing canonical empty state through whichever empty branch owns the trigger, and the next non-empty render performs an audited full rebuild.

Non-empty-to-non-empty subset changes remain optimized and must continue reusing unchanged `PlotDataItem`, `PlotItem`, and `ViewBox` objects. Successful reuse also gains a realized-geometry postcondition. If an active subplot projection is measured after a synchronous layout settle and its scene geometry does not meaningfully occupy the current viewport, the canvas fails closed, clears the invalid render model, and returns an explicit full-rebuild reason. The postcondition is evaluated only when geometry is observable at all; an unrealized off-screen canvas is neither proof nor disproof and keeps the warm path (§7.3). It must never repair the chart by resizing the window, posting delayed resize work, or depending on a later user resize.

## 2. Incident and evidence

### 2.1 User-visible failure

After plotting a populated time-domain View in subplot mode, creating or switching through an empty View and then plotting or returning to the populated View can shrink the chart into a tiny area in the upper-left corner. The outer application window remains at its normal size.

The same state transition can be reached without View tabs:

- uncheck every subplot channel, then recheck one or more;
- close every checked channel eye, then reopen one or more;
- perform the same transition with only one subplot row;
- switch from a populated View to a zero-channel View and back.

Partial removal is not affected when at least one subplot row remains active. Overlay mode does not use the same row-height collapse path and is outside this behavior change.

### 2.2 Measured geometry

On a shown canvas, the two active `ViewBox.sceneBoundingRect()` sizes were approximately:

- before the zero-active transition: `741.1 × 294.5` and `741.1 × 257.1`;
- after restoring the rows: `8.5 × 0.5` and `8.5 × 0.5`;
- after a one-logical-pixel outer resize: `742.1 × 294.5` and `742.1 × 257.1`.

The one-pixel resize is diagnostic evidence, not an acceptable repair. It proves that the data, `PlotItem` objects, and row constraints were present, while the containing `GraphicsLayout` had not been realized back into the unchanged viewport.

### 2.3 Regression origin

The first bad commit is:

`ba099e335efb8308a537346d41902de129ad6770` — `fix(plot): restore dense HDF interaction budget` (2026-07-27, later included in v7.9).

That change introduced retained subplot rows in `TimeDomainCanvasPG._try_apply_subplot_selection_delta()`. Dormant rows are hidden and assigned both minimum and maximum height `0.0`; restoring the rows resets their constraints and visibility. When all rows become dormant, the containing layout also collapses. Restoring only the child rows does not guarantee that the unchanged outer canvas receives a geometry event, so object identity and positive `maximumHeight()` are insufficient proof of recovery.

### 2.4 Why existing tests missed it

`TestTimeDomainCanvasPGSelectionDelta.test_subplot_remove_restore_reuses_plot_items_and_viewboxes` verifies object identity, visibility, constraints, X range, cursor state, and data-union behavior. It does not exercise the all-active-to-zero-active boundary and does not assert realized scene geometry on a shown canvas.

`test_switch_view_preserves_per_view_channels` verifies View state projection but not the rendered `ViewBox` dimensions after an empty View round trip.

The current performance standard also overstates the optimization contract by requiring warm hide/restore identity without distinguishing non-empty subset changes from a zero-active structural transition.

## 3. Goals

1. Eliminate the collapsed-canvas state for every confirmed zero-active subplot trigger.
2. Define zero active subplot rows as a canonical structural boundary instead of a retained-layout state.
3. Preserve object reuse and current interaction performance for compatible non-empty-to-non-empty subplot changes.
4. Preserve semantic View state across a zero-active reset: checked/hidden channel state, X range, per-channel Y ranges, plot mode, tick density, and cursor placement continue to be owned by `ViewState` and existing cursor state, not by retained graphics objects.
5. Detect future invalid subplot reuse at the render boundary using realized scene geometry and fail closed to the audited rebuild path.
6. Add deterministic tests that fail without an actual resize if the canvas occupies only a tiny fraction of its viewport.
7. Correct the performance specification and historical implementation notes so future optimizations do not reintroduce the invalid zero-row requirement.

## 4. Non-goals

- Replacing pyqtgraph, pinning or rolling back its version, or adding a version-specific workaround.
- Rebuilding every subplot membership change. Compatible non-empty subset changes and append-only additions remain warm.
- Changing overlay zero-selection behavior. Overlay does not collapse `PlotItem` row heights. Its existing zero-selection outcome is preserved exactly as-is: with more than one bound channel the generic path already returns the `overlay-topology-change` fallback (`canvas.py` topology guard), which is what makes `test_all_checked_channels_hidden_shows_hint_but_keeps_statistics` show the hint today; with a single bound channel it stays on the visibility-only fast path and may legally end with an empty active set. Neither outcome changes.
- Redesigning View tabs, channel eyes, cursor semantics, or the empty-state copy.
- Adding asynchronous resize retries, synthetic window resizes, repaint loops, or `processEvents()` loops to production code.
- Broadly decomposing `canvas.py`; the change stays at the existing selection-delta and layout-settle seams.

## 5. Considered approaches

### 5.1 Accepted: structural zero boundary plus geometry fail-closed guard

Keep retained rows while the requested active set is non-empty. Reject an empty subplot request before mutating any `PlotItem`. The existing owner path converts that rejection into a canonical empty canvas. Rebuild when data becomes non-empty again. Validate realized geometry before reporting any later non-empty subplot delta as successful.

This approach matches the actual ownership boundary: `MainWindow` owns the empty-state transition and full-render decision; the canvas owns whether an in-place delta is safe. It preserves the high-value non-empty warm path and removes the fragile state that collapses the outer layout.

### 5.2 Rejected: keep the zero-row warm model and force layout reactivation

This would restore every child constraint, invalidate and activate the layout, and potentially post additional layout work. It retains object identity across zero, but it remains dependent on Qt/pyqtgraph geometry propagation details. The measured failure already shows that child constraints can look correct while the realized parent geometry remains collapsed. A later dependency or axis-layout change could recreate the problem.

### 5.3 Rejected: full rebuild on every subplot membership change

This is simple but discards the accepted dense-HDF interaction optimization, violates the non-empty warm identity performance gates, and adds unnecessary work to common single-row hide/show operations. The defect is specific to the zero-active boundary and invalid realized geometry, so global rebuilding is disproportionate.

## 6. State model and transition contract

The canvas has three relevant render states:

| State | Required properties |
|---|---|
| Canonical empty | `axes_list`, selection-bound keys, retained subplot order/handles/constraints, curve bindings, and primary X owner are empty; an optional `_empty_hint_item` may occupy the layout. |
| Active retained subplot | At least one requested subplot row is active; dormant rows may remain retained at height zero; unchanged active/dormant objects may be reused. |
| Invalid transient projection | A non-empty in-place mutation completed internally, and active scene geometry was observable but failed the postcondition. This state is never returned as successful and is synchronously cleared before control returns to the owner. |

Required transitions:

| From | Request | Result |
|---|---|---|
| Active retained subplot | compatible non-empty subset or append | Attempt in-place reuse, settle layout, validate geometry when observable, then return `subplot-object-reuse`. |
| Active retained subplot | empty active set | Return `subplot-empty-selection-reset` without mutating rows. The owner's existing empty branch performs the canonical `clear()` (§7.4). |
| Canonical empty | non-empty set | `try_apply_selection_delta()` returns `no-render-model`; owner calls `plot_channels()` for a full rebuild. |
| In-place non-empty mutation | observable and invalid realized geometry | `clear()` synchronously, record `subplot-realized-geometry-invalid`, and return a failed delta so the owner rebuilds. |
| In-place non-empty mutation | geometry not observable (hidden canvas / zero-size viewport) | Skip the postcondition and return `subplot-object-reuse`. A hide→show transition delivers a resize event that re-runs the settle seam. |
| Any state | incompatible topology, order, source revision, plot mode, or render context | Preserve the existing explicit fallback reasons and audited full rebuild. |

No successful `subplot-object-reuse` result may leave `_selection_active_keys` empty.

## 7. Component design

### 7.1 `TimeDomainCanvasPG._try_apply_subplot_selection_delta()`

Add an early empty-request guard after confirming that an ordinary retained subplot model exists and before capturing X limits, appending rows, changing visibility, or changing row constraints:

```python
if not requested:
    self._last_selection_delta = {
        "applied": False,
        "reason": "subplot-empty-selection-reset",
    }
    return dict(self._last_selection_delta)
```

For compatible non-empty requests, keep the existing reuse behavior. Reorder the commit sequence so that selection bookkeeping, dense-raster notifications, quality scheduling, and `chart_rebuilt` are published only after layout settle and geometry validation pass.

### 7.2 Central subplot layout settle

Introduce `_settle_subplot_layout()` as the single end-of-projection settle seam. Its only precondition is a non-empty `axes_list`; it performs, in this order:

1. inside/outside subplot label placement recheck, guarded by `_subplot_label_specs`;
2. tick-density application before final axis measurement;
3. `_unify_subplot_bottom_axis_heights()`;
4. `_unify_subplot_left_axis_widths()`;
5. the existing `_settle_layout()` helper, which invalidates and activates the `GraphicsLayout`.

Only step 1 may be skipped. Steps 2–5 always run for a non-empty `axes_list`, because `active_specs` can legally come out empty while active rows exist (a spec entry is appended only when `channel_data` still holds the row), and a seam that skips tick density and layout activation in that case would fail the postcondition for a reason unrelated to the defect.

Step 5 reuses `_settle_layout()` rather than re-inlining `invalidate()`/`activate()`. It is required even though the two unifiers do their own layout activation: it makes the postcondition independent of their internal early returns (`_unify_subplot_left_axis_widths()` returns early with fewer than two left axes) and ensures late `AxisItem` work cannot leave the first frame stale.

The unifier order is bottom-heights-then-left-widths, which is the current **full-build** order. It is authoritative because the left unifier measures tick-label text width, and the tick set depends on the row heights the bottom unifier has just assigned; left must therefore run last. This changes the delta path's current left-then-bottom order — a deliberate consolidation onto one verified order, covered by the strengthened geometry assertions in the non-empty remove/restore test and by `test_subplot_x_grid_geometry_is_aligned_before_first_frame`. The `resizeEvent` settle path is out of scope and unchanged.

The normal full-build path calls the same seam, replacing the duplicated end-of-build tick-density and subplot unifier calls. The overlay branch of that tail keeps its own tick-density application **and** `_repin_overlay_channel_ticks()`; the two subplot unifiers may be dropped from the overlay/single branch only because both provably short-circuit on an empty `_subplot_label_specs`, which is the documented non-subplot marker. Full builds are not rejected by the runtime geometry guard because `defer_first_frame` and temporarily hidden canvases can legitimately defer realization; their behavior is protected by shown-canvas integration tests.

The early `_unify_subplot_left_axis_widths()` call inside initial subplot construction stays. It runs before per-row binding measures pixel width for dense-decimation decisions, it is idempotent, and removing it would change decimation inputs with no test covering that effect.

### 7.3 Realized-geometry postcondition

The postcondition is two helpers, because “cannot be measured” and “measured and collapsed” must not share an outcome.

`_subplot_geometry_is_observable() -> bool` decides whether realized geometry means anything yet. It requires a non-empty `axes_list`, a shown canvas and `_glw`, and a viewport with positive logical width and height.

**A non-observable canvas skips the postcondition and keeps the warm path.** Failing closed there would be strictly worse than the defect it guards: the fallback is a full rebuild that is itself unrealized, so every later delta on an off-screen pane (a split secondary canvas before its first expose, a canvas rebuilt while its stack page is not current) would degrade to a permanent full rebuild — exactly the interaction budget `ba099e3` bought. Nothing is lost by skipping: a hide→show transition delivers a resize event, and the existing resize settle path re-runs label placement, tick targets, and both unifiers. This is the same mechanism that made the diagnostic one-pixel resize appear to “fix” the chart, used where it is legitimate rather than as a repair.

`_subplot_realized_geometry_is_usable() -> bool` is the measurement, evaluated only when observable. It is a conservative runtime guard for a claimed successful in-place reuse, not a resize mechanism. For a non-empty active subplot projection it requires:

- one valid, finite `sceneBoundingRect()` per active `ViewBox`, and a present, visible `PlotItem` per active handle;
- every active row width to be at least `max(1 logical px, 25% of viewport width)`;
- every active row height to be at least `max(1 logical px, 10% of viewport height / active row count)`;
- the combined top-to-bottom span of active rows to be at least `max(1 logical px, 25% of viewport height)`.

These relative gates are intentionally permissive. They accept normal axis gutters, many-row layouts, and platform font differences while rejecting the observed `8.5 × 0.5` collapsed result. The tests independently inspect raw scene rectangles rather than merely trusting this helper.

Finiteness is checked with `isfinite` on the four rectangle scalars, extending the module's existing `from math import ceil`. This runs per active row on every warm delta, so it must not allocate a NumPy array per row in the path whose entire purpose is interaction latency.

If the postcondition is observable and fails after a non-empty delta:

1. create `{"applied": False, "reason": "subplot-realized-geometry-invalid"}`;
2. call `clear()` to remove the invalid graphics model and invalidate queued callbacks;
3. restore `_last_selection_delta` to the failure result because `clear()` resets it;
4. return the failed result to the owner;
5. let the existing `MainWindow._plot_time_on_canvas()` fallback call `plot_channels()` with `full_rebuild_reason="subplot-realized-geometry-invalid"`.

The guard must not call `resize()`, change a parent/window size, schedule a timer, or retry after `processEvents()`.

### 7.4 `MainWindow._plot_time_on_canvas()`

No new owner API is required. The existing branches already implement every required fallback. There are **two distinct empty branches**, and they reach canonical empty by different calls — implementation and tests must not assume one of them:

- **nothing checked at all** (`not all_checked`): a failed delta calls `canvas.clear()` then `canvas.draw()`. No empty hint is installed, so `_empty_hint_item` stays `None`;
- **checked but every row hidden** (`not checked`): a failed delta calls `canvas.show_empty_hint("已选择 N 个通道，当前均已隐藏")`, which begins with `clear()`;
- **non-empty data**: a failed delta invalidates the envelope cache and calls `canvas.plot_channels(..., full_rebuild_reason=reason)`.

Both empty branches satisfy the canonical-empty requirement in §6, because `show_empty_hint()` is `clear()` plus a `LabelItem`. Only the second one may be asserted against `_empty_hint_item` / `_empty_hint_text`.

Integration tests make these generic branches part of the explicit contract. Production code should not special-case a View-tab source, checkbox source, or eye source; all trigger paths converge on the same active-row set.

### 7.5 Semantic state preservation

The structural reset deliberately drops graphics-object identity only across the zero-active boundary. It must not drop user state:

- `_ch_changed()` and `_on_time_channel_visibility_changed()` capture the live canvas ranges before projecting changed channel controls into the bound `ViewState`;
- `capture_canvas_ranges_into()` treats `_primary_xaxis_ax is None` as “no live render range” and preserves prior semantic X/Y state instead of recording the empty-canvas `(0, 1)` fallback; generic canvases without that attribute keep their historical capture behavior;
- `_render_view_to_canvas()` restores `state.xlim`, `state.ylims`, and tick density after a rebuild;
- `TimeDomainCanvasPG.clear()` continues preserving cursor placement while removing cursor graphics items;
- after a successful non-empty subplot delta, dual A/B items are reconciled against the exact ordered active `ViewBox` owners, not merely the row count; stale items are detached through their recorded `ViewBox` owner before replacements are published.

Tests must assert restored ranges and cursor placement where the existing behavior promises them. Object identity must be asserted only for non-empty-to-non-empty reuse.

## 8. Error handling and diagnostics

The following reason strings are stable diagnostics for this change:

- `subplot-empty-selection-reset`: empty active set is a deliberate structural boundary; no row mutation occurred.
- `subplot-realized-geometry-invalid`: a non-empty reuse projection failed an observable realized-geometry postcondition and was cleared before return.
- `no-render-model`: expected next transition from canonical empty to non-empty; owner rebuilds.
- `subplot-object-reuse`: success is legal only for a non-empty active set whose geometry either passed validation or was not observable.

Exceptions from individual Qt getters continue to be treated conservatively. A missing `PlotItem`, missing `ViewBox`, hidden `PlotItem`, invalid rectangle, or non-finite dimension makes the geometry postcondition fail and routes to rebuild. A hidden canvas or non-positive viewport is different in kind: it makes the postcondition *not applicable* (§7.3), not failed. Broad exceptions must not be swallowed and then reported as reuse success.

## 9. Test design

### 9.1 Direct canvas tests

Extend `TestTimeDomainCanvasPGSelectionDelta` with shown-canvas tests that:

- parameterize one-row and two-row subplot models;
- call `try_apply_selection_delta([])` and assert `subplot-empty-selection-reset`;
- prove the early refusal did not hide rows, set row heights to zero, change active keys, or alter realized geometry;
- preserve the existing non-empty partial remove/restore identity assertions;
- inspect raw `ViewBox.sceneBoundingRect()` values immediately after the synchronous delta settle and before any explicit resize;
- inject a failed geometry postcondition and assert the canvas is canonical-empty, the result is `subplot-realized-geometry-invalid`, and no success notifications are emitted;
- assert the non-observable decision directly: a hidden canvas keeps the warm path and returns `subplot-object-reuse` even with the measurement predicate forced to fail.

Every existing test that asserts a **successful** subplot delta becomes geometry-sensitive under this change, because an unrealized layout would otherwise be indistinguishable from a collapsed one. Implementation must audit those tests and ensure the canvas layout is realized (a `processEvents()` pump after the build) before the delta. At minimum this covers `test_subplot_remove_restore_reuses_plot_items_and_viewboxes` and `test_subplot_append_adds_one_row_without_rebuilding_existing_rows`, the latter of which currently sends its delta with no event pump after `plot_channels`.

### 9.2 MainWindow trigger matrix

Shown `MainWindow` integration tests cover:

1. populated subplot View → create/switch to empty View → return to populated View;
2. all subplot channels unchecked → rechecked;
3. all checked subplot channel eyes closed → reopened;
4. the zero boundary with a single subplot row.

For every round trip, tests keep the outer window size unchanged and assert:

- the empty step owns no retained render model, asserted against the branch that trigger actually uses (§7.4): `_empty_hint_item` only for the all-hidden trigger, never for the all-unchecked one;
- the restored step uses a full rebuild (`_last_full_rebuild_reason == "no-render-model"` where applicable);
- active scene widths and heights exceed independent viewport-relative thresholds;
- the combined active row span materially fills the viewport;
- X/Y/cursor semantic state is restored as applicable;
- no one-pixel resize or extra resize event is performed by the test.

Cursor coverage must be meaningful rather than nominal. `ViewState` stores only `cursor_mode`, not A/B positions, and `clear()` deliberately preserves placement — so setting `_cursor.ax` directly and asserting it survived tests nothing this change touches. Enable the cursor through its public API so the round trip must rebuild cursor graphics items, then assert both placement and item restoration.

### 9.3 Performance and compatibility tests

Existing tests continue to require:

- partial non-empty hide/restore reuses the original `PlotDataItem` and `ViewBox`;
- append-only compatible selection creates exactly one new row;
- overlay visibility-only uncheck/recheck and eye toggles preserve identity and X state;
- incompatible topology retains explicit full-rebuild reasons;
- dense-raster visibility and idle-quality scheduling remain correct after successful reuse.

The deterministic performance standard is amended so zero-active reset/rebuild is excluded from warm identity gates and explicitly covered by the geometry/correctness gate.

## 10. Documentation changes

Implementation must update all current or misleading contracts:

- `docs/analyzer/specs/2026-07-26-plot-performance-standards.md`: limit warm subplot identity gates to transitions that keep at least one active row; add the zero-active reset/rebuild geometry gate.
- `docs/analyzer/plans/2026-07-26-hdf-timedomain-performance-implementation.md`: add a dated supersession note to the former “empty selection prefers delta-hide” decision instead of rewriting historical execution facts.
- `docs/analyzer/reviews/2026-07-26-hdf-timedomain-performance-regression-report.md`: add the same dated qualification to the retained-row recommendation.
- `docs/lessons-learned/codex-pg-subplot-reuse-needs-realized-geometry.md`: retain the regression lesson and its shown-canvas verification requirement.

A final repository search must find no unqualified active requirement that empty subplot selection remain delta-hidden or preserve graphics-object identity.

## 11. Acceptance criteria

The hardening is complete only when all of the following hold:

1. Every confirmed zero-active subplot trigger restores a materially full-size chart without changing the outer window size.
2. `try_apply_selection_delta([], mode="subplot", ...)` returns `subplot-empty-selection-reset` before mutating a valid retained model.
3. Canonical empty state owns no retained subplot graphics model.
4. The next non-empty request rebuilds from `no-render-model` and restores semantic View state.
5. Compatible non-empty subset changes and append-only additions retain their existing object-reuse contracts.
6. An observable and failed non-empty geometry postcondition returns `subplot-realized-geometry-invalid`, clears the invalid model, and routes through the audited rebuild path.
7. A non-observable canvas keeps the warm path instead of degrading to a permanent full rebuild, and this is asserted by a test rather than assumed.
8. No production resize, delayed resize, event-pump loop, dependency pin, or version check is introduced.
9. Direct canvas, View-switch, checkbox, eye-toggle, single-row, performance, and compatibility regressions pass on a shown offscreen-Qt canvas.
10. Performance and historical design documents no longer instruct future work to retain zero active subplot rows.
11. `git diff --check`, targeted test files, and the repository lessons completion gate pass.

## 12. Risks and mitigations

- **Geometry timing differences:** settle synchronously with final layout invalidation/activation; test before an explicit resize and without relying on an extra resize event.
- **False geometry rejection on small or many-row canvases:** use permissive viewport-relative thresholds with a one-logical-pixel floor; restrict the runtime guard to claimed non-empty in-place reuse.
- **False rejection on an unrealized canvas silently disabling the optimization:** separate observability from measurement (§7.3), skip rather than fail when geometry cannot be measured, and pin the decision with a hidden-canvas warm-path test.
- **Existing warm-path tests becoming geometry-sensitive:** audit every test asserting a successful subplot delta for a realized layout before the delta (§9.1), so a red test means collapsed geometry and never an un-pumped event queue.
- **Performance regression:** keep the non-empty retained-row path, measure object creation counts, and exclude only the rare zero-active boundary from warm identity.
- **State loss across rebuild:** exercise X/Y/cursor restoration through real `MainWindow` flows, not only the canvas API.
- **Stale queued callbacks after fail-closed recovery:** use the existing `clear()` lifecycle, which increments `_interaction_generation`, replaces timers, disconnects listeners, and clears dense-raster state.
- **Future documentation drift:** amend the normative performance standard and mark the exact historical empty-selection decision as superseded.
