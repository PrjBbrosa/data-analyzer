---
role: pyqt-ui
tags: [layout, inspector, navigator, responsive-pane, rework, max-width, wide-pane]
created: 2026-04-24
updated: 2026-04-26
cause: rework
supersedes: []
---

## Context

After the Precision Light UI pass, narrow-window screenshots showed right
Inspector controls overlapping and the left file list showing only one
loaded file. The first follow-up changed form rows into vertical field
blocks, but the user clarified that the desired behavior was container
scrolling/resizing, not a different form layout. The 2026-04-26 R3
紧凑化 follow-up uncovered the *wide* end of the same axis: with the
splitter dragged to 1500px+, every Expanding child (QSpinBox /
QComboBox / QLineEdit) grew unboundedly, producing the screenshot
complaint "点击使用范围，宽度就变了" — the visual pane width changed
in response to a checkbox toggle because newly-shown Expanding
controls re-stretched the layout.

## Lesson

Responsive pane defects should be solved at the container level before
changing control semantics. In this app, right Inspector overflow belongs
to a pane-level `QScrollArea`, while left file-list capacity belongs to a
splitter or resizable file region. **Wide-pane behavior is its own axis**:
any pane whose splitter slot can grow beyond its content's natural width
must cap the content widget (`scroll_body.setMaximumWidth(...)`) and
left-anchor it inside a stretch host, otherwise Expanding children fight
the cap by growing into whatever slack the splitter hands them.

## How to apply

When screenshot feedback mentions narrow panes, clipping, overlap, or
too little list space, inspect `QScrollArea`, `QSplitter`, stretch
factors, and min/max heights first. Preserve compact `QFormLayout` rows
unless the user explicitly asks for label-over-control form styling.

**Wide-pane verification (2026-04-26 amendment):** any splitter pane
whose contents can grow with the splitter slot — particularly the right
Inspector pane — must be visually verified at three widths: narrow
(≤ minWidth, e.g. 280px), default (the spec's `setSizes` slot), and
wide (≥ 1.5×~3× the default, e.g. 1500–2000px). At the wide end the
content should remain capped (visible right-side gap inside the pane
is acceptable and expected) while at the narrow end no clipping should
occur. Toggling visibility of any Expanding child (a checkbox that
shows/hides spinboxes, a mode switch that swaps a contextual card)
must NOT change the pane's apparent width — this is the easiest
regression to spot during exercise. Cross-reference
`pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`
for the cap pattern.
