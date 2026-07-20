---
id: codex-qt-tree-itemchanged-column-guard
status: active
owners: [codex]
keywords: [PyQt5, QTreeWidget, itemChanged, checkbox, hover-icon]
paths: [mf4_analyzer/ui/widgets/]
checks: ["checkbox itemChanged handlers reject col != 0"]
tests: [tests/ui/test_file_navigator.py]
---

# Guard QTreeWidget Checkbox Handlers By Column

Trigger: Editing icons, tooltips, colors, or other item data in a
`QTreeWidget` whose `itemChanged` handler also owns checkbox behavior.

Past failure: Painting a detach icon into column 2 for a hovered file parent
emitted `itemChanged`. The handler treated that display-only update as a
column-0 checkbox edit and recursively cleared checked channel children.

Rule: Checkbox membership handlers must return immediately for every column
except the actual checkbox column, and display-only item writes should retain
the existing re-entrancy guard.

Verification: Exercise the hover/icon path while asserting no
`channels_changed` signal and no checked-channel mutation; run
`pytest tests/ui/test_file_navigator.py -q`.
