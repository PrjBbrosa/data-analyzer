---
id: codex-qt-checkbox-doubleclick-hit-region
status: active
owners: [codex]
keywords: [pyqt, qtreewidget, checkbox, double-click, mouse-event, tickbox]
paths: [mf4_analyzer/ui/widgets/__init__.py, tests/ui/test_channel_widget.py]
checks: [git diff --check]
tests:
  - .venv/Scripts/python.exe -m pytest tests/ui/test_channel_widget.py -q
---

# Qt Checkbox Doubleclick Hit Region

Trigger: Load when custom PyQt item-view checkbox hit handling is changed,
especially for QTreeWidget/QTreeWidgetItem rows.

Past failure: The channel tree widened checkbox hit handling only intercepted
MouseButtonPress. After selecting a channel row, a fast click on the checkbox
could arrive as MouseButtonDblClick, bypass the custom hit band, emit the tree
double-click behavior, and fail to toggle the tickbox.

Rule: Any custom checkbox hit region in a Qt item view must consume both left
press and left double-click events for that region, routing both through the
same setCheckState/itemChanged path.

Verification: Add or keep a QTest.mouseDClick regression that first selects the
row, then double-clicks inside the checkbox hit band, and asserts the checkbox
toggles while itemDoubleClicked is not emitted.
