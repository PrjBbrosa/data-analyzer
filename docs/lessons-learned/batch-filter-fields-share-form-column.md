---
id: batch-filter-fields-share-form-column
status: active
owners: [codex]
keywords: [pyqt, batch, filter, qformlayout, alignment, _fit_field, ExpandingFieldsGrow]
paths: [mf4_analyzer/ui/drawers/batch/filter_panel.py, mf4_analyzer/ui/inspector_sections/time_filter.py, mf4_analyzer/ui/inspector_sections/_helpers.py, tests/ui/test_batch_input_panel.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_batch_input_panel.py::test_batch_filter_editors_share_one_field_column]
tests: [tests/ui/test_batch_input_panel.py]
---

# Batch Filter Fields Share One Form Column

Trigger: Editing batch dialog form rows that wrap short combo/spin editors,
especially under `BatchFilterPanel` or another card that mirrors the
time-domain filter layout.

Past failure: `BatchFilterPanel` wrapped editors with a local `_field()` helper
that capped `maximumWidth` and appended stretch after the control, while the
form kept macOS `FieldsStayAtSizeHint`. 类型 / 截止 / 阶数 then parked at
different sizeHints and looked jagged next to the time-domain `FilterPanel`.

Rule: Reuse `_fit_field` / `_pair_field` and set
`QFormLayout.ExpandingFieldsGrow` so every editor fills one shared field
column. Do not reintroduce a left-aligned max-width host for these rows.

Verification: Run
`tests/ui/test_batch_input_panel.py::test_batch_filter_editors_share_one_field_column`
and keep it green with the time-domain twin
`tests/ui/test_time_filter_panel.py::test_filter_editors_share_one_field_column`.
