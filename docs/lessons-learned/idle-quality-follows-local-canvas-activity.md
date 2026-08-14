---
id: idle-quality-follows-local-canvas-activity
status: active
owners: [codex]
keywords: [pyqtgraph, idle-quality, mouseButtons, QTimer, antialias]
paths:
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - tests/ui/test_pg_line_canvas.py
checks:
  - rg -n "QApplication.mouseButtons" mf4_analyzer/ui/pg_canvas/line_canvas.py
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_idle_quality_completes_despite_foreign_global_mouse_press tests/ui/test_pg_line_canvas.py::test_idle_quality_pending_on_local_press_recovers_on_release tests/ui/test_pg_line_canvas.py::test_idle_quality_provider_exception_is_logged_timer_errors_propagate -q
---

# Idle Quality Follows Local Canvas Activity

Trigger: Changing pyqtgraph idle-AA / idle-quality timers, especially any
`QApplication.mouseButtons()` gate on `PgLineCanvas` or a sibling canvas.

Past failure: `_enable_idle_quality` re-armed forever while any global mouse
button was down, so a press in another window left THIS canvas pending. Tests
monkeypatched the live Qt query and flaked; `except Exception: pass` also
hid provider failures and timer `start()` bugs.

Rule: Own press/move/release, wheel, gesture, and kinetic activity on the
canvas. `mouseButtons()` may remain only as an injectable defensive provider
and must not be the sole idle blocker. Provider failures are logged;
timer programming errors are not swallowed. Stop the idle timer on
destroyed/clear and check `sip.isdeleted` before reuse.

Verification: The four local-activity tests in `tests/ui/test_pg_line_canvas.py`
must pass without depending on the machine's live mouse, and the foreign-press
node must survive a 20-repeat.
