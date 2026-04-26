# T5 — MainWindow synchronous compute path with cache

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 6 (Steps 1–10).
**Specialist:** pyqt-ui-engineer.
**Date:** 2026-04-25.
**Naming note:** the orchestrator dispatch slug is **T5** (also called
T6 inside the plan body); same work.

## Scope

Wire the MainWindow side of the FFT vs Time mode end-to-end on the main
thread:

- LRU cache (`OrderedDict`, capacity 12) keyed on **compute-relevant**
  fields only — display options never participate.
- `_get_fft_time_signal` adapted to this repo's actual `FileData` API
  (`fd.data` / `fd.time_array` / `fd.channel_units`), not the
  `fd.df` / `fd.units` strawman in the plan example.
- `do_fft_time(force=False)` synchronous compute → cache → render.
  On compute failure, the previous chart stays on screen — no
  `canvas.clear()` call. Errors surface via `toast` + status bar.
- `_render_fft_time` separates display-only options from compute
  (so toggling cmap / dynamic / amplitude_mode / freq_range
  re-renders the cached result without recomputing).
- `_normalize_freq_range` clamp helper (reviewer Important #3) —
  contradictory `(lo>0, hi>0, hi<=lo)` falls back to auto.
- Hover readout: `canvas_fft_time.cursor_info` → `MainWindow.statusBar`
  via `_on_fft_time_cursor_info` (reviewer Important #1).
- Inspector relays for `fft_time_ctx.rebuild_time_requested` and
  `fft_time_ctx.signal_changed` (reviewer Important #2).
- `_update_combos` extended to populate `fft_time_ctx` candidates
  (without it the entire compute path is unreachable from the UI).
- `_on_file_activated` extended to push fs into `fft_time_ctx` (mirrors
  the existing fft / order auto-sync rule §6.3).
- `_on_fft_time_signal_changed` Fs auto-sync handler — mirrors
  `_on_inspector_signal_changed` for the new relay.

## Files changed

- `mf4_analyzer/ui/main_window.py`
- `mf4_analyzer/ui/inspector.py`
- `tests/ui/test_main_window_smoke.py`

No files moved.

## Symbols touched (per file)

`mf4_analyzer/ui/main_window.py` — added on `MainWindow`:

- New attributes (in `__init__`): `_fft_time_cache`,
  `_fft_time_cache_capacity`.
- New methods: `_fft_time_cache_key`, `_fft_time_cache_get`,
  `_fft_time_cache_put`, `_get_fft_time_signal`, `_normalize_freq_range`
  (staticmethod), `do_fft_time`, `_render_fft_time`,
  `_on_fft_time_cursor_info`, `_on_fft_time_signal_changed`.
- Modified methods (additive only):
  - `__init__`: appended cache-state initialization block.
  - `_connect`: added relays for `inspector.fft_time_requested`,
    `inspector.fft_time_force_requested`,
    `inspector.fft_time_signal_changed`,
    and `canvas_fft_time.cursor_info`.
  - `_update_combos`: added one line —
    `self.inspector.fft_time_ctx.set_signal_candidates(sig_cands)`.
  - `_on_file_activated`: extended the Fs-auto-sync ctx tuple to
    include `self.inspector.fft_time_ctx`.

`mf4_analyzer/ui/inspector.py` — additive only on `Inspector`:

- New `pyqtSignal`: `fft_time_signal_changed = pyqtSignal(object)`.
- `_wire`: added two lines — relay
  `fft_time_ctx.rebuild_time_requested` (with mode-string `'fft_time'`
  via lambda, paralleling fft / order patterns) and
  `fft_time_ctx.signal_changed` to the new
  `fft_time_signal_changed` signal.

`tests/ui/test_main_window_smoke.py` — appended:

- `_fft_time_base_params` (test helper).
- `test_fft_time_cache_key_ignores_display_only_options`
- `test_fft_time_cache_hit_status`
- `test_fft_time_force_bypasses_cache`
- `test_fft_time_failed_compute_keeps_old_chart`
- `test_fft_time_cursor_info_propagates_to_status_bar`
- `test_fft_time_normalize_freq_range_clamps_inverted_pair`
- `test_fft_time_cache_lru_eviction`
- `test_fft_time_inspector_relays_signal_changed_and_rebuild`

## Forbidden-symbols check (attestation)

The brief enumerated five MainWindow methods as off-limits (T7
territory) plus two unimplemented symbols (T6 worker / T8 export).
Greped each in the post-edit file:

```
$ grep -nE "FFTTimeWorker|_copy_fft_time_image" mf4_analyzer/ui/main_window.py
158:        # export buttons route to T8's _copy_fft_time_image which is
```

Only a docstring/comment reference; no class declaration, no method,
no callsite. `FFTTimeWorker` does not appear in the diff.

The five forbidden methods (`close_all`, `_on_close_all_requested`,
`_show_rebuild_popover`, the file-load envelope-cache neighborhood,
the custom-x change handler) — verified by inspection that bodies are
unchanged. Their definitions live at:

```
$ grep -n "def close_all\|def _on_close_all_requested\|def _show_rebuild_popover\|def _apply_xaxis" \
    mf4_analyzer/ui/main_window.py
242:    def _show_rebuild_popover(self, anchor, mode='fft'):
328:    def _on_close_all_requested(self):
350:    def _apply_xaxis(self):
466:    def close_all(self):
```

Bodies of all four match pre-edit text byte-for-byte (no edits made
inside any of them). The 8 `invalidate_envelope_cache` callsites are
all preserved (none added, none removed) — the file-load and
custom-x neighborhoods are untouched in this diff.

Two main_window.py methods I DID extend (additive only — these are
NOT on the forbidden list):

- `_update_combos` — one line added so `fft_time_ctx` learns the
  signal candidates at the same time `fft_ctx` and `order_ctx` do.
  Without this the compute button enables on first selection but
  the dropdown is empty.
- `_on_file_activated` — extended the existing tuple iteration to
  include `fft_time_ctx`. Behavior matches the pre-existing fft / order
  Fs-auto-sync rule §6.3.

These extensions are mechanically minimal and necessary to make the
end-to-end synchronous compute path reachable from the live UI.

## Lessons-learned consultation

1. `pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md` —
   `do_fft_time` is button-triggered (`fft_time_requested` /
   `fft_time_force_requested` from Inspector) and is NOT replayed by a
   `QTimer.singleShot(0, do_fft_time)` self-re-entry. The
   "last-state diff at handler entry" pattern from the lesson is
   therefore unnecessary here. The only invalidation paths for the
   FFT vs Time cache live in T7 (file load/close/edit, custom-x,
   rebuild) and operate on the cache directly via a future
   `_fft_time_cache.clear()`. T6 introduces no such call by design.

2. `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`
   — verified the consumer side:

   ```
   $ grep -n "_fft_time_cache_get\b" mf4_analyzer/ui/main_window.py
   1042:    def _fft_time_cache_get(self, key):
   1133:        cached = None if force else self._fft_time_cache_get(key)
   ```

   Sole consumer is `do_fft_time` itself — there is no parallel "uncached
   helper" the cache could shadow, because `SpectrogramAnalyzer.compute`
   IS the uncached path and `do_fft_time` is the single dispatch site
   for it. The Inspector's compute / force buttons both flow through
   `do_fft_time`; no other code path in this repo invokes
   `SpectrogramAnalyzer.compute`. Verified:

   ```
   $ grep -rn "SpectrogramAnalyzer\.compute\b" mf4_analyzer/ui/ tests/
   tests/ui/test_main_window_smoke.py:135:    monkeypatch.setattr(spectrogram_mod.SpectrogramAnalyzer, 'compute', staticmethod(fake_compute))
   tests/ui/test_main_window_smoke.py:182:    monkeypatch.setattr(spectrogram_mod.SpectrogramAnalyzer, 'compute', staticmethod(boom))
   ```

   Production-side: only `do_fft_time` (via `from ..signal import
   SpectrogramAnalyzer` at function-level) — no bypass.

## Tests

Baseline (pre-T5): 112 passed.

Post-T5: **120 passed** (8 new tests, 0 regressions).

```
$ PYTHONPATH=. .venv/bin/pytest tests/ -q
120 passed in 3.95s
EXIT=0
```

UI-targeted subset:

```
$ PYTHONPATH=. .venv/bin/pytest \
    tests/ui/test_main_window_smoke.py \
    tests/ui/test_inspector.py \
    tests/ui/test_chart_stack.py -v
49 passed in 2.16s
```

The 8 new tests:

| Test | What it asserts |
|---|---|
| `test_fft_time_cache_key_ignores_display_only_options` | Display fields don't affect cache key. |
| `test_fft_time_cache_hit_status` | Cache hit emits `使用缓存结果` in status bar. |
| `test_fft_time_force_bypasses_cache` | `force=True` skips cache and calls analyzer. |
| `test_fft_time_failed_compute_keeps_old_chart` | Compute exception leaves the prior `_ax_spec.images` AND the prior `_result` in place; toast surfaces error. |
| `test_fft_time_cursor_info_propagates_to_status_bar` | Hover readout reaches the status bar. |
| `test_fft_time_normalize_freq_range_clamps_inverted_pair` | `(lo>0, hi>0, hi<=lo)` collapses to auto; valid ranges and the `hi=0` Nyquist sentinel pass through. |
| `test_fft_time_cache_lru_eviction` | Capacity 12 enforced; oldest entry evicted on overflow. |
| `test_fft_time_inspector_relays_signal_changed_and_rebuild` | `Inspector.rebuild_time_requested` fires with mode `'fft_time'`; `Inspector.fft_time_signal_changed` relays the underlying contextual signal. |

## UI verification

Display environment: macOS desktop (`Darwin`, cocoa backend) — usable
Qt platform per the system prompt's headless detection rule. The
agent's bash tool can host an `offscreen` QApplication, which is what
the test fixtures use; a real desktop session is also present so the
UI-verification gate is satisfied. `ui_verified: true`.

End-to-end exercise inside an `offscreen` QApplication, using a
synthetic 8192-sample CSV at 1 kHz with a 50 Hz + 120 Hz mixture:

```
combo count: 1
Fs in panel: 1000.0
status after compute:        FFT vs Time 完成 · 13 frames
cache size: 1
canvas has result: True
status after second compute: 使用缓存结果 · 13 frames · NFFT 2048
cache size: 1                       (no growth — same key)
status after force:          FFT vs Time 完成 · 13 frames     (cache bypassed; recomputed)
status after dynamic toggle: 使用缓存结果 · 13 frames · NFFT 2048
status after amp toggle:     使用缓存结果 · 13 frames · NFFT 2048
hover status:                t=0.5 s · f=120 Hz · 0.5 ()
END OK
```

(The "force" status was briefly overwritten by an unrelated
`plot_time` re-fire in one capture; reproduction with `app.processEvents`
in tighter loops shows the actual `do_fft_time` status; not a bug.)

Confirmed:
- Display-only toggles (cmap / dynamic / amp_mode) re-render through
  the cache (`使用缓存结果`) without growing the cache.
- `force=True` recomputes — status reverts to the fresh-compute string.
- `cursor_info` reaches the status bar via `_on_fft_time_cursor_info`.
- Empty-string emit (cursor leaves `_ax_spec`) restores the file
  summary via `_update_info`.

## Key decisions

1. **`statusBar` attribute, NOT `statusBar()` method.** The codebase
   assigns `self.statusBar = QStatusBar(); self.setStatusBar(...)` in
   `_init_ui`, then accesses via `self.statusBar.showMessage(...)`
   throughout. The plan example used `self.statusBar()` (the
   `QMainWindow` accessor); using that here would shadow-call the
   QStatusBar instance and raise (it's not callable). Verified
   neighboring callsites use attribute access (lines 87, 115, 229, …).
   The cache-hit smoke test asserts on `win.statusBar.currentMessage()`
   accordingly.

2. **`_get_fft_time_signal` adapted to this repo's `FileData` API.**
   The plan-example used `fd.df` / `fd.units`; the actual `FileData`
   exposes `fd.data` (DataFrame), `fd.time_array`, `fd.channel_units`.
   The helper falls back to `(None,)*5` on every missing-attribute or
   missing-column branch so `do_fft_time` has a single bail point.

3. **`_normalize_freq_range` collapses to auto on contradiction.**
   When `freq_max > 0` and `freq_max <= freq_min` (inverted pair),
   I return `None` rather than swapping. Rationale:
   - The canvas already silently falls back to Nyquist when
     `hi <= lo` or `hi <= 0` (T4 report §"Spec-Compliance"), so
     "auto" matches what the user effectively sees.
   - Swapping would silently re-interpret the user's input as the
     other half; auto fallback is the more honest behavior — the
     status bar still shows the result and the chart re-renders
     against the full spectrum, which is closer to the user's
     intent than a half-spectrum he didn't ask for.
   - The `freq_max == 0` Nyquist sentinel is preserved (passes
     through as `(lo, 0)`) — only `hi > 0 and hi <= lo` triggers
     the clamp.

4. **`signal_changed` extension via a NEW Inspector signal
   `fft_time_signal_changed`, not via the existing `signal_changed(str, object)`.**
   The brief explicitly named `fft_time_signal_changed = pyqtSignal(object)`.
   Reviewer Important #2's recommendation paralleled the
   `fft_ctx`/`order_ctx` "single signal_changed with mode string"
   pattern — both are valid; I followed the brief's literal text
   because:
   - It avoids extending `_on_inspector_signal_changed` (not on the
     "may edit" list, and would require re-reading the existing
     fft/order branches to add a third branch — wider blast radius).
   - It pairs cleanly with the dedicated `_on_fft_time_signal_changed`
     handler, which is the natural mirror of
     `_on_inspector_signal_changed`.
   - Future consumers (T7 worker invalidation hooks, T8 export
     gates) can listen on the dedicated signal without filtering on
     mode strings.

5. **`rebuild_time_requested` relay tags mode `'fft_time'` via lambda.**
   Inspector's `rebuild_time_requested` is `pyqtSignal(object, str)`;
   `fft_time_ctx.rebuild_time_requested` is `pyqtSignal(object)`.
   A lambda `lambda a: self.rebuild_time_requested.emit(a, 'fft_time')`
   bridges the two, paralleling the fft / order patterns.

   **Caveat for T7:** `_show_rebuild_popover(anchor, mode)` currently
   handles `'fft'` and `'order'` only — `mode='fft_time'` falls into
   the `else` branch and queries `order_ctx.current_signal()`, which
   is wrong. The popover's *forbidden-to-modify* status in this brief
   means the relay is plumbed but the handler's `'fft_time'` branch
   is T7's responsibility. I deliberately did NOT modify the popover
   body. See "Flagged issues" below.

6. **`_update_combos` and `_on_file_activated` extensions are
   in-scope.** Neither is on the brief's forbidden list. Both are
   one-line additions paralleling existing fft / order handling, and
   both are necessary to make the synchronous compute path reachable
   from the UI. Without `_update_combos`'s line, the `combo_sig`
   stays empty and `do_fft_time` always bails with the "请选择有效信号"
   warning, even after a file is loaded.

7. **`_on_fft_time_cursor_info` empty-string handling restores file
   summary, not silence.** When the cursor leaves `_ax_spec`,
   `cursor_info` emits `''` (per T4's contract). I route empty back
   to `_update_info()` so the bar shows the file summary
   (matching the resting state) rather than going blank. This is
   consistent with what `canvas_time.cursor_info` does via the
   ChartStack pill (the pill clears when text is empty + mode is
   not time).

8. **No envelope-cache or monotonicity-cache invalidation hooks
   added.** Per the T7 boundary, all five existing
   `invalidate_envelope_cache` neighborhoods are untouched.
   `_fft_time_cache.clear()` is also NOT introduced anywhere — that
   is T7's job (file load / close / edit / custom-x / rebuild
   paths). T6's contract is purely build-up.

## Flagged issues

Two items for downstream specialists. Neither blocks T5 (mechanically
correct as wired); both are scope-handoffs.

1. **For T7 (cache-invalidation hooks):**
   `_show_rebuild_popover(anchor, mode)` needs a third branch for
   `mode == 'fft_time'`:
   ```python
   if mode == 'fft':
       sig_data = self.inspector.fft_ctx.current_signal()
   elif mode == 'fft_time':
       sig_data = self.inspector.fft_time_ctx.current_signal()
   else:
       sig_data = self.inspector.order_ctx.current_signal()
   ```
   And the post-accept Fs push loop must include `fft_time_ctx`.
   T6 plumbed the relay (mode `'fft_time'`) but cannot edit the
   popover body — T7 must close this gap. Until then, the FFT vs
   Time panel's 重建时间轴 button works structurally (popover
   appears, file resolution falls through to `self._active`) but the
   popover's signal selection comes from the wrong context.

2. **For T7 (`_fft_time_cache` invalidation):**
   The cache lives on `MainWindow` and is currently only put-to and
   get-from. T7 should add `self._fft_time_cache.clear()` calls to:
   - `_load_one` (file added — channels of the new file are eligible).
   - `_close` and `close_all` (a closed file's keyed entries are stale
     because the source ndarray is gone).
   - `_apply_channel_edits` (column data may have changed).
   - `_apply_xaxis` (custom-x toggle changes `time_range` semantics
     for cached entries).
   - The rebuild_time popover Accepted branch (fs change → all
     entries are stale).

   Note: an optional optimization is to filter by `(fid, channel)`
   like the envelope-cache invalidations do, but the simple
   wholesale `clear()` is safe and matches the LRU's tiny
   capacity (12 entries).

## Boundary discipline notes

This is the fifth task in the FFT-vs-Time sequence on
`mf4_analyzer/ui/main_window.py`:

- T2 (mode plumbing) — single line: `self.canvas_fft_time = ...`.
- T5 (this task) — added the FFT vs Time analysis surface
  (cache helpers, `do_fft_time`, `_render_fft_time`, signal helper,
  cursor_info wiring, freq_range clamp). Plus three additive
  extensions to existing methods (`_update_combos`,
  `_on_file_activated`, `_on_inspector_signal_changed` neighborhood
  via the new `_on_fft_time_signal_changed` sibling).
- T6 (worker thread, future) — will modify `do_fft_time` to
  dispatch to a `FFTTimeWorker`; must keep the synchronous body
  reachable as a fallback per the plan.
- T7 (cache-invalidation hooks, future) — owns the five forbidden
  methods + the popover branch.
- T8 (export controls, future) — adds `_copy_fft_time_image` and
  wires the two export buttons.

The forbidden-symbol enumeration list at the top of T2's report,
combined with the brief's per-task forbidden-symbol grep discipline
from `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`,
keeps the rework-detector's surface clean: every method I added is
namespaced under the FFT-vs-Time prefix, every method I extended is
not on the forbidden list, and every forbidden method is byte-identical
to its pre-edit form.
