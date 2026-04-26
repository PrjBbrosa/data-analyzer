**Verdict:** PASS-WITH-FIXES

**Issues found:**

1. **Severity: Medium / `tests/ui/test_order_worker.py:273` / test name overclaims latest-generation proof / fix before Wave C / class: MECHANICAL, target `pyqt-ui-engineer`.**  
   `test_rapid_redispatch_drops_stale_generation` says only the latest generation reaches `_render_order_time`, but the assertion at `tests/ui/test_order_worker.py:301` is only `len(rendered_kinds) <= 1`, followed by a generation counter stability check at `tests/ui/test_order_worker.py:302`. This permits zero renders and does not prove that the one accepted render, if any, came from `final_gen`. Tighten it by wrapping `_on_order_result` before dispatch, recording the generation only when the wrapped call actually renders, then assert accepted generations equal `[final_gen]`.

2. **Severity: Low / `tests/ui/test_order_worker.py:107` / test name does not match assertion / fix with rename or stronger assertion / class: MECHANICAL, target `pyqt-ui-engineer`.**  
   `test_order_worker_stale_generation_is_ignored` does not test ignoring stale generations. Its own docstring says it validates only the three-argument signal delivery contract, and the assertion at `tests/ui/test_order_worker.py:133` checks `('time', 99)`. Rename it to something like `test_order_worker_result_signal_carries_generation`, or add a true stale-drop assertion. The real stale-drop unit test exists separately at `tests/ui/test_order_worker.py:250`.

**Boundary check:**

| Task | files_changed actually present for Wave B remainder | Allowed | Result |
|---|---|---|---|
| T3 `signal-processing-expert` | `tests/test_order_analysis.py`; `tests/test_batch_runner.py` | exactly those two files | PASS |
| T5 `pyqt-ui-engineer` | `mf4_analyzer/ui/main_window.py`; `tests/ui/test_order_worker.py` | exactly those two files | PASS |
| Prior Wave A / T4 / T4-rev1 still in worktree | `mf4_analyzer/signal/order.py`, `mf4_analyzer/batch.py`, `mf4_analyzer/ui/canvases.py`, `tests/ui/test_canvases_envelope.py`, `mf4_analyzer/ui/inspector.py`, `requirements.txt`, docs/lesson artifacts | subtract per Wave A review and T4-rev1 notes | No Wave B leak |
| T6-sensitive files | no `mf4_analyzer/ui/inspector_sections.py`; no `tests/ui/test_order_smoke.py`; `MainWindow.open_batch` remains at `mf4_analyzer/ui/main_window.py:935` with no Wave B diff hunk | T6 owns these later | PASS |

Raw `git status --short` was checked. After subtracting prior-wave files, the remainder is exactly T3 + T5. I also checked for accidental edits to `canvases.py`, `inspector.py`, `inspector_sections.py`, `signal/order.py`, and `batch.py`; the changed files there are prior-wave/T4 ownership, not Wave B remainder.

**Spec compliance (T5):**

`OrderWorker` signal signatures match exactly at `mf4_analyzer/ui/main_window.py:95`: `result_ready = pyqtSignal(object, str, int)`, `failed = pyqtSignal(str, int)`, and `progress = pyqtSignal(int, int, int)`. `_dispatch_order_worker` bumps `_order_generation` first at `main_window.py:1284`, disconnects all three old-worker signals before cancel at `main_window.py:1290`, cancels/waits before constructing the new worker, and has the `terminate(); wait(500)` fallback at `main_window.py:1300`.

All three order slots guard generation before UI mutation: progress at `main_window.py:1320`, failed at `main_window.py:1328`, and result at `main_window.py:1337`. `closeEvent` handles both worker shapes: order QThread subclass at `main_window.py:1525`, FFT-time QObject+QThread at `main_window.py:1539`, with `super().closeEvent(event)` at `main_window.py:1553`.

Rendering contracts match. `_render_order_time` uses `matrix=result.amplitude.T` with x=`times`, y=`orders` at `main_window.py:1358`. `_render_order_rpm` uses `matrix=result.amplitude`, x=`orders`, y=`rpm_bins` at `main_window.py:1404`. `_render_order_track` clears before `add_subplot(2, 1, ...)` at `main_window.py:1445`, calls `build_envelope(..., xlim=None, pixel_width=max(self.canvas_order.width(), 600), is_monotonic=True)` at `main_window.py:1464`, and resets heatmap state at `main_window.py:1485`. `def _order_progress` is gone; remaining `QApplication.processEvents()` calls are `_load_one`, batch, and `do_fft` paths at `main_window.py:599`, `main_window.py:953`, and `main_window.py:1122`.

**Test discipline:**

T5 has 9 tests and all passed. `test_order_worker_emits_result_with_generation` matches its assertions at `tests/ui/test_order_worker.py:11`. Pre-cancel is deterministic: `worker.cancel()` is before `worker.start()` at `test_order_worker.py:68`. Mid-run cancel uses `qtbot.waitUntil` before `worker.cancel()` and `worker.wait()` at `test_order_worker.py:101`. The B6 RPM test asserts x extent 1.0 to 5.0, y extent 600.0 to 1800.0, shape `(3, 5)`, and row 0 values at `test_order_worker.py:160`. CloseEvent tests use `warnings.catch_warnings(record=True)` and assert no QThread/destroyed warnings at `test_order_worker.py:192` and `test_order_worker.py:241`. The stale-generation unit test is present at `test_order_worker.py:250`; the end-to-end stale test needs the Issue 1 assertion tightening. There is no actual `QTimer.singleShot(...)+worker.wait()` pattern in the file; only a warning comment at `test_order_worker.py:49`.

T3’s four tests are clean. The cancel-token test uses a state machine at `tests/test_order_analysis.py:294` and raises `RuntimeError(...cancelled...)` at `test_order_analysis.py:300`. The progress test asserts at least one callback and final `cur == total` at `test_order_analysis.py:322`. The batch CSV tests assert exact column order and non-empty output at `tests/test_batch_runner.py:138` and `tests/test_batch_runner.py:156`.

**Hand-off readiness for Wave C:**

- `btn_cancel.setEnabled(...)` is defensively gated behind `getattr(self.inspector.order_ctx, 'btn_cancel', None)` at `main_window.py:1315`, `main_window.py:1332`, and `main_window.py:1341`.
- `_dispatch_order_worker` centralizes worker start/cancel state at `main_window.py:1274`, so T6 has a clean place to wire `cancel_requested -> _cancel_order_compute`.
- `open_batch` is untouched in Wave B; stale-preset downgrade remains available for T6 at `main_window.py:935`.

**Pre-existing flake check:**

The two deselected smoke tests remain outside Wave B causality. `tests/ui/test_main_window_smoke.py` has no git diff, and neither test calls `closeEvent`; they exercise `do_fft_time` and `_on_fft_time_failed` around `tests/ui/test_main_window_smoke.py:863` and `tests/ui/test_main_window_smoke.py:913`. I ran them for confirmation: the auto-retry test timed out at `test_main_window_smoke.py:866` waiting for `_fft_time_thread is None and compute_calls >= 2`, and the combined run then aborted while the user-cancel test waited at `test_main_window_smoke.py:914`. That aligns with the known FFT-time retry/thread-drain flake, not the new T5 closeEvent path.

**Closing notes:**

Requested corroboration passed: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_worker.py -v` reported 9 passed, and `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py tests/test_batch_runner.py -v` reported 18 passed. Non-blocking cleanup: `tests/ui/test_order_worker.py:6` imports `QEventLoop, QTimer` but does not use them.

## Rev1 Re-review

**Verdict:** PASS

**Issue 1 status:** verified  
The hook now exists before the dispatch loop: `accepted_generations` is initialized at `tests/ui/test_order_worker.py:288`, the original slot is captured at `tests/ui/test_order_worker.py:289`, the wrapper starts at `tests/ui/test_order_worker.py:290`, and `win._on_order_result` is replaced at `tests/ui/test_order_worker.py:294`; the redispatch loop starts later at `tests/ui/test_order_worker.py:306`. The wrapper checks `gen == getattr(win, '_order_generation', -1)` at `tests/ui/test_order_worker.py:291`, appends only that accepted generation at `tests/ui/test_order_worker.py:292`, and passes through to `original_on_result(result, kind, gen)` at `tests/ui/test_order_worker.py:293`, so the real slot guard still runs. `_render_order_time` remains stubbed at `tests/ui/test_order_worker.py:295`, and the final assertion is exact list equality at `tests/ui/test_order_worker.py:315`.

**Issue 2 status:** verified  
The test is renamed exactly to `test_order_worker_result_signal_carries_generation` at `tests/ui/test_order_worker.py:106`. Its docstring names both real stale-drop tests: `test_on_order_result_drops_stale_generation_deterministically` at `tests/ui/test_order_worker.py:109` and `test_rapid_redispatch_drops_stale_generation` at `tests/ui/test_order_worker.py:110`.

**Cleanup status:** verified  
The file-top import block now contains `os` at `tests/ui/test_order_worker.py:1`, `numpy` at `tests/ui/test_order_worker.py:4`, `pytest` at `tests/ui/test_order_worker.py:5`, and `OrderAnalysisParams` at `tests/ui/test_order_worker.py:7`; the old `from PyQt5.QtCore import QEventLoop, QTimer` import is gone. No required Qt import was deleted: the close-event test still imports `QThread, QObject, pyqtSignal` at `tests/ui/test_order_worker.py:207`.

**Test run:** `tests/ui/test_order_worker.py` — 9 passed (`tests/ui/test_order_worker.py::test_order_worker_result_signal_carries_generation PASSED`)

**Hand-off readiness for Wave C:** Carry forward the rev0 sign-off for Wave C. Rev1 resolves the two review issues and cleanup item in the scoped test file, and main Claude may proceed to Wave C (T6). New note: the current worktree still shows pre-existing production diffs, including `mf4_analyzer/ui/main_window.py`; this re-review did not edit production files.
