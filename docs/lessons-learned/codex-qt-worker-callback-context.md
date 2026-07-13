---
id: codex-qt-worker-callback-context
status: active
owners: [codex]
keywords: [qt, qthread, qobject, worker, sender, callback, lifecycle]
paths: [mf4_analyzer/ui/analysis_jobs.py, tests/ui/test_analysis_jobs.py]
checks: [rg -n "sender\(" mf4_analyzer/ui/analysis_jobs.py]
tests: [tests/ui/test_analysis_jobs.py]
---

# Qt Worker Callbacks Retain Run Context

Trigger: Changing worker completion/progress callbacks or QThread cleanup in
the shared analysis job service.

Past failure: A queued worker callback called ``QObject.sender()`` after the
worker's thread quit and deleted the sender. On macOS this caused a Bus error
during the analysis-job regression.

Rule: Bind the active-run context to a receiver QObject that lives on the
service thread. Do not reconstruct a worker run from ``QObject.sender()`` in
a delayed callback.

Verification: Run the focused analysis-job tests and confirm
``analysis_jobs.py`` contains no ``sender()`` call.
