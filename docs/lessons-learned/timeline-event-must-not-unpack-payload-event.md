---
id: timeline-event-must-not-unpack-payload-event
status: active
owners: [codex]
keywords: [startup, timing, measurement, event, kwargs]
paths:
  - tools/measure_windows_startup.py
checks:
  - git diff --check
tests:
  - tests/test_startup_timing.py
---

# Timeline Event Must Not Unpack Payload Event

Trigger: Recording an external message into a tool timeline by unpacking that message as keyword arguments.

Past failure: `note("splash_feedback_received", **feedback)` collided with `feedback["event"]`. The call either raised `TypeError` or stored `splash_painted` as the timeline event. A measurement-tool exception then looked like the application had crashed, and a splash-only run could not be distinguished from a finished main window.

Rule: Pass the foreign payload as a mapping. Set the timeline event name after copying payload fields, and keep the payload's own event under a separate field such as `feedback_event`. A tool exception must be reported as a measurement failure, not as a process crash.

Verification: `tests/test_startup_timing.py::test_timeline_row_keeps_tool_event_when_feedback_carries_event` and `test_measurement_tool_exception_is_not_reported_as_an_application_crash`.
