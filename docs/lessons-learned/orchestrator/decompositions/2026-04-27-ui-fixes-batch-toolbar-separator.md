# Decomposition: ui-fixes-batch-toolbar-separator

Date: 2026-04-27
Slug: ui-fixes-batch-toolbar-separator
Top-level request: Three UI fixes — (1) btn_batch always-enabled guard removal, (2) NavigationToolbar2QT buttons squarified 32×32 + spacing 4→8px, (3) chartToolbarSep separator made more visible (height 20px, color #94a3b8).

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| T1 — batch-button-enable-state | pyqt-ui-engineer | — | Confined to `toolbar.py`: remove `btn_batch.setEnabled(True)` from `set_enabled_for_mode` and drop `btn_batch` from the initial mass-disable loop; pure enable-state surface fix. |
| T2 — chart-toolbar-nav-buttons-and-sep | pyqt-ui-engineer | — | Confined to `chart_stack.py` (icon size 14→22, button setFixedSize 32×32, spacing 4→8) and `style.qss` (chartToolbarSep height→20, color→#94a3b8); both chart-toolbar and QSS surface are owned here. Issues 2+3 bundled because both touch `chart_stack.py` — serializing prevents git-add collision per the parallel-same-file lesson. |

## File-boundary matrix

| file | T1 | T2 |
|---|---|---|
| `mf4_analyzer/ui/toolbar.py` | OWNS | forbidden |
| `mf4_analyzer/ui/chart_stack.py` | forbidden | OWNS |
| `mf4_analyzer/ui/style.qss` | forbidden | OWNS |

## Parallel safety

T1 and T2 have fully disjoint file sets — they can be dispatched in parallel.

## Rework forecast

No cross-specialist overlap anticipated (disjoint file sets). Issues 2 and 3 share `chart_stack.py`; bundling into T2 eliminates the intra-wave collision risk.

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — Same-expert parallel tasks touching the same file cause git-add collisions; bundle into one brief.
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md` — QSS rules beat Python margin/size calls; verify with processEvents after stylesheet polish.
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — Toolbar height changes can cascade into pane sizing; verify at default splitter.
