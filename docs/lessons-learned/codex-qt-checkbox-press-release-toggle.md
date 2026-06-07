---
id: codex-qt-checkbox-press-release-toggle
status: active
owners: [codex]
keywords: [pyqt, qtreewidget, checkbox, mouse-release, item-view]
paths: [mf4_analyzer/ui/widgets/__init__.py, tests/ui/test_channel_widget.py]
checks: [git diff --check]
tests:
  - .venv/bin/python -m pytest tests/ui/test_channel_widget.py -q
---

# Qt Checkbox Press Release Toggle

Trigger: Changing custom PyQt item-view checkbox hit handling, especially
QTreeWidget/QTreeWidgetItem checkbox rows with widened hit regions.

Past failure: The channel tree toggled the check state during
mousePressEvent and returned without calling super(), but a real
QTest.mouseClick/user click still delivered mouseReleaseEvent. When the click
landed on the native checkbox indicator, Qt's default release handler toggled
the item back to unchecked, so a selected channel row could not be checked.

Rule: If custom checkbox hit handling toggles on press, it must also consume
the matching left-button release. Tests must use a full click sequence on the
checkbox center, not only a synthetic press event.

Verification: Run the channel widget tests and git whitespace check:
`.venv/bin/python -m pytest tests/ui/test_channel_widget.py -q` and
`git diff --check`.
