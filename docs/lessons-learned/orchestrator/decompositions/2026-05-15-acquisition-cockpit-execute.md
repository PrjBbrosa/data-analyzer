---
date: 2026-05-15
slug: acquisition-cockpit-execute
mode: plan
source_user_request: |
  用 agent 编排完成 Acquisition Cockpit UI 实现；按 stage 推进，
  每隔几个大 stage 让 codex review；最终写总结报告。
  本波次范围：Stage 0–5（含 capture-first MVP 早出）；Stage 6/7/8 deferred。
spec: docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md
plan: docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md
---

## Scope decision

In-scope (this wave):
- Stage 0 — Preflight inputs (refactor-architect: doc + import scan, no .py changes beyond test scaffolds if needed for cross-package boundary).
- Stage 1 — `ui_kit` extraction (refactor-architect).
- Stage 2 — Capture core + health + thresholds + writer spike + CLI MVP (refactor-architect). Capture-First Cut allows shipping ahead of Stage 1 if scheduling demands; we keep it sequenced after Stage 0 and in parallel with Stage 1.
- Stage 3 — A2L events / search / config / preflight-estimate models (refactor-architect).
- Stage 4 — Cockpit shell, four-state UI, demo entry, fake/replay live cards (pyqt-ui-engineer).
- Stage 5 — Recording flow, review modal, Analyzer handoff (pyqt-ui-engineer; touches `mf4_analyzer/ui/main_window.py` for the public `load_file` wrapper only).
- Final — Execution report (refactor-architect; docs-only).

Deferred (explicit, NOT this wave):
- Stage 6 — History tab.
- Stage 7 — Packaging + Analyzer launch integration.
- Stage 8 — Vector/XCP production gate (requires Windows hardware).

## Codex review checkpoints

Inserted as `codex:codex-rescue` decomposition nodes (review-only, no code edits):
- CR1 — after Stage 2 (capture-first MVP gate). Validates: capture core public API, writer spike contract, CLI MVP behavior, channel-naming round-trip, against spec §Recorder Backend / §Health Snapshot / §Threshold Contract.
- CR2 — after Stage 4 (Cockpit shell gate). Validates: state-machine transitions, health-strip binding, left-pane search model wiring, no `_load_one` reference yet (Stage-5-owned), no Vector imports at macOS import time.
- CR3 — after Stage 5 (pre-report final gate). Validates: stop/flush/finalize ordering, `MainWindow.load_file` public wrapper does not regress Analyzer smoke tests, expected-channels round-trip, dropped-frame prompt branches.

Each codex review uses `task --prompt-file /tmp/<slug>.prompt --write` per
`orchestrator/2026-04-25-codex-prompt-file-for-long-review.md`.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S0 — Stage 0 preflight: confirm prototype paths, `_load_one`-gap note, P0 status, `.venv/bin/python` policy; record green-field scope list at `docs/analyzer/acquisition/reports/2026-05-15-cockpit-stage0-gap-note.md` | refactor-architect | [] | Stage 0 is pre-coding gate; produces a doc artifact under `docs/analyzer/acquisition/`. No widget surface, no signal processing. refactor-architect owns inventory/import-boundary scan. |
| S1 — Stage 1 `ui_kit` extraction + import-boundary AST test (`tests/ui/test_import_boundaries.py`) | refactor-architect | [S0] | Module relocation (`ui/icons.py`, `_fonts.py`, `style.qss`, `ui/widgets/searchable_combo.py` → `ui_kit/...`) + ast-walk boundary test = package structure / cross-module move. Per roster, refactor-architect owns package/import work even for Qt-adjacent files. |
| S2 — Stage 2 capture core + health.py + thresholds.py + writer spike + CLI MVP (`python -m mf4_analyzer.acquisition_capture`) | refactor-architect | [S0] | Pure-Python services with no Qt; CLI-first MVP. Capture-First Cut allows S2 to ship before S1 lands UI changes, so we run S1‖S2 (independent file ownership: `ui_kit/` vs `acquisition_capture/`). Per roster, this is non-FFT/non-filter Python module construction → refactor-architect, NOT signal-processing-expert. |
| CR1 — codex review of S1+S2 (capture-first MVP gate) | codex:codex-rescue | [S1, S2] | Review-only checkpoint. Audits actual git diff + pytest output against spec §Recorder Backend / §Health / §Threshold / §Persistence and against the channel-naming round-trip test. No code edits. |
| S3 — Stage 3 A2L events + search + config_store + preflight_estimates models | refactor-architect | [CR1] | Pure-Python models (no Qt). Search/scoring/filter/event-intersection/persistence/preflight-estimate functions; tests are unit-level. refactor-architect domain (module construction + algorithmic, but NOT FFT/filter). |
| S4 — Stage 4 Cockpit shell, state machine, health strip, left pane (consuming S3 models), live cards, right-panel variants, `--demo` entry, `live_downsampler` widget | pyqt-ui-engineer | [S3] | All deliverables are Qt widgets, signal/slot wiring, four-state machine, layout. pyqt-ui-engineer surface per roster. Cites responsive-pane-containers lesson for splitter/scroll cap on the left pane. |
| CR2 — codex review of S3+S4 (cockpit shell gate) | codex:codex-rescue | [S3, S4] | Review-only. Audits state-machine transitions, health-strip view model, search-span rendering, threshold module boundary (UI must not inline thresholds), no Vector import on macOS, no `_load_one` reference in cockpit code. |
| S5 — Stage 5 stop/flush/finalize sequence, review modal, `MainWindow.load_file(path)` public wrapper, expected-channels round-trip test, dropped-frame `继续/停止` prompt branches | pyqt-ui-engineer | [CR2] | Qt modal dialog + signal-slot stop/flush wiring + Analyzer-side public method addition. Touches `mf4_analyzer/ui/main_window.py` for ONE method only — bundled into the same specialist's brief per `orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md` (paired call-site / contract change). Cockpit side and Analyzer side are coupled by the handoff contract → single specialist owns both ends. |
| CR3 — codex review of S5 (pre-report final gate) | codex:codex-rescue | [S5] | Review-only. Audits stop/flush/finalize ordering, public-wrapper boundary, archive-vs-save failure isolation, dropped-frame prompt parity with spec, expected-channels test green. |
| REPORT — write execution report to `docs/analyzer/acquisition/reports/2026-05-15-cockpit-execute-report.md`: per-stage actual deliverables, test results, codex verdicts (verbatim quote of each CR's PASS/FAIL line), deferred items list, follow-up TODOs for Stage 6/7/8 | refactor-architect | [CR3] | Docs-only artifact; refactor-architect handles non-code documentation. Cites in/out-of-scope decisions, codex verdicts, and pinning of deferred work for the next planning cycle. |

## Parallelism & serialization rules

- **S1 ‖ S2**: independent file ownership (`mf4_analyzer/ui_kit/*` vs `mf4_analyzer/acquisition_capture/*`); dispatch in one message block.
- **S0 → {S1, S2}**: serial — S0 produces the gap note that S1/S2 must read.
- **CR1 → S3**: serial — Stage 3 lessons may surface from CR1 (e.g., channel-naming feedback could ripple into A2L event modeling).
- **S3 → S4**: serial — S4 imports S3 models.
- **CR2 → S5**: serial — S5 only starts after CR2 PASS.
- **CR3 → REPORT**: serial — REPORT cites CR3 verdict.
- Same-expert serialization: S1/S2/S3 are all refactor-architect; S0→S1‖S2→CR1→S3 keeps `git add` collision-free (each S touches disjoint paths) but S1‖S2 must use disjoint paths (verified above).

## Boundary discipline (forbidden symbols / files per stage)

- **S1 forbidden:** any file under `mf4_analyzer/acquisition_capture/`, `mf4_analyzer/acquisition_ui/`, `mf4_analyzer/ui/main_window.py` (Stage 5 owns its only modification).
- **S2 forbidden:** any file under `mf4_analyzer/ui/`, `mf4_analyzer/ui_kit/`, `mf4_analyzer/acquisition_ui/`. No Qt imports anywhere in `acquisition_capture/`.
- **S3 forbidden:** Qt imports; `acquisition_ui/*`; `ui/*`. May modify `can_logger/p0/a2l_probe.py` per Stage 3 owned-files list.
- **S4 forbidden:** `mf4_analyzer/acquisition_capture/*` modifications (consume only), `mf4_analyzer/ui/main_window.py`, `_load_one` references. Must import thresholds from `acquisition_capture/thresholds.py` rather than inline.
- **S5 forbidden:** any new top-level surface in `mf4_analyzer/ui/main_window.py` beyond the single public `load_file(path)` wrapper; `_load_one` body must remain unchanged.

Cross-references for the forbidden-symbol verification step (per
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`):
every specialist return must include a `symbols_touched` array; main Claude
greps the forbidden list before launching the next CR.

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index.
- `docs/lessons-learned/.state.yml` — counters: `top_level_completions=37`, `last_prune_at=21`; gap=16, below 20-threshold; no prune dispatch this run.
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — orchestrator returns plan only.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — fold mechanical metadata into the body-creator's brief; S1 import-hygiene is bundled into the same refactor-architect that does the move.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — require `symbols_touched`; reviewer greps forbidden symbols.
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md` — bundle Analyzer-side `MainWindow.load_file` into the Cockpit-side Stage 5 brief (single specialist owns both ends of the handoff contract).
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md` — codex review must use `--prompt-file --write`.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — same-expert parallel scheduling needs disjoint paths (verified for S1‖S2).
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — left navigator / right inspector container scroll & splitter rules; cited in S4 brief.
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` — state-machine driven enable/disable propagation; cited in S4 brief for health-strip and freeze-during-record.
- `docs/lessons-learned/pyqt-ui/2026-04-26-popover-accept-deactivate-race.md` — review modal QDialog idempotency; cited in S5 brief.
- `docs/lessons-learned/pyqt-ui/2026-04-27-modal-from-qthread-finished-segfaults-offscreen.md` — review modal must gate on `isVisible()`; cited in S5 brief.
- `docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md` — stop/flush/finalize Qt threading discipline; cited in S5 brief.

## Cadence

- `top_level_completions = 37`, `last_prune_at = 21`, gap = 16 (< 20). No prune dispatch needed at end of this run; main Claude still increments on completion of each top-level wave.
- If this run completes (top_level_status `done` or `partial`), counter becomes 38; still under threshold.

## Notes

- The user explicitly invoked agent orchestration ("用 agent 编排"); the message would have routed via squad runbook even without the keyword match. No missed-trigger lesson needed.
- Capture-First Cut: plan line ~167 authorizes Stage 2 to ship before Stage 1. We schedule S1‖S2 (independent paths) rather than S2-then-S1, so CR1 can validate the capture MVP and the ui_kit extraction in one review pass — saves one codex round-trip.
- No `superpowers:brainstorming` invocation: scope and stage boundaries are unambiguous from the user's message + the plan document. Three explicit codex checkpoints are user-requested, no design uncertainty.
- `superpowers:writing-plans`: the plan document already exists at `docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md`; we do not author a new plan, only execute against it.
