---
id: codex-help-screenshot-generator-follows-analysis-service
status: active
owners: [codex]
keywords: [help, screenshots, analysis-jobs, analysis-views, MainWindow, documentation]
paths: [tools/gen_help_screenshots.py, mf4_analyzer/help, mf4_analyzer/ui/analysis_jobs.py]
checks: ["rg -n '_attach_files_to_active_context|mark_saved|is_busy' tools/gen_help_screenshots.py"]
tests: [tests/test_gen_help_screenshots.py]
---

# Help Screenshot Generator Must Follow The Current Analysis Service

Trigger: Regenerating application-help screenshots after analysis
orchestration, View source ownership, dirty-session handling, completion
callbacks, or `MainWindow` analysis methods have changed.

Past failure: The real-render generator first depended on removed
`MainWindow._on_fft_time_finished` and `_on_order_finished` callbacks. After
moving to `AnalysisJobService`, it still assumed every analysis selector saw
the Time View's files and that `win.close()` was non-interactive. The current
app instead gives each analysis View its own initially empty file scope, and
loading demo data marks the throwaway session dirty. That produced empty
FFT-vs-Time captures and a hidden unsaved-project modal after successful PNG
generation.

Rule: Drive the real public analysis entry points. Attach the loaded demo files
through the active analysis View's production attach path before selecting
signals. Wait until the section is neither running nor busy *and* the target
canvas reports a rendered result; surface the service's `failed` signal and
fail clearly when a required selector entry is absent. Isolate QSettings, then
mark only the throwaway screenshot session clean before closing so the normal
product dirty guard remains untouched.

Verification: Run
`TMPDIR=/tmp PYTHONPATH=. .venv/bin/python tools/gen_help_screenshots.py --only <mode> --promote`
for `time`, `fft`, `fft_time`, `order`, and `imports` on the real Qt platform;
inspect each PNG and its guide overlay in a browser. Also run
`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_gen_help_screenshots.py tests/test_help_content.py`.
