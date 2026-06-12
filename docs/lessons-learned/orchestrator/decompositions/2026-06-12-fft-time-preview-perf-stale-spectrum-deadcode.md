# Decomposition — FFT time-preview perf + stale-spectrum UX + dead-code removal

**Date:** 2026-06-12
**Mode:** plan
**Top-level request (verbatim, zh):** "性能优化这个需要安排。另外几个是我确认的。死代码移除了。选择变化就清空？不用重新点计算吗？"
**Context:** main Claude reviewed today's two codex commits (908f5bc9 "Improve FFT
source preview UI", 0b2c11d7 "Improve FFT and analysis pyqtgraph views") and
confirmed three changes with the user. Routed via CLAUDE.md "Missed triggers"
(no literal squad keyword, but substantive multi-file `.py` perf + UI behavior change).

## Same-file overlap warning (for main Claude rework prediction)

Task 1 and Task 2 BOTH touch `mf4_analyzer/ui/pg_canvas/line_canvas.py` AND
`mf4_analyzer/ui/main_window.py`. Task 3 touches `main_window.py` only.
=> All three share at least one file. They MUST be serialized (no parallel fan-out),
and each brief MUST enumerate forbidden symbols so post-task disjoint-scope rework
is recognizable. Suggested order: Task 3 (trivial delete) -> Task 1 (perf, owns
the time-preview plot path) -> Task 2 (UX stale-state, owns the spectrum-clear path).
Sequencing Task 1 before Task 2 lets Task 2 build the stale path on top of whatever
downsampling entry-point Task 1 establishes.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| T3 remove dead `t = t[m]` in `_fft_fetch_signal` | signal-processing-expert | — | DSP-helper body edit; `_fft_fetch_signal` returns `sig, fd.fs`, the `t` slice is unused. signal-processing-expert owns the FFT fetch helper. Done first because it's a one-line delete that de-risks later same-file edits. |
| T1 FFT time-preview row downsampling | signal-processing-expert | T3 | Computation/perf: envelope/downsample of potentially millions of points per channel; reuse `pg_canvas/canvas.py` `positions_envelope`/`build_envelope` viewport-clipped to ~pixel_width×2, else PlotDataItem autoDownsample+clipToView+peak. CPU-raster/overlay-superlinear is signal-processing-expert's perf domain. |
| T2 keep-but-stale already-computed spectrum on selection change | pyqt-ui-engineer | T1 | Surface/behavior: a visual stale state (dim/desaturate amplitude curve + "结果已过期，请重新计算" marker) and a new no-clear path; surface over computation => pyqt-ui-engineer. Depends on T1 to build on the final time-preview redraw path. |

## Cross-file boundary contract (must appear in briefs)

- T1 owns: `line_canvas.py::_plot_time_preview_entries` (the `self._plot_time.plot(...)`
  loop) and the downsampling plumbing it needs; the `_refresh_fft_time_preview` redraw
  trigger in `main_window.py` ONLY where it concerns time-preview rendering. T1 must
  NOT alter the spectrum-clear semantics (`clear_spectrum`) — that is T2 territory.
- T2 owns: `line_canvas.py::plot_time_preview` stale path + a new no-clear branch and
  the stale visual state on the upper amplitude curve/title/entries; the
  `main_window.py` selection-change call site that currently passes
  `clear_spectrum=True`. T2 must NOT change the time-preview downsampling logic T1 built.
- T3 owns: `main_window.py::_fft_fetch_signal` ONLY (the `t = t[m]` line). Must not touch
  the return statement contract or anything in the preview/spectrum paths.

## Lessons consulted (step 4)

- docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md
- docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md
- docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md
- docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md
- docs/lessons-learned/signal-processing/2026-05-28-component-speedup-does-not-imply-end-to-end-target.md
- docs/lessons-learned/pyqt-ui/2026-05-28-arraytoqpath-not-byte-identical-to-moveto-lineto-loop.md
- docs/lessons-learned/signal-processing/2026-04-25-envelope-cache-bucket-width-quantization.md

## Skills check

- brainstorming: NOT invoked — request is unambiguous (3 pre-confirmed subtasks).
- writing-plans: NOT invoked — exactly 3 specialist dispatches (threshold is >3).
- prune cadence: 51 − 41 = 10 < 20 — no prune this cycle.
