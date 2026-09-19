---
id: qt5-mapto-descendant-native-crash
status: active
owners: [codex]
keywords: [Qt5, mapTo, mapFrom, SIGSEGV, viewport, pinned-cursor]
paths: [mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py, mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py]
checks: []
tests: []
---

# Qt5 Coordinate Mapping Must Respect Widget Ancestry

Trigger: Mapping QWidget coordinates into descendant widgets or QGraphicsView scenes, especially Pin geometry timers.

Past failure: Parent `canvas.mapTo(child, point)` reproduced native SIGSEGV in Qt5; calling production `_sync_leaders` reached pinned_cursor_overlay.py:1211 and exited 139. September 19 runtime crash reports also showed QWidget::mapTo/0x28. Python exception guards and sip.isdeleted did not prevent the bad ancestry call.

Rule: Use descendant.mapFrom(ancestor, point) for ancestor-to-descendant conversion; use global round trips when ancestry is not guaranteed. QGraphicsView.mapToScene receives viewport coordinates, so map into the viewport explicitly. Verify the direction and coordinate domain, not just object liveness. Keep native-crash probes in isolated subprocesses.

Verification: Compare mapped coordinates by round trip in real widget hierarchies, including nonzero view/viewport offsets. Add subprocess coverage for dense/edge Pin leaders and frequency hit tests when implementing the fix. The diagnosis and reproduction are recorded in docs/analyzer/reviews/2026-09-19-pin-layout-and-crash-analysis.md; product correction and Cocoa acceptance remain pending.
