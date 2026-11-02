---
id: qt-canvas-callbacks-need-receiver-lifetime
status: active
owners: [codex]
keywords: [PyQt5, QObject, destroyed, partial, weakref, gc, pinned-cursor]
paths: [mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py]
checks: [git diff --check]
tests:
  - tests/ui/test_pinned_cursor_lifecycle.py::test_canvas_signals_disconnect_when_controller_is_destroyed
  - tests/ui/test_pinned_cursor_lifecycle.py::test_controller_canvas_gc_does_not_call_destroyed_receiver
  - tests/ui/test_pinned_cursor_lifecycle.py::test_canvas_receiver_cleanup_keeps_controller_alive
---

# Qt Canvas Callbacks Need Receiver Lifetime

Trigger: Connecting canvas signals to a QObject owner that can be destroyed first, especially with `partial(bound_method, key)` or during cyclic GC.

Past failure: Canvas callbacks retained a deleted PinnedCursorController. Creating host, controller, then canvas and collecting the cycle reproduced `_on_canvas_destroyed -> _drop_owner -> self._owners` raising `RuntimeError: wrapped C/C++ object ... has been deleted`. Explicit controller deletion also left external signal receivers connected. A receiver holding the controller strongly still allowed a callback after GC had cleared the controller's Python attributes.

Rule: Give external callbacks a QObject receiver parented to their owning controller, using decorated slots so Qt disconnects them when that lifetime ends. Keep the controller reference weak and check its Qt lifetime before dispatch, because cyclic GC can clear Python state before all destruction signals finish. Explicit unbind/close must retire the receiver. Do not replace ownership with broad exception swallowing or global widget sweeps.

Verification: Cover late destroyed/content-invalidated/chart-rebuilt signals, unbind/close/canvas-first cleanup, and fresh-process natural GC in both creation orders with parented and parentless canvases. The seven focused cases passed; a Cocoa subprocess with `PYTHONMALLOC=debug` collected all four combinations without callback errors and exited normally. This fixes the demonstrated destruction callback failure; it does not establish the cause of separate hover/pin assertion failures.
