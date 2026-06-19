# Decomposition: surface system redesign plan/spec review

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1 — read-only evidence review of `docs/superpowers/specs/2026-06-19-surface-system-redesign-design.md` and `docs/superpowers/plans/2026-06-19-surface-system-redesign.md` against the current checkout, including UI direction conflicts, live file/class/test/QSS selector availability, Task 1 test-fragility risks, and Task 2 status bar API preservation | pyqt-ui-engineer | [] | The request is entirely PyQt/UI surface review: porcelain tray, rounded floating bars, chart toolbar row, QSS selectors, Qt fixtures/APIs, and `MainWindow.statusBar` behavior. No DSP computation or package/module relocation ownership is needed. |

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
- `docs/lessons-learned/orchestrator/2026-05-30-ui-redesign-verb-missed-squad-trigger.md`
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md`
- `docs/lessons-learned/orchestrator/2026-04-26-interactive-playground-unblocks-ui-alignment.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`

## Notes

- User explicitly requested read-only review and fixed stdout shape (`REVIEW_DONE`, then `Findings / Risks / Suggested edits`). Specialist brief must preserve that output contract and must not edit files.
- Additional Codex lessons read for the review brief: `docs/lessons-learned/codex-review-report-contract.md`, `docs/lessons-learned/codex-plan-spec-literal-evidence.md`, `docs/lessons-learned/codex-visual-parity-rendered-screenshot.md`, and `docs/lessons-learned/pyqt-ui/2026-05-12-chart-toolbar-label-order.md`.
