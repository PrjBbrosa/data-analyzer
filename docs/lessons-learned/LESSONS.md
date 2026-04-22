# Master Lessons Index

Format: `- [<slug>](<role>/YYYY-MM-DD-<slug>.md) [tag1][tag2] — one-line hook`

Write protocol: `docs/lessons-learned/README.md`.

## orchestrator

- [task-tool-unavailable-blocks-dispatch](orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md) [dispatch][tooling][architecture][planner-executor-split] — Task absence is EXPECTED, not a blocker; orchestrator plans, main Claude dispatches.
- [move-then-tighten-causes-cross-specialist-rework](orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md) [decomposition][rework][cross-specialist] — Splitting "create file body" and "tighten file imports" across two specialists causes file-level rework; fold mechanical metadata edits into the body creator's brief unless domain expertise is required.

## signal-processing

## pyqt-ui

## refactor

- [cross-layer-constant-promote-to-package-root](refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md) [layering][constants][dependency-rules] — When two layers forbidden from importing each other share a constant, hoist it to the package root, do not duplicate it.
