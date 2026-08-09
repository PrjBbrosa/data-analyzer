---
id: pyqt-ui/2026-08-08-action-button-natural-height-under-wrapped-label-pressure
status: active
role: pyqt-ui
owners: [codex]
keywords: [qpushbutton, qsizepolicy, word-wrap, vertical-layout, screenshot]
paths: [mf4_analyzer/ui/inspector_sections]
checks: [git diff --check]
tests: [tests/ui/test_inspector.py]
created: 2026-08-08
updated: 2026-08-08
cause: insight
supersedes: []
---

# Action Button Natural Height Under Wrapped Label Pressure

Trigger: A compact vertical Qt form places a user action between elastic controls and a word-wrapped description, especially during mode switching or widget reparenting.

Past failure: The FRF input/output swap button had a valid size hint but no minimum height or fixed vertical policy. A Cocoa capture taken after a multiline source description was laid out showed the action compressed into an unreadable stripe, while a different state happened to render normally.

Rule: Give indispensable action buttons `minimumHeight >= sizeHint().height()` and a vertically `Fixed` size policy when neighbouring wrapped or expanding content may absorb the height budget. Do not treat a later state or a settled unit-test construction as proof that every captured layout state is legible.

Verification: Exercise the narrow production container with multiline text, assert the button's minimum/actual height against its font and size hint, and inspect the final Cocoa screenshot rather than accepting a clipped intermediate frame.
