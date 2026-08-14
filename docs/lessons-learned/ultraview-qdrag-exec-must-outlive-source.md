---
id: ultraview-qdrag-exec-must-outlive-source
status: active
owners: [codex]
keywords: [pyqt, qdrag, deleteLater, nested-event-loop, sip.isdeleted, qFatal]
paths: [mf4_analyzer/ui/chart_stack/ultraview/**, tests/ui/test_ultraview_page.py]
checks:
  - do not rebuild or deleteLater a QDrag source while exec_ is on the stack
  - parent QDrag to a stable host window, not the row/card being dragged
  - emit drag_finished only after sip.isdeleted check; swallow RuntimeError so it cannot escape a Qt virtual
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_page.py -q -k "drag_finishes or drop_clamps"
---

# QDrag.exec_ Must Outlive Its Source Widget

Trigger: Implementing or testing Qt drag-drop that rebuilds the library, grid,
tray, or any widget tree from a drop handler.

Past failure: UltraView drop handlers mutated Board state and rebuilt the
library/cards/tray inside `QDrag.exec_()`'s nested event loop. `deleteLater` of
the drag source, plus `QDrag(self)` parenting and `drag_finished.emit()` from a
dead wrapper, escaped a reimplemented virtual as `RuntimeError` and aborted via
PyQt5 `qFatal()`. Deferring the drop with `QTimer.singleShot(0, ...)` still
fires inside that nested loop and does not help.

Rule: Keep a drag-in-progress flag and skip widget rebuild until
`drag_finished`. Parent `QDrag` to `source.window()`, not the source. After
`exec_` returns, emit finished only if `sip.isdeleted(source)` is false, and
catch `RuntimeError` so it cannot leave a Qt virtual.

Verification: `test_library_rebuild_is_deferred_until_drag_finishes` and
`test_card_rebuild_is_deferred_until_drag_finishes` keep the source alive
across `set_board` / `set_library_rows` and only destroy it after
`_on_drag_finished`.
