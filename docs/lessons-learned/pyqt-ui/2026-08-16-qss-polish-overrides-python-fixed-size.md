---
id: pyqt-ui/2026-08-16-qss-polish-overrides-python-fixed-size
status: active
owners: [codex]
keywords: [QSS, polish, setFixedSize, min-width, content box, layoutThumb, RAIL_BUTTON_SIZE]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/chart_stack/ultraview/chrome.py
  - tests/ui_kit/test_qss_border_shorthand.py
checks:
  - rg -n "setFixedSize|setMinimumSize|min-width:|min-height:" mf4_analyzer/ui/chart_stack/ultraview/chrome.py mf4_analyzer/ui_kit/style.qss
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_chrome.py -q
---

# QSS Polish Overrides Python setFixedSize

Trigger: Pairing a Python `setFixedSize` / `setMinimumSize` with QSS `min-width` / `min-height` on the same UltraView control.

Past failure: Qt QSS `min-width`/`min-height` are the content box. `QStyleSheetStyle::polish` writes `content + padding + border` into `setMinimumSize()`, which overrides the Python fixed size. Rail icons, warning dots, and layout thumbs shrank or grew under production QSS even though unit tests that skipped app QSS stayed green.

Rule: Size the QSS content box so the polished outer box matches the Python design size (`content = outer − padding − 2×border`). Do not set `min-*: 0` to "reset" a widget that still inherits a generic `QToolButton { min-height: 22px }`. Measure after polish, not the Python call.

Verification: `tests/ui/test_ultraview_chrome.py`; inventory at `docs/analyzer/verify/2026-08-16-daily-followup/qss-python-size-inventory.md`.
