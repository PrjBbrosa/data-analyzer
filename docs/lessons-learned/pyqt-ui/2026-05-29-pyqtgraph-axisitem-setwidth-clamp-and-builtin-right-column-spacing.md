---
role: pyqt-ui
tags: [pyqtgraph, axisitem, setwidth, overlay, grid, showgrid, setHorizontalSpacing, layout, geometry]
created: 2026-05-29
updated: 2026-05-29
cause: insight
supersedes: []
---

## Context
Overlay `TimeDomainCanvasPG` showed a tangle of multi-colored, misaligned
horizontal Y grids and right-side channel names crammed against the
neighbouring axis's tick numbers. The prior "fix" pinned each overlay
`AxisItem` with `setWidth(44)` and documented it as a width floor.

## Lesson
Two pyqtgraph quirks: (1) `AxisItem.setWidth(w)` is a HARD CLAMP, not a
floor — a wide-number axis that auto-sizes to 53px is forced down to `w`
and its tick numbers cram against the rotated label; release with
`setWidth(None)` and let it auto-size, then provide clearance with layout
spacing. (2) `PlotItem.showGrid(y=...)` toggles the Y grid on BOTH built-in
left+right axes, so in overlay (left/right linked to different per-channel
ViewBoxes with different Y ranges) each draws its own grid at its own ticks
in its own pen color — use `showGrid(x=True, y=False)` and keep only the
single shared X grid. (3) `PlotItem.layout.setHorizontalSpacing(n)` does NOT
apply across the boundary between the built-in right-axis column (col 2,
which abuts the ViewBox) and the next appended column, so a built-in-right +
appended-right mix always overlaps the FIRST axis pair while the rest are
spaced; route EVERY right channel through fresh appended `AxisItem`s in
contiguous columns starting at col 3 (leave col 2 empty) so the spacing is
uniform. The rotated axis label also overhangs ~5px past `width()`, so the
spacing must exceed that overhang to leave a visible gap.

## How to apply
When stacking multiple pyqtgraph right axes (overlay/twinx-style): never pin
`setWidth` as a "floor" (it clamps); auto-size and space via the layout.
Test real clearance — assert adjacent y-`AxisItem` `sceneBoundingRect`s do
not overlap and no axis is narrower than its natural (`setWidth(None)`)
width — never just `"\n" not in label`. For overlay grids, disable the Y
grid (`showGrid(x=True, y=False)`) because no single Y range is canonical;
keep both grids only for single/subplot. Geometry-sensitive blank-click test
helpers must scan a fine grid (e.g. 25x25 over a 0.04–0.96 band): a few-px
plot-rect shift can drop a coarse scan below the pick radius without any
behavior change.
