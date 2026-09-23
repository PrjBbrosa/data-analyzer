---
id: native-glass-needs-backdrop-and-opaque-fallback
status: active
owners: [codex]
keywords: [glass, blur, Cocoa, Acrylic, splash, material]
paths: [mf4_analyzer/qt_panel_style.py, mf4_analyzer/qt_panel_cocoa.py, mf4_analyzer/ui/startup_splash.py]
checks: []
tests: [tests/ui/test_qt_panel_style.py, tests/ui/test_startup_splash.py]
---

# Native glass needs a real backdrop and an opaque fallback

Trigger: Translating an HTML glass prototype to Qt translucent panels.

Past failure: A CSS blur reference constant and translucent fills were treated
as glass on macOS even though the only native backend was Windows. Background
text remained sharp. Extra blue rectangle washes and flat cyan tips also made
the native panel look unlike the accepted HTML.

Rule: Trace the actual platform backdrop backend, then match layer composition.
Alpha is not blur. Native AppKit/Acrylic materials do not expose CSS blur pixels.
If backdrop blur is unavailable, use an opaque light fallback. Release native
views and disconnect destruction callbacks on hide/reapply; fake native handles
must be released before monkeypatch teardown, even when assertions fail.

Verification: Use real foreground panels over readable text and colored blocks;
check blurred detail, clear foreground text, rounded corners and no rectangular
washes. Test repeated show/pin/hide, idempotent release and missing capability.
Keep Cocoa evidence distinct from Windows frozen acceptance.
