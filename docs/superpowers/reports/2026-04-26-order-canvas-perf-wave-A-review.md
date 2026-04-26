1. **Verdict:** FAIL

2. **Issues found:**

1. Severity: blocker
   file:line citation: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:27`, `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:2324`
   What is wrong: Boundary evidence from `git status --short` shows files outside the Wave A T1/T2/T4 allowed sets: `requirements.txt` is modified and `docs/lessons-learned/orchestrator/decompositions/2026-04-26-order-canvas-perf-execute.md` is untracked. I did not read their contents because they are outside the scoped file set, but the plan's file map and aggregate boundary rule make this a leak until ownership is explained.
   What to do: Remove those files from the Wave A change set, or explicitly move them into an owning task/wave and rerun boundary review. If they are pre-existing unrelated worktree changes, document that before claiming Wave A clean.
   Class: DOMAIN - squad-orchestrator/main dispatcher; minimal fix brief: audit unassigned files and either revert from Wave A or reassign with an explicit owner.

2. Severity: important
   file:line citation: `mf4_analyzer/ui/canvases.py:585`, `mf4_analyzer/ui/canvases.py:593`, `tests/ui/test_canvases_envelope.py:66`
   What is wrong: `TimeDomainCanvas._envelope` keeps `xlim` required in the signature, but it still accepts `xlim=None` at runtime because it forwards directly to `build_envelope`, whose `None` branch means full range. The test named `test_timedomain_envelope_thin_wrapper_does_not_accept_none` never passes `None`; it only verifies the tuple path, so it does not enforce the spec/review contract that `None` belongs only to module-level `build_envelope`.
   What to do: Add an explicit guard in `TimeDomainCanvas._envelope` rejecting `xlim is None` and update the test to assert `pytest.raises(...)` for `canvas._envelope(..., xlim=None, ...)`. Keep `build_envelope(..., xlim=None, ...)` valid.
   Class: DOMAIN - pyqt-ui-engineer; minimal fix brief: tighten the wrapper contract and strengthen the test.

3. **Boundary check:**

| Task | Files changed (found) | Files allowed | Leak? |
|---|---|---|---|
| T1 | `mf4_analyzer/signal/order.py`; `tests/test_order_analysis.py`; `docs/lessons-learned/signal-processing/2026-04-26-batched-fft-transient-buffers-dominate-chunk-budget.md`; `docs/lessons-learned/LESSONS.md` | Same T1 set, with signal-processing lesson/index row allowed | No |
| T2 | `mf4_analyzer/batch.py`; `tests/test_batch_runner.py` | Same T2 set | No |
| T4 | `mf4_analyzer/ui/canvases.py`; `tests/ui/test_canvases_envelope.py` | Same T4 set | No file leak; contract issue above |
| Unassigned / outside Wave A | `requirements.txt`; `docs/lessons-learned/orchestrator/decompositions/2026-04-26-order-canvas-perf-execute.md` | None under T1/T2/T4 | Yes - blocker |

4. **Test discipline:**

Requested run passed: `21 passed in 9.52s`.

T1 has 7 Wave A tests plus one pre-existing baseline. `test_rpm_order_counts_are_per_frame_not_per_nonzero` is well named and red-proven by the old nonzero-count behavior. `test_rpm_bin_index_vectorized_matches_argmin_at_boundaries` is well named but is a pure algorithm test, not an implementation red test. `test_time_order_recovers_target_order_amplitude`, `test_time_order_vectorized_matches_loop`, and `test_vectorized_paths_match_loop_for_all_results` match their assertions; the vectorized-vs-loop tests are regression/equivalence tests and may pass against a pre-vectorized implementation. `test_metadata_records_nyquist_clipped_at_median_rpm_orders` is red-proven by missing metadata. `test_order_compute_memory_within_chunk_budget` is red-proven against an unchunked all-frames stack. `test_order_track_recovers_bin_aligned_tone_amplitude` remains a useful existing correctness guard.

T2 has 3 Wave A tests plus 3 existing runner tests. `test_current_single_fft_preset_handles_auto_nfft` is red-proven for `'自动'`. `test_matrix_to_long_dataframe_vectorize_shape` checks output layout but would not necessarily fail on an old loop implementation. `test_analysis_preset_replace_after_frozen_removed` preserves `dataclasses.replace` behavior, but `replace` also works on frozen dataclasses, so it is not red-proof for frozen removal.

T4 has 7 tests and no flaky QTimer wait-then-check pattern. The heatmap reuse, shape-change rebuild, and track-roundtrip tests are well targeted. The `build_envelope` module-level and `xlim=None` tests are red-proven. The `_envelope` "does not accept None" test name does not match its assertion, as covered in Issue 2.

5. **Hand-off readiness:**

- Verified OK: `from mf4_analyzer.ui.canvases import build_envelope` is backed by module-level `build_envelope` at `mf4_analyzer/ui/canvases.py:192`; no circular import was introduced in the scoped file.
- Verified OK: `_ORDER_BATCH_FRAMES` is importable from `mf4_analyzer.signal.order` at `mf4_analyzer/signal/order.py:19` and is consulted in all three chunk loops at `mf4_analyzer/signal/order.py:249`, `mf4_analyzer/signal/order.py:318`, and `mf4_analyzer/signal/order.py:387`.
- Verified OK: `OrderAnalyzer.compute_time_order_result`, `compute_rpm_order_result`, and `extract_order_track_result` accept `progress_callback` and `cancel_token` at `mf4_analyzer/signal/order.py:226`, `mf4_analyzer/signal/order.py:292`, and `mf4_analyzer/signal/order.py:365`.
- Verified OK: `PlotCanvas.plot_or_update_heatmap` keyword signature matches the T5 call shape at `mf4_analyzer/ui/canvases.py:1471`.
- Not signed off: `TimeDomainCanvas._envelope` must reject `None` before T4 is contract-clean.

6. **Closing notes:**

Verified OK: T1 doubling branches match the spec for nfft 2/3/4/5; chunking is real, not just a constant; cancel checks appear three times per chunk; RPM counts use `counts[ri] += 1`; `safe_counts = np.maximum(counts, 1)` is non-mutating; broadcast `argmin(..., axis=1)` is retained; and all three result metadata dicts use `nyquist_clipped_at_median_rpm`. The T1 lesson accurately describes the current in-place/del memory behavior.

Verified OK: T2 handles `str`/non-positive/positive `nfft` per plan, raises shape mismatch with explicit expected `(rows, cols)`, clears figures in `finally`, uses `turbo`/`bilinear`, keeps `AnalysisPreset` defaults, and documents `_matches` substring-then-regex behavior.

Fine, but next iteration should add direct tests for `_matrix_to_long_dataframe` mismatch errors and for positive/non-positive `nfft` fallback cases. The T2 frozen-removal test should assert the mutability contract if mutability is the actual requirement.

---

## Rev1 Re-review — 2026-04-26

**Reviewer:** code-reviewer (Rev1)
**Scope:** Issue #1 resolution, Issue #2 fix, Bonus UI fix only. T1/T2/T4 prior-passing checks not re-run.

**Verdict:** PASS

**Issue #1 — Boundary leak:** verified
The prior boundary allegation is resolved for Rev1 scope. `requirements.txt` still shows an uncommitted `scipy>=1.10` addition, but current `HEAD` (`5a928cc`) already imports `from scipy.signal import get_window as _scipy_get_window` at `mf4_analyzer/signal/fft.py:27` while `HEAD:requirements.txt` lacks scipy, so the requirements line is a dependency sync for existing committed FFT code rather than a Wave A T1/T2/T4 change. The literal claim that the scipy import existed at `62eee64` is not supported by `git show 62eee64:mf4_analyzer/signal/fft.py`, which has no scipy import, but that correction does not leave a Wave A leak. The decomposition file is untracked, but its content is explicitly an orchestrator task-ownership/decomposition artifact under `docs/lessons-learned/orchestrator/decompositions/`, so it belongs to Phase 1 orchestration rather than specialist output.

**Issue #2 — _envelope None rejection:** verified
`TimeDomainCanvas._envelope` now guards `xlim is None` and raises `TypeError` before forwarding to `build_envelope` (`mf4_analyzer/ui/canvases.py:593-597`). The module helper remains intentionally unchanged: `build_envelope(..., xlim=None, ...)` still maps empty input safely and otherwise uses the full `(t[0], t[-1])` range (`mf4_analyzer/ui/canvases.py:221-226`). The test now covers both sides of the contract: tuple `xlim` succeeds at `tests/ui/test_canvases_envelope.py:77-78`, and `xlim=None` is asserted with `pytest.raises(TypeError)` at lines 80-81.

**Bonus UI fix — Inspector max-width cap:** clean
`mf4_analyzer/ui/inspector.py` has one executable change in `Inspector.__init__`: `self.setMaximumWidth(_INSPECTOR_CONTENT_MAX_WIDTH + 16)` at line 67, with explanatory comments only. The existing `_scroll_body.setMaximumWidth(_INSPECTOR_CONTENT_MAX_WIDTH)` and trailing `host_lay.addStretch(1)` remain, so this is a mechanical outer-widget width cap and does not affect Wave A T1/T2/T4 files or contracts.

**Pytest result:** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_canvases_envelope.py -v`
`collected 7 items`
`tests/ui/test_canvases_envelope.py::test_timedomain_envelope_thin_wrapper_does_not_accept_none PASSED [ 57%]`
`============================== 7 passed in 8.82s ==============================`

**Hand-off readiness:** Wave B ready
Rev0's signal-off list remains accepted within this scoped re-review: `build_envelope` is importable, order chunk/progress/cancel surfaces were previously signed off, and `plot_or_update_heatmap` remains available for T5. The new wrapper guard closes the remaining T4 contract gap without changing the module-level `build_envelope(xlim=None)` path needed by order-track rendering.
