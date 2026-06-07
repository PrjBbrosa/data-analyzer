# Decomposition — 时域 View 标签切换收尾(修回归测试 + Task 9 Step 5 focus routing)

**Date:** 2026-06-04
**Mode:** plan
**Routing note:** No squad trigger keyword matched the user message;
routed under CLAUDE.md "Missed triggers" rule because it is substantive
multi-step UI `.py` work (chart_stack.py / main_window.py / pyqtgraph
canvases). missed_keyword: none (semantic judgement).

## Task summary

Continue codex's WIP (archived at fd625478): P1 Task1-7 done, P2
Task8/Task9 first-4-steps done. Two remaining items:

- **A.** Fix 2 codex-introduced regression tests in
  `tests/ui/test_chart_stack.py` (turn the branch green). Root cause:
  `_time_card` was wrapped in a `QSplitter` (`_time_split`) and
  `ChartStack.__init__` now does `self.stack.addWidget(self._time_split)`,
  so `cs.stack.widget(0)` returns the splitter, not the `TimeChartCard`.
  Two old tests assert `isinstance(widget(0), TimeChartCard)` and access
  `widget(0).toolbar`. Fix = adapt the TESTS to go through the splitter
  (`cs._time_card` or `cs.stack.widget(0).widget(0)`). Do NOT revert the
  QSplitter wrapping.
- **B.** Finish P2 Task 9 Step 5 focus routing: `ChartStack.focused_card()`
  / `focused_canvas()` (default primary; secondary becomes focused on
  click), focus highlight via `setProperty("focused", True)` + stylesheet,
  and route `MainWindow.plot_time` / `_ch_changed` target canvas from the
  hard-coded `self.canvas_time` to `self.chart_stack.focused_canvas()`.
  This step: primary→secondary click switch + highlight + channel-check
  routing only; cursor/toolbar routing is later same-milestone polish.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| A. Adapt 2 regression tests in test_chart_stack.py to reach TimeChartCard through the QSplitter | pyqt-ui-engineer | (none) | Test-side adaptation to a Qt widget-tree structural change (QSplitter wrapping) — pyqt-ui domain; touches no algorithm. Surface/widget-tree, not computation. |
| B. Implement ChartStack.focused_card()/focused_canvas() + click-to-focus highlight + MainWindow target-canvas routing | pyqt-ui-engineer | A | PyQt widget focus state, QSS/setProperty highlight, signal/slot click handling, canvas routing — squarely pyqt-ui. Serialized after A because both edit chart_stack.py / main_window.py (shared-file collision rule). |

## Serialization rationale

A and B are the SAME expert and B edits `chart_stack.py` + `main_window.py`.
A edits `tests/ui/test_chart_stack.py` only — file-disjoint from B's
sources, BUT they are sequenced (A → B) anyway so the branch is green
before B layers focus routing on top, and so the executor gets a clean
rework-detection baseline. They could in principle run parallel (disjoint
files), but A is a fast prerequisite that proves the structural baseline;
running A first de-risks B's understanding of the splitter tree.
Per `parallel-same-file-drawer-task-collision`, never parallelise
same-expert tasks that might converge on a shared file; keeping them
serial is the safe default here.

## Red lines surfaced to both briefs (repo memory)

1. `project-ui-files-structural-corruption`: chart_stack.py / main_window.py
   have a history of duplicate same-name method definitions (last one
   wins). Before adding/editing any method, `grep -n "def <name>"` to
   confirm a single definition in the class.
2. `verify-ui-visually`: focus highlight is a visual change — verify a
   real rendered window (screenshot / native read), not just "property
   set" + unit test pass. Reference the existing cocoa smoke script that
   produced `view_tabs_split_cocoa_smoke.png`.

## Lessons consulted

- docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md
- docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md
- docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md
- docs/lessons-learned/pyqt-ui/2026-05-31-splitter-setsize-requires-shown-widget.md (cited in brief B)
- docs/lessons-learned/pyqt-ui/2026-04-26-action-button-on-group-title-needs-qframe-header.md (QFrame+QSS focused-property pairing, cited in brief B)
