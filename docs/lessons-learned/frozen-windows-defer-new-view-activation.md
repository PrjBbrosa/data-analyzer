---
id: frozen-windows-defer-new-view-activation
status: active
owners: [codex]
keywords: [windows, pyinstaller, qt, pyqtgraph, view, event-loop]
paths: [mf4_analyzer/ui/view_state.py, mf4_analyzer/ui/main_window/view_activation.py, mf4_analyzer/ui/main_window/_view_mixin.py, mf4_analyzer/ui/main_window/_analysis_mixin.py]
checks: [git diff --check]
tests: [tests/ui/test_view_activation_timing.py, tests/ui/test_view_manager.py, tests/ui/test_view_switch_integration.py, tests/ui/test_analysis_multiview_integration.py]
---

# Frozen Windows Defers New View Activation

Trigger: Changing the path from a View-tab ``+`` click to canvas activation or
rebuild in a frozen Windows build.

Past failure: Adding a View in the packaged Windows app synchronously emitted
``active_changed`` during the button click, which rebuilt the pyqtgraph canvas
before the native pointer-release event completed and showed a transient window
surface. macOS did not reproduce the symptom.

Rule: Keep new-View state insertion synchronous, but on ``win32`` frozen
runtime defer the active transition by one Qt event-loop turn. Resolve the
queued target by stable ``view_id`` and apply inherited files only after that
View is active. Do not change direct manager callers or non-frozen platforms.

Verification: Run the focused View timing/manager/integration tests, then
``git diff --check``. Confirm the packaged Windows app can add Time and
analysis Views without a transient window in a foreground desktop session.
