---
id: codex-timedomain-new-channel-yfit-after-restore
status: active
owners: [codex]
keywords: [timedomain, overlay, view-state, ylims, defer-first-frame, y-autofit]
paths:
  - mf4_analyzer/ui/pg_canvas/canvas.py
  - mf4_analyzer/ui/main_window.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - git diff --check
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode::test_restore_visible_ylims_fits_new_overlay_channel_to_visible_x -q
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py -q
---

# Timedomain New Channel Y-Fit After Restore

Trigger: Touching timedomain channel-selection replots, ViewState
`xlim`/`ylims` restore, `defer_first_frame`, or overlay Y-autofit behavior.

Past failure: Adding a channel in overlay after a view/split-aware replot could
bind empty first-frame curves while restoring X. Existing channels recovered
their saved `ylims`, but the newly added channel had no saved range and could
stay on an empty/default or full-data-driven Y range. Manual `Y 轴自适应`
fixed it because that path computes Y from raw samples inside the current X
window.

Rule: After restoring saved ylims, any currently plotted channel without a
saved ylim must be fitted once from raw data inside the restored visible X
range. Do not overwrite channels that already restored explicit ylims. Keep
overlay nice-grid framing separate from subplot's plain 5% padded Y-fit.

Verification: Add or run a regression that rebuilds overlay with
`defer_first_frame=True`, restores X and old ylims, then asserts a newly added
channel fits the visible-X data window and ignores outliers outside it. Also
run the overlay grid/tick tests.
