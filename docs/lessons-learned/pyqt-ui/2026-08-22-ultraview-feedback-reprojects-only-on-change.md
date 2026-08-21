---
id: pyqt-ui/2026-08-22-ultraview-feedback-reprojects-only-on-change
status: active
owners: [codex]
keywords: [ultraview, edge-pan, ghost, overlay, cocoa, repaint, viewport, feedback]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py
  - mf4_analyzer/ui/chart_stack/ultraview/viewport_feedback.py
checks:
  - rg -n "workspace_gesture_changed|refresh_workspace_gesture|_paint_fingerprint_seen|set_move_previews" mf4_analyzer/ui/chart_stack/ultraview/page.py mf4_analyzer/ui/chart_stack/ultraview/widgets.py mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py
tests:
  - tests/ui/test_ultraview_feedback_pipeline.py
  - tests/ui/test_ultraview_gesture_preview.py
  - tests/ui/test_ultraview_gesture_coalesce.py
---

# UltraView Feedback Reprojects Only On Change

Trigger: Changing UltraView move/resize feedback, edge auto-pan, pointer coalescing, transparent overlays, or Cocoa backing-store recovery.

Past failure: The Page started a 16 ms edge timer for every active gesture and
called `refresh_workspace_gesture()` even when edge velocity and viewport
geometry were unchanged. The lifetime signal only published the first live
pointer, the candidate fingerprint was written but never compared, and an
identical preview still called `raise_()` plus full `update()` on a translucent
overlay as large as the elastic workspace. A full-Page Cocoa probe held one
pointer sample for 500 ms and observed 34 preview submissions and 42 paints for
both move and resize while the feedback model itself remained populated.

Rule: Keep gesture lifetime, latest pointer, and immutable feedback frame as
separate contracts. An edge tick may re-resolve a gesture only after scroll,
extent, or origin actually changes, and must use the latest pointer. An
unchanged snapped candidate does not plan or present again. Backing-store
recovery repaints the cached frame without calling the planner. Full repaint is
allowed only on a feedback surface bounded to the visible viewport; never use
the elastic Board-sized transparent sibling as the high-frequency surface.

Verification: A complete Page test holds move and resize outside the edge band
for at least 500 ms and observes zero extra planner/frame submissions after the
initial settle. Edge-pan tests prove latest-pointer use and at most one
reprojection per real viewport change. Surface geometry equals the viewport,
expose repaints without planning, release flushes the displayed final sample,
and Cocoa 0/100/500/2000 ms frame samples retain the target border and resize
badge.
