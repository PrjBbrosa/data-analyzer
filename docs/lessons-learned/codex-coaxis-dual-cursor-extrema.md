---
id: codex-coaxis-dual-cursor-extrema
status: active
owners: [codex]
keywords: [coaxis, axis_group, overlay, dual-cursor, extrema, min, max, ScatterPlotItem]
paths: [mf4_analyzer/ui/pg_canvas/cursor.py, tests/ui/test_pg_timedomain_canvas.py]
checks: [git diff --check]
tests: [tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGCursorInteraction::test_dual_cursor_marks_every_channel_in_a_shared_coaxis_group]
---

# Co-axis Dual Cursor Must Retain Every Member Extremum

Trigger: Changing dual-cursor min/max markers, co-axis groups, or TimeDomain
overlay axis-slot ownership.

Past failure: The marker update resolved one channel name per axis handle. A
co-axis group has one handle for several curves, so the first channel's points
overwrote the rest and users saw only one min/max pair.

Rule: Group extrema by the actual axis handle and append a min plus max point
for every visible member channel; keep composite channel identity until the
handle lookup is complete.

Verification: Run the focused shared-coaxis marker test and the existing
single-channel marker test, then run `git diff --check`.
