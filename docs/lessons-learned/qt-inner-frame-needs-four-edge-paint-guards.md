---
id: qt-inner-frame-needs-four-edge-paint-guards
status: active
owners: [codex]
keywords: [qt, popup, scroll-area, paintEvent, border, dpr, cocoa]
paths: [mf4_analyzer/ui/widgets/view_overflow_popup.py, tests/ui/test_view_tabbar.py]
checks: [git diff --check]
tests: [tests/ui/test_view_tabbar.py::test_overflow_popup_omits_help_copy_and_paints_list_separators]
---

# Qt Inner Frame Needs Four Edge Paint Guards

Trigger: Custom-painting an inner frame around an opaque scroll area or other
spanning child widget.

Past failure: The View overflow list reserved padding only on the left and
right. Cocoa let the scroll child cover the top and bottom strokes, leaving two
side lines with unmatched endpoints. The pixel test accepted any nearby
non-white content as border ink, so it stayed green.

Rule: Reserve paint-owned padding on all four edges and derive the complete
frame from one rectangle. Pixel assertions must match the intended border
color at the top, bottom, left, right, and four joined corners; convert logical
geometry to physical pixels with the grabbed image DPR.

Verification: Run the focused separator test with both
`QT_QPA_PLATFORM=offscreen` and `QT_QPA_PLATFORM=cocoa`, then run
`git diff --check`.
