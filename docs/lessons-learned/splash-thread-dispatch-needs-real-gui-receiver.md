---
id: splash-thread-dispatch-needs-real-gui-receiver
status: active
owners: [codex]
keywords: [startup, splash, QTimer, threading, shutdown, IPC]
paths: [mf4_analyzer/startup_splash_child.py, mf4_analyzer/startup_feedback.py, mf4_analyzer/app.py]
checks: [git diff --check]
tests: [tests/test_startup_splash_child.py, tests/test_startup_splash_integration.py, tests/test_startup_feedback.py]
---

# Splash Thread Dispatch Needs A Real GUI Receiver

Trigger: Dispatching splash IPC state from a Python reader thread into Qt GUI callbacks, or changing splash-to-main-window handover.

Past failure: The reader called QTimer.singleShot with a plain Python session
method, without a GUI QObject receiver. A real source child painted but stayed
alive after finish; the parent terminated it at about 1.02 seconds. A separate
offscreen probe received finish while the view stayed open despite a running
GUI event loop. FakeSplash.show queued app.quit, so test cleanup could make the
widget look successfully closed without proving delivery of finish.

Rule: Route worker commands to a GUI-owned QObject using an explicit queued
connection or equivalent receiver-bound delivery. Only acknowledge invisibility
after the view hides. Distinguish hidden acknowledgement, normal process exit,
and forced reaping. A main-window first-paint callback is too late for a product
contract that requires splash disappearance before the main window appears.

Verification: Exercise the real reader, GUI event loop, view and child process.
Require finish-triggered hidden acknowledgement and natural exit zero, with no
test-initiated app.quit or reaper termination supplying success. A watchdog is
failure-only. Check thread identity, stage updates, EOF and late-child races.
Source offscreen checks do not prove Windows compositor visibility order;
record continuous native frames separately. See the 2026-09-23 sky-glass panels
and startup handover plan for the current evidence and pending implementation.
