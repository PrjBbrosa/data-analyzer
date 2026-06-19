# Decomposition Audit: Surface / Background Color System Redesign (云白 / snow)

**Date:** 2026-06-19
**Slug:** surface-system-snow-redesign
**User request summary:** Implement the approved "云白 / snow" surface redesign
(Tasks 1-8 of the approved plan) as a single serialized `pyqt-ui-engineer` track
in `mf4_analyzer/ui_kit/style.qss`, with a main-Claude visual-verification
checkpoint after Task 7 and a final invariant audit in Task 10.

## Subtask Table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| T0: Baseline capture (test run + before screenshots) | pyqt-ui-engineer | — | Single-file QSS work; specialist owns the run skill and can record test counts; no upstream deps |
| T1: Snow token header + global base `#f0f3f7` | pyqt-ui-engineer | T0 | Replaces the old palette comment + changes the one global window bg rule; must come first so all subsequent tasks inherit the correct base color |
| T2: Left pane FileNavigator → snow panel + divider seam | pyqt-ui-engineer | T1 | Recolors `style.qss:786-790`; the divider value from T1 must be settled before the seam is set |
| T3: Center ChartStack → snow surface + white chart card border | pyqt-ui-engineer | T1 | Recolors `style.qss:1163-1178`; surface token `#f7f9fc` from T1 required |
| T4: Right Inspector pane → snow panel + divider seam | pyqt-ui-engineer | T2 | Mirrors T2 on the right side; ordering after T2 keeps seam values consistent and allows visual comparison |
| T5: Detint green signal card → white | pyqt-ui-engineer | T4 | Touches `style.qss:978-985`; T4 must land first so inspector pane bg is already settled (avoids one-step-at-a-time calibration confusion) |
| T6: Detint blue params card → white | pyqt-ui-engineer | T5 | Touches `style.qss:1012-1018`; depends on T5 so both cards are whitened in one review pass |
| T7: Divider logic B — transparent splitter handle + toolbar seam + frame seams | pyqt-ui-engineer | T6 | Touches `style.qss:40-44`, `:302-305`, and appended frame-seam rules; must come after all pane colors are settled to avoid calibrating the seam against an unsettled bg |
| T8: Selected mode tab → accent wash | pyqt-ui-engineer | T7 | Touches the `[segment]:checked` rule; logically last because it's the only interaction-color change, not a surface change |
| T9 (main Claude checkpoint): Visual calibration — screenshot all 4 modes | main Claude | T8 | GUI screenshotting is NOT possible inside a headless subagent; main Claude or the user does this step and decides if a token nudge (§10 fallback) is needed |
| T10: Final verification + invariant audit | pyqt-ui-engineer | T9 | `pytest tests/ui -q`; grep diff for forbidden dimension keywords; export regression guard; commit if any review fixes |

**Serialization note:** All T1-T8 subtasks touch the same file (`style.qss`)
and are dispatched to the SAME specialist. Per
`orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`,
same-file mutations must be serialized even when diffs are disjoint. T1→T2→T3→T4→T5→T6→T7→T8 run sequentially in a single brief.

## Lessons consulted

- `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`
- `docs/lessons-learned/pyqt-ui/2026-06-04-dynamic-property-border-needs-styledbackground-and-padding.md`
- `docs/lessons-learned/pyqt-ui/2026-04-26-action-button-on-group-title-needs-qframe-header.md`
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
