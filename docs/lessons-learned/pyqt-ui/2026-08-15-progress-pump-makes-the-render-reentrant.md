---
id: pyqt-ui/2026-08-15-progress-pump-makes-the-render-reentrant
status: active
owners: [codex, claude]
keywords: [processevents, reentrancy, view-switch, time-domain, progress-bar, qtimer, viewstate, blank-chart, xlim]
paths:
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/main_window/_view_mixin.py
  - mf4_analyzer/ui/main_window/_state_holders.py
  - mf4_analyzer/ui/main_window/_fft_mixin.py
  - mf4_analyzer/ui/main_window/_project_io_mixin.py
checks:
  - rg -n "processEvents\(\)" mf4_analyzer/ui   # must return nothing: every pump passes ExcludeUserInputEvents
  - rg -n "_time_render_scope|_time_render_busy|TimeRenderGate" mf4_analyzer/ui/main_window
tests:
  - tests/ui/test_view_switch_reentrancy.py
evidence:
  - docs/analyzer/verify/2026-08-15-view-switch-reentrancy/README.md
---

# A Progress Pump Makes The Render Re-Entrant

Trigger: Adding or touching any `QApplication.processEvents` on a render/compute
path, the time-domain View switch pipeline (`_switch_view` /
`_apply_active_view` / `_render_view_to_canvas` / `_capture_focused_view`), or a
`QTimer.singleShot(0, ...)` that navigates to a View.

Past failure: `_begin_compute_progress` called a bare `QApplication.processEvents()`
so the status-bar bar would reach the screen before a long synchronous plot.
That pump delivers the user's NEXT View-tab click while the previous View is
still being projected, so `_switch_view` ran nested inside
`_render_view_to_canvas`. Two visible bugs, one cause:

* The nested `_capture_focused_view` had no re-entrancy guard, so it captured a
  screen that was a MIXTURE — navigator already projected to the incoming View,
  canvas still holding the outgoing frame — and wrote it into whichever View
  held the focus. Tab said View 2, content was View 3, and the next switch made
  the corruption permanent ("通道都换了").
* That same write dropped a 260 s file's zoom window (118–125 s) onto a View
  whose file is only 49.5 s long. `_render_view_to_canvas` restored the saved
  xlim verbatim, the viewport landed entirely outside the data, and the chart
  went blank. 绘图 could not recover it (the selection-delta replot never
  touches X); only 右键·全图 did.

Note what the pump does NOT protect: a `QTimer.singleShot(0, ...)` posted
earlier (UltraView `navigate_to_view`) is still delivered by
`processEvents(ExcludeUserInputEvents)`. Excluding input is necessary, not
sufficient.

Rule: (1) Never write a bare `processEvents()`; a pump whose only job is to
paint a widget passes `QEventLoop.ExcludeUserInputEvents` so queued clicks stay
queued and run in order. (2) A pipeline that pumps must declare itself
non-reentrant: wrap it in `ViewMixin._time_render_scope()` (backed by
`TimeRenderGate`), park a switch intent that still arrives by **view id** —
never by index, which a concurrent delete/reorder invalidates — and replay only
the newest one from a `singleShot(0)` after the outermost scope unwinds, never
inline (`_apply_active_view` renders two panes back to back). (3) Any capture
that reads live widgets is a no-op while a render is in flight; a capture must
only ever see a settled screen. (4) Restoring a persisted viewport is not
unconditional: run it through `_preserved_xlim_fits_data` and fall back to
`frame_x_to_data()` + `_flush_pending_refresh()`, so a window that no longer
frames its data reframes instead of rendering an empty chart. (5) A parked
intent must die with its window: the drain bails on `sip.isdeleted(self)` or a
window no longer visible, and `closeEvent` clears it. Otherwise the replayed
switch starts a render whose OWN pump lets the queued `deleteLater` through, and
the rest of that render touches destroyed children (`PillSwitch`,
`ComputeProgressWidget`, `QStackedWidget` — measured, not hypothetical).

Verification: `tests/ui/test_view_switch_reentrancy.py` — the pump-flags test
fails on a bare `processEvents()`; the interleave/last-wins tests drive a real
switch from inside the pump via a `QApplication` proxy and assert
active/focused/navigator/canvas agree and no ViewState absorbed another's
channels or window; the reframe test asserts an out-of-range View window paints
curves instead of a blank chart, and the zoom test asserts a legitimate zoom is
still restored verbatim.

Offscreen is not a visual acceptance here: the real-window A/B lives in
`docs/analyzer/verify/2026-08-15-view-switch-reentrancy/` (guard-off 0.217 % ink
/ 1 point per curve — the user's blank screenshot; guard-on 61.04 % ink / 1736
points), and its probe re-runs both sides in one process.
