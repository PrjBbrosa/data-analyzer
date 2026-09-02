---
id: qt-inner-frame-needs-four-edge-paint-guards
status: active
owners: [codex]
keywords: [qt, popup, scroll-area, paintEvent, border, dpr, cocoa]
paths: [mf4_analyzer/ui/widgets/view_overflow_popup.py, tests/ui/test_view_tabbar.py]
checks: [git diff --check]
tests: [tests/ui/test_view_tabbar.py::test_overflow_popup_omits_help_copy_and_paints_list_separators]
---

# Qt Popup Body Frame Must Share The Outer Shell Edge

Trigger: Custom-painting a body frame between a popup header and footer around
an opaque scroll area.

Past failure: The View overflow body reserved 8px on the left and right. Its
four corners were internally closed, but the body sides visibly stepped inward
from the rounded outer shell above and below. The regression test encoded that
8px inset as correct, so exact-color pixel checks still protected the wrong
visual target.

Rule: Translate “上下对齐” into a shared shell coordinate, not merely matching
body-line endpoints. Keep only the one logical paint pixel needed to protect
the stroke from the scroll child, and assert that the full-width body widget and
its left/right strokes share the outer surface edges. Use a full-popup Cocoa
render to verify the header/body/footer transition; a body-only grab cannot
prove cross-section alignment.

Verification: Run the focused separator test with both
`QT_QPA_PLATFORM=offscreen` and `QT_QPA_PLATFORM=cocoa`, render a many-row popup
from the production widget and stylesheet, then run `git diff --check`.
