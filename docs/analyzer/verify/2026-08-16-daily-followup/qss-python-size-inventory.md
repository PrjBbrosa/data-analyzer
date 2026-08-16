# QSS ↔ Python size overlap inventory (2026-08-16)

Recorded during daily-review followup Task 6. The three product defects
(rail icon 36→34 content, warning-dot 8→6 content, layoutThumb content
`154×98` so polish restores `_LAYOUT_THUMB_CELL` 168×118) are fixed. This
list is the remaining overlap between
`mf4_analyzer/ui_kit/style.qss` `min-*`/`max-*` and Python `setFixed*` /
`setMinimum*` in UltraView chrome. **Do not treat it as a fix list.**

Qt QSS `min-width`/`min-height` is **content** size. `QStyleSheetStyle::polish`
writes `content + padding + border` into `widget.setMinimumSize()`, which
overwrites a Python `setFixedSize`/`setMinimumSize` if the QSS value was
authored as the outer box.

## Already compensated (same pattern as the Task 6 rail fix)

| QSS selector | QSS content | Python outer | Notes |
|---|---|---|---|
| `QFrame#ultraViewBoardIsland` (and Global/Nav/Status/CardContext) `QToolButton[role="icon"]` | 30×30 + 1px border | `_icon_button(..., size=32)` | 32 − 2×1 = 30 |
| `QFrame#ultraViewToolRail QToolButton[role="icon"]` | 34×34 + 1px border | `RAIL_BUTTON_SIZE = 36` | **fixed this batch** |
| `QLabel#ultraViewRailFilterWarningDot` | 6×6 + 1px border | `setFixedSize(8, 8)` | **fixed this batch** |
| `QFrame#ultraViewLayoutPopover QToolButton[role="layoutThumb"]` | 154×98 + padding 8/6/10/6 + 1px border | `_LAYOUT_THUMB_CELL` 168×118 | **fixed this batch**; generic `QToolButton { min-height: 22px }` would otherwise polish to 42px |

## Remaining overlaps (not fixed)

| Location | Python | QSS | Risk |
|---|---|---|---|
| `chrome.py` rail badges `setMinimumSize(14, 14)` (`ultraViewRail*Badge`, `ultraViewRailSyncAllBadge`) | 14×14 | `min-width/min-height: 14px` + `padding: 0 3px` + `border: 1px` (`style.qss` ~4690) | Polish may grow badges past 14px |
| `chrome.py` island icon buttons vs. the 30px QSS rule | 32 outer | already compensated | watch if `border` changes |
| `widgets.py:559` `setFixedSize(8, 8)` | 8×8 | no matching `#id` QSS found | low; confirm if a generic `QLabel` min applies |
| `widgets.py:4243` `setFixedSize(168, 112)` | 168×112 | layoutThumb is now 154×98 content | different widget; re-check if it picks up `role="layoutThumb"` |
| Generic `QPushButton { min-height: 26px }` (`style.qss` ~1007 comment) | many `setFixedSize` callers | known historical clash; some roles already use `min-height: 0` | outside UltraView rail |

## Rule for later batches

Python already `setFixedSize`/`setMinimumSize` → QSS must not write `min-*`/`max-*`,
or the QSS content value must be `constant − 2×border − padding` with the constant
named in a comment. QSS-owned sizes → Python does not also write the outer box.
