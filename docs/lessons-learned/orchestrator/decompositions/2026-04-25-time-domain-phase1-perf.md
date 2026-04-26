# Decomposition: Time-Domain Plot Performance — Phase 1 (items 1–6)

Date: 2026-04-25
Source report: `docs/superpowers/reports/2026-04-25-time-domain-plot-performance-report.md`
User scope: only time-domain plot; skip order analysis and FFT.
Phase 1 items 1–6 only. Phase 2 / Phase 3 deferred.

## Routing summary

Two specialists touch the same shared file (`mf4_analyzer/ui/canvases.py`)
and one of them also touches `mf4_analyzer/ui/main_window.py`. Per
`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
the two tasks MUST run **serially**, not in parallel, and per
`orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
each brief MUST enumerate forbidden methods to keep the cross-specialist
edits boundary-disjoint and avoid spurious rework detection.

`refactor-architect` is NOT needed: there is no module relocation; both
specialists modify methods inside files that already own them.

## Subtasks

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| sp-envelope-core | signal-processing-expert | — | Pure numerical primitive: viewport-aware min/max envelope with bucketization, sorted min/max positions, monotonic searchsorted fast path, non-monotonic fallback (old `_ds()`), NaN handling per report (nanargmin/nanargmax, all-NaN bucket policy), and a tiny LRU envelope cache keyed by `(data_id, channel_name, quantized_xlim, pixel_width)`. Adds monotonicity-cache helper keyed by `(custom_xaxis_fid, custom_xaxis_ch)`. Statistics path is left untouched (must keep using original data). Owns: new `_envelope`, monotonicity cache, LRU cache structure, and the read-only refactor of the existing `_ds()` to call into the new envelope when xlim is known (or keep the legacy code path when not). Tests: TDD numerical tests for envelope correctness, NaN buckets, non-monotonic fallback, cache hit/miss, narrow-spike preservation. |
| ui-xlim-debounce-and-refresh | pyqt-ui-engineer | sp-envelope-core | UI plumbing only. Hooks the primary x-axis `xlim_changed` callback (single hookup in subplot mode since axes share x via `sharex`), debounces with a `QTimer` (30–50 ms), and force-flushes the pending refresh on `button_release_event` so end-of-pan/zoom frame is not held back. On debounce fire: pull current xlim + canvas pixel width, call `_envelope` for each visible channel, update lines via `line.set_data(x_ds, y_ds)`, then `draw_idle()`. Applies the three free rcParams (`path.simplify`, `path.simplify_threshold=0.8`, `agg.path.chunksize=10000`) once at canvas construction. Wires cache invalidation events listed in the report (file load, file close, channel edit applied, selected channels changed, custom-x change, range filter change, structural plot-mode change). Removes the array-copy hotspots in `MainWindow.plot_time()` (`fd.time_array` reference, `to_numpy(copy=False)`, conditional `custom_x.copy()`, only filter when range filter active) per report section "Avoid Unnecessary Copies", documenting the read-only convention for callers. Statistics path MUST remain on original (post-range-filter) data — never the envelope output. |

### Forbidden methods (per refactor-then-ui-same-file lesson)

`canvases.py`:
- `sp-envelope-core` may add `_envelope`, monotonicity-cache helpers, and an LRU cache class/dict; it may modify `_ds()` ONLY to delegate to the new envelope when the calling site supplies xlim, otherwise keep legacy behavior. It must NOT touch `plot_channels`, the `xlim_changed` connection, the `button_release_event` connection, the `SpanSelector`, cursor/blitting code, `set_tick_density`, `tight_layout` calls, `twinx` setup, `add_subplot`, or rcParams.
- `ui-xlim-debounce-and-refresh` owns: the `xlim_changed` hookup, `button_release_event` hookup, the `QTimer` debounce, the `line.set_data` refresh path, rcParams at canvas construction, and the cache-invalidation calls. It must NOT modify `_envelope`, the LRU cache class, the monotonicity-cache helpers, or the numerical math inside `_ds()`. If it needs a new method on the canvas (e.g. `_refresh_visible_data()`), that is allowed; the body must only call already-existing envelope/cache helpers from `sp-envelope-core`.

`main_window.py`:
- `ui-xlim-debounce-and-refresh` exclusively edits `plot_time` and the cache-invalidation hook sites (`_on_file_activated`, channel-edit apply, selected-channels-change, custom-x-change handler, range-filter-change handler, plot-mode-change handler). Must NOT touch FFT / order paths.
- `sp-envelope-core` does NOT touch `main_window.py` at all.

### Why serial, not parallel

Both subtasks edit `mf4_analyzer/ui/canvases.py`. Per
`2026-04-24-parallel-same-file-drawer-task-collision.md`, even small
shared-file edits race `git add`. Serial dispatch with the forbidden
list above keeps the boundary disjoint and avoids the commit-collision
pattern from Wave 9.

### Statistics-vs-envelope safeguard

`sp-envelope-core` brief explicitly forbids routing statistics through
the envelope output. The numerical TDD must include a test that locks
in: statistics over a channel after envelope is enabled equal
statistics over the same channel without envelope (within float eps).

### Cache invalidation contract

`sp-envelope-core` exposes:
- `invalidate_envelope_cache(reason: str, *, data_id=None, channel=None)`
- `invalidate_monotonicity_cache(custom_xaxis_fid=None, custom_xaxis_ch=None)`

`ui-xlim-debounce-and-refresh` calls these from the seven event sites.

## Skills the executor should invoke

- `superpowers:test-driven-development` before dispatching
  `sp-envelope-core` (numerical correctness, NaN edge cases, narrow
  spike preservation, non-monotonic fallback, cache hit/miss).
- `superpowers:verification-before-completion` before declaring
  `top_level_status: done` (run the existing test suite, plus a manual
  smoke check that initial plot appearance, cursors, span selection,
  and tick density are unchanged).

## Lessons consulted

- `docs/lessons-learned/README.md`
- `docs/lessons-learned/LESSONS.md`
- `docs/lessons-learned/.state.yml`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`

## Notes for the executor

- `refactor-architect` is intentionally NOT in the plan. There is no
  module relocation; both specialists work inside existing files. Do
  not add a relocation subtask unless `sp-envelope-core` flags one.
- Phase 2 (axes/Line2D reuse, tight_layout reduction, rubber-band
  blitting) is explicitly deferred per user. Do NOT let either
  specialist drift into it. If a specialist proposes structural-rebuild
  changes, treat as out-of-scope and re-scope.
- Mip-map (Phase 3) is fully out of scope.
