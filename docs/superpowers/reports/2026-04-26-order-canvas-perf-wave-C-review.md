**Verdict:** PASS

**Issues found:**

1. None. No MECHANICAL or DOMAIN issues found in the T6 review scope.

**Spec compliance + plan literal match:**

`OrderContextual.cancel_requested` is a class-level `pyqtSignal()` at `mf4_analyzer/ui/inspector_sections.py:952`, adjacent to the other class-level order signals, not assigned inside `__init__`. The cancel button matches the literal plan: `QPushButton("取消计算", self)` at `mf4_analyzer/ui/inspector_sections.py:1072`, `setObjectName("orderCancelBtn")` at `mf4_analyzer/ui/inspector_sections.py:1073`, initial `setEnabled(False)` at `mf4_analyzer/ui/inspector_sections.py:1074`, and `clicked.connect(self.cancel_requested)` at `mf4_analyzer/ui/inspector_sections.py:1075`. It is appended directly to the existing `root` layout at `mf4_analyzer/ui/inspector_sections.py:1076`, after the progress label and before the final stretch, with no new container.

`MainWindow._connect` wires the signal exactly once: `self.inspector.order_ctx.cancel_requested.connect(self._cancel_order_compute)` at `mf4_analyzer/ui/main_window.py:299`. `rg` found no other `cancel_requested.connect` site. `_cancel_order_compute` is guarded with `getattr(self, '_order_worker', None)` and `worker.isRunning()` at `mf4_analyzer/ui/main_window.py:1304`, calls `worker.cancel()` at `mf4_analyzer/ui/main_window.py:1306`, sets the status bar to exactly `阶次计算已取消` at `mf4_analyzer/ui/main_window.py:1307`, and clears progress with `set_progress("")` at `mf4_analyzer/ui/main_window.py:1308`.

`open_batch` builds `current_preset` from `_last_batch_preset or _build_current_batch_preset()` at `mf4_analyzer/ui/main_window.py:947`, checks `source == 'current_single'` at `mf4_analyzer/ui/main_window.py:954`, treats `signal is None` or `signal[0] not in self.files` as stale at `mf4_analyzer/ui/main_window.py:956`, toasts exactly `当前单次预设已失效，请改用自由配置` with warning severity at `mf4_analyzer/ui/main_window.py:958`, and sets `current_preset = None` before constructing `BatchSheet` at `mf4_analyzer/ui/main_window.py:959-960`.

The three T5 defensive `getattr(..., 'btn_cancel', None)` gates are gone in the live file. The worker start path directly enables the button at `mf4_analyzer/ui/main_window.py:1350`; `_on_order_failed` disables it after the generation guard at `mf4_analyzer/ui/main_window.py:1365`; `_on_order_result` disables it after the generation guard at `mf4_analyzer/ui/main_window.py:1372`.

**Boundary check:**

| Set | Files present in `git status --short` | Boundary result |
|---|---|---|
| T6 allowed remainder | `mf4_analyzer/ui/inspector_sections.py`; `mf4_analyzer/ui/main_window.py`; `tests/ui/test_order_smoke.py`; `docs/superpowers/reports/2026-04-26-order-perf-manual-smoke.md` | PASS |
| Prior Wave A / T4 / rev1 artifacts | `mf4_analyzer/signal/order.py`; `mf4_analyzer/batch.py`; `mf4_analyzer/ui/canvases.py`; `mf4_analyzer/ui/inspector.py`; `tests/test_order_analysis.py`; `tests/test_batch_runner.py`; `tests/ui/test_canvases_envelope.py`; `requirements.txt`; lessons docs | Subtracted per prior passing Wave A review/re-review |
| Prior Wave B / T5 rev1 artifacts | `tests/ui/test_order_worker.py`; T5 portions of `mf4_analyzer/ui/main_window.py`; Wave B review report | Subtracted per Wave B rev1 PASS |
| Rollout plan/spec/review inputs | modified plan/spec docs and existing Wave A/Wave B reports | Pre-T6 rollout artifacts; not counted as T6 source/test edits |
| Forbidden T6 leak check | `OrderWorker`, render methods, `canvases.py`, `inspector.py`, `signal/order.py`, `batch.py`, other tests | No new T6 ownership found |

**Test discipline:**

`test_order_contextual_exposes_cancel_signal` at `tests/ui/test_order_smoke.py:22` is named accurately, instantiates `OrderContextual`, adds it to `qtbot`, and asserts `hasattr(w, 'cancel_requested')` at `tests/ui/test_order_smoke.py:27`. It is red-proven against pre-T6: `git show HEAD:mf4_analyzer/ui/inspector_sections.py` contains `OrderContextual` and `lbl_progress`, but no `cancel_requested`, `btn_cancel`, or `orderCancelBtn`.

`test_open_batch_drops_stale_preset_signal` at `tests/ui/test_order_smoke.py:30` matches the requested shape. It monkeypatches `mf4_analyzer.ui.drawers.batch_sheet.BatchSheet` to a `FakeSheet` capturing `current_preset` at `tests/ui/test_order_smoke.py:56`, sets `win.files[0] = object()` at `tests/ui/test_order_smoke.py:47`, assigns a stale `AnalysisPreset.from_current_single(... signal=(99999, "nope"))` at `tests/ui/test_order_smoke.py:49`, monkeypatches `win.toast` into `(kind, msg)` capture at `tests/ui/test_order_smoke.py:68`, calls `win.open_batch()` at `tests/ui/test_order_smoke.py:73`, then asserts `current_preset is None` and a toast message containing `失效` at `tests/ui/test_order_smoke.py:75` and `tests/ui/test_order_smoke.py:79`. It is red-proven against the pre-T6 `open_batch`, where `current_preset` was passed directly to `BatchSheet` immediately after construction with no stale block.

Requested tests passed fresh:

```text
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_smoke.py -v
2 passed in 9.24s

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -k 'not non_uniform_auto_opens_rebuild and not non_uniform_user_cancel_does_not_retry'
207 passed, 2 deselected, 16 warnings in 15.04s
```

**Manual checklist content:** Verified. `docs/superpowers/reports/2026-04-26-order-perf-manual-smoke.md` contains the required A behavior smoke section at lines 5-15, B Gouraud-vs-Bilinear visual comparison at lines 17-26, C batch 200-file memory observation at lines 28-37, and the sign-off table at lines 39-45. The wording and acceptance criteria match plan Step 8 at `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:2215`.

**Pre-existing flake check:** Verified. `tests/ui/test_main_window_smoke.py` has no git diff, and the two deselected tests are FFT-time retry tests at `tests/ui/test_main_window_smoke.py:807` and `tests/ui/test_main_window_smoke.py:878`; they exercise `do_fft_time`, `_fft_time_thread`, and rebuild-popover retry state, not T6 `_cancel_order_compute` or `open_batch`. Wave B already recorded the same timeout behavior in its pre-existing flake section, so these remain pre-existing and not freshly induced by T6.

**Final hand-off readiness:** Signed off. The new signal and method contracts are present, the dispatcher lifecycle still uses the T5 generation-token pattern, render orientation was not touched by T6, and the cancel button state transitions are direct at worker start/result/failure. Main Claude can proceed to Phase 3 aggregation and Phase 4 state update.
