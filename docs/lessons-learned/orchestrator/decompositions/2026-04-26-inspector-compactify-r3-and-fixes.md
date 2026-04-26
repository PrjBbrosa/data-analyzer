# Inspector compactify R3 (#3-B / #6 / #8 / #9) + A/B/C fixes

**Date:** 2026-04-26
**Trigger:** user message "请实施 Inspector 紧凑化方案 #3 / #6 / #8 / #9 + A/B/C"
**Routing note:** message contained no canonical squad keyword (agent / squad / 团队 / 分工 / 重构 / refactor / 多专家 / multi-agent). Main Claude force-routed under the "missed keyword" rule because the body is clearly a multi-section UI refactor across the Inspector. Recommendation: add `紧凑化` and `实施 #N` to the trigger list. (Tracked separately by main Claude in an `orchestrator/` rework lesson if appropriate.)
**Mode:** plan

## Decomposition

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| T1 | inspector-compactify-r3-and-fixes (combined #3-B + #6 + #8 + #9 + A + B + C) | pyqt-ui-engineer | — | All 7 changes live in the same two files (`mf4_analyzer/ui/inspector_sections.py` + `mf4_analyzer/ui/style.qss`) plus a colocated test file (`tests/ui/test_inspector.py`). Splitting them invites the exact failure modes recorded in `orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` and `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`. The work is one coherent UI surface (Inspector) and one specialist domain (PyQt5 layout + QSS), so a single `pyqt-ui-engineer` dispatch is correct. The brief enumerates each change as an internal checklist with hard contracts and TDD ordering so the specialist still treats them as discrete deliverables. |

Single-specialist single-subtask is intentional. The user's request enumerates 7 sub-changes, but per `move-then-tighten-causes-cross-specialist-rework` and `parallel-same-file-drawer-task-collision`, splitting same-file same-domain changes across specialists or parallel slots produces rework or git-add collisions with no domain-boundary justification. The brief embeds the 7-item checklist so the specialist still ships them as discrete commits/edits inside one envelope.

## Lessons consulted

- `docs/lessons-learned/README.md`
- `docs/lessons-learned/LESSONS.md`
- `docs/lessons-learned/.state.yml`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`

## Notes

- No ambiguity that requires `superpowers:brainstorming` — the user has already aligned on every sub-change with main Claude in the prompt, including the Plan-A vs Plan-B trade-off for #9 (header_row composite over QGroupBox::title hack) and the C upgrade path (extend PresetBar to a builtin-aware mode rather than ship a parallel widget).
- Single dispatch → `superpowers:writing-plans` not required (>3 specialist dispatches threshold is not crossed).
- Hard constraints around contracts (`acknowledged` signal, public attrs of `PersistentTop`, primary-button role styles, color tokens) are repeated verbatim in the brief so the specialist cannot accidentally rename anything.
- TDD ordering is mandatory in the brief; specialist must report `tests_before` (red) and `tests_after` (green) plus `symbols_touched` per `silent-boundary-leak-bypasses-rework-detection`.
