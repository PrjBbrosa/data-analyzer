# FFT vs Time 2D - Module E Final Delivery Review

## Verdict

request-changes

The implementation appears functionally green: fresh pytest passes, the
Module C source nit is actually cleaned up, and the validation smoke has
real evidence for the Phase 1 feature surface. I would not declare the
rollout complete yet because the final validation artifact has stale and
internally inconsistent automated-test evidence, and it is missing the
required Lessons Added trail.

## Blockers

1. Automated-test evidence is not internally consistent enough for final
   delivery. `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:26`
   records a 128-test full-suite run, and
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:49`
   says the 16 signal tests plus 112 UI tests sum to 128. However the per-file table at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:34`
   through
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:47`
   sums to 123, not 128. The same mismatch exists in the T9
   source payload at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-T9-test-execution.md:34`
   through
   `docs/superpowers/reports/2026-04-25-fft-vs-time-T9-test-execution.md:55`.
   A fresh rerun for this review also collected and passed
   135 tests (`PYTHONPATH=. .venv/bin/pytest -q`, exit 0, 135 passed in
   12.78s), so the validation report needs a current or clearly scoped count
   before it can be the final record.

2. The validation report is missing the required Lessons Added trail.
   `docs/lessons-learned/LESSONS.md:27` lists
   `pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md`, and
   `docs/lessons-learned/LESSONS.md:28` lists
   `pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`. The validation
   report links the tight-bbox lesson only in smoke/limitations prose at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:114`
   and
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:181`,
   does not mention the QThread lesson, and has no
   `## Lessons Added` section before its final status block at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:325`.

## Important

1. The memory-ceiling probe does not match the requested exact parameter
   trace. The review checklist says the probe should be a 5e6-sample signal
   with `nfft=8192` and `overlap=0.99`; the validation report records
   `overlap=90%` at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:115`.
   The 90% case still exceeds the 64 MB ceiling and is useful evidence, but
   the final report should either correct the parameter or explain the
   intentional deviation.

2. T6's task report appears to have a dangling lesson-section promise.
   `docs/superpowers/reports/2026-04-25-fft-vs-time-T6-worker-thread.md:361`
   through
   `docs/superpowers/reports/2026-04-25-fft-vs-time-T6-worker-thread.md:367`
   says the QThread deadlock lesson is being written and
   refers to a "Lessons added" section below, but the file ends there without
   that section. The lesson itself exists in the corpus, so this is a report
   trail issue, not a code issue.

## Nits

1. The validation report refers to `SpectrogramAnalyzer.compute_amplitude`,
   but the actual signal-layer API is `SpectrogramAnalyzer.compute`.
   Instances are at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:115`
   and
   `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md:149`;
   the implementation defines `compute` at
   `mf4_analyzer/signal/spectrogram.py:160`.

2. The Module C nit is resolved in source. The former future-tense
   `_copy_fft_time_image` comment is gone; `mf4_analyzer/ui/main_window.py:217`
   now starts a real FFT-vs-Time wiring block and
   `mf4_analyzer/ui/main_window.py:226` through
   `mf4_analyzer/ui/main_window.py:230` connects the export
   relay signals to `_copy_fft_time_image`.

## Spec-compliance scorecard

| Item | Status | one-line note |
|---|---|---|
| 1. Validation report completeness | PASS | Required sections are present, and the 13-row manual UI table has 13 PASS rows with concrete observations at `validation.md:101-115`; automated-test arithmetic is handled under item 3. |
| 2. Consistency with design | PASS | Excluded Phase 1 items are listed at `validation.md:160-169`; included cursor, slice FFT, color/dynamic controls, export, and cache behavior are exercised at `validation.md:107-114`. |
| 3. Test count traceable | FAIL | Validation cites T9 and 128 tests at `validation.md:18-30`, but the per-file totals at `validation.md:34-47` do not add to 128, and fresh pytest now passes 135 tests. |
| 4. Module review verdicts | PASS | Validation references A=approve and B/C/D=approve-with-nits at `validation.md:217-224`. |
| 5. Module C nit closure | PASS | Actual source no longer has the dangling future-tense comment; export wiring exists at `mf4_analyzer/ui/main_window.py:217-230`. |
| 6. Real-data validation justification | PASS | MF4 rejection and synthetic CSV justification are explicit at `validation.md:81-90`, including `relative_jitter ~= 2.04` and the synthetic 4 Hz + 50 Hz CSV. |
| 7. Memory ceiling probe | FAIL | Rejection trace exists at `validation.md:115`, but it records `overlap=90%` rather than the requested `overlap=0.99`. |
| 8. Cross-task lesson trail | FAIL | Lessons exist in `LESSONS.md:27-28`, but validation has no Lessons Added section and omits the QThread lesson. |
| 9. No-git fallback | PASS | Repository has no `.git`; T10 records the Plan v2 no-commit fallback at `T10-manual-smoke.md:217-223`, and validation records changed files at `validation.md:334-342`. |
| 10. Flagged-issues hygiene | PASS | T5 flags were closed by T7, Module C comment nit was closed by T8, and T8's offscreen export evidence/desktop limitation is carried in validation at `validation.md:117-137` and `:181-189`. |
| 11. Pytest re-run | PASS | Fresh command `PYTHONPATH=. .venv/bin/pytest -q` exited 0 with 135 passed in 12.78s; count drift is the blocker, not test failure. |
| 12. Cosmetic / contradictions / links | FAIL | Broken arithmetic in test totals, missing Lessons Added section, and `compute_amplitude` API typo remain. Checked referenced report/lesson paths exist. |

## Final recommendation for main Claude

Do not run the final aggregation pass or update `docs/lessons-learned/.state.yml`
yet. First make a documentation-only cleanup pass on the validation/T6
evidence trail: reconcile the pytest count with a fresh run or explicitly
scope the historical 128-test count, add a Lessons Added section linking both
pyqt-ui lessons, and fix the memory-probe/API-name inconsistencies. Then rerun
Module E. After Module E approves, proceed with aggregation, state.yml update,
and the final user-facing rollout summary.
