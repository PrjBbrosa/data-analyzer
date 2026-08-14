---
id: idle-quality-follows-local-canvas-activity
status: active
owners: [codex]
keywords: [pyqtgraph, idle-quality, mouseButtons, QTimer, antialias]
paths:
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - mf4_analyzer/ui/pg_canvas/quality.py
  - tests/ui/test_pg_line_canvas.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - rg -n "QApplication.mouseButtons" mf4_analyzer/ui/pg_canvas/line_canvas.py
  - rg -n "QApplication.mouseButtons" mf4_analyzer/ui/pg_canvas/quality.py — every
    hit must be the injectable default-provider assignment or its defensive probe,
    never a `!= Qt.NoButton` (or similar) gate on `_idle_quality_allowed` /
    `try_enable_idle_quality`
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_idle_quality_completes_despite_foreign_global_mouse_press tests/ui/test_pg_line_canvas.py::test_idle_quality_pending_on_local_press_recovers_on_release tests/ui/test_pg_line_canvas.py::test_idle_quality_provider_exception_is_logged_timer_errors_propagate -q
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k idle -q
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

## Addendum (2026-08-15, P1-6): transplanted into `QualityManager`
(time-domain canvas)

This lesson's own frontmatter warned "or a sibling canvas" and it stayed
true: 40c3e038 fixed `line_canvas.py` (the FFT canvas) but left
`ui/pg_canvas/quality.py`'s `QualityManager` — the time-domain canvas'
idle-AA gate — on the exact same anti-pattern: `_idle_quality_allowed()`
gated unconditionally on `QApplication.mouseButtons() != Qt.NoButton`, and
`try_enable_idle_quality()` (the timer's own timeout slot) just `return`ed
with the timer left stopped when the gate blocked — no re-arm, so recovery
silently waited for an unrelated canvas event once a foreign press aged out.

The port (2026-08-15 post-v8 review, P1-6) does not literally reuse
`_IdleQualityActivity` — `QualityManager`'s host canvas already tracks its
own local "busy" state for an unrelated reason (`_interaction_depth`,
incremented/decremented by `_begin_view_interaction` / `_end_view_interaction`
around every ViewBox drag) plus `_overlay_axes.dragging` for the overlay
Y-drag. `_idle_quality_locally_busy()` reads those two as the primary judge
instead — same shape as `is_busy()`, sourced from state the canvas already
owned rather than a new tracker class. `QApplication.mouseButtons()` is kept
only as `_probe_idle_mouse_buttons_provider()`: an injectable
(`_mouse_buttons_provider`), defensively-queried, non-gating call whose sole
job is to keep a raising provider observable (`logger.warning(...,
exc_info=True)`), mirroring `_query_idle_mouse_buttons` in spirit. And
`try_enable_idle_quality()` now calls `schedule_idle_quality()` (re-arming
the timer) when the gate is blocked specifically because
`_idle_quality_locally_busy()` is true, instead of a bare `return` — the
P1-6 fix for the "hit the gate, give up silently" half of the bug.

Rule (addendum): the "own press/move/release/drag, `mouseButtons()` is
defensive-only" rule above is NOT scoped to `line_canvas.py` — it applies to
every idle-AA gate in `ui/pg_canvas/`. `QualityManager` is the other one
today (used only by the time-domain canvas, `canvas.py:603`); if a third
idle-AA implementation appears, this lesson applies to it too. A blocked
idle-quality check must re-arm when the block reason is THIS canvas' own
transient activity, not disappear until an unrelated event happens to touch
the canvas again.
