---
id: codex-status-hint-button-geometry
status: active
owners: [codex]
keywords: [pyqt, qss, statusbar, hint-bar, quickref, qtoolbutton, clipped, showMessage, inspector-help, toast, surfacestatusbar]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/chart_stack/stack.py
  - mf4_analyzer/ui/chart_stack/cards.py
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/main_window/_order_mixin.py
  - mf4_analyzer/ui/main_window/_frf_mixin.py
  - mf4_analyzer/ui/main_window/_fft_time_mixin.py
  - mf4_analyzer/ui/compute_progress.py
  - mf4_analyzer/ui/inspector.py
  - tests/ui/test_main_window_smoke.py
  - tests/ui/test_compute_progress.py
checks:
  - inspect the rendered QToolButton geometry after style.qss is applied
  - QStatusBar.showMessage must not paint left of the QuickRef '?'
  - Inspector 「使用说明」 must sit inside the help button and the card radius
  - rg -n "def showMessage" mf4_analyzer/ui/main_window/window.py — SurfaceStatusBar
    must keep calling super().showMessage("", 0) unconditionally (it never paints);
    any new error/failure-path call site added near a statusBar.showMessage(...)
    call must be paired with self.toast(msg, "error"/"warning"), not rely on the
    status bar alone
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_status_hint_quickref_button_stays_inside_bar_under_qss tests/ui/test_compute_progress.py::test_status_bar_single_file_can_label_is_fully_visible_under_qss -q
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_order_job_failed_routes_to_toast_and_status_bar tests/ui/test_main_window_smoke.py::test_frf_failed_routes_to_toast_and_status_bar tests/ui/test_main_window_smoke.py::test_fft_time_failed_routes_to_toast_and_status_bar -q
---

# Status Chrome Must Keep Glyphs Inside Rounded Hosts

Trigger: Changing the bottom status-line hint bar, the quickref `?` button,
QSS dimensions for compact status/inspector chrome, compute-progress labels,
or Inspector's `? 使用说明` link.

Past failure: QSS tokens looked fine while three glyphs still clipped or
leaked: the QuickRef `?` was shaved by the 32px pill; `QStatusBar.showMessage`
painted crushed copy (`1%`) in the native left gutter beside `?`; a
contents-rect mask on `#computeProgressLabel` shaved 1px off `%`; and an
empty-text `QPushButton` ignored its child-label layout so 「说明」 ran into
Inspector's 7px corner.

Rule: Load `style.qss` and assert rendered geometry, not tokens. Do not let
the native status-bar message painter occupy the left gutter once the hint
bar is docked (`currentMessage()` can stay for callers). A progress-label
mask may clip in X but must leave vertical slack for glyph descent.
`QPushButton` sizeHint must include the inner layout when the button text is
empty, and the help link must clear the card radius.

Verification: Run the status-hint geometry regression and the compute-progress
full-label test before claiming the visual fix.

## Addendum (2026-08-15, P1-5): `SurfaceStatusBar.showMessage()` is a pure
logic API now — route user-visible feedback through `toast()`

58fee980 finished what this lesson's "Rule" above only asked for half of:
`SurfaceStatusBar.showMessage()` (`ui/main_window/window.py`) now
unconditionally calls `super().showMessage("", 0)` and stores the real text
only in `_logical_message` / `currentMessage()`. It **never paints
anything**, by design — not "still clipped", not "still crushed": zero dark
pixels, confirmed by the panel's own render-parity assertion. That is the
correct fix for the crushed-copy failure above, but it means every one of the
50+ `self.statusBar.showMessage(...)` call sites across `ui/main_window/*.py`
is now, on its own, invisible to the user.

2026-08-15 post-v8 review (P1-5) audited all of them (see
`docs/analyzer/plans/2026-08-15-post-v8-batch-fixes-plan.md` appendix). The
finding: every error/failure-class call site already routes through
`self.toast(msg, "warning"/"error")` right next to the `statusBar.showMessage`
line (`_on_order_job_failed`, `_on_frf_failed`, `_on_fft_time_failed`,
`_warn_if_order_speed_unsuitable`, `_warn_action_blocked`, the project-open
render-restore-failed path, …) — no NEW toast calls were needed. The
remaining call sites are genuinely informational (progress ticks, ready-state
hints, success confirmations already toasted separately, user-driven-cancel
notices) and correctly keep `statusBar.showMessage` as their only channel
per this lesson's original "Rule" (`currentMessage()` stays for callers that
want the logical text, e.g. tests).

Rule (addendum): `statusBar.showMessage(...)` is a **pure logic API** —
useful for `currentMessage()`-reading tests and for callers that want a
non-visual record of "what happened last", but it is not a user-visible
notification channel. Any **new** error/failure-class message must pair a
`self.toast(msg, "warning")` / `self.toast(msg, "error")` call alongside it
(see the three regression-guard tests below); do not assume `statusBar.
showMessage` alone will reach the user, and do not "fix" this by trying to
make `SurfaceStatusBar` paint again (that reopens the crushed-copy failure
this lesson exists to prevent). Informational-only messages may keep
`statusBar.showMessage` as their sole channel.

