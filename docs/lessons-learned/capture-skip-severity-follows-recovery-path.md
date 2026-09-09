---
id: capture-skip-severity-follows-recovery-path
status: active
owners: [codex]
keywords: [ultraview, capture, warning, unstable, digest-changed, throttling]
paths:
  - mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
  - tests/ui/test_ultraview_capture.py
checks: []
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_capture.py -q
---

# Capture Skip Severity Follows Recovery Path

Trigger: Reducing UltraView capture warning noise or explaining a skipped preview.

Past failure: Expected digest retries and an unstable outgoing canvas were both reported as WARNING, obscuring actual capture failures. The outgoing synchronous capture has no guaranteed retry after the canvas is rebound.

Rule: Classify the exact reason and outcome. A best-effort leaving-bound-canvas/unstable skip may be DEBUG, while unsupported hosts, unavailable digests and exhausted retries remain WARNING. Never grab unstable content merely to silence a log. Keep the last valid preview and describe its possible age honestly. If severity varies by reason, ensure throttling cannot let a DEBUG event consume the WARNING budget.

Verification: Exercise the public leave/rebind path: no unstable grab, no overwrite of the old preview, no new-view pixels published to the old ref, successful stable recapture, and preserved fault-level diagnostics. Do not infer live recovery from a log-level test.
