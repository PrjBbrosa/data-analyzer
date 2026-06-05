---
id: codex-overlay-graticule-wheel-contract
status: active
owners: [codex]
keywords: [overlay, graticule, ticks, wheel, timedomain]
paths:
  - mf4_analyzer/ui/pg_canvases.py
  - mf4_analyzer/ui/chart_stack.py
  - tests/ui/test_overlay_grid_ticks.py
checks:
  - git diff --check
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/ -q
---

# Overlay Graticule And Wheel Contract

Trigger: Work touching TimeDomain pyqtgraph overlay-mode grid lines, per-channel
Y ticks, Y-density controls, selected-channel Y wheel behavior, or drag-release
Y snap.

Past failure: Older tests and code assumed overlay vertical wheel could mutate
the X-master `[0, 1]` graticule ViewBox, and that drag-release snap preserved
the current Y span by scene-coordinate center snapping. The new contract uses
nice-number graticules and selected-channel-only vertical wheel behavior.

Rule: In overlay mode, the X-master ViewBox owns only shared X and the fixed
`[0, 1]` grid. Inspector Y density is the overlay division count. Per-channel
Y axes must be framed to nice-number divisions and explicitly ticked at
`k/N`; vertical wheel without Ctrl must target only the selected channel, emit
a select-channel hint when none is selected, and never change X-master Y.

Verification: Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m
pytest tests/ui/test_overlay_grid_ticks.py -q` for focused behavior and
`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/
-q` for the full UI contract. `scripts/verify_overlay_grid_ticks.py` should
produce `/tmp/overlay_grid_ticks.png` and print matching per-channel ticks.
