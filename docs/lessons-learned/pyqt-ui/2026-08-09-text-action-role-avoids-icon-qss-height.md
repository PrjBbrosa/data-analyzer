---
id: pyqt-ui/2026-08-09-text-action-role-avoids-icon-qss-height
status: active
owners: [codex]
keywords: [qss, qpushbutton, role, min-height, inspector, geometry]
paths: [mf4_analyzer/ui/inspector_sections, mf4_analyzer/ui_kit/style.qss]
checks: [git diff --check]
tests: [tests/ui/test_inspector.py]
---

# Text Actions Must Not Reuse Icon-Only QSS Roles

Trigger: Adding or reviewing a textual button in a compact Qt form that uses a
shared QSS role selector with dimensional rules.

Past failure: The FRF input/output swap action used `role="tool"`, whose QSS
intentionally sets `min-height: 0` for icon buttons. It overrode the widget's
Python-side minimum-height guard, and the real styled Inspector assigned the
text action an 8px row despite a 17px font. A bare-widget test passed because
it did not load the production stylesheet.

Rule: Reserve icon-only QSS roles for icon-only controls. Give textual actions
their own semantic role and a QSS height floor, then test them in the complete
production-styled container rather than only as an isolated widget.

Verification: Load `ui_kit.load_stylesheet()` in the focused Inspector test;
assert the action's actual and minimum height exceed its font height; inspect a
rendered narrow Inspector screenshot; run `git diff --check`.
