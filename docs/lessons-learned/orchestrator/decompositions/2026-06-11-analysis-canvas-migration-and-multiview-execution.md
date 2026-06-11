# Decomposition — Execute analysis canvas migration (P1–P3) + analysis multiview (P4)

**Date:** 2026-06-11
**Branch:** `feature/analysis-multiview-pyqtgraph` (pre-created)
**Plans executed:**
- `docs/superpowers/plans/2026-06-10-analysis-canvas-migration.md` (11 tasks, M1–M11)
- `docs/superpowers/plans/2026-06-10-analysis-multiview.md` (11 tasks, V1–V11; gated on M11)

**Spec:** `docs/superpowers/specs/2026-06-10-analysis-multiview-pyqtgraph-design.md`

Plans contain full TDD steps, code, and commit points — specialists follow the
plan task verbatim but MUST re-locate line-number anchors by grep (plans dated
2026-06-10; working tree has drifted, `inspector_sections.py` is dirty).

## Subtask table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| M1-analysis-worker | pyqt-ui-engineer | — | QThread/pyqtSignal lifecycle plumbing; qthread lessons live in pyqt-ui corpus |
| M2-heatmap-skeleton | pyqt-ui-engineer | — | pyqtgraph canvas (surface rule: canvas → pyqt-ui even with levels math) |
| M3-heatmap-remarks | pyqt-ui-engineer | M2 | same file `heatmap_canvas.py` → serial |
| M4-heatmap-export | pyqt-ui-engineer | M3 | same file; grab_pixmap export needs offscreen/hidpi grab lesson |
| M5-order-rewire | pyqt-ui-engineer | M1, M4 | chart_stack/main_window wiring; consumes worker + heatmap canvas |
| M6-order-visual-gate | pyqt-ui-engineer | M5 | visual acceptance + canvases.py heatmap-cluster deletion; gates P2 |
| M7-heatmap-slice-row | pyqt-ui-engineer | M6 | same file as M2–M4; gated behind P1 visual acceptance |
| M8-heatmap-export-modes | pyqt-ui-engineer | M7 | same file `heatmap_canvas.py` → serial |
| M9-ffttime-rewire-del-spectrogram | pyqt-ui-engineer | M8 | chart_stack/main_window/canvases.py — serial after M5 (chain) and M6 (canvases.py) |
| M10-line-canvas | pyqt-ui-engineer | M2 | new file `line_canvas.py` — PARALLEL LANE alongside M3–M9 (disjoint files) |
| M11-fft-rewire | pyqt-ui-engineer | M9, M10 | chart_stack/main_window serial tail; needs PgLineCanvas |
| V1-view-state-model | signal-processing-expert | M11 | widget-free serializable dataclass model; persistence schema pairs with V3 (body-vs-shape lesson) |
| V2-viewmanager-factory | pyqt-ui-engineer | V1 | QObject/pyqtSignal class generalization in `view_state.py`; test imports AnalysisViewState |
| V3-project-io-persistence | signal-processing-expert | V1 | JSON persistence/remap in `project_io.py` → persistence routes to signal-processing |
| V4-analysis-cache | signal-processing-expert | M11 | cache keying/eviction logic, no Qt; PARALLEL with V1 |
| V5-section-bridge | pyqt-ui-engineer | V1 | capture/apply against inspector widgets; may touch `inspector_sections.py` |
| V6-section-page | pyqt-ui-engineer | V1, V2 | pane container + ViewTabBar widget; splitter/offscreen test lesson applies |
| V7-chartstack-mainwindow-routing | pyqt-ui-engineer | V4, V5, V6 | big wiring, chart_stack + main_window |
| V8-levels-locked | pyqt-ui-engineer | V7 | same files as V7 (`analysis_section_page.py`, `main_window.py`) → serial |
| V9-fft-delta-readout | pyqt-ui-engineer | M11 | only touches `line_canvas.py` — PARALLEL LANE alongside V1–V8 |
| V10-project-save-load-wiring | pyqt-ui-engineer | V3, V8 | main_window serial tail after V8; consumes V3 schema + V4 cache invalidation |
| V11-release-gate | pyqt-ui-engineer | V9, V10 | split export + P4 visual acceptance + time-domain smoke (release gate) |

## Same-file serialization map

- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`: M2 → M3 → M4 → M7 → M8 (strict serial)
- `mf4_analyzer/ui/chart_stack.py` + `mf4_analyzer/ui/main_window.py`: M5 → M9 → M11 → V7 → V8 → V10 (strict serial)
- `mf4_analyzer/ui/canvases.py`: M6 (PlotCanvas heatmap cluster) → M9 (SpectrogramCanvas) via chain
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`: M10 → V9 (plan-2 gate keeps them apart anyway)
- `mf4_analyzer/ui/analysis_section_page.py`: V6 → V8 via V7
- No task edits `pg_canvas/__init__.py` — no init-file race between M2 and M10

## Parallel waves (for main Claude)

1. M1 ∥ M2
2. M3, M10 (parallel lane after M2)
3. M4 → M5 → M6 → M7 → M8 → M9 (serial; M10 may still be running in parallel)
4. M11 (joins M9 + M10) — END OF PLAN 1 GATE
5. V1 ∥ V4 ∥ V9
6. V2 ∥ V3 ∥ V5 (all after V1)
7. V6 (after V2)
8. V7 → V8 → V10 (serial)
9. V11 (joins V9 + V10) — release gate

## Lessons consulted (step-4 reads)

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`

## Notes

- `refactor-architect` deliberately NOT used: the only deletions (SpectrogramCanvas,
  PlotCanvas heatmap cluster) are inseparable from the same-file rewiring edits;
  splitting them would manufacture cross-specialist same-file rework
  (move-then-tighten lesson → fold into the wiring owner's brief).
- Dirty working tree (`inspector_sections.py` modified, `toolbar_mockup.html`
  untracked) must be resolved by main Claude BEFORE the first dispatch.
- All briefs mandate path-scoped `git add <file>...` (never `-A`) and
  `symbols_touched` reporting (silent-boundary-leak lesson).
- Memory caveat for M4/M8/V11: OpenGL viewport breaks `grab`-based export
  (all-white pixmaps observed 2026-06); export paths must verify saved PNG pixels.
