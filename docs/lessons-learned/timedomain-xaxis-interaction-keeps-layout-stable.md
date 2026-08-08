---
id: timedomain-xaxis-interaction-keeps-layout-stable
status: active
owners: [codex]
keywords: [pyqtgraph, timedomain, AxisItem, setTicks, autoReduceTextSpace, quiet-window, zoom]
paths: [mf4_analyzer/ui/pg_canvas/canvas.py, mf4_analyzer/ui/pg_canvas/tick_density.py, tests/ui/test_pg_timedomain_canvas.py]
checks: [rg -n "_use_adaptive_x_ticks_during_range_change|autoReduceTextSpace=False|test_x_ticks_and_bottom_geometry_stay_stable_before_zoom_settles"]
tests: [tests/ui/test_pg_timedomain_canvas.py::test_x_ticks_and_bottom_geometry_stay_stable_before_zoom_settles, tests/ui/test_pg_timedomain_canvas.py::test_range_change_burst_resets_explicit_x_ticks_only_once, tests/ui/test_timedomain_hotpath_perf.py]
---

# TimeDomain X-Axis Interaction Keeps Layout Stable

Trigger: Changing TimeDomain target X ticks, X-range interaction, the interaction quiet window, or bottom AxisItem sizing.

Past failure: Settled explicit target ticks stayed installed while a zoom moved to a range containing none of them. The interaction frame drew no X tick labels, pyqtgraph reduced `textHeight` to zero, and the bottom axis plus ViewBox border moved until quiet-window reticking restored them.

Rule: During the first X-range change in a burst, release stale explicit ticks to pyqtgraph adaptive ticks once per AxisItem, keep the TimeDomain bottom-axis text reserve non-shrinking, and restore target-count ticks only after the existing quiet window. Never run target-tick fitting on every range event.

Verification: Exercise subplot-1, subplot-3, and overlay-3 before `_flush_pending_refresh()`; require drawn X labels plus stable bottom-axis/ViewBox geometry, then verify explicit ticks return after flush. Run the burst single-reset regression, `tests/ui/test_timedomain_hotpath_perf.py`, and the pg-canvas backref invariant gate.
