---
id: subplot-bottom-axis-role-must-release-height
status: active
owners: [codex]
keywords: [pyqtgraph, subplot, AxisItem, setHeight, selection-delta, bottom-axis]
paths: [mf4_analyzer/ui/pg_canvas/canvas.py, mf4_analyzer/ui/pg_canvas/overlay_axes.py, tests/ui/test_pg_timedomain_canvas.py]
checks: [rg -n "if not bottom_axes:|setHeight\\(None\\)|_configure_subplot_bottom_axis" mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/overlay_axes.py]
tests: [tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta::test_subplot_collapse_releases_former_upper_bottom_axis, tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta::test_shared_axis_unique_slot_releases_bottom_axis_height]
---

# Subplot Bottom Axis Role Must Release Height

Trigger: Changing TimeDomain subplot bottom-axis role, selection-delta reuse,
`_unify_subplot_bottom_axis_heights`, or `_configure_subplot_bottom_axis`.

Past failure: Unchecking subplot rows until only a former upper row remained
left that row's bottom AxisItem at `setHeight(1.0)`. The unifier returned
before `len(bottom_axes) < 2`, and role restore only flipped `showValues`.
The plot area ate the X-axis band; ticks vanished and the title entered the
ViewBox.

Rule: Project the current bottom-axis role completely, including height.
Upper rows stay collapsed at ~1 px. The unique remaining row is still the
bottom axis: `setHeight(None)` plus layout activation. Count axes, not
curves. Repeat the helper without accumulating reserved space. Do not rebuild
every PlotItem just to dodge a leftover pin.

Verification: Run the selection-delta collapse matrix (3→2→1, 3→1, 1→3,
keep first/middle/last) and the shared unique-slot pin-then-settle case.
Assert `fixedHeight is None`, layout `height() > 20`, and at least one
drawable X number whose text rect stays outside the ViewBox.
