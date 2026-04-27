# Decomposition: toolbar-statusbar-ui-fixes

Date: 2026-04-27
Slug: toolbar-statusbar-ui-fixes
Top-level request: 6 UI fixes — batch button always enabled, toolbar height/back-forward restore, tab centering, remove cursor+lock buttons, tooltip two-line styling, statusbar separator height+spacing.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| T1 — toolbar-button-fixes (issues 1, 3, 4) | pyqt-ui-engineer | — | All changes confined to `toolbar.py` (batch enable-state, mode-segment centering, cursor/lock button removal) and minimal `main_window.py` signal unwiring. Pure toolbar surface. |
| T2 — chart-toolbar-and-statusbar-fixes (issues 2, 5, 6) | pyqt-ui-engineer | — | All changes confined to `chart_stack.py` (toolbar height regression, back/forward restore), `_toolbar_i18n.py` (back/forward retain=True), `style.qss` (tooltip color, separator height+spacing). Pure chart-toolbar and QSS surface. |

## File-boundary matrix

| file | T1 | T2 |
|---|---|---|
| `mf4_analyzer/ui/toolbar.py` | OWNS | forbidden |
| `mf4_analyzer/ui/main_window.py` | OWNS (signals only) | forbidden |
| `mf4_analyzer/ui/chart_stack.py` | forbidden | OWNS |
| `mf4_analyzer/ui/_toolbar_i18n.py` | forbidden | OWNS |
| `mf4_analyzer/ui/style.qss` | forbidden | OWNS |

## Parallel safety

T1 and T2 have disjoint file sets — they can be dispatched in parallel.

## Rework forecast

No cross-specialist overlap anticipated (disjoint file sets).

## Lessons consulted

- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md` — QSS padding wins over Python margin calls; use inline stylesheet overrides.
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — Toolbar height changes can cascade into pane-level sizing; verify at default and dragged splitter positions.
