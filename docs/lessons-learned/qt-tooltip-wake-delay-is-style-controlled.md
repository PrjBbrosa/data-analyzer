---
id: qt-tooltip-wake-delay-is-style-controlled
status: active
owners: [codex]
keywords: [PyQt5, tooltip, QStyle, latency, event-filter]
paths: [mf4_analyzer/ui_kit/glass_tooltip.py, tests/ui/test_glass_tooltip.py]
checks: ["TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_glass_tooltip.py -q"]
tests: [tests/ui/test_glass_tooltip.py]
---

# Set Ordinary Qt Tooltip Wake Delay Through The Application Style

Trigger: Changing the latency of ordinary QWidget tooltips in an app that
intercepts `QEvent.ToolTip`.

Past failure: The event filter only receives the tooltip event after Qt's style
has applied its wake delay. Showing a custom popup immediately in that filter
does not make first-hover latency consistent across native controls.

Rule: Set one app-wide `SH_ToolTip_WakeUpDelay` policy through the active style,
preserve other style hints and style identity, and leave explicitly timed hover
cards or panel peeks on their existing timers.

Verification: Assert the wake and fall-asleep hints and style identity in the
focused tooltip test; measure ordinary tooltips on macOS and Windows native Qt.
