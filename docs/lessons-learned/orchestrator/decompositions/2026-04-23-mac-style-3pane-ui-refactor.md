# Decomposition — Mac light-theme 3-pane UI refactor

**Date:** 2026-04-23
**Plan:** `docs/superpowers/plans/2026-04-23-mac-style-3pane-ui-refactor.md`
**Spec:** `docs/superpowers/specs/2026-04-23-mac-style-3pane-ui-design.md`
**Mode:** plan (orchestrator runbook Phase 1)

## Context

The user already has a 4-phase / ~30-task plan that has passed two
rounds of codex review. The plan is explicitly partitioned by phase
into refactor-heavy (Phase 1 MainWindow decomposition + shim aliases)
vs UI-heavy (Phase 2 Inspector/FileNavigator/ChartStack content, Phase
3 drawer/sheet/popover, Phase 4 QSS polish) work. Constraint:
`signal/*` and `io/*` are untouched; pure UI refactor; no feature
deletion.

Scope is large (~30 plan tasks), so decomposing each plan task 1:1
into its own specialist dispatch would balloon the message budget and
make rework detection noisy. The useful granularity is **one subtask
per coherent implementation slice** — typically one plan task, but
grouped where the plan itself chains tests-then-commit within a single
author's domain. Each dispatched subtask still points the specialist
at the exact plan section so they follow the plan's step-by-step
code.

## Boundary between refactor-architect and pyqt-ui-engineer

Applying the roster rule "**surface-vs-computation → prefer
pyqt-ui-engineer for widgets/layouts**" and the rework lesson
`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`:

- **refactor-architect owns:** Phase-1 MainWindow atomic rewrite
  (Task 1.5 — `_init_ui` / `_connect` / shim-alias layer / `_load_one`
  / `_close` rewiring — this is cross-module signal-wiring surgery
  affecting dozens of references in `plot_time / do_fft / do_order_*`
  and is explicitly flagged in the plan as "intentionally atomic").
  Also Task 1.7 (delete dead `_left / _right`), Task 2.2 (delete
  `file_tabs` flow from MainWindow — still cross-module plumbing), and
  **Task 2.7** (rewire every analysis method's form-value read through
  the Inspector API — the plan itself calls this out as cross-module,
  and the user's brief explicitly nominated refactor-architect for
  this one).
- **pyqt-ui-engineer owns:** every widget/section/drawer/QSS task. All
  the Phase 1 skeleton widget files (Tasks 1.1-1.4), all Phase 2
  Inspector section content (Tasks 2.3-2.6), ChartStack cursor pill
  and stats strip (Tasks 2.9-2.10), navigator enhancements (Tasks
  2.1/2.11/2.12), all drawer/sheet/popover migration (Phase 3 Tasks
  3.1-3.4), plus Phase 3 Task 3.5 (`_reset_cursors /
  _reset_plot_state` rewrite — this is widget-topology catch-up
  living inside MainWindow but all reads go to the new UI widgets, so
  it is a UI consumer rewrite rather than architecture work), and
  Phase 4 QSS polish (Tasks 4.1-4.3).

## Rework-risk mitigation (applying lesson 2026-04-22)

The known rework pattern is "refactor-architect creates file body →
pyqt-ui-engineer edits same file's UI semantics right after." The
places that pattern appears in this plan:

1. **Task 1.5 (refactor) → Tasks 2.3-2.6 (ui) touching
   `inspector_sections.py`.** Not true rework: Task 1.5 doesn't write
   `inspector_sections.py` — the skeleton (Task 1.4) is pyqt-ui's
   already. The skeletons are written by pyqt-ui-engineer in Tasks
   1.1-1.4 exactly so Task 1.5's wiring can reference them. No
   cross-specialist file overlap here.
2. **Task 2.2 (refactor, deletes `file_tabs` from `main_window.py`) →
   Task 2.7 (refactor, rewires analysis methods in `main_window.py`).**
   Same specialist on both, so not rework.
3. **Task 2.9 / 2.10 (ui, edits `main_window.py`) → Task 3.5 (ui,
   rewrites `_reset_cursors` / `_reset_plot_state` in
   `main_window.py`).** Same specialist (pyqt-ui-engineer) on both, so
   not cross-specialist rework.
4. **Task 2.7 (refactor on `main_window.py`) → Task 3.5 (ui on
   `main_window.py`).** This IS cross-specialist on a shared file.
   Mitigation: Task 2.7's brief must leave the `_reset_cursors` /
   `_reset_plot_state` bodies untouched (plan explicitly defers them
   to Task 3.5), and Task 3.5's brief must cite Task 2.7's return for
   the final set of Inspector widget-method names. That removes the
   ambiguity that causes rework edits. This is captured in the
   decomposition as `ui-reset-methods-rewrite` with `depends_on:
   [main-window-analysis-rewire]`.

## Parallelism

Within a phase, parallelism is bounded by the fact that Phase 1
atomic rewrite (`main-window-atomic-rewire`) imports the four skeleton
modules, so those four skeletons are the only things that can run
fully parallel at the start. After Phase 1 is green, Phase 2 widget
content tasks parallelize (they touch distinct section classes or
distinct files). Phase 3 drawer/sheet/popover tasks are all
parallelisable once Phase 2 Inspector/ChartStack API is locked in.
Phase 4 QSS/polish is sequential-last.

## Decomposition table

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| 1 | `test-infra-bootstrap` (plan Task 0.1: requirements.txt + `tests/ui/conftest.py`) | pyqt-ui-engineer | — | Pure Qt test infra (`QApplication` fixture, `QT_QPA_PLATFORM=offscreen`, pytest-qt); owned by UI specialist. |
| 2 | `skeleton-toolbar` (plan Task 1.1) | pyqt-ui-engineer | test-infra-bootstrap | PyQt widget with signals/slots + enabled matrix — surface keyword match. |
| 3 | `skeleton-file-navigator` (plan Task 1.2) | pyqt-ui-engineer | test-infra-bootstrap | QWidget wrapping existing `MultiFileChannelWidget` — widget scaffolding. |
| 4 | `skeleton-chart-stack` (plan Task 1.3) | pyqt-ui-engineer | test-infra-bootstrap | `QStackedWidget` + NavigationToolbar mount — widget scaffolding. |
| 5 | `skeleton-inspector` (plan Task 1.4) | pyqt-ui-engineer | test-infra-bootstrap | Right pane widget framework + section stubs — widget scaffolding. |
| 6 | `main-window-atomic-rewire` (plan Task 1.5 — atomic 3-pane `_init_ui` + `_connect` + legacy shim aliases + `_load_one` / `_close` migration) | refactor-architect | skeleton-toolbar, skeleton-file-navigator, skeleton-chart-stack, skeleton-inspector | Cross-module: rips out `_left / _right`, replaces with `QSplitter`, wires dozens of signal connections, sets up `_legacy_hidden` shim widgets so `plot_time / do_fft / do_order_*` still compile. Plan explicitly flags this as atomic and high-risk. |
| 7 | `main-window-integration-tests-and-shim-exit-plan` (plan Tasks 1.6 + 1.7) | refactor-architect | main-window-atomic-rewire | Integration tests over the rewired MainWindow + delete dead `_left / _right` + document shim-exit plan — still architecture-of-MainWindow work. |
| 8 | `file-navigator-rows-and-kebab` (plan Task 2.1) | pyqt-ui-engineer | main-window-atomic-rewire | `_FileRow` QFrame + scroll area + kebab QMenu + active-state styling. Pure UI. |
| 9 | `main-window-delete-file-tabs` (plan Task 2.2) | refactor-architect | file-navigator-rows-and-kebab | Rips `_add_tab / _tab_changed / _tab_close / _get_tab_fid` and rewires `_load_one / _close / close_all` to navigator API. Architecture plumbing. |
| 10 | `inspector-persistent-top` (plan Task 2.3) | pyqt-ui-engineer | skeleton-inspector | Xaxis / Range / Tick-density groupbox content + getters. Widget content. |
| 11 | `inspector-time-contextual` (plan Task 2.4) | pyqt-ui-engineer | skeleton-inspector | Plot-mode + cursor segmented buttons + plot button. Widget content. |
| 12 | `inspector-fft-contextual` (plan Task 2.5) | pyqt-ui-engineer | skeleton-inspector | Signal/Fs/params/options + FFT button. Widget content. |
| 13 | `inspector-order-contextual` (plan Task 2.6) | pyqt-ui-engineer | skeleton-inspector | Order analysis form + 3 buttons + track section. Widget content. |
| 14 | `main-window-analysis-rewire` (plan Task 2.7 + Task 2.8 verification) | refactor-architect | inspector-persistent-top, inspector-time-contextual, inspector-fft-contextual, inspector-order-contextual, main-window-delete-file-tabs | Cross-module read-path rewrite: every `plot_time / do_fft / do_order_*` method stops reading shim widgets and reads the Inspector's typed API. Explicitly nominated for refactor-architect in the user's brief. Includes Task 2.8's custom-X mid-plot validation test. |
| 15 | `chart-stack-cursor-pill` (plan Task 2.9) | pyqt-ui-engineer | main-window-analysis-rewire | Move cursor pill ownership from MainWindow to ChartStack; connect canvas `cursor_info / dual_cursor_info` signals; remove old `lbl_cursor / lbl_dual` from MainWindow. |
| 16 | `chart-stack-stats-strip` (plan Task 2.10) | pyqt-ui-engineer | chart-stack-cursor-pill | Add `StatsStrip` widget to `widgets.py`; mount on ChartStack; replace every `self.stats.update_stats(...)` in MainWindow with `self.chart_stack.stats_strip.update_stats(...)`. |
| 17 | `navigator-activation-wiring` (plan Task 2.11) | pyqt-ui-engineer | main-window-analysis-rewire | `_on_file_activated` updates Inspector Fs + range limits; deduplicate close-all confirm. Small slot rewrite on MainWindow. |
| 18 | `navigator-channel-search-tests` (plan Task 2.12) | pyqt-ui-engineer | file-navigator-rows-and-kebab | Behavioral tests for search / All / None / Inv / >8 warning. Pure UI tests. |
| 19 | `drawer-channel-editor` (plan Task 3.1) | pyqt-ui-engineer | chart-stack-stats-strip, navigator-activation-wiring | Right-anchored drawer wrapping existing `ChannelEditorDialog`. UI container form only. |
| 20 | `drawer-export-sheet` (plan Task 3.2) | pyqt-ui-engineer | chart-stack-stats-strip | Top-anchored sheet wrapping existing `ExportDialog`. UI container form only. |
| 21 | `drawer-rebuild-time-popover` (plan Task 3.3) | pyqt-ui-engineer | chart-stack-stats-strip | Frameless QDialog popover with `WindowDeactivate` auto-close. Pure UI. |
| 22 | `drawer-axis-lock-popover` (plan Task 3.4) | pyqt-ui-engineer | chart-stack-stats-strip | Frameless popover replaces `axis_lock_toolbar.py` which is deleted. Pure UI. |
| 23 | `ui-reset-methods-rewrite` (plan Task 3.5) | pyqt-ui-engineer | main-window-analysis-rewire, chart-stack-cursor-pill, chart-stack-stats-strip, drawer-rebuild-time-popover, drawer-axis-lock-popover, inspector-persistent-top, inspector-time-contextual, inspector-fft-contextual, inspector-order-contextual | Rewrite `_reset_cursors / _reset_plot_state` against the final widget topology; delete `_legacy_hidden`. All reads/writes are against the new UI widgets, so this is a UI-consumer rewrite — pyqt-ui-engineer. Must run AFTER `main-window-analysis-rewire` to avoid re-editing those same methods. |
| 24 | `qss-light-theme` (plan Task 4.1) | pyqt-ui-engineer | ui-reset-methods-rewrite | Full rewrite of `style.qss` + remove deprecated inline stylesheets. QSS is the pyqt-ui-engineer's explicit domain. |
| 25 | `toolbar-segmented-control` (plan Task 4.2) | pyqt-ui-engineer | qss-light-theme | Make mode buttons a `QButtonGroup` with segment QSS. Widget polish. |
| 26 | `final-parity-verify` (plan Task 4.3) | pyqt-ui-engineer | toolbar-segmented-control | Run full pytest + §15 manual parity matrix. UI verification. |

Total subtasks: **26** (vs ~30 plan tasks — collapses Tasks 1.6+1.7,
2.7+2.8 which the plan itself chains tightly within one author).

## Cross-specialist file-overlap forecast

Following the Phase 3 rework-scan protocol, here are the expected
overlaps main Claude should watch for:

| Earlier | Later | File(s) | Same expert? |
|---|---|---|---|
| `main-window-atomic-rewire` (refactor) | `main-window-delete-file-tabs` (refactor) | `main_window.py` | yes → no rework |
| `main-window-delete-file-tabs` (refactor) | `main-window-analysis-rewire` (refactor) | `main_window.py` | yes → no rework |
| `main-window-analysis-rewire` (refactor) | `chart-stack-cursor-pill` (ui) | `main_window.py` | **no → watch this one** — but scopes are disjoint (analysis-rewire edits plot/fft/order; cursor-pill only removes `lbl_cursor / lbl_dual` mount). If spec boundaries hold, this is a coordinated handoff, not rework. |
| `main-window-analysis-rewire` (refactor) | `chart-stack-stats-strip` (ui) | `main_window.py` | **no → watch this one** — scope disjoint (stats_strip only replaces `self.stats.update_stats(...)` call sites that analysis-rewire does NOT touch). Coordinated handoff. |
| `main-window-analysis-rewire` (refactor) | `navigator-activation-wiring` (ui) | `main_window.py` | **no → watch this one** — scope disjoint (`_on_file_activated` only). |
| `main-window-analysis-rewire` (refactor) | `ui-reset-methods-rewrite` (ui) | `main_window.py` | **no → HIGHEST rework risk** — same-file, different specialists, edits to adjacent methods. The plan explicitly defers `_reset_cursors / _reset_plot_state` to Task 3.5 precisely to separate concerns. If rework-detection later fires on this pair, the lesson should capture "method-level boundary is fine; rework occurred because analysis-rewire accidentally touched reset helpers — tighten the brief." |

If any of the last four actually overlap on shared line ranges, main
Claude writes a `cause: rework` lesson per the runbook Phase 3.

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
  — confirms orchestrator only plans; main Claude dispatches.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
  — informs the cross-specialist file-overlap forecast above; also
  drove the decision to fold Task 2.8 into Task 2.7 (avoid a trivial
  refactor→ui split on `main_window.py`) and to keep Task 3.5 on the
  pyqt-ui-engineer side rather than bouncing it back to
  refactor-architect just because it lives in `main_window.py`.
- `docs/lessons-learned/refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md`
  — not directly applicable (no new cross-layer constants introduced
  by this refactor).

## Notes for main Claude

- Plan is 30+ tasks with test-first structure per task. Each subtask
  brief below pins the specialist to the exact plan task numbers so
  they follow the already-reviewed step-by-step code.
- The user's brief explicitly nominated `refactor-architect` for Phase
  1 and Task 2.7, and `pyqt-ui-engineer` for Phases 2/3/4. This
  decomposition honors that nomination.
- Because the plan is already reviewed (two rounds of codex), the
  specialist briefs tell them to **implement verbatim** rather than
  redesign. Any structural deviation they spot should be flagged, not
  silently applied.
- `superpowers:writing-plans` is NOT re-invoked here because the user
  already has a reviewed plan; the orchestrator's job is only to route
  it.
- Watch the rework-forecast table above during Phase 3 aggregation.
