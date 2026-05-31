# Decomposition — TimeDomain 右键菜单重设计 + 复制/导出高清化

**Date:** 2026-05-30
**Branch:** plan/pyqtgraph-timedomain-migration
**Mode:** plan
**Authoritative spec:** `docs/superpowers/specs/2026-05-30-timedomain-context-menu-redesign-design.md`
**Prototype:** `docs/analyzer/ui-prototypes/2026-05-29-timedomain-context-menu-options.html` (方案 A)
**Routing note:** did NOT match a squad trigger keyword; main Claude routed it
deliberately (multi-part `.py` UI change). Recorded as a roster-gap below.

## Task shape

Pure PyQt/pyqtgraph surface + Qt-rendering work. No numerical/DSP path is
touched (FFT/变换/降采样 are being REMOVED from the menu, not implemented).
Therefore `signal-processing-expert` is NOT dispatched. All subtasks →
`pyqt-ui-engineer`.

## Shared-file analysis (drives serialization)

| File | S1 menu redesign | S2 hi-DPI export |
|---|---|---|
| `mf4_analyzer/ui/pg_canvases.py` | yes (menu trim/reorder, tooltip off, QSS hook) | yes (`grab_pixmap` scale) |
| `mf4_analyzer/ui/chart_stack.py` | yes (mouse-mode 联动 to toolbar) | yes (`save_figure`, copy path, 药丸 scale) |
| `mf4_analyzer/ui_kit/style.qss` | yes (`#pgContextMenu` 方案 A) | no |
| `tests/ui/test_pg_timedomain_canvas.py` | yes | yes |
| `tests/ui/test_chart_stack.py` | yes | yes |

Both subtasks are `pyqt-ui-engineer` and overlap on `pg_canvases.py`,
`chart_stack.py`, and BOTH test files. Per
`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`,
same-expert same-file tasks MUST be serialized (a 1-line overlap is enough to
race `git add`). S2 `depends_on` S1.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1 menu-redesign-and-mouse-mode-sync | pyqt-ui-engineer | — | Native QMenu trim/reorder, tooltip-off bug fix, 方案 A QSS, and mouse-mode↔toolbar single-source-of-truth all live in `pg_canvases.py` + `chart_stack.py` + `style.qss`. One coherent surface edit; bundling the QSS hook with the menu code avoids a move-then-tighten split. |
| S2 hi-dpi-copy-and-save-export | pyqt-ui-engineer | S1 | High-scale `grab_pixmap`/exporter render with capped ~2x / ~1920–2560px width, cursor-pill composite scaled, offscreen `isNull()`/1×1 fallback preserved. Touches the same two `.py` files + both test files as S1, so MUST run after S1, not in parallel. |

## Why not split S1 finer

The menu trim, tooltip-off, QSS theming, and mouse-mode sync are all one
specialist's coherent edit to the same two source files. Splitting "trim menu
actions" from "apply 方案 A QSS" would re-trip the move-then-tighten rework
pattern (`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`)
inside a single expert and single file set, for no domain-expertise gain.

## Lessons consulted

- `docs/lessons-learned/README.md`
- `docs/lessons-learned/LESSONS.md`
- `docs/lessons-learned/.state.yml`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md`

## Roster gap (routing)

Task phrasing "重设计/redesign 菜单改造" did not match any squad trigger keyword
in CLAUDE.md (`agent|squad|团队|分工|重构|refactor|多专家|multi-agent`). Main
Claude routed correctly anyway. Recommend main Claude record a
`[routing][roster-gap]` orchestrator lesson if it has not already, suggesting a
UI-redesign verb (`重设计`/`redesign`/`改造`) be added to the trigger set.
