---
id: codex-wwt-ultraview-real-boundary-test
status: active
owners: [codex]
keywords: [WWT, UltraView, integration, monkeypatch, atomicity]
paths:
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - mf4_analyzer/ui/main_window/ultraview_workspace_controller.py
  - tests/ui/test_ultraview_native_layout.py
checks:
  - /usr/bin/python3 scripts/lessons/check.py --status
tests:
  - tests/ui/test_ultraview_native_layout.py
---

# Exercise The Real WWT To UltraView Boundary

Trigger: A WWT import change adds or modifies the projection from generated
TimeDomain Views into an UltraView Board.

Past failure: WWT flow tests replaced the real UltraView projection method
with a lambda. A misspelled coordinator attribute then reached foreground use,
and warning-bearing placement could mutate the Board without committing its
history, dirty state, and refresh.

Rule: Keep narrow WWT tests stubbed only when UltraView is unrelated, and keep
at least one owner-level integration test that calls the real projection seam.
Assert both atomic success and zero mutation on failure; warning-bearing
partial placement must still commit the complete Board transaction.

Verification: Run `tests/ui/test_ultraview_native_layout.py` and the WWT import
flow tests without replacing the real projection in the owner-level boundary
case.
