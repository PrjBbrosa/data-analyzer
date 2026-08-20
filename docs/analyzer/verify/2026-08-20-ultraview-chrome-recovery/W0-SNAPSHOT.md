# W0 construction snapshot — UltraView Miro operation UI restoration

- Date: 2026-08-20
- Branch: `codex/ultraview-authoring-tools`
- HEAD: `14ef0c179894ab79a2d6cdfb1dd7b4a31bc8b3c3`
- Python: 3.12.14
- Qt: 5.15.14
- Last good gradient baseline: `c80f46e0`

## Dirty fingerprint (pre-implementation)

Owner files already dirty in this checkout (prior chrome-recovery work; this
plan supersedes that direction and continues on the same files):

- `mf4_analyzer/ui/chart_stack/ultraview/{page,widgets,chrome,author_chrome,author_selection,author_tools,author_geometry}.py`
- `mf4_analyzer/ui_kit/{style.qss,ultraview_style.py}`
- `mf4_analyzer/ui/{hints.py,quickref.py}` and help
- focused UltraView tests

Unrelated and not touched: `ssh-keygen`, `ssh-keygen.pub`.

## Offscreen evidence archived here

- `selected-card-toolbar.png`
- `selected-shape-toolbar.png`
- `sticky-flyout.png`
- `compact-800x560.png`

## Panel action inventory (must not change)

Rail panels, in order: Library, Free Grid, Layout, Filter, Unplaced, Sync All.
Author segment (this plan): Select, Sticky, Text, Shapes, Draw.
Global: Display, Export, Presentation.
Nav: Overview, Zoom out, Zoom in, Fit, 1:1.

## Card action bar (must remain)

Open / Focus / Fit / Remove / More. Hover, focus, action-button focus, and
the existing “常驻显示卡片操作” preference.
