---
id: windows-dwm-backdrop-can-fill-rounded-splash-corners
status: active
owners: [codex]
keywords: [windows, dwm, acrylic, splash, rounded-corners, qt]
paths:
  - mf4_analyzer/ui/startup_splash.py
  - mf4_analyzer/qt_panel_style.py
checks:
  - git diff --check
tests:
  - tests/ui/test_startup_splash.py::test_windows_splash_keeps_the_rounded_shell_without_dwm_backdrop
  - tests/ui/test_startup_splash.py::test_screenshot_saved_and_geometry_asserted
---

# Windows DWM Backdrop Can Fill Rounded Splash Corners

Trigger: Adding a Windows system backdrop to a translucent, frameless Qt panel whose visible card is painted with rounded corners.

Past failure: Qt offscreen grabs showed transparent rounded corners, but a packaged Windows screenshot showed gray rectangular patches behind them. DWM's transient Acrylic is drawn behind the entire window bounds, outside the card's antialiased path.

Rule: Keep the splash's Windows surface inside its own rounded Qt paint path. Check native compositor output on Windows before claiming the corners or material are accepted; a Qt grab cannot prove this.

Verification: Run the focused splash corner and Windows surface policy tests, inspect the rendered splash, then check the four corners on a fresh Windows package at the target DPI.
