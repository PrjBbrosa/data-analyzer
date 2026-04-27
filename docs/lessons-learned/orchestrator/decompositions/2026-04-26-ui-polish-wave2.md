# Decomposition audit — UI polish Wave 2 (Tasks 2.1–2.14)

**Date:** 2026-04-26
**Mode:** plan
**Source plan:** `docs/superpowers/plans/2026-04-26-ui-polish-and-order-rpm-removal.md` (lines 510–1909)
**Wave-1 gate report:** `docs/superpowers/reports/2026-04-26-ui-polish-wave1-review.md` (passed)

## Specialist roster

All 13 implementation tasks (2.1–2.13) route to `pyqt-ui-engineer` per
spec §7 file ownership table. Task 2.14 is a Wave-end codex gate
(no specialist dispatch — handled by main Claude per project memory
`feedback_squad_wave_review.md` / `feedback_module_review.md`).

## File-overlap matrix (the dispatch constraint)

| File | Tasks that modify | Notes |
|---|---|---|
| `mf4_analyzer/ui/_axis_interaction.py` | 2.1 (create) | Only 2.1. |
| `mf4_analyzer/ui/_toolbar_i18n.py` | 2.5 (create) | Only 2.5. |
| `mf4_analyzer/ui/canvases.py` | 2.2, 2.3, 2.4, 2.9, 2.10 | 5-way same-file chain — MUST serialize. |
| `mf4_analyzer/ui/chart_stack.py` | 2.6, 2.7, 2.12 | 3-way same-file chain — MUST serialize. |
| `mf4_analyzer/ui/style.qss` | 2.8 | Disjoint. |
| `mf4_analyzer/ui/main_window.py` | 2.11 | Disjoint. Wave-1 also touched this file but on different lines. |
| `mf4_analyzer/ui/inspector_sections.py` | 2.13 | Disjoint. Wave-1 also touched this file but on different lines. |
| `tests/ui/test_axis_interaction.py` | 2.1, 2.2, 2.3, 2.4 | Owned by canvases.py chain — serialized via 2.2→2.3→2.4. |
| `tests/ui/test_toolbar_i18n.py` | 2.5 | Disjoint. |
| `tests/ui/test_chart_stack.py` | 2.7 | Plus existing test file (no creation). |
| `tests/ui/test_chart_stack_stats_visibility.py` | 2.12 (create) | Disjoint. |
| `tests/ui/test_canvas_compactness.py` | 2.9 (create), 2.10 | Owned by canvases.py chain. |
| `tests/ui/test_inspector.py` | 2.13 | Disjoint. |

## Dependency graph (used to derive sub-batches)

- 2.1 → 2.2 → 2.3 → 2.4 → 2.9 → 2.10 (canvases.py serial chain; 2.2-2.4 import from _axis_interaction; 2.9 retroactively replaces literal 45 written by 2.2/2.3/2.4 with AXIS_HIT_MARGIN_PX, so MUST run after them)
- 2.5 → 2.6 → 2.7 (chart_stack.py serial chain; 2.6 wires `_toolbar_i18n`; 2.7 edits the same file)
- 2.12 also touches chart_stack.py (set_mode + __init__ tail) but on disjoint methods from 2.6/2.7. To be safe under the
  parallel-same-file-collision rule (orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md),
  serialize 2.12 AFTER 2.7.
- 2.11 imports `CHART_TIGHT_LAYOUT_KW` introduced in 2.9 → 2.11 depends on 2.9.
- 2.8 depends on 2.6 conceptually (style targets toolbar produced by i18n) but the QSS edit does not collide on any
  source file — independent dispatch is safe; we still gate 2.8 after 2.6 so visual smoke runs against the i18n state.
- 2.13 has no source-file dependency on any other Wave-2 task.

## Sub-batches main Claude can derive from `depends_on`

- W2.B1 (parallel): 2.1, 2.5 (two new helper modules, disjoint files)
- W2.B2 (parallel chains, no shared files):
  - canvases chain: 2.2 → 2.3 → 2.4
  - chart_stack chain: 2.6 → 2.7
- W2.B3: 2.9 (after 2.4 lands; canvases.py free of in-flight edits)
- W2.B4 (parallel): 2.10 (canvases.py spectrogram), 2.11 (main_window.py), 2.12 (chart_stack.py), 2.13
  (inspector_sections.py), 2.8 (style.qss). All five files are now disjoint — 2.10 owns canvases.py alone,
  2.12 owns chart_stack.py alone since 2.6/2.7 already landed.
- W2.B5: 2.14 codex gate (NOT a specialist dispatch; main-Claude direct)

## Forbidden-symbol discipline

Lessons applied:
- `silent-boundary-leak-bypasses-rework-detection` — every brief includes a `symbols_touched` return contract and an
  explicit forbidden-symbols list; main Claude must grep forbidden symbols against each diff before accepting the return.
- `refactor-then-ui-same-file-boundary-disjoint` — although Wave 2 is single-expert, same-file briefs still enumerate
  forbidden methods (e.g., 2.2 must not touch PlotCanvas; 2.3 must not touch TimeDomainCanvas; 2.6 must not touch
  segmented buttons; 2.7 must not touch toolbar-i18n hookup; 2.12 must not touch toolbar code or segmented buttons).

## Lessons consulted (Step 4)

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — same-file parallel
  forbidden; serialize within each file's chain.
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` — disjoint method
  scope inside a shared file is safe IFF briefs enumerate forbidden methods.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — require
  `symbols_touched` and grep-based forbidden-symbol verification in every same-file brief.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — confirms
  the importance of bundling mechanical follow-ups; here we DELIBERATELY split 2.9 from 2.2/2.3/2.4 because 2.9
  introduces module-level constants that need a fresh review surface separate from per-canvas wiring.
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md` — Wave-2 gate (Task 2.14) must
  use `--prompt-file` + `--write` for the codex run.
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md` — relevant to 2.2/2.3/2.4
  dblclick + hover wiring; cite in briefs so specialists store cids and disconnect on rebuild.
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` —
  relevant to 2.12 (StatsStrip visibility must be seeded once at __init__ end and toggled in set_mode).

## Subtask table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| w2-1-axis-interaction-helper | pyqt-ui-engineer | — | New UI helper module + Qt-aware tests; pure Qt domain. |
| w2-5-toolbar-i18n-helper | pyqt-ui-engineer | — | New UI helper module + tests; QAction.setData / matplotlib NavigationToolbar domain. |
| w2-2-timedomain-dblclick-hover | pyqt-ui-engineer | w2-1 | Wires TimeDomainCanvas to _axis_interaction. |
| w2-3-plotcanvas-dblclick-hover | pyqt-ui-engineer | w2-2 | Same-file serial after 2.2; refactors PlotCanvas dblclick. |
| w2-4-spectrogram-dblclick-hover | pyqt-ui-engineer | w2-3 | Same-file serial after 2.3. |
| w2-6-chart-stack-toolbar-wire | pyqt-ui-engineer | w2-5 | chart_stack.py i18n + _find_action upgrade. |
| w2-7-segmented-i18n-tool-hints | pyqt-ui-engineer | w2-6 | Same-file (chart_stack.py) serial after 2.6. |
| w2-9-canvas-compact-constants | pyqt-ui-engineer | w2-4 | Adds CHART_TIGHT_LAYOUT_KW + AXIS_HIT_MARGIN_PX, retro-replaces 45 literals from 2.2/2.3/2.4. |
| w2-10-spectrogram-figsize | pyqt-ui-engineer | w2-9 | Same-file (canvases.py) serial after 2.9; uses SPECTROGRAM_SUBPLOT_ADJUST. |
| w2-11-main-window-tight-layout | pyqt-ui-engineer | w2-9 | Imports CHART_TIGHT_LAYOUT_KW; disjoint file from 2.10. |
| w2-12-stats-visibility-time-only | pyqt-ui-engineer | w2-7 | Same-file (chart_stack.py) serial after 2.7. |
| w2-13-preset-default-names | pyqt-ui-engineer | — | inspector_sections.py disjoint. |
| w2-8-toolbar-qss-compact | pyqt-ui-engineer | w2-7 | style.qss disjoint, but gated after 2.7 so visual smoke is meaningful. |

## Notes

- Total dispatched specialists: 13 (all pyqt-ui-engineer). Task 2.14 is the Wave-2 codex gate handled directly by
  main Claude.
- This decomposition has >3 dispatches → `superpowers:writing-plans` was honored at planning level by leaning on the
  existing source plan rather than creating a new one. No additional plan artifact required.
- No `superpowers:brainstorming` invocation needed — request is unambiguous and specifies file boundaries via spec §7.
