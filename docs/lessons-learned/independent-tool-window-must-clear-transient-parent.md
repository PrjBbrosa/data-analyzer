---
id: independent-tool-window-must-clear-transient-parent
status: active
owners: [codex]
keywords: [qt, qdialog, tool-window, transient-parent, z-order, ultraview, batch]
paths:
  - mf4_analyzer/ui/drawers/batch/_geometry.py
  - mf4_analyzer/ui/drawers/ultraview/sheet.py
  - mf4_analyzer/ui/drawers/batch/sheet.py
checks:
  - after show(), windowHandle().transientParent() is None
  - QPushButton in the tool window is not autoDefault/default
tests:
  - tests/ui/test_ultraview_mode_integration.py
  - tests/ui/test_batch_compact_contract.py
---

# Independent Tool Window Must Clear Transient Parent

Trigger: Adding or changing a non-modal QDialog tool window parented to MainWindow
(Batch, UltraView, or a new sibling panel).

Past failure: UltraView was a QDialog with parent=MainWindow and Qt.Window flags.
The QWidget parent kept a native transient-for link, so every click inside 总览
activated and raised the Analyzer over the Board. QDialog also made the first
QPushButton the default button, so Return could accept/close the tool window.

Rule: Independent tool windows must go through
`configure_independent_tool_window` and `present_independent_tool_window`.
After `show()`, call `clear_tool_window_transient_parent` so the native window
is not transient-for the Analyzer. Do not poke Analyzer widgets (Inspector,
mode stack) from Board actions except the explicit "打开原 View" path. Swallow
QDialog's Return-as-accept, and turn off autoDefault/default on Board buttons.

Verification: `tests/ui/test_ultraview_mode_integration.py` asserts
`transientParent() is None` and that layout/add/Return leave the Board in the
tool window; `tests/ui/test_batch_compact_contract.py` covers BatchSheet.
