---
role: pyqt-ui
tags: [qmessagebox, offscreen, modal, testing, headless, qt-platform]
created: 2026-05-19
updated: 2026-05-19
cause: rework
supersedes: []
---

# QMessageBox.warning static call hangs offscreen tests; use .open() + WindowModal

## Context

Implementing T2-2 (A2L pick failure raises an operator-visible warning), I used the static `QMessageBox.warning(self, title, body)` convenience form. Existing UI tests that fed `apply_a2l_path` an empty fixture file — previously a silent-failure path — now triggered the warning, and `pytest` froze indefinitely with no failure output. Killed three background runs before tracing it to the modal `exec()` underneath the static helper.

## Lesson

`QMessageBox.warning(...)`, `.information(...)`, `.critical(...)` (the static class methods) call `exec()` internally and block until a button is clicked. Under `QT_QPA_PLATFORM=offscreen` there is no user to click, so the call never returns — the entire test process hangs (not a timeout, not a test failure, just a deadlock). The companion lesson `modal-from-qthread-finished-segfaults-offscreen` covers a related shape (segfault from QThread); this one is the silent hang from the main thread.

The fix is to drive an instance manually and call `.open()` (non-blocking) instead of `.exec()`. Pair with `setWindowModality(Qt.WindowModal)` to keep the operator-must-acknowledge semantics, and hold a Python reference to the box so it isn't GC'd before the user dismisses it:

```python
box = QMessageBox(self)
box.setIcon(QMessageBox.Warning)
box.setWindowTitle("A2L 加载警告")
box.setText(message)
box.setWindowModality(Qt.WindowModal)
self._a2l_warning_box = box  # keep alive
box.open()
```

This survives offscreen tests because `.open()` returns immediately; production gives operators a modal that blocks the cockpit window but not the event loop.

## How to apply

When adding ANY user-attention dialog to a widget that has a headless test (cockpit, settings dialog, review modal): never use `QMessageBox.warning/information/critical` static methods. Always: construct a `QMessageBox(self)` instance, call `setWindowModality(Qt.WindowModal)`, store the reference on `self._<purpose>_box`, then `.open()`. Provide a `_warn_*` (or similar) wrapper method so tests can stub it via attribute assignment without rendering anything.
