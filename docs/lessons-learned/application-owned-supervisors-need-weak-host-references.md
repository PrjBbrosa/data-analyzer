---
id: application-owned-supervisors-need-weak-host-references
status: active
owners: [codex]
keywords: [Qt, lifetime, supervisor, weakref, QApplication, import]
paths: [mf4_analyzer/ui/main_window/import_coordinator.py, mf4_analyzer/acquisition_ui/replay_tab.py, mf4_analyzer/ui/drawers/batch/sheet.py]
checks: []
tests: [tests/ui/test_import_coordinator.py, tests/ui/test_batch_dbc_parent_close_subprocess.py]
---

# Application-owned supervisors need weak host references

Trigger: A Qt task supervisor outlives its window or tab so a running QThread can finish safely.

Past failure: An application-owned import coordinator strongly referenced its host. Closing the host and shutting down the coordinator did not release either object: a 20-host probe retained all 20, while ordinary QWidget and weak-host controls retained none. Explicit deleteLater-only tests missed this ownership cycle. A separate last-window probe showed that application ownership also does not guarantee draining: an immediately cancelled BatchSheet import outlived an event-loop exit and left its worker orphaned.

Rule: Retain the supervisor for active worker teardown, but keep its host back-reference weak and reject a missing or deleted host. Stop timers, invalidate queued requests and discard late results on destruction. Do not repair product retention by sweeping widgets in test fixtures or removing application ownership needed by active threads. Preserve the dirty guard, then defer the last parent close until every owned import supervisor has drained; retain only a close intent, not a strong host callback. Normal event-loop exit and process exit code zero are not proof of child-process cleanup.

Verification: Test close plus normal GC without qtbot.addWidget or explicit deleteLater, both with and without shutdown. Also delete a host during a blocked task and verify the supervisor survives until cancellation drains, no result is published, and application child counts return to baseline. Exercise real QApplication shutdown in a disposable process and inspect the specifically owned child PID after exit, including cancel-then-immediate-close. Keep a red reproduction before the fix and run the affected lifecycle, Replay and BatchSheet tests.
