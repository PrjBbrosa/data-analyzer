---
id: pyqt-ui/2026-08-16-tools-installing-app-qss-pollutes-test-session
status: active
owners: [codex]
keywords: [pytest, QSS, qApp, stylesheet, tools/verify_ultraview_visuals, tests/conftest.py]
paths:
  - tests/conftest.py
  - tests/test_verify_ultraview_visuals.py
  - tools/verify_ultraview_visuals.py
checks:
  - rg -n "setStyleSheet|load_stylesheet" tests/conftest.py tests/ui/conftest.py tools/verify_ultraview_visuals.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_verify_ultraview_visuals.py tests/ui/test_pill_switch.py tests/ui/test_ultraview_chrome.py tests/ui/test_chart_stack.py tests/ui/test_batch_output_panel.py -q
---

# Tools Installing App QSS Pollute The Test Session

Trigger: Importing or running a `tools/` visual harness inside pytest, or adding a test that calls `qApp.setStyleSheet` / `load_stylesheet` without restoring the previous sheet.

Past failure: `tools/verify_ultraview_visuals` installed the production app QSS on the shared `QApplication`. Later tests in the same process (pill geometry, ChartStack, batch sliders) read polished sizes and failed. Fixture isolation in `tests/ui/conftest.py` was not enough because the tool mutated the process-global stylesheet.

Rule: Snapshot and restore `qApp.styleSheet()` at the session/root conftest boundary. A tools module used by tests must not leave production QSS on the app. Do not add a test-only branch inside the tool to skip QSS; isolate at the test process instead.

Verification: The POLLUTE argument order in the daily-followup plan; `tests/conftest.py` stylesheet snapshot.
