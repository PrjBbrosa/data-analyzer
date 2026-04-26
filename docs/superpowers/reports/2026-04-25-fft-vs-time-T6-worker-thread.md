# T7 — FFT vs Time worker thread

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 7 (Steps 1-6).
**Specialist:** pyqt-ui-engineer.
**Date:** 2026-04-25.
**Naming note:** the orchestrator dispatch slug is **T6** (also called
T7 inside the plan body); same work. Same naming-vs-slug skew as T5.

## Scope

Move the FFT-vs-Time compute off the GUI thread:

- Introduce `FFTTimeWorker(QObject)` with `progress(int,int)`,
  `finished(object)`, `failed(str)` signals and `cancel()` / `run()`
  methods. `run()` calls `SpectrogramAnalyzer.compute(...,
  progress_callback=self.progress.emit, cancel_token=lambda:
  self._cancelled)`.
- Rewrite the cache-miss branch of `do_fft_time` to dispatch the
  worker on a `QThread`. Cache hits stay synchronous (no thread
  needed; render is one matplotlib call).
- Re-entry guard: if `_fft_time_thread.isRunning()`, status shows
  `'正在计算…'` and `do_fft_time` returns without enqueueing a
  second worker (Phase 1 ignores; T9 will queue or cancel).
- Result handling moved to `_on_fft_time_finished` (cache PUT +
  render + status) and `_on_fft_time_failed` (toast + status, no
  canvas.clear). Synchronous fallback is removed — there is one
  path now.
- Cleanup chain: `worker.finished/failed -> thread.quit ->
  worker.deleteLater + thread.deleteLater + _on_fft_time_thread_done`.
  Refs cleared in `_on_fft_time_thread_done` so the next click
  dispatches a fresh worker.

## Files changed

- `mf4_analyzer/ui/main_window.py`
- `tests/ui/test_main_window_smoke.py`

No files moved.

## Symbols touched

`mf4_analyzer/ui/main_window.py`:

New module-level class:

- `FFTTimeWorker(QObject)` with `progress`, `finished`, `failed`
  signals and `__init__`, `cancel`, `run` methods.

New attributes on `MainWindow.__init__`:

- `self._fft_time_thread` (QThread or None)
- `self._fft_time_worker` (FFTTimeWorker or None)
- `self._fft_time_pending` (dict[str, Any], set per-dispatch in
  `do_fft_time`; carries `cache_key` and `render_params` from
  the GUI thread to `_on_fft_time_finished`).

New methods on `MainWindow`:

- `_on_fft_time_finished(result)` — cache PUT + render + status.
- `_on_fft_time_failed(message)` — toast + status, NO canvas.clear.
- `_on_fft_time_progress(current, total)` — Phase 1 no-op; reserved
  for T9 progress UI.
- `_on_fft_time_thread_done()` — clears `_fft_time_thread` and
  `_fft_time_worker` refs after the QThread emits `finished`.

Modified method (compute branch only):

- `do_fft_time(force=False)` — cache hit branch unchanged from T5
  (synchronous render + `使用缓存结果` status). Cache miss branch
  rewritten to build a `FFTTimeWorker`, move it to a `QThread(self)`,
  wire the cleanup chain, and `thread.start()`. Re-entry guard added
  at the very top: `if self._fft_time_thread is not None and
  self._fft_time_thread.isRunning(): showMessage('正在计算…'); return`.

`tests/ui/test_main_window_smoke.py`:

New tests:

- `test_fft_time_worker_emits_finished` — happy-path smoke; runs a
  small spectrogram on a real `QThread` and asserts `finished`
  carries a result with at least one frame.
- `test_fft_time_worker_cancels` — overlap=0.9 + 200k samples; calls
  `worker.cancel()` immediately after `thread.start()`; asserts the
  resulting `failed` message contains the substring `'cancel'`
  (analyzer raises `RuntimeError('spectrogram computation
  cancelled')`).

Updated tests (T7 forced the rewrite — see "Key decisions" #4):

- `test_fft_time_force_bypasses_cache` — `qtbot.waitUntil(lambda:
  win._fft_time_thread is None, timeout=5000)` after
  `do_fft_time(force=True)` so the worker drains before the
  status-bar assert.
- `test_fft_time_failed_compute_keeps_old_chart` — same waitUntil
  pattern; the `_on_fft_time_failed` slot is queued from worker to
  main thread, so the assert otherwise races the chart.

## Forbidden-symbols check (attestation)

The brief enumerated four T5 method bodies as off-limits (cache
helpers + render/normalize/cursor) plus five T7 cache-invalidation
sites. Greped each post-edit:

```
$ grep -n "def _fft_time_cache_key\|def _fft_time_cache_get\|def _fft_time_cache_put\|def _get_fft_time_signal\|def _render_fft_time\|def _normalize_freq_range\|def _on_fft_time_cursor_info" mf4_analyzer/ui/main_window.py
1090:    def _fft_time_cache_key(self, params):
1109:    def _fft_time_cache_get(self, key):
1118:    def _fft_time_cache_put(self, key, result):
1126:    def _get_fft_time_signal(self):
1150:    def _normalize_freq_range(p):
1277:    def _render_fft_time(self, result, p):
1292:    def _on_fft_time_cursor_info(self, text):
```

Bodies of all seven match the post-T5 text byte-for-byte (no edits
made inside any of them). They are CALLED from the new finished/failed
handlers — `_render_fft_time` from `_on_fft_time_finished`,
`_fft_time_cache_put` from `_on_fft_time_finished` — but never modified.

```
$ grep -n "_copy_fft_time_image" mf4_analyzer/ui/main_window.py
217:        # export buttons route to T8's _copy_fft_time_image which is
```

Only the comment from T5 — no class or method declaration; T8
territory still untouched.

The five cache-invalidation neighborhoods (`close_all`,
`_on_close_all_requested`, `_show_rebuild_popover`, the file-load
envelope-cache neighborhood, the custom-x change handler) — verified
by inspection, untouched. The 8 `invalidate_envelope_cache` callsites
are still 8.

```
$ grep -n "def close_all\|def _on_close_all_requested\|def _show_rebuild_popover\|def _apply_xaxis" mf4_analyzer/ui/main_window.py
301:    def _show_rebuild_popover(self, anchor, mode='fft'):
387:    def _on_close_all_requested(self):
409:    def _apply_xaxis(self):
525:    def close_all(self):

$ grep -n "_fft_time_cache.clear" mf4_analyzer/ui/main_window.py
(empty)
```

No `_fft_time_cache.clear()` calls anywhere — T7 (cache-invalidation
hooks) territory still untouched.

## Tests

Baseline (post-T5): 120 passed.

Post-T7: **122 passed** (2 new tests, 0 regressions).

```
$ PYTHONPATH=. .venv/bin/pytest tests/ -q
122 passed in 4.02s
EXIT=0
```

Worker-targeted subset:

```
$ PYTHONPATH=. .venv/bin/pytest \
    tests/ui/test_main_window_smoke.py::test_fft_time_worker_emits_finished \
    tests/ui/test_main_window_smoke.py::test_fft_time_worker_cancels -v
2 passed in 0.67s
```

The 2 new worker tests:

| Test | What it asserts |
|---|---|
| `test_fft_time_worker_emits_finished` | A `FFTTimeWorker` on a real `QThread` emits `finished` with a `SpectrogramResult` whose `amplitude` matrix has at least one frame. |
| `test_fft_time_worker_cancels` | `worker.cancel()` immediately after `thread.start()` causes the analyzer to raise mid-loop; `failed` payload contains `'cancel'`. |

The 2 updated T5 tests now use `qtbot.waitUntil` for the
asynchronous drain.

## UI verification

Display environment: macOS desktop (`Darwin`, cocoa backend), with the
`offscreen` Qt platform usable for end-to-end fixture exercises. The
process can host a real `QApplication` — UI-verification gate
satisfied. `ui_verified: true`.

End-to-end exercise inside an `offscreen` QApplication, using a
synthetic 8192-sample CSV at 1 kHz with a 50 Hz + 120 Hz mixture:

```
files: 1
fft_time signal candidates: 1
fft_time current_signal: ('f0', 'ch1')
fft_time fs: 1000.0
thread before: None
thread after dispatch: True            <-- worker actually started
status during: 正在计算…                 <-- in-flight status set
thread cleared: True                   <-- _on_fft_time_thread_done ran
status after: FFT vs Time 完成 · 13 frames
cache-hit status: 使用缓存结果 · 13 frames · NFFT 2048
worker running on first call (force): True
status after re-entry click: 正在计算…   <-- re-entry guard triggered
thread cleared after force: True
END OK
```

Confirmed:
- Compute dispatches a real `QThread`; `_fft_time_thread.isRunning()`
  is `True` mid-flight.
- The "正在计算…" status fires on dispatch and again on re-entry
  while a worker is busy — no second worker enqueued.
- On finish, `_on_fft_time_thread_done` clears both refs to `None`
  so the next click dispatches a fresh worker.
- Cache hit on the second call stays synchronous (no thread spun up)
  and renders the cached result directly.
- `force=True` bypasses the cache and dispatches the worker
  (cache-bypass test from T5 + worker dispatch from T7 work
  together).

## Key decisions

1. **`QObject + moveToThread`, not `QThread` subclass.** The plan's
   sample code uses the `QObject + moveToThread` pattern (Qt's
   recommended one). I kept it verbatim. Subclassing `QThread.run`
   would put `compute()` on the worker thread the same way, but the
   QObject pattern lets us wire `finished`/`failed`/`progress`
   signals directly on the worker without a forwarding layer, which
   matters for the future progress dialog (T9).

2. **Status-bar `'正在计算…'` re-entry guard, NOT a queue.** Plan
   Task 7 Step 4 explicitly says "Phase 1 ignores (status: 正在计算…)".
   A queue would race against cache invalidation in T8 (a queued
   compute against a stale signal would cache and render data the
   user no longer wants); ignoring is the safer Phase-1 choice. The
   button doesn't visibly disable but the second click is a no-op,
   which the status bar surfaces.

3. **`_fft_time_pending` dict carries cache_key + render_params.**
   The worker only knows the analyzer-side `SpectrogramParams`; the
   GUI-side cache key (which folds in `fid`, `channel`, `time_range`)
   and the display options (which `_render_fft_time` reads) live on
   the GUI thread. Stashing them on `MainWindow` between dispatch
   and finished-handler is the simplest way to hand them across; an
   alternative would be `functools.partial` on the connect line, but
   the pending-dict pattern is more debuggable (you can `print` the
   pending state in `_on_fft_time_finished` to diagnose a cache
   miss). The trade-off is that overlapping dispatches would clobber
   the dict, but the re-entry guard rules that out by construction.

4. **Existing T5 tests adapted to the asynchronous path.** Two T5
   tests (`test_fft_time_force_bypasses_cache`,
   `test_fft_time_failed_compute_keeps_old_chart`) were written
   against the synchronous compute branch. The brief lists T5
   methods as forbidden but does NOT list T5 tests as forbidden; the
   move to a worker mechanically requires test updates because the
   status bar / canvas state are no longer set inline by
   `do_fft_time` — they are set by the queued
   `_on_fft_time_finished` / `_on_fft_time_failed` slots. I added
   `qtbot.waitUntil(lambda: win._fft_time_thread is None,
   timeout=5000)` after each `do_fft_time(force=...)` call so the
   subsequent asserts run after the slot drains. No assertion logic
   changed; only the synchronization point.

5. **`Qt.DirectConnection` on `worker.finished -> thread.quit` in
   the standalone worker tests.** The plan-spec test code wires
   `worker.finished.connect(thread.quit)` with `AutoConnection` and
   then calls `thread.wait(5000)` on the main thread. That deadlocks
   in practice: `worker.finished` is emitted on the worker thread,
   `thread.quit` is a slot on the QThread (which lives on the main
   thread), so AutoConnection becomes Queued; the queued event never
   drains because the main thread is blocked in `thread.wait()`.
   `QThread.quit()` is documented as thread-safe, so wiring with
   `Qt.DirectConnection` makes the call run on the worker thread
   without the main loop. This is a non-obvious deadlock — see the
   lesson written for it.

   Inside `MainWindow.do_fft_time` the application's main event
   loop is running normally, so `AutoConnection` is correct there;
   the DirectConnection is only needed in the standalone test where
   we synchronously block on `thread.wait`.

6. **Cancel test uses `worker.cancel()` BEFORE `thread.wait()`,
   not after `thread.start()` and a delay.** The plan example calls
   `worker.cancel()` immediately after `thread.start()`. There is a
   race: if `cancel()` flips `_cancelled` before `run()` enters its
   loop, the loop body checks the token at frame 0 and raises
   immediately. If `run()` starts first, the token is checked
   anyway at every frame, so the cancel still fires within a few
   frames. Both branches end up at `failed.emit(...)` — verified by
   running the test 30 times in a row to look for flakes (none).

7. **Cancel routes through `failed`, not a separate signal.** The
   analyzer raises `RuntimeError('spectrogram computation
   cancelled')`, which `worker.run()` catches in its generic
   `except Exception` block and re-emits via `failed`. We don't
   distinguish cancel-vs-error in the UI in Phase 1 — a cancelled
   run shows `'FFT vs Time 错误: spectrogram computation cancelled'`
   which is unambiguous to a developer; user-facing wording can be
   added in T9 alongside a Cancel button by sniffing the message
   string OR adding a dedicated `cancelled` signal. Phase 1 keeps
   the failure surface single.

8. **Cleanup chain order.** `worker.finished -> thread.quit` BEFORE
   `worker.finished -> _on_fft_time_finished` ensures the QThread's
   event loop will exit; the finished slot runs on the main thread
   regardless of order because it is queued. `thread.finished ->
   worker.deleteLater + thread.deleteLater + _on_fft_time_thread_done`
   triggers AFTER the QThread's event loop has exited, so Qt is
   safe to delete both objects. The refs are nulled in
   `_on_fft_time_thread_done` so the next compute can dispatch
   without seeing a dangling deleted-C++-object reference.

## Flagged issues

None for downstream specialists. T7's contract is fully delivered
within the brief's scope.

Two notes for T8 (cache invalidation hooks) — informational, not
blockers:

1. T8 will add `self._fft_time_cache.clear()` calls. None of those
   sites need to interact with the worker; the cache is GUI-thread
   only and the worker neither reads nor writes the LRU itself
   (worker hands the result to `_on_fft_time_finished`, which then
   calls `_fft_time_cache_put` on the main thread).

2. If T8 wants to cancel an in-flight compute when (e.g.) the user
   closes the source file, the call is `if self._fft_time_worker is
   not None: self._fft_time_worker.cancel()`. The analyzer will
   raise mid-loop and `_on_fft_time_failed` will fire on the main
   thread. T8 doesn't need to wait — the toast/status update happens
   asynchronously when the worker exits. (This is a hypothetical
   improvement; the brief doesn't mandate it.)

## Boundary discipline notes

This is the sixth task in the FFT-vs-Time sequence on
`mf4_analyzer/ui/main_window.py`:

- T2 (mode plumbing) — single line: `self.canvas_fft_time = ...`.
- T5 (synchronous compute) — added cache helpers, `do_fft_time`,
  `_render_fft_time`, signal helper, cursor wiring, freq_range
  clamp.
- T7 (this task — worker thread) — added `FFTTimeWorker`, replaced
  the cache-miss branch of `do_fft_time` with a worker dispatch,
  added `_on_fft_time_finished` / `_on_fft_time_failed` /
  `_on_fft_time_progress` / `_on_fft_time_thread_done`. T5's seven
  forbidden bodies are byte-identical to their post-T5 form.
- T8 (cache-invalidation hooks, future) — owns the five forbidden
  cache sites + the popover branch.
- T9 (export controls + progress UI, future) — adds
  `_copy_fft_time_image` and probably a Cancel button that calls
  `self._fft_time_worker.cancel()`.

Per-task forbidden-symbol grep discipline from
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
keeps the rework-detector's surface clean: every method I added is
namespaced under the FFT-vs-Time prefix; every forbidden T5 method
is byte-identical to its pre-edit form; every forbidden T8 site is
untouched.

## Lessons-learned consultation

No prior in-repo lesson on QThread + cancel + worker pattern in this
app (verified by grep). The deadlock pitfall in
`Qt.AutoConnection + thread.wait()` is genuinely non-obvious and
I'm writing a new pyqt-ui lesson for it (see "Lessons added"
below).
