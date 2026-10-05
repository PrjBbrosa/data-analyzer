---
id: qt-test-input-state-survives-failed-widget-tests
status: active
owners: [codex]
keywords: [pytest, Qt, mouse, pin, teardown, isolation]
paths: [tests/ui/conftest.py, tests/ui/test_qt_input_isolation.py]
checks: [Preserve the original test failure while releasing synthetic mouse buttons at teardown.]
tests: [tests/ui/test_qt_input_isolation.py, tests/ui/test_qt_fixture_lifecycle.py]
---

# Qt Test Input State Survives Failed Widget Tests

Trigger: Hover or pin tests pass alone but fail later in a shared QApplication.

Past failure: A QTest mousePress followed by a failed assertion left QApplication.mouseButtons() pressed even after pytest-qt deleted the widget. A bounded two-item child reproduced the leak; injecting pressed input also broke later pin actions. This proves the mechanism, not every historical flaky failure's cause.

Rule: Pair local press/release with finally when possible. At the UI teardown boundary, release residual synthetic buttons on a private sink, never a surviving product widget. Preserve the original failure and existing Qt ownership/leak checks; do not fix this with sleeps or ordering.

Verification: The child deliberately fails before release. Before repair both child items fail; after repair exactly the original item fails and the following item sees Qt.NoButton. Existing teardown lifecycle and static-source tests must continue passing.
