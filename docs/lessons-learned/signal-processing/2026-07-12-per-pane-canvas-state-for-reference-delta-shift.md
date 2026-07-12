---
role: signal-processing
tags: [heatmap, manual-color-window, reference-delta, per-pane-state, canvas-encapsulation, split-pane, db-reference]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

## Context

Spec §8.3.1 requires a heatmap section's MANUAL z-window (`z_floor`/
`z_ceiling`) to shift by `delta = 20*log10(ref_old/ref_new)` whenever the
effective dB reference changes, so an already-tuned colour window keeps
tracking the (unclipped) shifted matrix instead of appearing black/blank.
`z_floor`/`z_ceiling` are View-level Inspector widgets shared by every pane,
but the dB reference is resolved PER PANE (`_resolve_db_reference_for_source`
per `(fid, ch)`), and a split view can render two panes with two DIFFERENT
references from one `do_fft_time()`/`do_order_time()` call — a naive
MainWindow/section-level "last known reference" ledger would either diff the
wrong pane's old value against a different pane's new one, or need duplicated
per-pane bookkeeping threaded through two mixins and their several call paths
(queue dispatch, cache-hit render, catalog-save rerender, worker-finished).

## Lesson

Since each pane already owns exactly one `PgHeatmapCanvas` instance, the
"reference the last render on THIS pane actually used" belongs on the canvas
itself, not on the window/mixin that drives it. `PgHeatmapCanvas.
reference_delta_since_last_render(new_ref)` stores `_last_db_reference` and
returns the delta (or `None` on first render / unchanged reference); every
call path that eventually calls the canvas's render method — regardless of
which mixin or trigger — gets a correct per-pane delta for free, with zero
extra dict/ledger state in `MainWindow`/`_analysis_mixin.py`.

## How to apply

When a per-pane display parameter needs "what was true on the LAST render of
this specific pane" to compute a diff/delta (auto-level writeback, a
reference-change shift, etc.) and the pane can be reached via multiple call
paths (split-queue dispatch, cache hit, external catalog/settings change,
worker-finished callback), store the tracking state as an attribute on the
per-pane canvas/widget object itself, not on the owning window or a
cross-cutting mixin — it is automatically pane-correct and requires no
additional wiring when a new call path is added later.
