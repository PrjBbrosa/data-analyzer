---
id: qt-full-ui-stylesheet-gate-must-finish
status: active
owners: [codex]
keywords: [qt, pytest, ui, stylesheet, gate, timeout]
paths:
  - tests/ui/
  - mf4_analyzer/ui_kit/style.qss
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q -p no:randomly tests/ui
tests: []
---

# Full Qt UI Gate Must Finish Before It Is Evidence

Trigger: A change requires the complete `tests/ui` stability gate, especially
after a test applies the production application stylesheet.

Past failure: On 2026-08-02 the full offscreen UI suite reached roughly 10%
then stayed CPU-bound for five minutes in `QApplication.setStyleSheet()` Qt
style recursion.  Focused Batch tests were green, but the required full-suite
gate had not completed and therefore could not support a stability claim.

Rule: Run the full UI suite in a separately observable process with captured
output and a bounded diagnostic policy.  Record an exit code and final pass or
failure count.  If it stalls or is terminated, record the exact progress and
native sample/stack evidence; never summarize the partial dot output as PASS
or substitute focused UI tests for the full-suite gate.

Verification: Confirm the command exits normally and its captured log ends
with the pytest summary.  For a stall, record the PID, elapsed time, progress,
and a `sample <pid>` result before terminating only the self-started test
process.
