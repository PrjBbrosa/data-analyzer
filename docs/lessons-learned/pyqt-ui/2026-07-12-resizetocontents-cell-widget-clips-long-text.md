---
role: pyqt-ui
tags: [qtablewidget, qheaderview, resizetocontents, cellwidget, sizehint, scientific-notation, clipping, db-reference]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

## Context

`DbReferenceDefaultsDialog`'s catalog table renders the "0 dB reference"
column with a `ScientificReferenceSpinBox` set as the CELL WIDGET (not a
`QTableWidgetItem`), under `QHeaderView.ResizeToContents`. The macOS on-screen
Task 10 visual-tour screenshot showed the built-in `acceleration.g` row's
value (`1.019716213e-7` — the exact 17-significant-digit value the spin box's
own `setDecimals(30)` docstring cites as its reason for existing) silently
missing its last character, cut off mid-glyph, with no ellipsis.

## Lesson

`QHeaderView.ResizeToContents` on a column whose cells are WIDGETS (via
`setCellWidget`) sizes the column from each widget's generic `sizeHint()`,
not from the widget's CURRENTLY DISPLAYED text. A `QDoubleSpinBox`-family
widget's `sizeHint()` reported a constant `(56, 31)` here regardless of
whether its line edit held `"1e-6"` or `"1.019716213e-7"` — so the column
converged on a width that fit the SHORT common case and silently clipped the
one row whose value needed more horizontal room (a 120px-wide string inside a
116px line-edit content area, 4px short). `QLineEdit` does not elide; it just
shows from position 0 and clips the tail, so the failure mode looks like a
truncated/broken number, not a `…` ellipsis — easy to miss in code review,
obvious the moment you `grab()` and zoom into a real screenshot.

## How to apply

When a `QTableWidget` column hosts CELL WIDGETS (spin boxes, combo boxes,
buttons) rather than plain items, do not trust `ResizeToContents` if any row's
content can be meaningfully longer than a "typical" value — measure the
WIDEST realistic displayed text (e.g. via `QFontMetrics.horizontalAdvance` on
every row's actual formatted string, or just pick a generous explicit width)
and set `QHeaderView.Interactive` + `resizeSection(col, width)` instead — the
exact fix already applied one column over in this same file for the same
reason (`物理量`/quantity labels). Verify with a real screenshot at the ROW
that needs the most space, not just the default/first row.
