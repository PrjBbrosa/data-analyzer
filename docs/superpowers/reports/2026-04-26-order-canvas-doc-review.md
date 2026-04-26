# Order Canvas Transformation Document Review

Date: 2026-04-26

Scope reviewed:
- `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md`
- `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`
- `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md`
- Listed source context files and directly referenced contract/test files.

## A. Mathematical Correctness

### A1. RPM-order `counts` semantic change

Finding: The current implementation clearly counts nonzero order amplitudes, not frames: `counts[ri] += values > 0`, then divides by `safe_counts`. The review argues this is mathematically suspect and recommends frame counts, while the plan preserves only the `(rpm_bins, orders)` shape. Internal repo consumers appear to use `amplitude`, not `counts`; external consumers are hypothesis - needs verification because `OrderRpmResult` is exported.

Evidence: `mf4_analyzer/signal/order.py:180-210`; `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md:51-64`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:100-121`; `mf4_analyzer/signal/__init__.py:3-12`.

Priority: P1.

Recommended action: Document this as an intentional API semantic change, add a compatibility note, and add a test that verifies both shape preservation and per-row frame-count semantics.

### A2. `_order_amplitudes_batch` DC/Nyquist scaling

Finding: The design snippet scales by `2 / mean(window)` then halves DC and even-Nyquist, which matches the `one_sided_amplitude` contract. The plan snippet uses the better base-single scaling and doubles interior bins, but its `if amps.shape[1] > 2` guard misses odd `nfft == 3`, where the last bin is interior and must be doubled. This is low-probability through the UI but not a strict contract match for the public API.

Evidence: `mf4_analyzer/signal/fft.py:75-82` and `123-134`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:231-237`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:252-258`.

Priority: P1.

Recommended action: Implement scaling exactly as `one_sided_amplitude`: base single-sided amplitude, then for even `nfft` double `[:, 1:-1]`, for odd `nfft` double `[:, 1:]`.

### A3. Arithmetic RPM-bin index equivalence

Finding: The spec and plan disagree: the spec says floor-style `int((rpm_mean - rpm_min) / rpm_res)` plus clamp, while the plan uses `+ 0.5`. Neither is proven equivalent to `argmin` at exact half-bin boundaries: `np.argmin` picks the lower bin on ties, while `int(x + 0.5)` picks the upper bin. The proposed test only checks finite shape, not bin identity.

Evidence: `mf4_analyzer/signal/order.py:173-190`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:34`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:131-155`.

Priority: P0.

Recommended action: Add parametrized tests around half-bin ties, near `rpm_min`, near `rpm_max`, and non-even `rpm_res`; either preserve exact `argmin` semantics or explicitly document the changed tie rule.

### A4. Frame-stack memory and `BATCH=256`

Finding: Chunking at 256 frames bounds the temporary frame stack, but the design still says the vectorized method stacks all frames, and the output matrix is still fully allocated. For typical `nfft=1024`, 256 frames is about 2 MB of raw frames, but high `nfft` values and large output matrices still need profiling. The spec recommends fallback but does not require it.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:35`, `252-260`, and `352`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:292-318`; `mf4_analyzer/ui/inspector_sections.py:971-974`.

Priority: P1.

Recommended action: Reconcile spec and plan so chunking is mandatory, make `BATCH` a named constant, and add a memory-profile step for high `nfft` and large frame counts.

### A5. Time-order vectorization equivalence tests

Finding: Full reproduction is possible if starts, hop, times, `rpm_mean`, window normalization, and interpolation are unchanged. The proposed test samples only three frames and compares against `OrderAnalyzer._order_amplitudes`, which may itself be modified or share the same bug. It does not cover all frames, invalid RPM, boundary order frequencies, or the rpm/track paths.

Evidence: `mf4_analyzer/signal/order.py:117-162`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:201-238` and `240-329`.

Priority: P1.

Recommended action: Keep a legacy loop helper solely for tests or write an independent baseline using `one_sided_amplitude`; compare the full matrix for time-order and representative rpm/track cases.

## B. Rendering Layer Contract

### B6. `imshow` extent and matrix orientation in order-rpm mode

Finding: This is a blocker. The current `pcolormesh(ords, rb, om)` maps x=order, y=rpm, with `om` shaped `(N_rpm_bins, N_orders)`. The plan passes `matrix=result.amplitude.T`, which is `(N_orders, N_rpm_bins)`, but still sets `x_extent=orders` and `y_extent=rpm_bins`; for `imshow`, rows are y and columns are x, so this swaps the data axes.

Evidence: `mf4_analyzer/ui/main_window.py:1187-1193`; `mf4_analyzer/signal/order.py:39-43` and `206-210`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1128-1138` and `1163`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:110`.

Priority: P0.

Recommended action: For rpm-order, call `plot_or_update_heatmap(matrix=result.amplitude, x_extent=orders, y_extent=rpm_bins, ...)`, or swap the extents if using `.T`.

### B7. Heatmap reuse with changed matrix shape

Finding: The planned compatibility check does not inspect shape and has no shape-change fallback. Matplotlib `AxesImage.set_data` can handle a changed shape, so this may work, but the plan should not claim a clear-and-rebuild fallback for this case. `existing_ax in self.fig.axes` is a reasonable stale-axis guard, but it does not verify that the current structure is exactly one heatmap plus its colorbar.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:112-126` and `315`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:771-796`.

Priority: P2.

Recommended action: Either document that changed shapes update in place and test it, or add an explicit shape/signature check before deciding whether to clear and rebuild.

### B8. Track-to-heatmap colorbar ghost risk

Finding: The planned track path begins with `self.canvas_order.clear()`, and the planned `PlotCanvas.clear()` resets `_heatmap_*` and clears the figure. Setting `_heatmap_* = None` again after building the two-subplot track view should not leave a colorbar ghost. The next heatmap call will be incompatible and rebuild.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:820-831` and `1194-1234`; current `PlotCanvas.clear()` at `mf4_analyzer/ui/canvases.py:1389-1393`.

Priority: P2.

Recommended action: Add a regression test for heatmap -> track -> heatmap that asserts the final figure has exactly the expected heatmap axis and colorbar axis.

## C. Threading Layer

### C9. Order cancellation latency

Finding: The plan checks `cancel_token` once per 256-frame batch. That can be acceptable for medium datasets, but it is weaker than the existing FFT-vs-Time worker contract, which polls every frame. For large `nfft`, a 256-frame FFT chunk can exceed the intended responsive cancellation feel.

Evidence: `mf4_analyzer/ui/main_window.py:39-42`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:292-318`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:351`.

Priority: P1.

Recommended action: Check cancellation before frame stacking, before/after the batch FFT, and during any Python per-frame loops; consider reducing `BATCH` or making it adaptive.

### C10. Worker lifetime on MainWindow close

Finding: The plan constructs `OrderWorker(..., parent=self)` but does not add a `closeEvent` that cancels and waits for an active worker. A parented `QThread` still must not be destroyed while running. The current `main_window.py` has no `closeEvent`, and the plan does not add one.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1028-1039`; `mf4_analyzer/ui/main_window.py:80-109`; repository grep for `closeEvent` returned no `main_window.py` hit.

Priority: P0.

Recommended action: Add `MainWindow.closeEvent` to cancel and wait on `_order_worker` and any running FFT-time thread/worker, with bounded waits and user-safe fallback handling.

### C11. Rapid repeated order dispatch

Finding: `_dispatch_order_worker` overwrites the single `self._order_worker` after `cancel(); wait(2000)` without checking whether `wait` succeeded. If the old worker keeps running, it can leak, emit a stale `result_ready`, or render over a newer request. The spec mentions `terminate()` as a timeout fallback, but the plan snippet does not implement it.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:181` and `351`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1028-1039`.

Priority: P0.

Recommended action: Add a generation token to ignore stale results, handle `wait(False)` explicitly, disconnect old signals before replacement, and avoid starting a new worker until the previous one is stopped or safely quarantined.

## D. Test Design

### D12. Counts test does not distinguish old vs new semantics

Finding: The proposed counts test is invalid. It assumes six frames because `n = nfft * 6`, but `compute_rpm_order_result` uses `hop = nfft // 4`, so that input produces 21 frames. The old nonzero-count behavior can also pass parts of the test if leakage makes many interpolated values positive.

Evidence: `mf4_analyzer/signal/order.py:177-183`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:68-88`; current minimal order test coverage at `tests/test_order_analysis.py:8-29`.

Priority: P0.

Recommended action: Compute `expected_frames = len(OrderAnalyzer._frame_starts(...))` and assert the populated row equals that value in every order column; use a signal that makes old nonzero counting provably differ.

### D13. Heatmap reuse test is too weak

Finding: Capturing `id(canvas.fig.axes[0])` verifies only that the first axes stayed first. It can miss a newly added colorbar, and it can fail if Matplotlib changes axes ordering even when the intended heatmap artist was reused. The test also does not assert image object reuse.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:730-748`; planned colorbar update path at `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:792-817`.

Priority: P1.

Recommended action: Capture `canvas._heatmap_ax`, `canvas._heatmap_im`, and `canvas._heatmap_cbar.ax`; assert those identities and `len(canvas.fig.axes)` remain stable after the second call.

### D14. Worker cancel test can miss the cancel path

Finding: `QTimer.singleShot(50, worker.cancel)` followed immediately by `worker.wait(5000)` can block the main event loop, preventing the timer from firing until after the wait. If the worker finishes naturally, the test passes without proving cancellation. If it runs long, the timer may never execute in time.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:907-922`; existing FFT worker tests use explicit signal/thread wiring in `tests/ui/test_main_window_smoke.py:575-607`.

Priority: P1.

Recommended action: Call `worker.cancel()` directly after `start()` or drive the event loop with `qtbot.waitUntil`; assert no `result_ready` is emitted after cancellation.

### D15. Acceptance criteria coverage

Finding: T3/T5/T6 do not collectively automate all eight spec acceptance criteria. Performance FPS, visual clarity, cache-hit timing, batch memory peak, and full control behavior remain manual or conditional. The manual smoke checklist covers some interaction observations but not a quantitative FPS or memory measurement.

Evidence: acceptance criteria at `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:333-344`; T3/T5/T6 test plans at `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:537-645`, `856-1275`, and `1278-1419`.

Priority: P1.

Recommended action: Add an acceptance matrix to the plan marking each criterion as automated, manual, or deferred; add at least a memory-profile step and explicit screenshot comparison step.

## E. Module Boundaries and Squad Fit

### E16. `build_envelope` boundary ownership

Finding: The boundary split is mostly clean. `build_envelope` is extracted in `canvases.py`, consumed by `TimeDomainCanvas` and `main_window.py`, and both files are assigned to `pyqt-ui-engineer`. This keeps the TimeDomainCanvas usage chain inside the PyQt UI boundary.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:273-287`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:648-852` and `1194-1217`; current `TimeDomainCanvas._envelope` at `mf4_analyzer/ui/canvases.py:420-541`.

Priority: P2.

Recommended action: In the execution handoff, explicitly state that signal-processing specialists must not edit `canvases.py` or `main_window.py` when adding order vectorization.

### E17. Dependency graph and hidden file overlaps

Finding: The graph avoids cross-expert overlap on `main_window.py` because T5 and T6 are both assigned to `pyqt-ui-engineer` and T6 depends on T5. T1/T3 and T2/T3 share test files, but they remain within `signal-processing-expert`. No hidden parallel file collision is evident from the file map.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:25-52`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1278-1284` and `1445-1454`.

Priority: P2.

Recommended action: Keep T5 and T6 sequential under one UI worker; do not split their `main_window.py` edits across parallel specialists.

### E18. Deleting `_order_progress`

Finding: The checklist premise is already covered. The current source has `_order_progress` calling `QApplication.processEvents()`, and the plan includes a dedicated T5 step to delete it after worker progress signals replace it. The risk is execution drift, not plan omission.

Evidence: `mf4_analyzer/ui/main_window.py:1093-1097`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1251-1253` and `1271-1274`.

Priority: P2.

Recommended action: Add a post-task grep in T5 for `_order_progress` and `processEvents()` inside order paths to ensure no synchronous residue remains.

## F. Missing Items

### F19. Issues from the review report not fully carried into the plan

Finding: The spec mentions all four requested items, but the plan is incomplete. It covers FFT `'自动'` and stale preset, but the stale preset test only proves `_expand_tasks` returns zero, which is current behavior, not UI degradation. The plan does not implement the `_matches` documentation item, and it omits the high-order-above-Nyquist clipping step despite the spec naming it.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:33`, `47`, `50-51`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:371-418`, `1305-1324`, and `1366-1377`; review items at `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md:108-149`.

Priority: P1.

Recommended action: Add explicit plan steps for `_matches` comment, high-order clipping or a corrected valid-mask policy, and a stale-preset test that verifies `open_batch` passes `current_preset=None`.

### F20. Remaining display-quality gap vs spectrogram

Finding: A real gap remains after this transformation. Spectrogram has dB display, dynamic range policies, dB cache, and frequency-range controls; the order spec settles on linear `vmin/vmax` and explicitly does not introduce order dB mode in the first pass. This may be acceptable, but it conflicts with the review report's stated display-quality target unless called out.

Evidence: `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md:169-181`; `mf4_analyzer/ui/canvases.py:1117-1225`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:267-268` and `367`.

Priority: P1.

Recommended action: Add a "remaining display gaps" subsection that explicitly defers dB mode, dynamic-range controls, and order-axis range controls; align acceptance criteria with that narrower target.

### F21. Bilinear vs Gouraud visual review

Finding: The spec says bilinear is visually close to Gouraud and has an open question about bilinear vs nearest, but the plan does not require a before/after screenshot comparison against the current Gouraud output. The manual checklist asks for screenshots, but not for side-by-side review or explicit user signoff.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:104`, `266`, `340`, and `370`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1395-1412`.

Priority: P2.

Recommended action: Add a manual visual-review step: capture old Gouraud and new bilinear screenshots on the same data/range and record whether the user accepts the difference.

## G. Risk Points

### G22. `build_envelope` extraction risk

Finding: Extracting `build_envelope` can preserve TimeDomainCanvas behavior if `_envelope` becomes a thin wrapper, as planned. Existing tests are strong around envelope behavior and xlim refresh, so they should catch behavior drift if the full UI test set is run. The new "matches current _envelope" test alone is insufficient if both implementations are changed incorrectly.

Evidence: current implementation at `mf4_analyzer/ui/canvases.py:420-541`; existing tests at `tests/ui/test_envelope.py:43-109` and `tests/ui/test_xlim_refresh.py:63-106`; planned extraction at `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:655-728`.

Priority: P2.

Recommended action: Keep T4 Step 5 mandatory and explicitly run `tests/ui/test_envelope.py` plus `tests/ui/test_xlim_refresh.py` after extraction.

### G23. Removing `frozen=True` from `AnalysisPreset`

Finding: `dataclasses.replace` should continue to work after removing `frozen=True`; the existing caller in `BatchSheet.get_preset()` replaces only `outputs`. The real behavior change is that presets become mutable. Current `AnalysisPreset` is already not practically hashable because it contains a mutable `dict` field.

Evidence: `mf4_analyzer/batch.py:31-39`; `mf4_analyzer/ui/drawers/batch_sheet.py:183-185`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:354`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:472-475`.

Priority: P2.

Recommended action: Add a test that `replace(preset, outputs=...)` still works after the dataclass change, and document that presets should be treated as value objects despite mutability.

### G24. Medium-scale memory acceptability

Finding: `1200 x 1024 x 8` is about 10 MB for raw stacked frames, so the medium-scale frame-stack estimate is reasonable. The plan still needs a memory-profile step because total peak also includes windowed frames, spectra, interpolation outputs, and the full result matrix. The spec has a batch memory acceptance criterion, but the plan does not operationalize it.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:259`, `343`, and `352`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:292-318`; `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md:187-189`.

Priority: P1.

Recommended action: Add a `tracemalloc` or RSS measurement task for medium and large synthetic inputs, with thresholds for frame-stack chunking and batch 200-file processing.

## Overall Verdict

Can this plan enter squad execution as-is?

No. The documents are close, but several P0 blockers must be fixed before squad execution because they can produce wrong visuals, false-positive tests, or unsafe worker lifecycle behavior.

P0 blockers:
- A3: Arithmetic RPM-bin indexing is not proven equivalent to `argmin`, and the proposed test does not validate bin identity.
- B6: `order_rpm` heatmap orientation is wrong when `result.amplitude.T` is paired with `x_extent=orders` and `y_extent=rpm_bins`.
- C10: No `closeEvent` cancellation/wait path is planned for a running parented `OrderWorker`.
- C11: Rapid repeated dispatch can overwrite a still-running worker and allow stale results or leaks.
- D12: The counts test is invalid because it assumes six frames while the implementation uses `hop = nfft // 4`.

Recommended remediation:
1. Fix the rpm-order heatmap matrix/extent contract in both spec and plan.
2. Replace the arithmetic-index test with boundary/tie-case tests, then decide whether exact `argmin` compatibility is required.
3. Redesign order-worker lifecycle: close handling, stale-result generation token, failed wait handling, and signal cleanup.
4. Rewrite the counts semantic test using `OrderAnalyzer._frame_starts(...)` for expected frame count and a signal that provably distinguishes frame counts from nonzero counts.
5. Add the missing plan steps for high-order Nyquist policy, `_matches` documentation, and memory/visual acceptance checks before dispatching specialists.
