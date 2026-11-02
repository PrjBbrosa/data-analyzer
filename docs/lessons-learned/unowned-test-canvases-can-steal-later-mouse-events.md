---
id: unowned-test-canvases-can-steal-later-mouse-events
status: active
owners: [codex]
keywords: [pytest, Qt, offscreen, hover, mouse, ownership, qtbot]
paths: [tests/ui/test_dialogs.py, tests/ui/test_pill_switch.py, tests/ui/test_pinned_cursor_panels.py]
checks: [git diff --check]
tests: [tests/ui/test_dialogs.py, tests/ui/test_pill_switch.py, tests/ui/test_pinned_cursor_panels.py]
---

# Unowned Test Canvases Can Steal Later Mouse Events

Trigger: Hover or pin tests pass alone but fail in a shared QApplication although widgetAt, active window, style, and mouse buttons look correct.

Past failure: A dialogs test left a shown 1200x800 canvas alive. Running that real predecessor before five later hover/pin tests reproduced their full-suite failures: widgetAt found the intended new widget, but native moves reached the old canvas. PillSwitch never entered hover; new cursor lines were never populated. Registering that canvas/dialog fixed the minimal sequence, but the complete owner still failed because five other tests also left shown widgets alive.

Rule: Give each created canvas and parentless dialog an explicit test owner, including every dialog created in loops. Fix the actual creator or an explicit helper contract; do not sweep all QApplication top levels, force hover state, weaken assertions, or assume correct widgetAt proves event delivery. After a minimal predecessor reproduces the issue, validate the full creating owner with its affected consumers to catch multiple creators.

Verification: Compare target hit tests with the actual event receiver and inspect survivors after normal fixture teardown. Run the dialogs, PillSwitch, and pinned-panel owner files together, then confirm the repaired sequence without diagnostic plugins. Keep focused evidence distinct from the complete suite result.
