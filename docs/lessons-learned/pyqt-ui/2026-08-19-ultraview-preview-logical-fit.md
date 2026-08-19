---
id: pyqt-ui/2026-08-19-ultraview-preview-logical-fit
status: active
owners: [codex]
keywords: [ultraview, preview, high-dpi, dpr, aspect-fit, free-grid]
paths:
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - mf4_analyzer/ui/chart_stack/ultraview/free_grid.py
checks:
  - preview dimensions are converted from raw device pixels to current card logical pixels before calling fit_rect_for_aspect
tests:
  - tests/ui/test_ultraview_placement_history.py::test_add_with_retina_preview_uses_logical_pixels_for_first_fit
---

# UltraView Preview Fit Uses Logical Pixels

Trigger: Changing an UltraView preview-to-Free-Grid aspect-fit path.

Past failure: PreviewStore intentionally normalizes a capture to DPR=1 while
retaining its raw device-pixel width and height. Passing those dimensions to a
logical-widget grid solver made Retina captures appear twice as large, leaving
a visibly oversized card shell and unused area around the preview.

Rule: Keep PreviewStore buffers as raw pixels, but divide their dimensions by
the current card screen DPR before using them in any card-fit geometry. Do not
change the QImage itself, crop the source view, or make plot pixels transparent.

Verification: Run the focused Retina first-insert regression together with the
UltraView free-grid and placement-history tests.
