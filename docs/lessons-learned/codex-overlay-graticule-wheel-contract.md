---
id: codex-overlay-graticule-wheel-contract
status: active
owners: [codex]
keywords: [overlay, graticule, ticks, wheel, timedomain, y-axis-drag]
paths:
  - mf4_analyzer/ui/pg_canvases.py
  - mf4_analyzer/ui/chart_stack.py
  - tests/ui/test_overlay_grid_ticks.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - git diff --check
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/ -q
---

# Overlay Graticule And Wheel Contract

Trigger: Work touching TimeDomain pyqtgraph overlay-mode grid lines,
per-channel Y ticks, Y-density controls, selected-channel Y wheel behavior,
Y-axis gutter dragging, or drag-release Y snap.

Past failure: Older tests and code assumed overlay vertical wheel could mutate
the X-master `[0, 1]` graticule ViewBox, and that drag-release snap preserved
the current Y span by scene-coordinate center snapping. The first nice-graticule
pass also left X-master Y mouse interaction enabled and only let curve-body
presses start channel Y-drag, so the grid could still feel draggable while
axis/tick-gutter dragging felt dead. A later failure: RectMode box-zoom
("局部放大") goes through pyqtgraph's `setRange(rect)`, which ignores
`mouseEnabled` and pulls the X-master Y off `[0, 1]`, collapsing the fixed k/N
graticule to the 2-3 lines that fall inside the box — and nothing restored it,
so the grid "stopped redrawing" after a zoom. Drag-release snap also jumped the
curve up to half a division instantly, which read as an abrupt "突跳".

Rule: In overlay mode, the X-master ViewBox owns only shared X and the fixed
`[0, 1]` grid. Its mouse interaction must be `x=True, y=False` at rest and
`x=False, y=False` only during selected-channel Y drags. Inspector Y density
is the overlay division count. Per-channel Y axes must be framed to
nice-number divisions and explicitly ticked at `k/N`; vertical wheel without
Ctrl must target only the selected channel, emit a select-channel hint when
none is selected, and never change X-master Y. Pressing a channel's Y-axis
gutter should select that channel and start the same Y-drag path as pressing
the curve body. Drag release should keep the current span and snap the axis
back to its current graticule instead of expanding the range again; the snap
glides there over `_snap_anim_ms` (default 150 ms, `<= 0` = synchronous) so the
release is not an instant jump. RectMode box-zoom on the X-master must re-lock
its Y to `[0, 1]` (so the k/N graticule never collapses) and redirect the box's
Y fraction onto the selected channel — framed to nice divisions — while the base
class keeps the shared X zoom; with no channel selected it degrades to X-only.
This runs from `_apply_overlay_box_zoom_y`, called after `super().mouseDragEvent`
in `_ModifierWheelViewBox` only on a RectMode finish landing on the X-master.

Verification: Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m
pytest tests/ui/test_overlay_grid_ticks.py -q` for focused behavior,
`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest
tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGOverlayMouseInteraction
-q` for mouse routing, and `QT_QPA_PLATFORM=offscreen PYTHONPATH=.
.venv/bin/python -m pytest tests/ui/ -q` for the full UI contract.
`scripts/verify_overlay_grid_ticks.py` should produce
`/tmp/overlay_grid_ticks.png` and print matching per-channel ticks.
