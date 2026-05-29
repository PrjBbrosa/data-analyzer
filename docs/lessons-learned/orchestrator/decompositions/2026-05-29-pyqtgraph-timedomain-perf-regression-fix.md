# Decomposition — PyQtGraph TimeDomain perf-regression fix

**Date:** 2026-05-29
**Mode:** plan
**Source plan:** `docs/superpowers/plans/2026-05-29-pyqtgraph-timedomain-perf-regression-fix.md`
**Top-level request:** "你参照这个 plan 安排 agent 执行" — execute the existing,
fully-fleshed perf-regression-fix plan via the squad.

## Task summary

The plan defines four tasks. Tasks 1-3 are pure PyQt/pyqtgraph rendering
fixes, all editing the **same two files**:

- `mf4_analyzer/ui/pg_canvases.py` (production)
- `tests/ui/test_pg_timedomain_canvas.py` (tests)

Task 4 is verification only (no code).

| # | Plan task | Edits |
|---|-----------|-------|
| 1 | Drop `antialias=True` at two curve sites | pg_canvases.py:572,581 + test |
| 2 | Add `_teardown_inside_labels`; fix ghost-badge scene leak | pg_canvases.py clear()/_recheck + test |
| 3 | Pin inside labels top-left; drop per-frame `sigRangeChanged` reposition | pg_canvases.py:2106-2111 + test |
| 4 | Full regression sweep + live GUI verification | none (verify only) |

## Routing decision

- The surface under change is the pyqtgraph TimeDomain canvas: curves,
  inside-label `TextItem` badges, GraphicsScene lifecycle, range/resize
  signal wiring. This is a **surface/rendering** concern, not a
  computation (no FFT/Welch/filter). Surface-vs-computation rule →
  `pyqt-ui-engineer`.
- It is NOT a package/module refactor, so the persistent-UI routing note
  keeps it with `pyqt-ui-engineer` rather than `refactor-architect`.

## Sequencing constraint (decisive)

Tasks 1, 2, 3 all mutate the SAME two files. Per
`2026-04-24-parallel-same-file-drawer-task-collision.md`, parallelising
same-file edits (even one-line ones) races `git add` and produces commits
whose titles don't match their contents. The prescribed fix is to
**bundle shared-file edits into a single specialist's brief**. Therefore
tasks 1-3 are collapsed into ONE `pyqt-ui-engineer` envelope that does
all three TDD cycles sequentially with three separate commits (as the
plan already specifies). Task 4 (verification) depends on that envelope
and runs after it.

This collapse also keeps each `git commit` boundary intact (one commit
per fix, exactly as the plan's Step 5 blocks dictate), which a parallel
fan-out would have destroyed.

## Decomposition

| subtask | expert | depends_on | rationale |
|---------|--------|------------|-----------|
| impl-tasks-1-3 (antialias drop + ghost-badge teardown helper + pin labels / drop per-frame reposition), each TDD-driven, three commits | pyqt-ui-engineer | — | All three are pyqtgraph canvas rendering fixes in the same two files; bundled into one envelope to avoid same-file `git add` collisions (lesson 2026-04-24). |
| verify-task-4 (full regression sweep + live GUI verification) | pyqt-ui-engineer | impl-tasks-1-3 | Verification-only; must run after the code lands. Live GUI check is mandatory because offscreen tests missed the original live lag. |

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`

## Specialist-citation lessons (for briefs)

- `docs/lessons-learned/pyqt-ui/2026-05-28-arraytoqpath-not-byte-identical-to-moveto-lineto-loop.md`
  — pyqtgraph curve-build subtleties; relevant context for the curve sites.
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
  — pyqtgraph vs matplotlib test-coupling; relevant when running the suite.
- `docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`
  — the Task 3 test drains `_flush_pending_refresh()` after `set_xlim`;
  ordering matters.
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`
  — callback/listener lifecycle on rebuild; conceptual parallel to the
  scene-item + signal teardown in Task 2/3.
