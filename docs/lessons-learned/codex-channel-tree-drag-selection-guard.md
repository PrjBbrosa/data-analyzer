---
id: codex-channel-tree-drag-selection-guard
status: active
owners: [codex]
keywords: [PyQt5, QTreeWidget, channel-tree, selection, drag, mouseMoveEvent, Ctrl, Shift]
paths: [mf4_analyzer/ui/widgets/__init__.py, tests/ui/test_channel_widget.py, mf4_analyzer/ui/quickref.py]
checks: [git diff --check]
tests:
  - .venv\\Scripts\\python.exe -m pytest -q tests/ui/test_channel_widget.py tests/ui/test_file_navigator.py tests/ui/test_quickref.py tests/ui/test_quickref_panel.py
---

# Channel Tree Drag Selection Guard

Trigger: Changing channel-tree selection modes or mouse press, move, release,
or double-click handling.

Past failure: In `ExtendedSelection` mode, dragging the left mouse button over
adjacent channel rows silently extended the blue selection. The gesture was
easy to trigger accidentally and was poorly suited to the normal
non-adjacent-channel workflow.

Rule: Suppress left-button move events before `QTreeWidget` enters
drag-selection state, while retaining plain-click selection and Qt's
`Ctrl+click` / `Shift+click` semantics. Keep the checkbox press/release and
double-click handling intact; checkbox state and blue batch selection remain
separate states.

Verification: Add or retain a real left-button drag test that asserts the
selection stays on its initial channel; run the focused channel-tree,
navigator, and quick-reference tests plus `git diff --check`.
