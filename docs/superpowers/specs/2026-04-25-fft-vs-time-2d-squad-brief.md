# FFT vs Time 2D — Squad Dispatch Brief

**Date:** 2026-04-25
**Status:** ready to dispatch — design approved, plan v2 review-clean

This file is the input to the Phase 1 `squad-orchestrator` call for the
FFT vs Time module. Plan v2 fixed the issues from the first review;
the orchestrator should read this brief, then read the design and
plan, then return a `decomposition[]`.

## How to dispatch

Main Claude (the executor) runs:

```text
Task(
  subagent_type=squad-orchestrator,
  prompt=<the entire "Orchestrator prompt" block below, verbatim>
)
```

After the orchestrator returns a JSON plan, main Claude dispatches the
specialists per `decomposition[]`, respecting `depends_on`, then
aggregates per the Phase 3 rules in `CLAUDE.md`.

---

## Orchestrator prompt

```
mode: plan

user request:
你先 review 下 docs 内新增的几个 spec 和 plan，我要做一个 fft vs time 的模块。
你看 plan 内的内容和操作是否合理，逻辑是否严谨，还有哪里需要优化？
（review 已完成；plan 已修订到 v2。本次任务是按修订后的 plan 实施 FFT vs Time 模块。）

reference documents the orchestrator MUST read before producing the
decomposition:

- docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md (revised)
- docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md (v2)
- docs/superpowers/specs/2026-04-25-fft-vs-time-2d-brainstorm.md (background only)

specialists available in this repo:

- signal-processing-expert  — owns mf4_analyzer/signal/* and tests
                              under tests/test_*.py that exercise
                              numeric correctness (TDD-first).
- pyqt-ui-engineer          — owns mf4_analyzer/ui/* widgets, dialogs,
                              canvases, signal/slot wiring, Chinese
                              fonts, and tests under tests/ui/.
- refactor-architect        — owns module boundaries, canvas-promotion
                              from ChartStack onto MainWindow,
                              cache-invalidation hook placement, and
                              cross-module relocations (no internal
                              algorithm work).

required decomposition (the orchestrator should align with this
shape — adjust only if a lesson contradicts):

  T1  signal-processing-expert  — Task 1 (scipy + shared FFT helpers
                                  + DC/Nyquist audit) and Task 2
                                  (SpectrogramAnalyzer with TDD).
                                  No GUI imports. Must run
                                  tests/test_fft_amplitude_normalization.py
                                  and tests/test_signal_no_gui_import.py
                                  green before returning.

  T2  refactor-architect       — Task 3 (mode plumbing across
                                  toolbar / chart_stack / inspector /
                                  canvases skeleton / main_window
                                  canvas promotion). Verifies that
                                  MainWindow.canvas_fft_time resolves
                                  to chart_stack.canvas_fft_time.
                                  depends_on: T1 (needs the signal
                                  module to exist for imports).

  T3  pyqt-ui-engineer         — Task 4 (FFTTimeContextual real
                                  controls + presets + disabled-button
                                  + selection-preservation tests).
                                  depends_on: T2.

  T4  pyqt-ui-engineer         — Task 5 (SpectrogramCanvas rendering,
                                  vmin/vmax wiring, freq_range ylim,
                                  click selection, hover readout with
                                  cursor_info signal, lazy dB cache).
                                  depends_on: T2.

  T5  pyqt-ui-engineer         — Task 6 (synchronous do_fft_time +
                                  cache + cache-hit status +
                                  failed-keep-old-chart test).
                                  depends_on: T3, T4.

  T6  pyqt-ui-engineer         — Task 7 (worker thread + finished and
                                  cancel pytest-qt smokes).
                                  depends_on: T5.

  T7  refactor-architect       — Task 8 (cache-invalidation hooks at
                                  the five sites listed in the plan,
                                  plus targeted-clear helper).
                                  depends_on: T5.

  T8  pyqt-ui-engineer         — Task 9 (export pixmap helpers +
                                  clipboard copy + has_result guard).
                                  depends_on: T4.

  T9  signal-processing-expert — Task 10 Steps 1-3 (run pytest:
                                  algorithm, UI, full suite — collect
                                  outputs for the validation report).
                                  depends_on: T6, T7, T8.

  T10 pyqt-ui-engineer         — Task 10 Steps 4-6 (manual UI smoke
                                  + write the validation report with
                                  real observations + commit).
                                  depends_on: T9.

lessons to surface (orchestrator: pull these into applicable_lessons[]
if they exist in docs/lessons-learned/, otherwise ignore):

- orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch
  — reminds main Claude that subagents do not get Task; the
    orchestrator only plans, main Claude dispatches.
- any prior lesson about "MainWindow attribute promotion from
  ChartStack" or "canvas plumbing across UI tiers" — directly
  applicable to T2.
- any prior lesson about "scipy.signal.get_window symmetric vs
  fftbins flag" — applicable to T1.
- any prior lesson about "PyQt worker QThread move + cancel
  pattern in this app" — applicable to T6.

constraints:

- No specialist may edit files outside its remit. signal-processing-
  expert never touches mf4_analyzer/ui/*. pyqt-ui-engineer never
  edits mf4_analyzer/signal/*. refactor-architect does not redesign
  algorithm internals.
- Each specialist returns the role-specific fields in CLAUDE.md
  (ui_verified, tests_run, tests_before, tests_after, files_moved,
  files_changed). Main Claude must not drop them during aggregation.
- TDD on every numeric or algorithmic change — failing test, then
  implementation. signal-processing-expert is bound to this.
- The plan ships in 10 commits (one per Task). Plan v2 commit
  messages are inside the plan file.

return shape:

  status: "ready"
  decomposition: [...]
  applicable_lessons: [...]
  notes: free text (e.g. "main Claude must invoke
        superpowers:executing-plans before dispatching" if relevant)
```

---

## Notes for main Claude (executor)

After the orchestrator returns:

1. **If `status: blocked`** — surface the orchestrator's reason to the
   user verbatim. Do not dispatch.
2. **If `status: ready`** — for each `decomposition[]` item:
   - Concatenate `item.brief` with any upstream specialist outputs the
     item depends on (especially T2 and T5, which downstream UI tasks
     need to read).
   - Cite the relevant lessons from `applicable_lessons[]` in the
     specialist prompt.
   - Dispatch parallel where `depends_on` is empty for the same wave;
     sequential where `depends_on` is non-empty.
3. **Aggregation** — collect each specialist's full return JSON. Run
   the rework-detect rule across `(S_i, S_j)` file overlaps and write
   a `cause: rework` lesson if any pair of different experts touched
   the same file.
4. **State counter** — increment `top_level_completions` in
   `docs/lessons-learned/.state.yml` only if `top_level_status` is
   `done` or `partial` (not `blocked`).
5. **Prune** — if `top_level_completions - last_prune_at >= 20`, run
   `Task(subagent_type=squad-orchestrator, prompt="mode: prune")` and
   attach the report path.

## Out of scope for this dispatch

- 3D waterfall, multi-channel subplot, streaming, HDF input, PSD UI,
  display-layer downsampling, UI cancel button. All explicitly out
  per design §2.2 and §9.
- Documentation rewrites beyond the validation report.
- Anything in `mf4_analyzer/order/` or `OrderAnalyzer` beyond the
  `__init__.py` line that re-exports it.
