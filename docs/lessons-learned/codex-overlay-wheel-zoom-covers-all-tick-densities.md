---
id: codex-overlay-wheel-zoom-covers-all-tick-densities
status: active
owners: [codex]
keywords: [overlay, wheel, zoom, tick-density, nice-step, pyqtgraph]
paths: [mf4_analyzer/ui/pg_canvas/overlay_axes.py, tests/ui/test_overlay_grid_ticks.py]
checks: [rg -n "zoom_(out|in)_strictly|adjacent_nice_step" tests/ui/test_overlay_grid_ticks.py mf4_analyzer/ui/pg_canvas/overlay_axes.py]
tests: [tests/ui/test_overlay_grid_ticks.py]
---

# Overlay Wheel Zoom Covers All Tick Densities

Trigger: Changing overlay Y-axis Shift-wheel zoom, nice-step selection, range
framing, or the supported tick-density controls.

Past failure: Tests exercised only positive wheel delta at the default density.
Zoom-out first selected the next larger nice step, then framed only `n - 1`
divisions and let the generic tick helper re-derive the step. At Y densities
3 through 6 that derivation snapped back to the current step, so `set_ylim`
received the unchanged range and zoom-out became a no-op.

Rule: Once overlay zoom selects an adjacent nice per-division step, frame
exactly `n` divisions with that fixed step; do not pass a smaller candidate
span through a helper that may choose the step again. Regression tests must
exercise both wheel directions, every supported Y density 3 through 20, and
multiple consecutive steps, asserting strict monotonicity and the exact
adjacent nice-step span.

Verification: Run
`.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_overlay_grid_ticks.py`
and confirm the parameterized zoom-in and zoom-out cases pass for all Y
densities 3 through 20.
