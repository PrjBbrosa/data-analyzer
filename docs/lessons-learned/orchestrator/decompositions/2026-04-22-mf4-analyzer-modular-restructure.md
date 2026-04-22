---
task: "Refactor MF4 Data Analyzer V1.py into modular package mf4_analyzer/{io,signal,ui} + app.py per approved spec"
date: 2026-04-22
updated: 2026-04-22
spec: docs/superpowers/specs/2026-04-22-mf4-analyzer-modular-restructure-design.md
---

# Decomposition

Six subtasks, strictly serial (S1 → S2 → S3 → S4 → S5 → S6). Adopted
verbatim from the approved spec; this audit re-states them and
captures briefs the executor will dispatch.

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1 `scaffold-package` | refactor-architect | — | Pure file scaffolding, no code moves. Routing keyword: `package`, `module`, `relocation`. |
| S2 `move-signal` | refactor-architect | [S1] | Verbatim copy of `FFTAnalyzer`/`OrderAnalyzer`/`ChannelMath` into `signal/`. Pure relocation. Originals stay in monolith to keep AST-extract test green. |
| S3 `move-io` | refactor-architect | [S2] | Verbatim copy of `DataLoader`/`FileData` into `io/`. Pure relocation. Originals stay in monolith. |
| S4 `move-ui-and-app` | refactor-architect | [S3] | Move 8 UI classes into `ui/`, move `setup_chinese_font`, move `FILE_PALETTES`, write `app.py`, empty monolith to 4-line launcher. Pure relocation + import wiring. |
| S5 `rewire-tests-and-guard` | signal-processing-expert | [S4] | Rewrite `test_fft_amplitude_normalization.py` to use direct import; add `test_signal_no_gui_import.py` guard test. Tests are the safety net for numeric correctness; rewriting test import strategy belongs to sig-proc per spec. |
| S6 `tighten-ui-imports` | pyqt-ui-engineer | [S5] | Replace `from PyQt5.QtWidgets import *` in 4 ui/*.py files with explicit name lists. Knowing which Qt classes each UI module uses is UI-domain knowledge. |

# Lessons consulted

- `docs/lessons-learned/README.md`
- `docs/lessons-learned/LESSONS.md`
- `docs/lessons-learned/.state.yml`
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
- `docs/lessons-learned/orchestrator/decompositions/2026-04-22-fft-ylabel-zh-and-amp-scaling-sanity.md` (audit, not a lesson)
- `docs/lessons-learned/orchestrator/decompositions/2026-04-22-fftanalyzer-docstring-smoke-test.md` (audit, not a lesson)

The role-specific lesson directories (`signal-processing/`, `pyqt-ui/`,
`refactor/`) currently contain no `<role>/YYYY-MM-DD-<slug>.md` lesson
files — only `.gitkeep` placeholders if any. There are therefore no
refactor / package-reorg / test-import-switch lessons to cite from
those subdirectories at this time.

# Notes

- Spec was produced via `superpowers:brainstorming` and committed
  before this plan was requested. Plan adopts the spec wholesale.
- Serial execution mandated by the spec (S2/S3 both edit the monolith;
  S5/S6 require the post-S4 empty-monolith state). No parallelism.
- Expected rework hits per spec (5–6 lessons) are healthy artefacts of
  the move-then-tighten pattern, not regressions. Main Claude's Phase
  3 will auto-write them.
- Post-runbook: spec calls for `codex:rescue` independent review after
  Phase 4 completes. That is outside the squad runbook proper but
  noted here so the executor remembers.
- `superpowers:writing-plans` was effectively satisfied by the design
  spec itself (spec covers >3 dispatches with full layout, dependency
  rules, test strategy, and acceptance criteria). No separate plan
  document is required.
