# T7 — FFT vs Time cache invalidation hooks + popover mode-routing

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 8 (Steps 1-5).
**Specialist:** refactor-architect.
**Date:** 2026-04-25.
**Naming note:** the orchestrator dispatch slug is **T7** (also called
T8 inside the plan body); same work. Same naming-vs-slug skew as T5/T6.

## Scope

Close out the cache-invalidation half of the FFT vs Time feature:

- New helper `_fft_time_cache_clear_for_fid(fid)` — drops every
  OrderedDict entry whose `key[0] == fid`. Used by per-file
  invalidation hooks where wiping the entire cache would be wasteful
  (other files' results stay valid).
- Wired `self._fft_time_cache.clear()` (or the targeted helper) at
  the seven canonical state-change sites listed below.
- Closed the T5-flagged gap in `_show_rebuild_popover(anchor, mode)`:
  added a `mode == 'fft_time'` branch that resolves `sig_data` via
  `inspector.fft_time_ctx.current_signal()` and extends the post-accept
  Fs push loop to include `fft_time_ctx` so the panel's Fs spinbox
  stays in sync after a rebuild.

No algorithm bodies were modified. No public symbols were renamed.

## Files changed

- `mf4_analyzer/ui/main_window.py`
- `tests/ui/test_main_window_smoke.py`

No files moved.

## Symbols touched

`mf4_analyzer/ui/main_window.py`:

New method on `MainWindow`:

- `_fft_time_cache_clear_for_fid(self, fid)` — added between
  `_fft_time_cache_put` (line 1156) and `_get_fft_time_signal` (now line
  1178). Iterates `self._fft_time_cache`, pops any key with `k[0] == fid`.

Modified methods (additive — new lines only, no behavior change to
existing code paths):

- `_show_rebuild_popover` (line 301) — added an `elif mode == 'fft_time'`
  branch reading `inspector.fft_time_ctx.current_signal()`; added a
  per-fid cache clear after `fd.rebuild_time_axis(new_fs)`; extended
  the Fs-push tuple `(fft_ctx, order_ctx)` to include `fft_time_ctx`.
- `_on_close_all_requested` (line 402) — prepended `self._fft_time_cache.clear()`
  before `self.close_all()`.
- `_apply_xaxis` (line 409) — added wholesale `self._fft_time_cache.clear()`
  after the existing envelope/monotonicity invalidations (custom-x
  semantics shift `time_range` interpretation across all fids).
- `_load_one` (line 466) — added `self._fft_time_cache_clear_for_fid(fid)`
  after the envelope/monotonicity invalidations and before
  `_update_combos`.
- `_close` (line 506) — added `self._fft_time_cache_clear_for_fid(fid)`
  after the envelope/monotonicity invalidations and before
  `del self.files[fid]`.
- `close_all` (line 525) — added wholesale `self._fft_time_cache.clear()`
  alongside the existing envelope/monotonicity wipes.
- `_apply_channel_edits` (line 721) — added
  `self._fft_time_cache_clear_for_fid(fid)` at the top of the body,
  before the per-channel envelope-cache invalidation loop.

`tests/ui/test_main_window_smoke.py` — appended three tests under a
new `# FFT vs Time cache invalidation hooks (Plan Task 8)` section:

- `test_fft_time_cache_clears_on_close_all`
- `test_fft_time_cache_clears_for_fid_on_rebuild`
- `test_fft_time_rebuild_popover_resolves_signal_via_fft_time_ctx`

## Hook-site enumeration

Per the cache-consumer-grep lesson: every site in `main_window.py`
that touches `_fft_time_cache` post-T7, with line numbers and which
specialist owns the body:

| Line | Site | Operation | Owner |
|------|------|-----------|-------|
| 98 | `__init__` (init) | `OrderedDict()` allocation | T5 |
| 99 | `__init__` (init) | capacity = 12 | T5 |
| 332 | `_show_rebuild_popover` | `_clear_for_fid(target_fid)` (NEW) | T7 |
| 408 | `_on_close_all_requested` | `.clear()` (NEW) | T7 |
| 471 | `_apply_xaxis` | `.clear()` (NEW) | T7 |
| 516 | `_load_one` | `_clear_for_fid(fid)` (NEW) | T7 |
| 549 | `_close` | `_clear_for_fid(fid)` (NEW) | T7 |
| 566 | `close_all` | `.clear()` (NEW) | T7 |
| 764 | `_apply_channel_edits` | `_clear_for_fid(fid)` (NEW) | T7 |
| 1128 | `_fft_time_cache_key` (def) | producer | T5 (untouched) |
| 1147 | `_fft_time_cache_get` (def) | producer | T5 (untouched) |
| 1156 | `_fft_time_cache_put` (def) | producer | T5 (untouched) |
| 1164 | `_fft_time_cache_clear_for_fid` (def) | producer (NEW) | T7 |
| 1269-1270 | `do_fft_time` | cache-key build + GET | T5 (untouched) |
| 1369 | `_on_fft_time_finished` | PUT | T6 (untouched) |

The brief asked for five hook sites; I added seven because:

- `_close` (single-file close) was an explicit T5 recommendation
  ("`_close + close_all`") and the brief instructed to add it as a
  sixth site if it existed in the codebase. It does (line 506).
- `_apply_channel_edits` was also in T5's flag (`_apply_channel_edits
  (columns mutated)`); the brief instructed to include it as a sixth
  site if it actually exists. It does (line 721).

So with `_load_one`, `_close`, `close_all`, `_on_close_all_requested`,
`_apply_xaxis`, `_show_rebuild_popover` Accepted branch, and
`_apply_channel_edits`, the count is seven. Cache key shape stays
`(fid, channel, time_range_tuple, fs, nfft, window, overlap,
remove_mean, db_reference)` per T5; `key[0]` is the fid; helper
matches.

## Forbidden-symbols check (attestation)

Greped post-edit:

```
$ grep -n "def do_fft_time\|def _render_fft_time\|def _get_fft_time_signal\|def _normalize_freq_range\|def _on_fft_time_cursor_info\|def _on_fft_time_signal_changed" mf4_analyzer/ui/main_window.py
363:    def _on_fft_time_signal_changed(self, data):
1178:    def _get_fft_time_signal(self):
1202:    def _normalize_freq_range(p):
1230:    def do_fft_time(self, force=False):
1329:    def _render_fft_time(self, result, p):
1344:    def _on_fft_time_cursor_info(self, text):

$ grep -n "class FFTTimeWorker\|def _on_fft_time_finished\|def _on_fft_time_failed\|def _on_fft_time_progress\|def _on_fft_time_thread_done" mf4_analyzer/ui/main_window.py
28:class FFTTimeWorker(QObject):
1358:    def _on_fft_time_finished(self, result):
1376:    def _on_fft_time_failed(self, message):
1391:    def _on_fft_time_progress(self, current, total):
1403:    def _on_fft_time_thread_done(self):

$ grep -n "def _fft_time_cache_key\|def _fft_time_cache_get\|def _fft_time_cache_put" mf4_analyzer/ui/main_window.py
1128:    def _fft_time_cache_key(self, params):
1147:    def _fft_time_cache_get(self, key):
1156:    def _fft_time_cache_put(self, key, result):

$ grep -n "_copy_fft_time_image" mf4_analyzer/ui/main_window.py
217:        # export buttons route to T8's _copy_fft_time_image which is
```

Bodies of all T5/T6 forbidden methods are byte-identical to their
post-T6 form (verified by reading the surrounding lines). No
`_copy_fft_time_image` method was introduced — only the comment from
T5 still references it; left as-is per the optional-cleanup nit (the
next task — export controls — will overwrite that comment when it
adds the actual method).

The new helper `_fft_time_cache_clear_for_fid` is namespaced under
the FFT-vs-Time prefix and does not collide with any T5/T6 symbol.

## Tests

Baseline (post-T6): 122 passed.

Post-T7: **125 passed** (3 new tests, 0 regressions).

```
$ PYTHONPATH=. .venv/bin/pytest tests/ -q
........................................................................ [ 57%]
.....................................................                    [100%]
125 passed in 4.10s
```

Smoke-test subset:

```
$ PYTHONPATH=. .venv/bin/pytest tests/ui/test_main_window_smoke.py -v
21 passed in 1.60s
```

The 3 new tests:

| Test | What it asserts |
|---|---|
| `test_fft_time_cache_clears_on_close_all` | Pre-seeds the cache with one entry, primes `self.files` so `close_all`'s body runs (it early-returns when `files` is empty), and asserts the cache is empty after `close_all()`. |
| `test_fft_time_cache_clears_for_fid_on_rebuild` | Pre-seeds entries for fids `f1` and `f2`; calls `_fft_time_cache_clear_for_fid('f1')`; asserts `f1`'s key is gone and `f2`'s remains. |
| `test_fft_time_rebuild_popover_resolves_signal_via_fft_time_ctx` | Spies on `current_signal` for all three contextuals, calls `_show_rebuild_popover(anchor=None, mode='fft_time')` with a stub popover that returns Rejected, asserts `fft_time_ctx.current_signal` was queried and the `fft_ctx` / `order_ctx` ones were not. Closes T5's flagged mode-routing gap. |

## Key decisions

1. **Targeted clear vs wholesale clear.** Three sites use the targeted
   `_fft_time_cache_clear_for_fid(fid)` helper:
   - `_load_one` — the freshly added file's fid is known.
   - `_close` — the single-file close path knows its fid.
   - `_apply_channel_edits` — the edit drawer is bound to a single
     fid.
   - `_show_rebuild_popover` Accepted branch — `target_fid` is
     resolved before the rebuild.

   Four sites use wholesale `.clear()`:
   - `close_all` — every entry is dead by definition.
   - `_on_close_all_requested` — defensive duplicate so future
     refactors that bypass `close_all` still wipe.
   - `_apply_xaxis` — custom-x changes `time_range` semantics across
     all currently-loaded fids; the cache (cap 12) is too small for
     a per-fid sweep to outperform a wipe.

   Targeted clears avoid the worst case where (e.g.) the user closes
   one of three files and would lose two unrelated cached results.

2. **`_on_close_all_requested` defensive duplicate.** This method
   currently delegates to `close_all()`, which already wipes. The
   brief and the plan list `_on_close_all_requested` as its own site,
   so I added a duplicate `.clear()` before the delegation. Cost is
   one no-op call when the cache is already empty; benefit is a
   future-proof invariant — if a maintainer changes
   `_on_close_all_requested` to do a partial close instead of full
   `close_all`, the cache wipe still fires.

3. **`_show_rebuild_popover` mode branch shape.** I extended the
   existing `if/else` to `if/elif/else`:

   ```python
   if mode == 'fft':
       sig_data = self.inspector.fft_ctx.current_signal()
   elif mode == 'fft_time':
       sig_data = self.inspector.fft_time_ctx.current_signal()
   else:
       sig_data = self.inspector.order_ctx.current_signal()
   ```

   Pre-T7 the `else` branch silently captured `mode='fft_time'` and
   queried `order_ctx` — wrong context, but structurally non-fatal
   because the fall-through to `self._active` masked it. Post-T7 the
   panel's signal selection drives the popover.

4. **Fs-push loop extended to `fft_time_ctx`.** The post-accept loop
   in the popover walked `(fft_ctx, order_ctx)` only. T5's
   `_on_file_activated` already added `fft_time_ctx` to the
   activation Fs-push tuple; the rebuild Fs-push is the symmetric
   site (an Fs change for the active file should propagate to
   whichever ctx points at that file). The brief named this site
   explicitly: "the popover's post-accept Fs push loop must also
   include fft_time_ctx".

5. **`_apply_xaxis` wholesale clear, even though FFT vs Time uses
   `fd.time_array` not custom-x.** Strictly speaking, the FFT vs Time
   compute path reads `fd.time_array` directly (per T5's
   `_get_fft_time_signal`) and ignores the custom-x state, so
   custom-x changes do NOT invalidate cached SpectrogramResults. But
   T5 explicitly flagged `_apply_xaxis` as a hook site, and the
   plan body lists it. I followed T5's recommendation literally
   ("the simple wholesale `clear()` is safe and matches the LRU's
   tiny capacity") rather than skipping the site on a correctness
   argument. Cost: cap-12 LRU wiped on a button click. The decision
   trades a small efficiency loss for a tighter "if state-shift
   touches any of these methods, the cache is dropped" invariant.

6. **No invalidation inside `do_fft_time` itself.** Per the
   `cache-invalidation-event-conditional` lesson, invalidation must
   be tied to STATE-CHANGE events, not handler entry. `do_fft_time`
   is the consumer; its job is to read/PUT the cache, not invalidate
   it. The seven hook sites are all state-change sites (file added,
   file removed, columns mutated, custom-x changed, fs changed via
   rebuild). None are inside paint paths or `QTimer.singleShot`
   replay paths.

## Lessons-learned consultation

1. `pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md` —
   applied directly: invalidation is gated on the STATE-CHANGE
   methods (`_load_one`, `_close`, `close_all`,
   `_on_close_all_requested`, `_apply_xaxis`,
   `_apply_channel_edits`, `_show_rebuild_popover` Accepted branch)
   and never inside `do_fft_time`, `_render_fft_time`, or any paint
   path. The handler-replay trap that bit the envelope cache does
   not apply here because `do_fft_time` is button-triggered (T5
   noted the same in their lessons-learned section).

2. `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`
   — applied: the report's "Hook-site enumeration" table greps every
   `_fft_time_cache` reference in `main_window.py` and labels the
   producer / consumer / new-invalidation-call columns. The next
   reviewer can verify completeness by re-running the same grep and
   matching the row count.

3. `refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md`
   — not applicable; no cross-layer constants moved.

## Boundary discipline notes

This is the seventh task in the FFT-vs-Time sequence on
`mf4_analyzer/ui/main_window.py`:

- T2 (mode plumbing) — single line: `self.canvas_fft_time = ...`.
- T3 (FFTTimeContextual) — UI panel only; no main_window touches.
- T4 (SpectrogramCanvas) — canvas only; no main_window touches.
- T5 (synchronous compute + cache helpers) — added cache, helpers,
  `do_fft_time`, `_render_fft_time`, etc.
- T6 (worker thread) — added `FFTTimeWorker`, replaced cache-miss
  branch of `do_fft_time` with worker dispatch.
- T7 (this task — cache invalidation + popover mode routing) —
  added `_fft_time_cache_clear_for_fid` helper, seven invalidation
  call-sites, `_show_rebuild_popover` `fft_time` branch + Fs push.
- T8 (export controls — future) — adds `_copy_fft_time_image` and
  the export-button connections (overwrites the line-217 comment).

Per-task forbidden-symbol grep discipline keeps the rework-detector's
surface clean: every method I added is namespaced under the
FFT-vs-Time prefix; every forbidden T5/T6 method body is
byte-identical to its post-T6 form; the only extension to a
state-change method (`_show_rebuild_popover`) is the elif branch +
two-line cache-clear + tuple extension, all additive.

## UI verification

Display environment: macOS desktop (`Darwin`), `offscreen` Qt
platform usable for end-to-end fixture exercises. The full pytest
run drives the new tests through `qtbot.addWidget` so they exercise
the real `MainWindow` widget tree and real `Inspector` contextuals.

The third new test
(`test_fft_time_rebuild_popover_resolves_signal_via_fft_time_ctx`)
spies on each contextual's `current_signal` and asserts only
`fft_time_ctx` is queried for `mode='fft_time'`. This is the
post-edit behavior; pre-T7 the test would FAIL because the `else`
branch would call `order_ctx.current_signal` instead.

## Flagged issues

None for downstream specialists. T7's contract is fully delivered
within the brief's scope.

One informational note for the export task (T8 in plan body /
T9-by-slug):

- The line-217 comment (`# export buttons route to T8's
  _copy_fft_time_image which is...`) is intentionally left as-is.
  The export task will overwrite that comment when it adds the
  `_copy_fft_time_image` method body and wires the buttons. No
  action required from T7.

## Lessons added

None. The task surfaced no novel insight worth a new lesson:

- The `_clear_for_fid` helper pattern is straightforward and matches
  the `data_id`-keyed invalidation pattern already used by
  `canvas_time.invalidate_envelope_cache(data_id=fid)`.
- The seven hook sites are all standard "state-change → drop derived
  cache" applications of the existing
  `cache-invalidation-event-conditional` lesson.
- The popover mode-routing gap was a one-off boundary leak from T5
  (T5 plumbed the relay but couldn't edit the popover body); the
  fix is mechanically obvious once the gap is named.

If the next reviewer finds a non-obvious wrinkle in the per-fid
clear semantics or the popover mode routing, that's lesson-worthy;
nothing surfaced during this task.
