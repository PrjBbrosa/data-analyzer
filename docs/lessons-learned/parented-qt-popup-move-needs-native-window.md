---
id: parented-qt-popup-move-needs-native-window
status: active
owners: [codex]
keywords: [qt, popup, winId, move, show, first-show, recent-open, screen-coordinates]
paths:
  - mf4_analyzer/ui_kit/dialog_geometry.py
  - mf4_analyzer/ui/widgets/recent_open_popup.py
  - mf4_analyzer/ui/widgets/view_overflow_popup.py
checks:
  - git diff --check
tests:
  - tests/ui_kit/test_dialog_geometry.py::test_move_in_screen_creates_handle_before_first_show
  - tests/ui/test_recent_open_popup.py::test_first_show_at_clears_the_anchor_like_the_second_show
---

# Parented Qt Popup Move Needs Native Window

Trigger: Positioning a parented `Qt.Popup` with screen coordinates, especially
`move` then `show` on first open.

Past failure: The recent-open panel covered the Open button on the first click
and sat correctly below it on the second. Before the first Show there is no
`windowHandle`; `QWidget.move` is parent-local, so global `x/y` landed on the
toolbar. After hide the native window existed and the same `move` was screen
space.

Rule: Use `move_in_screen` (it calls `winId()` when the handle is missing)
before Show, then `move_in_screen` again after Show. Do not `move` a parented
popup with screen coordinates until a native window exists. PyQt5 has no
`createWinId()`; `winId()` is the create seam.

Verification: Run the `move_in_screen` and first-vs-second `show_at` tests.
Confirm production `show_at` paths call `move_in_screen`, not a bare `move`.
