---
id: deferred-section-entry-shares-render-gate
status: active
owners: [codex]
keywords: [section, deferred, timer, reentrancy, view]
paths: [mf4_analyzer/ui/main_window/window.py, mf4_analyzer/ui/main_window/_view_mixin.py]
checks: []
tests: [tests/ui/test_time_section_entry.py, tests/ui/test_view_switch_reentrancy.py]
---

# Deferred Section Entry Shares The Render Gate

Trigger: Scheduling a delayed Section replot or changing TimeRenderGate.

Past failure: Queued Section callbacks rendered after leaving time mode; even a mode/View guard allowed the callback to reenter another plot through its progress event pump.

Rule: Keep only the latest target, verify live View object identity and mode, and cancel on close. If the existing render gate is busy, retain the target and schedule once from the outer scope exit; never spin zero-ms retries or assume entering a depth scope prevents reentrancy.

Verification: `tests/ui/test_time_section_entry.py` covers rapid navigation, same-ID View replacement, close, exceptions and delivery inside an outer render scope. Run it with `tests/ui/test_view_switch_reentrancy.py`.
