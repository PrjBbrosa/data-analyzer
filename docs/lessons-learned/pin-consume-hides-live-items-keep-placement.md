---
id: pin-consume-hides-live-items-keep-placement
status: active
owners: [codex]
keywords: [pinned-cursor, consume-live, cursor-visible, InfiniteLine]
paths:
  - mf4_analyzer/ui/chart_stack/stack.py
  - mf4_analyzer/ui/pg_canvas/cursor.py
  - mf4_analyzer/ui/pg_canvas/canvas.py
checks:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pinned_cursor_panels.py::test_live_consumed_after_single_pin_returns_on_next_move tests/ui/test_pinned_cursor_panels.py::test_subplot_pin_hides_live_lines_keeps_overlay_pins tests/ui/test_pinned_cursor_panels.py::test_dual_pin_hides_live_and_keeps_placement tests/ui/test_pg_canvas_backref_invariants.py -q
tests:
  - tests/ui/test_pinned_cursor_panels.py::test_live_consumed_after_single_pin_returns_on_next_move
  - tests/ui/test_pinned_cursor_panels.py::test_subplot_pin_hides_live_lines_keeps_overlay_pins
  - tests/ui/test_pinned_cursor_panels.py::test_dual_pin_hides_live_and_keeps_placement
---

# Pin Consume Hides Live Items And Keeps Placement

Trigger: Changing live-cursor consume after a successful Pin, `consume_live_cursor_pill`, or `_cursor_visible` / live InfiniteLine visibility.

Past failure: `_consume_live` only dropped pill canvas state. `_cursor_line_items` (and dual A/B + hover dotted lines) stayed `visible=True` with `_cursor_visible` still True. After P, Pin overlay added lines at the same X so it looked like one line; axis-dragging the Pin left the leftover live line parked at the old X. Cocoa 2026-09-20, `.state/2026-09-20-progress-pin-audit/R0-PKEY-DRAG-VERDICT.md`. Drag-path dashed ghosts remain UNKNOWN and are not this lesson.

Rule: After a successful pin, hide live `_cursor_line_items` / `_cursor_a_items` / `_cursor_b_items` and dual extrema via `hide_live_cursor_items`. Do not call `set_cursor_visible(False)`: that blocks `_handle_cursor_mouse_move` and breaks “next pen move restores live”. Do not clear A/B placement, do not emit empty `cursor_info`, and do not let `set_collection` consume live.

Verification: Panels tests hover then P, assert overlay Pin lines exist, live items `isVisible() is False`, `_cursor_visible` stays True, rows emit restores the pill, and the next move can show live lines again.
