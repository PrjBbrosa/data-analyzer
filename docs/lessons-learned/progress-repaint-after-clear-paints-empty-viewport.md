---
id: progress-repaint-after-clear-paints-empty-viewport
status: active
owners: [codex]
keywords: [timedomain, clear, progress, updatesEnabled, empty-frame, plot_mode]
paths:
  - mf4_analyzer/ui/pg_canvas/canvas.py
  - mf4_analyzer/ui/main_window/_view_mixin.py
  - mf4_analyzer/ui/main_window/window.py
  - tests/ui/test_timedomain_mode_switch_empty_frame.py
checks:
  - rg -n "suppress_display_updates|_canvas_display_update_scope" mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/main_window
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_timedomain_mode_switch_empty_frame.py -q
---

# Progress Repaint After Clear Paints An Empty Viewport

Trigger: Changing TimeDomain full rebuilds, `canvas.clear()`, `_update_compute_progress(process_events=True)`, or 分屏/叠加 mode switching through MainWindow.

Past failure: Mode change made selection-delta fail, so `plot_channels` cleared the scene. The next progress callback only `repaint()`ed the status bar, but Cocoa still painted the dirty viewport with `n_axes=0`. The first nonempty paint already had target axis heights; there was no second contraction. Independent `canvas.plot_channels` did not flash.

Rule: Own a nested-safe `setUpdatesEnabled` scope on the canvas. Enter before `plot_channels`/`clear` and leave after `settle_view_restore` on the View path; also wrap non-View full rebuilds that clear plus progress. Restore the original flag in `finally` without using `return` — a finally `return` swallows an exception raised in a nested inner scope. Do not use the suppress scope to measure tick text, do not change the selection-delta hot path, and do not treat `_settle_layout()` as proof that inner axes have converged.

Verification: `tests/ui/test_timedomain_mode_switch_empty_frame.py` goes through TimeCard mode buttons or `plot_time()` full rebuild, probes a layout-neutral `repaint()` from the progress callback, and forbids a visible `n_axes=0` frame. Offscreen proves the suppress contract, not Cocoa/TraceLab/Windows foreground flash.
