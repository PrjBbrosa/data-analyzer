# Order Canvas Transformation Document Review - Round 2

Date: 2026-04-26

Scope reviewed:
- `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md`
- `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`
- `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md`
- Round-1 review: `docs/superpowers/reports/2026-04-26-order-canvas-doc-review.md`
- Listed source context files.

## A. Mathematical Correctness

### A1. RPM-order `counts` semantic change

Finding: The adjusted docs now explicitly state that `counts` changes from nonzero-order counts to per-frame counts, and the API compatibility note says this can break external consumers that interpret per-order differences. The original implementation intent is still not fully provable from source, because current code only shows the behavior (`counts[ri] += values > 0`) and the report calls it semantically unclear. Repository-internal impact appears low because `OrderRpmResult` is exported but grep finds no real `.counts` consumers outside docs/tests.

Evidence: `mf4_analyzer/signal/order.py:199-210`; `mf4_analyzer/signal/__init__.py:3-13`; `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md:51-66`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:33,505-507`.

Priority: P1.

Recommended revision/action: Keep the compatibility note, but fix D12's test so the semantic break is actually protected before execution.

### A2. `_order_amplitudes_batch` DC/Nyquist handling

Finding: The spec and plan still contradict the documented `one_sided_amplitude` contract for odd `nfft == 3`. `one_sided_amplitude` says odd `nfft` has an interior last bin that is doubled, but the new batch snippet leaves all `amps.shape[1] == 2` cases unchanged while also saying this includes `nfft == 3`. This is low-probability through the UI, but it is not a strict contract match.

Evidence: `mf4_analyzer/signal/fft.py:75-82,123-134`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:36,323-329`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:299-318`.

Priority: P1.

Recommended revision/action: Either disallow `nfft < 4` in order analysis, or implement/test the documented odd-`nfft` rule with an explicit `nfft=3` case.

### A3. RPM-bin argmin boundary equivalence

Finding: The prior arithmetic-index risk is resolved in the adjusted docs: both spec and plan preserve `np.argmin` semantics and vectorize it with broadcast. The test covers half-bin ties, bounds, and a range that is not evenly divisible by `rpm_res`. This removes the original P0 blocker.

Evidence: `mf4_analyzer/signal/order.py:189-190`; `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:34`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:152-203`.

Priority: P2.

Recommended revision/action: No blocker; optionally add a non-integer `rpm_res` case such as `97.5` to make the boundary suite more explicit.

### A4. Batch frame-stack memory

Finding: `_ORDER_BATCH_FRAMES = 256` is sufficient to bound the temporary frame stack for medium datasets, and the spec now includes a clear memory model. The remaining risk is that Step 19 profiles only a single order compute and does not cover batch image export or process RSS. Large output matrices are still fully allocated, so chunking protects the FFT stack but not every memory contributor.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:35,367-376`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:538-578`; `mf4_analyzer/batch.py:315-349`.

Priority: P1.

Recommended revision/action: Keep `_ORDER_BATCH_FRAMES`, and add one batch-level memory profile covering export_data plus export_image for many files.

### A5. Time-order vectorization equivalence

Finding: The adjusted plan improves equivalence testing, but it still does not verify all three result types as claimed. Step 15 says time/rpm/track, yet the code block compares only `compute_time_order_result` and `extract_order_track_result`; `compute_rpm_order_result` aggregation, `ri_array`, and `counts` are absent. That leaves a real regression gap in the path with the most semantic change.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:449-493`; `mf4_analyzer/signal/order.py:164-213`.

Priority: P1.

Recommended revision/action: Add an rpm-order baseline that reconstructs `matrix`, `counts`, and `amplitude` from old per-frame `_order_amplitudes` plus exact `argmin` bins.

## B. Rendering Layer Contract

### B6. `imshow` extent and order-rpm orientation

Finding: The executable plan is now mostly correct: `_render_order_rpm` passes `matrix=result.amplitude` with x=orders and y=rpm. However, the design spec still says `do_order_rpm` uses `om.T`, and the plan has a stale note saying `.T` maps to order/rpm extents. This inconsistency can mislead a specialist during implementation.

Evidence: current source `mf4_analyzer/ui/main_window.py:1192-1198`; fixed plan snippet `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1600-1618`; stale text `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:115`; stale plan note `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1643`.

Priority: P1.

Recommended revision/action: Delete the stale `.T` language and state once: rpm-order uses `(N_rpm_bins, N_orders)` without transpose.

### B7. Heatmap reuse on changed shape

Finding: The adjusted spec and plan now require all relevant handles, membership in `fig.axes`, `len(fig.axes) == 2`, and matching image shape before reuse. A shape change falls back to clear and rebuild, and the plan includes a dedicated test for this. This addresses the round-1 concern.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:439-446`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1044-1059,1118-1130`.

Priority: P2.

Recommended revision/action: No required change; keep the shape-change test tied to `_heatmap_im`, not `fig.axes[0]`.

### B8. Track path and colorbar ghost artifacts

Finding: The adjusted plan resets `_heatmap_*` in `PlotCanvas.clear()` and tests heatmap -> track -> heatmap. The track renderer also clears the canvas before creating its two subplots and nulls heatmap handles after rendering. This should prevent colorbar ghost axes on the next heatmap switch.

Evidence: current `PlotCanvas.clear()` lacks heatmap fields at `mf4_analyzer/ui/canvases.py:1389-1393`; plan reset/test at `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1062-1087,1171-1180,1711-1714`.

Priority: P2.

Recommended revision/action: No blocker; ensure implementation initializes `_heatmap_*` in `__init__` as well as clearing it.

## C. Threading Layer

### C9. OrderWorker cancellation latency

Finding: Cancellation is improved from round 1: the plan checks before each chunk, before stack, and before FFT. It still does not check inside `_order_amplitudes_batch`'s per-frame interpolation loop, so a large 256-frame FFT/interp chunk can delay cancel responsiveness. This is probably acceptable for medium data but should be tightened for interaction smoothness.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:493`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:372-397,408-415`; `_order_amplitudes_batch` loop at plan `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:320-330`.

Priority: P1.

Recommended revision/action: Pass `cancel_token` into the batch helper or check it in the Python per-frame loop; consider lowering/adapting `_ORDER_BATCH_FRAMES`.

### C10. MainWindow destruction while workers run

Finding: This remains a P0 blocker. The spec and plan closeEvent snippets iterate `('_order_worker', '_spectrogram_worker')`, but current source uses `_fft_time_thread` and `_fft_time_worker`, and `FFTTimeWorker` is a `QObject`, not a `QThread`. Executing the snippet literally will not cancel/wait the existing FFT-time thread and will not satisfy the acceptance criterion.

Evidence: current source fields `mf4_analyzer/ui/main_window.py:28-47,100-106,1469-1495`; spec snippet `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:245-260`; plan snippet/note `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1513-1532`.

Priority: P0.

Recommended revision/action: Replace the placeholder with exact `_fft_time_worker.cancel()` plus `_fft_time_thread.quit()/wait()/terminate()` handling, and add a UI test for an active FFT-time thread on close.

### C11. Rapid repeated order dispatch

Finding: The adjusted dispatch code now has generation tokens, signal disconnects, cancel, `wait(2000)`, and terminate fallback. The remaining gap is test strength: the rapid redispatch test does not force an old worker to emit after a newer generation, and the post-`terminate()` `wait(500)` return is not checked. The design is acceptable, but verification can still false-pass.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:45-47`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1457-1486,1815-1849`.

Priority: P1.

Recommended revision/action: Add a deterministic stale-signal test by calling `_on_order_result(..., old_generation)` after incrementing generation; assert no render occurs.

## D. Test Design

### D12. Counts test distinguishes frame-count from nonzero-count

Finding: The revised counts test is still not reliable and should block execution. It adds a full `nfft` sine segment at every even frame start, while the production hop is `nfft // 4`; those segments overlap heavily into odd frames. The old `values > 0` counting can therefore see nonzero amplitudes in most or all frames and pass accidentally.

Evidence: planned test construction `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:85-109`; production hop/count behavior `mf4_analyzer/signal/order.py:177-200`.

Priority: P0.

Recommended revision/action: Use a deterministic stub/baseline for `_order_amplitudes` that returns zero on selected frames, or design non-overlapping frame windows in a helper-level test; prove the old implementation fails.

### D13. Heatmap reuse test robustness

Finding: This round-1 issue is resolved. The updated test captures `_heatmap_ax`, `_heatmap_im`, and `_heatmap_cbar.ax` identities, then asserts the figure axes count remains stable. That avoids false passes from `fig.axes[0]` ordering.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1018-1041`.

Priority: P2.

Recommended revision/action: No required change.

### D14. Worker cancel test timing

Finding: The adjusted tests remove the specific `QTimer.singleShot`/`wait()` race from round 1. They include a pre-start cancel case and a mid-run cancel that waits for progress before calling `cancel()`. The mid-run case could still assert that no `result_ready` was delivered after cancel, but the original lost-timer risk is fixed.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1262-1291,1294-1318`.

Priority: P2.

Recommended revision/action: Optionally collect `results` and `failures` in the mid-run cancel test and assert no result is emitted after cancel.

### D15. Acceptance criteria coverage

Finding: The plan now has an acceptance matrix, but it overstates automation for memory and still leaves several criteria manual. FPS, visual clarity, no-freeze feel, order-track pan smoothness, and existing-control behavior are manual smoke checks; cache-hit timing is deferred. The matrix maps "batch 200 files memory < 200 MB" to a single-compute tracemalloc test, not a batch run.

Evidence: spec criteria `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:466-484`; plan matrix `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:2066-2084`; single-compute memory test `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:538-578`.

Priority: P1.

Recommended revision/action: Mark 7-9 as not yet covered by automation, or add a real `BatchRunner` memory test with multiple files and image export.

## E. Module Boundaries and Squad Fit

### E16. `build_envelope` ownership boundary

Finding: The boundary split is clean: `canvases.py`, `main_window.py`, and `tests/ui/*` are all assigned to `pyqt-ui-engineer`, so `build_envelope` and its TimeDomainCanvas usage chain stay within one ownership boundary. The only blocker is functional, not ownership-related: `xlim=None` is not specified enough, covered in G22.

Evidence: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:397-411`; `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:933-1000,1200-1203,1674-1697`.

Priority: P2.

Recommended revision/action: Keep T4/T5 under the same UI specialist, and explicitly tell signal specialists not to edit `canvases.py` or `main_window.py`.

### E17. Dependency graph and hidden file overlap

Finding: The dependency graph is mostly squad-safe: T1/T2/T4 are disjoint, and T5/T6 are sequential with the same owner for `main_window.py`. There is no cross-expert file-overlap risk in the adjusted map. The risk is local sequencing inside `pyqt-ui-engineer`, not rework detection.

Evidence: plan file map and graph `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:25-52`; owner boundary `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:401-409`; T5/T6 both list `main_window.py` at plan `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1210-1212,1884-1888`.

Priority: P2.

Recommended revision/action: Keep T6 dependent on T5 and require the same specialist to own both `main_window.py` edits.

### E18. Deleting `_order_progress`

Finding: This is now explicitly covered. The plan adds a dedicated Step 8 to delete `_order_progress` and grep for `_order_progress` or `QApplication.processEvents` residue in the order path. Current source still has `_order_progress`, so the step remains necessary during execution.

Evidence: current source `mf4_analyzer/ui/main_window.py:1098-1102,1123-1130,1183-1190,1239-1242`; plan deletion/grep `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1731-1741`.

Priority: P2.

Recommended revision/action: Keep the grep as an execution checklist item and fail the task if order-path `processEvents()` remains.

## F. Missing Items

### F19. Round-1 omitted issues coverage

Finding: Most omitted items are now covered: FFT `'自动'` nfft handling, stale preset validation, and `_matches` documentation all have plan steps/tests. The remaining weak point is Nyquist clipping metadata: the plan computes `nyquist_clipped` from median RPM, while amplitude validity is frame-local. In variable-RPM data, metadata can misrepresent which columns were actually clipped across frames.

Evidence: auto nfft plan `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:602-646`; stale preset plan `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:1909-1953,1995-2006`; `_matches` plan `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:781-805`; Nyquist metadata `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:351-359,504-527`.

Priority: P1.

Recommended revision/action: Rename metadata to `nyquist_clipped_at_median_rpm` or compute a per-column/per-frame clipped mask count and test variable RPM.

### F20. Remaining display-quality gap vs spectrogram

Finding: The docs now explicitly defer several display-quality gaps. After this transformation, order canvas still lacks dB mode, dB cache, dynamic range controls, and order/RPM axis range controls that spectrogram has. That is acceptable because the user explicitly scoped out feature breadth, but it should remain visible in deferred work.

Evidence: display gap report `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md:171-198`; spec deferred section `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:523-534`.

Priority: P2.

Recommended revision/action: Keep these items deferred and do not let specialists expand scope into dB/dynamic controls during this execution.

### F21. Bilinear vs Gouraud visual difference

Finding: This is now documented for manual review. The plan requires before/after screenshots and user sign-off for `pcolormesh(gouraud)` versus `imshow(bilinear)`, including peak position, blurring, and banding checks. That is the right level of verification for a visual tradeoff.

Evidence: `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:2024-2055`; spec decision `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:519`.

Priority: P2.

Recommended revision/action: No required change; ensure the manual smoke artifact is actually created during T6.

## G. Risk Points

### G22. `build_envelope` extraction and TimeDomainCanvas behavior

Finding: This is a new P0 blocker. The plan says `build_envelope` is copied from `TimeDomainCanvas._envelope` and tested against `xlim=(2.0, 8.0)`, but order_track calls it with `xlim=None`. Current `_envelope` immediately indexes `xlim[0]` and `xlim[1]`, so a literal extraction will crash unless the helper adds a new `None` behavior.

Evidence: current `_envelope` `mf4_analyzer/ui/canvases.py:466-467`; spec order_track call `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:291-298`; helper contract `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:452-464`; plan call/test `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:958-967,1693-1697`.

Priority: P0.

Recommended revision/action: Define `xlim=None` as full-range `(t[0], t[-1])`, add a direct test for that case, or pass an explicit full xlim from `_render_order_track`.

### G23. Removing `frozen=True` from `AnalysisPreset`

Finding: The adjusted plan covers the known compatibility risk. `AnalysisPreset` is currently frozen, and the plan adds a `dataclasses.replace(p, outputs=...)` test to ensure callers still work after removing `frozen=True`. That is sufficient for the documented concern.

Evidence: current dataclass `mf4_analyzer/batch.py:31-42`; replacement test plan `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:761-779`.

Priority: P2.

Recommended revision/action: No blocker; keep the replacement test and avoid in-place mutation of preset fields in new code.

### G24. Medium-scale memory realism

Finding: The 1200 x 1024 frame-stack estimate is acceptable for the compute chunk itself, and the spec's chunk model is reasonable. The plan still overclaims verification by mapping "batch 200 files memory < 200 MB" to a single synthetic compute test. It should include a batch-level RSS/tracemalloc check or mark that acceptance criterion manual/deferred.

Evidence: spec memory model `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:367-376`; memory test `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:538-578`; acceptance mapping `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md:2076-2078`.

Priority: P1.

Recommended revision/action: Add a small synthetic 200-task `BatchRunner` memory test with image export enabled, or downgrade 7-9 to manual smoke.

## Overall Verdict

Can this plan enter squad execution as-is? No.

P0 blockers that must be resolved first:

1. C10: `closeEvent` uses placeholder `_spectrogram_worker`, but the real FFT-time lifecycle is `_fft_time_thread` plus `_fft_time_worker`. Remediate by writing exact cleanup code for the existing QObject/QThread pair and adding an active FFT-time close test.
2. D12: the counts test can false-pass old nonzero-count semantics because alternating full-window tones overlap into adjacent hop windows. Remediate by using a deterministic stub/baseline or a non-overlapping helper-level test that proves old code fails.
3. G22: `build_envelope(xlim=None)` is used by order_track but not supported by the extracted TimeDomainCanvas behavior. Remediate by defining and testing `xlim=None` full-range behavior, or passing an explicit full xlim.

After those are fixed, the remaining P1 items are not blockers to dispatch but should be folded into the specialist briefs: odd-`nfft` amplitude parity, rpm-order full equivalence, cancellation granularity, stale-generation deterministic test, Nyquist metadata semantics, and batch-level memory verification.
