# Decomposition — pyqtgraph TimeDomainCanvas migration (codex-driven plan)

**Date:** 2026-05-28
**Source request:** 基于 codex 的更新安排 agent team 开展工作；每 wave 完成后 codex review.
**Driver specs:**
- `docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md`
- `docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md`
- `docs/superpowers/specs/2026-05-28-review-followup-fixes.md` (out-of-scope marker — B1-B7 are historical baseline)

## Wave layout (review cadence)

| Wave | Subtasks | Codex-rescue review focus |
| --- | --- | --- |
| W0 | T1 baseline+deps, T2 contract freeze | baseline numbers exist; contract tests really pin labels/signals/`channel_data` raw invariant |
| W1 | T3 AxisHandle adapter, T4 cutils envelope wrapper | adapter does not change dialog UI; envelope fallback parity exhaustive (empty/reversed/NaN/non-monotonic/non-contig) |
| W2 | T5 PG canvas skeleton, T6 subplot/overlay/cursor parity | custom curve/pixmap layer present (not bare PlotDataItem); inside-label parity verified with rendered screenshot |
| W3 | T7 production switch | screenshot-equivalent UI; full perf measurement; no UI deltas |
| W4 | T8 final report | report contract: baseline/final numbers, C-path-vs-fallback, exact verify cmds, remaining risks |

## Subtasks

| # | subtask | expert | depends_on | rationale |
| --- | --- | --- | --- | --- |
| T1 | Baseline & dependency gate (req+venv smoke+slow perf test+baseline numbers) | signal-processing-expert | — | Numeric measurement infra + dependency probe = numeric/wrapper work; UI invariance not yet under test. Body-creating perf harness routes to signal-processing-expert per `2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`. |
| T2 | Contract freeze tests + `reset_cursor_state()` helper on existing canvas + `MainWindow._reset_cursors` call-site update | pyqt-ui-engineer | T1 | Public surface = signals/buttons/shortcuts/cursor lifecycle; pyqt-ui owns Qt object surface and `MainWindow` UI plumbing. |
| T3 | `AxisHandle` protocol + `MplAxisHandle` + `ChartOptionsDialog` internal rewire + `_axis_interaction` dispatch | pyqt-ui-engineer | T2 | Dialog/axis adapter is widget/QObject surface; matplotlib axes are UI objects. |
| T4 | `positions_envelope(...)` wrapper around `asammdf.blocks.cutils.positions` with numpy fallback + parity tests + micro-bench | signal-processing-expert | T1 | Envelope downsampling + cutils call = numeric/DSP work, parity gates by build_envelope output semantics. |
| T5 | `TimeDomainCanvasPG` skeleton (single-channel, raw `channel_data`, compatibility facades, custom curve-layer cache, pixmap path) | pyqt-ui-engineer | T2, T3, T4 | Canvas widget + pyqtgraph view-box surface = UI engineering. Curve-layer cache straddles, but production-path widget = pyqt-ui. |
| T6 | Subplot/overlay/cursor/scroll parity in PG canvas (5-channel modes, Y drag, Ctrl/Shift/plain wheel, single+dual cursor HTML, inside label parity, span compat method) | pyqt-ui-engineer | T5 | Interaction parity = widget/event-handling surface. |
| T7 | Production switch in `ChartStack` (single construction point) + UI-invariant assertion tests + screenshot parity | pyqt-ui-engineer | T6 | Pure UI surface flip; old `TimeDomainCanvas` kept in tree for rollback. |
| T8 | Final verification + results report (baseline vs final numbers, C/fallback path, verify cmds, risks) | signal-processing-expert | T7 | Numeric measurement reporting + perf evidence = signal-processing-expert (matches `codex-performance-ui-audit-flow.md` author pattern). |

## Cross-cutting defensive notes (every brief MUST cite)

1. **No re-opening B1-B7.** Review-followup spec is historical. If a B1-B7 file is touched as a side effect, flag and stop.
2. **Codex-rescue prompt MUST be written to `/tmp/<wave>-prompt.md` and invoked via `task --prompt-file /tmp/<wave>-prompt.md --write`.** Never inline a long prompt with shell quoting — see `codex-prompt-file-for-long-review.md`.
3. **Codex review reports must follow exact-citation contract:** `git show --name-status --oneline <sha>` + `nl -ba` / `rg -n` for each finding; verdict tokens per the user's vocabulary; written to one markdown file under `docs/analyzer/reviews/` (per `codex-analyzer-doc-routing.md`).
4. **No "all green" without rendered screenshots** at W2 + W3 for inside-label/cursor-pill/overlay color — `codex-visual-parity-rendered-screenshot.md`.
5. **No bare `python ...` commands** in any doc/report; always `.venv/bin/python` and offscreen Qt with `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen` per `codex-runtime-verification-entrypoints.md`.
6. **Confirmed issue list = full scope.** If user later narrows to one phase, do not silently drop the rest (`codex-confirmed-issue-list-means-remaining-scope.md`). All 8 tasks remain in scope until explicit cancel.
7. **Phantom API guard.** `asammdf.blocks.cutils.positions` is not in the `.pyi`; the wrapper must `getattr` with `callable(...)` probe and fall back to `build_envelope`. No `MagicMock` mocking of pyqtgraph/asammdf module-level surfaces in tests — use `create_autospec` or structured fakes (`codex-phantom-api-surface-guards.md`).
8. **Plan-spec literal evidence.** Each specialist must `rg -n` for retired identifiers (`PlotDataItem.setData`, old `_ax/_bx` direct mutation, `enable_span_selector` autoenable, `B1-B7` references inside their changed files) before declaring task complete (`codex-plan-spec-literal-evidence.md`).
9. **Acquisition-doc isolation.** Report file goes to `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md` (analyzer scope, not acquisition); but if any side-effect cockpit/A2L import is touched, honor `codex-windows-native-import-guard.md`.
10. **FFT-time review shields.** This migration is TimeDomain-only; if any specialist touches `fft_time_ctx`, `FFTTimeWorker`, `SpectrogramResult`, or `_fft_time_cache_key`, halt and rescope (`codex-fft-time-review-shields.md`).
11. **Review report contract.** Each codex-rescue invocation MUST receive: (a) wave summary written by main Claude listing files changed, (b) explicit citation/verdict shape, (c) `--write` flag enabled (`codex-review-report-contract.md` + `codex-prompt-file-for-long-review.md`).
12. **Performance/UI audit flow.** Baseline numbers MUST be captured BEFORE any pyqtgraph code lands; report writing precedes optimization where the user asks for "research first" (`codex-performance-ui-audit-flow.md`). Here T1 satisfies the baseline-first rule.

## Lessons consulted (step 4 of orchestrator protocol)

- `docs/lessons-learned/LESSONS.md` (master index)
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`
- `docs/lessons-learned/codex-plan-spec-literal-evidence.md`
- `docs/lessons-learned/codex-confirmed-issue-list-means-remaining-scope.md`
- `docs/lessons-learned/codex-phantom-api-surface-guards.md`
- `docs/lessons-learned/codex-runtime-verification-entrypoints.md`
- `docs/lessons-learned/codex-windows-native-import-guard.md`
- `docs/lessons-learned/codex-review-report-contract.md`
- `docs/lessons-learned/codex-visual-parity-rendered-screenshot.md`
- `docs/lessons-learned/codex-performance-ui-audit-flow.md`
- `docs/lessons-learned/codex-acquisition-validation-evidence-gates.md`
- `docs/lessons-learned/codex-analyzer-doc-routing.md`
- `docs/lessons-learned/codex-fft-time-review-shields.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-qss-padding-overrides-setcontentsmargins.md`
- `docs/lessons-learned/signal-processing/2026-04-25-envelope-cache-bucket-width-quantization.md`
- `docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`

## Rework-risk heat map

- T2/T3/T5/T7 all may touch `mf4_analyzer/ui/canvases.py` and `mf4_analyzer/ui/chart_stack.py`. Main Claude must enforce that:
  - T2 touches `canvases.py` ONLY to add `reset_cursor_state()` (symbol allow-list).
  - T3 does NOT touch `canvases.py` — only `dialogs.py` + `_axis_interaction.py` + new `_axis_handle.py`.
  - T5 creates `pg_canvases.py` and MAY add a single import line in `canvases.py` only if necessary (prefer keeping the file untouched).
  - T7 touches `chart_stack.py` ONLY for the time-canvas construction line; UI label/shortcut blocks are off-limits.
- T4 vs T5: T4 owns `_envelope_cutils.py`; T5 only imports from it. No body change in T5.
- T6 vs T5: same file (`pg_canvases.py`), serial (T6 depends on T5) — no parallel collision risk.

## Wave-end codex-rescue dispatch template (main Claude usage)

For each wave end, main Claude assembles:

1. `git diff --stat <wave-start>..HEAD` and `git log --oneline <wave-start>..HEAD`.
2. Writes prompt-file to `/tmp/wave-<n>-rescue-prompt.md` containing:
   - wave goal (from this audit's wave table)
   - files changed
   - test commands run + outputs (last 50 lines each)
   - explicit ask: cite file:line for any concern; verdict token PASS / NEEDS-REWORK / NEEDS-INFO; write report to `docs/analyzer/reviews/2026-05-28-pyqtgraph-wave<n>.md`
3. Invokes `task --prompt-file /tmp/wave-<n>-rescue-prompt.md --write` with `TMPDIR=/tmp` env.
4. If verdict = NEEDS-REWORK: re-dispatch the affected expert with the rescue report content embedded in the brief.
