---
id: translucent-popup-chrome-must-self-paint
status: active
owners: [codex]
keywords: [qt, popup, paintEvent, hover, qss, widgetAt, overflow]
paths:
  - mf4_analyzer/ui/widgets/view_overflow_popup.py
  - mf4_analyzer/ui_kit/style.qss
checks:
  - git diff --check
tests:
  - tests/ui/test_view_tabbar.py::test_overflow_popup_omits_help_copy_and_paints_list_separators
  - tests/ui/test_view_tabbar.py::test_reproject_restores_hover_on_close_button_under_cursor
---

# Translucent Popup Chrome Must Self-Paint

Trigger: Drawing inner frames or hover fills on a `Qt.Popup` with
`WA_TranslucentBackground`, especially when a spanning child `QWidget` sits
over the chrome.

Past failure: View overflow well strokes were painted on the parent surface
and covered by the child's global `QWidget` white fill on Cocoa. Row `×`
`:hover` QSS never painted on the translucent popup; only the pointing-hand
cursor changed. Offscreen tests stayed green by grabbing the parent, mocking
`widgetAt`, or asserting `WA_UnderMouse`.

Rule: The widget that owns the pixels must paint them. Well strokes go in the
list-well `paintEvent`, inset via widget `contentsMargins` so the 1px line
stays in the pad and inside the clip. Transparent-button hover is a custom
`paintEvent` plus geometric `mapFromGlobal` hit tests, not QSS `:hover` and
not `QApplication.widgetAt`. Pixel tests must `grab()` that same widget.

Verification: Grab `viewOverflowListWell` and assert ink at the 8px inset
edges. After reproject, grab the close button under the cursor and assert the
hover fill `#fff0f2`, not just cursor or `WA_UnderMouse`.
