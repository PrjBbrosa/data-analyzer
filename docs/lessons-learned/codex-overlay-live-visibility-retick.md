---
id: codex-overlay-live-visibility-retick
status: active
owners: [codex]
keywords: [overlay, ticks, time-domain, filter-overlay, live-toggle, y-axis]
paths:
  - mf4_analyzer/ui/pg_canvas/canvas.py
  - tests/ui/test_pg_timedomain_canvas.py
  - tests/ui/test_overlay_grid_ticks.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestFilterCompanionOverlay::test_live_hide_original_repins_overlay_ticks_to_companion -q
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py -q
---

# Overlay Live Visibility Retick

Trigger: Touching TimeDomain overlay-mode live visibility toggles for filter
companions or originals (`set_original_lines_visible`,
`set_companion_lines_visible`) after companion-axis Y reframing.

Past failure: Hiding `显示原始` correctly refit the shared ViewBox Y range to the
visible filtered companion, but overlay-specific major tick labels stayed pinned
to the previous primary range. In the live app this made the left coordinate
axis appear collapsed, stale, or missing while the waveform used the new Y
range.

Rule: In overlay mode, any live visibility path that calls
`_pin_companion_axes_y_to_visible()` must also repin overlay channel ticks with
`_repin_overlay_channel_ticks()` before drawing. Do not replace this with a full
replot, and keep manual Y gestures separate from automatic visibility reframing.

Verification: Add or run a regression that toggles `显示原始` off/on in overlay
mode with a large primary plus tiny filtered companion, then asserts the major
tick values match the current `ylim` divisions after each toggle. Also run the
overlay grid tick suite and `git diff --check`.
