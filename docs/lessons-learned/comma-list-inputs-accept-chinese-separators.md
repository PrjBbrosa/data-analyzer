---
id: comma-list-inputs-accept-chinese-separators
status: active
owners: [codex]
keywords: [comma, chinese, fullwidth, separator, slice, time-range, list_text, IME]
paths: [mf4_analyzer/list_text.py, mf4_analyzer/ui/drawers/batch/slice_panel.py, mf4_analyzer/ui/drawers/batch/input_panel.py, mf4_analyzer/ui/drawers/batch/analysis_panel.py, mf4_analyzer/ui/db_reference_dialog.py, mf4_analyzer/acquisition_capture/__main__.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_list_text.py tests/ui/test_batch_slice_panel.py::test_slice_panel_accepts_chinese_and_mixed_separators]
tests: [tests/test_list_text.py, tests/ui/test_batch_slice_panel.py, tests/ui/test_batch_input_panel.py]
---

# Comma List Inputs Accept Chinese Separators

Trigger: Adding or editing a user-typed comma-separated field (slice
positions, time/source ranges, alias lists, CLI name lists).

Past failure: Batch slice positions only split on ASCII ``,``. Chinese IME
``，`` made ``5，10，20`` fail preflight even though the hint used Chinese
punctuation.

Rule: Route every such parser through ``mf4_analyzer.list_text.split_list_text``
so ASCII/Chinese commas and semicolons are accepted. Keep stored params /
formatted rewrites on ASCII separators. Update nearby hint copy to say
中英文逗号均可 when the field is user-facing.

Verification: Run ``tests/test_list_text.py`` and the Chinese-separator cases
in ``tests/ui/test_batch_slice_panel.py`` / ``tests/ui/test_batch_input_panel.py``.
