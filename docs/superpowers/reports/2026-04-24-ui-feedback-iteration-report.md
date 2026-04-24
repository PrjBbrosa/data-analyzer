# UI Feedback Iteration Report

**Date:** 2026-04-24
**Scope:** Precision Light UI follow-up after screenshot review.
**Status:** Implemented and verified.

## Summary

The UI modernization moved the app toward the selected **Precision Light**
direction, then went through two screenshot-driven correction passes. The
latest correction supersedes the first narrow-Inspector approach: pane
overflow is now handled by scrollable/resizable containers rather than by
changing compact form rows into stacked field blocks.

## User Feedback Captured

1. Active file row contrast was too strong.
2. Right Inspector controls overlapped when the window was narrow.
3. Spinbox/combobox button chrome looked too plain and later showed
   square/dot artifacts.
4. FFT axis text rendered incorrectly.
5. Time-domain y-axis titles could be clipped.
6. The final layout correction: the right side should add a scrollbar,
   and the left file list needs more vertical area for multiple files.

## Final Decisions

- Keep the three-pane topology.
- Keep Inspector forms compact and aligned with `QFormLayout`.
- Handle right-pane overflow with a pane-level `QScrollArea`.
- Handle left file-list capacity with a vertical `QSplitter` between the
  file list and channel tree.
- Avoid custom QSS arrow hacks for combo/spin controls if they render as
  artifacts on Windows.
- Use screenshot feedback to distinguish visual polish from layout
  semantics; do not solve container capacity problems by redesigning
  individual fields.

## Implementation Trail

- `6cb7904 feat(ui): apply precision light visual system`
  - Introduced Precision Light QSS, icons, toolbar, pane, chart, and
    Inspector polish.
- `6a7b973 fix(ui): prevent inspector field stacking`
  - Addressed first screenshot issues. Its vertical field-block part was
    later superseded by the container-level fix.
- `858d78a fix(ui): add inspector scroll and expandable file list`
  - Added right Inspector scrolling, restored compact form rows, expanded
    the left file area with a vertical splitter, and removed arrow
    artifact styling.

## Files Most Relevant To Future UI Work

- `mf4_analyzer/ui/style.qss`
- `mf4_analyzer/ui/file_navigator.py`
- `mf4_analyzer/ui/inspector.py`
- `mf4_analyzer/ui/inspector_sections.py`
- `mf4_analyzer/ui/canvases.py`
- `mf4_analyzer/ui/chart_stack.py`

## Verification

```bash
.\.venv\Scripts\python.exe -m pytest tests -q
# 53 passed
```

Constructor smoke after the final layout correction also confirmed:

- `Inspector` contains `QScrollArea#inspectorScroll`.
- `FileNavigator` contains `QSplitter#navigatorSplitter`.

## Agent Handoff

New lesson:

- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`

Agent memory updated:

- `.claude/agents/pyqt-ui-engineer.md`
- `.claude/agents/squad-orchestrator.md`

Future UI agents should load the new lesson for tasks involving narrow
panes, right Inspector overlap, left navigator file-list height, splitter
sizing, scroll areas, or screenshot-driven layout feedback.
