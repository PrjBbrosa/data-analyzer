---
id: codex-help-screenshot-generator-follows-analysis-service
status: active
owners: [codex]
keywords: [help, screenshots, analysis-jobs, MainWindow, documentation]
paths: [tools/gen_help_screenshots.py, mf4_analyzer/help, mf4_analyzer/ui/analysis_jobs.py]
checks: ["rg -n '_on_fft_time_finished|_on_order_finished' tools/gen_help_screenshots.py"]
tests: [tests/test_gen_help_screenshots.py]
---

# Help Screenshot Generator Must Follow The Current Analysis Service

Trigger: Regenerating application-help screenshots after analysis orchestration,
completion callbacks, or `MainWindow` analysis methods have changed.

Past failure: The real-render screenshot generator still monkeypatched removed
`MainWindow._on_fft_time_finished` and `_on_order_finished` callbacks. It saved
the synchronous pages, then crashed before producing FFT-vs-Time and Order
evidence, even though the live app had moved to `AnalysisJobService`.

Rule: Drive the real public analysis entry points, wait on
`window._analysis_jobs.is_running(section)`, surface the service's `failed`
signal, and assert the target canvas has a rendered result. Isolate QSettings so
documentation capture cannot read or overwrite the operator's live presets.

Verification: Run
`TMPDIR=/tmp PYTHONPATH=. .venv/bin/python tools/gen_help_screenshots.py`, inspect
all staged PNGs on the real Qt platform, and run
`TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_gen_help_screenshots.py -q`.
