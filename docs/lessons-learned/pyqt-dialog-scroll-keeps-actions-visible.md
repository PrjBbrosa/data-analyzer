---
id: pyqt-dialog-scroll-keeps-actions-visible
status: active
owners: [codex]
keywords: [pyqt, qdialog, scroll, availablegeometry, footer, chart-options]
paths: [mf4_analyzer/ui/dialogs.py, tests/ui/test_dialogs.py, tests/ui/test_dialog_with_handle.py]
checks: [QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_dialogs.py tests/ui/test_dialog_with_handle.py -q]
tests: [tests/ui/test_dialogs.py, tests/ui/test_dialog_with_handle.py]
---

# PyQt Dialog Scroll Keeps Actions Visible

Trigger: Touching PyQt dialogs with header/body/footer layouts, especially chart options or settings dialogs with enough fields to exceed short laptop screens.

Past failure: `ChartOptionsDialog` let the full tab content drive the top-level dialog height. On a short Windows screen the dialog opened taller than the usable area, so the Apply/OK row was hidden behind the taskbar and the user could not apply settings.

Rule: Keep action rows outside the scrollable body. Put long form content inside a `QScrollArea`, cap the dialog against `QScreen.availableGeometry()` including window-frame slack, and clamp the shown frame back inside the available screen.

Verification: Add a Qt offscreen regression that shows the dialog, asserts its height stays within available geometry, and checks Apply/OK buttons remain inside the dialog rect. Run `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_dialogs.py tests/ui/test_dialog_with_handle.py -q`.
