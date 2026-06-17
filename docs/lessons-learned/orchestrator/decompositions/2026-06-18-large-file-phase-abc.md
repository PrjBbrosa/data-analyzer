# Decomposition Audit — 2026-06-18 large-file-phase-abc

**Task:** Execute phases A, B, C of large-file structural decomposition
(spec: `docs/superpowers/specs/2026-06-18-large-file-decomposition-design.md`).
Phase D (canvases.py legacy matplotlib retirement) approved-for-later only.

## Subtask table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| A — `inspector_sections.py` → `inspector_sections/` package | refactor-architect | none | Pure form-A relocation (8+ independent widget classes, no shared self). Spec §3.1. refactor-architect owns move/shim/import wiring. QMenu monkeypatch anchor must survive in __init__.py. |
| B — `markup/editor.py` intra-package split | pyqt-ui-engineer | A (serialized for git-index safety) | Extracts QUndoCommand, QGraphicsItem, and view classes — all Qt widget domain. editor.py keeps MarkupEditor + re-imports moved names so editor_mod.X access is unchanged. Spec §3.3. |
| C — `chart_stack.py` → `chart_stack/` package | refactor-architect | B (serialized for git-index safety) | Form-A relocation of 4 major Qt classes + helper groups. ChartStack is the retained coordinator. __init__.py re-exports 4 names tested directly. Spec §3.2. Has toolbar/widget content — pyqt-ui-engineer named as secondary review in spec §5, but brief asks refactor-architect to do the structural move; toolbar behavior is NOT changing. |

## Serialization rationale

User said A/B/C are independent. However lesson
`docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
establishes that even disjoint-file parallel mutators share the git index/HEAD
on the same branch and can cross-contaminate commits. Each phase is a large
multi-file creation/deletion (~8+ new files per phase). Serializing A→B→C
adds a full pytest gate between each, which is required by DoD anyway.
Cost: sequential wall-clock time. Benefit: zero index collision risk.

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md`

## Phase D note

User approved retiring legacy matplotlib canvases in `canvases.py` (spec §3.6
step 2). This is NOT in this batch. Main Claude should record the approval
and schedule D as a follow-on task.
