---
id: pyqt-ui/2026-08-14-compute-progress-elides-from-qss-chrome
status: active
owners: [codex]
keywords: [status bar, compute progress, elide, QSS, QProgressBar, font-weight]
paths:
  - mf4_analyzer/ui/compute_progress.py
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/test_compute_progress.py
checks:
  - rg -n "_TEXT_PAD|_bar_slot_width|_label_text_budget" mf4_analyzer/ui/compute_progress.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_compute_progress.py::test_status_bar_single_file_can_label_is_fully_visible_under_qss -q
---

# Compute Progress Elides From QSS Chrome Not Long Copy

Trigger: Changing `ComputeProgressWidget`, status-bar load/compute labels, or QSS for `#computeProgressLabel` / `#computeProgressBar`.

Past failure: Single-file 「加载 1/1 · 读取 CAN 帧 · 32%」elided to 「3…」with empty space before the bar. The string was the design-length copy. QSS `font-weight: 600` widened CJK, the bar's 1px border inflated the slot from 160 to 162, and elision subtracted `_TEXT_PAD` again after layout already reserved it, so the budget was 2px short.

Rule: Size the widget from full-label metrics plus the painted bar slot (including QSS border). Elide against the label `contentsRect`, never subtract `_TEXT_PAD` a second time, and prove the canonical CAN string under real `style.qss` in `SurfaceStatusBar`. Do not treat that truncation as "the status bar is too narrow for filenames" — filenames stay in `showMessage`.

Verification: `test_status_bar_single_file_can_label_is_fully_visible_under_qss`.
