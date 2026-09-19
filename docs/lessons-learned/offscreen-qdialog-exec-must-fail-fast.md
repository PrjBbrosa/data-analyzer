---
id: offscreen-qdialog-exec-must-fail-fast
status: active
owners: [codex]
keywords: [pytest, pyqt, qdialog, exec, modal, hang, offscreen]
paths:
  - tests/ui/conftest.py
  - tests/ui/test_modal_exec_guard.py
  - tests/ui/test_smart_default_weighting.py
checks:
  - tests/ui/conftest.py autouse _fail_fast_unstubbed_modal_exec
  - do not pytest whole tests/ui/test_chart_stack.py or 12k-test T8 in one process to "see if it finishes"
tests:
  - tests/ui/test_modal_exec_guard.py::test_unstubbed_qdialog_exec_fails_instead_of_hanging
  - tests/ui/test_smart_default_weighting.py::test_audio_source_builtin_presets_keep_a_weighting_across_all_sections
---

# Offscreen QDialog.exec Must Fail Fast

Trigger: Combined UI pytest, `QDialog.exec_()`, preset load, confirmation boxes, or a session that appears stuck at a progress percentage.

Past failure: T8 `--ignore=tests/acquisition_ui` sat 2h26m at 0% CPU in `QDialog.exec_()` (`PresetBar._confirm_axis_preservation`) on `test_audio_source_builtin_presets_keep_a_weighting_across_all_sections`. The `-q` bar said 77% only because 9217/11923 tests had finished. A different hang (T3 whole `test_chart_stack.py`) also printed 77% while spinning in `setStyleSheet`.

Rule: `tests/ui/conftest.py` times out unstubbed `QDialog.exec_()` in 800ms and raises. Tests that only care about another field (weighting) must stub `_confirm_axis_preservation`, not rely on the dialog never appearing. Verify named tests, never one 12k-test process.

Verification: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_modal_exec_guard.py tests/ui/test_smart_default_weighting.py -q`
