---
id: binary-batch-combos-prefer-segmented-choice
status: active
owners: [codex]
keywords: [SegmentedChoice, binary, dropdown, slice, batch, two-option]
paths: [mf4_analyzer/ui/drawers/batch/slice_panel.py, mf4_analyzer/ui_kit/widgets/segmented_choice.py, tests/ui/test_batch_slice_panel.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_batch_slice_panel.py::test_slice_axis_uses_segmented_choice_not_dropdown]
tests: [tests/ui/test_batch_slice_panel.py]
---

# Binary Batch Combos Prefer SegmentedChoice

Trigger: Replacing or reviewing a product control that has exactly two fixed
options (especially in Batch cards).

Past failure: Slice dimension stayed a dropdown for width fear, while nearby
目标策略 / 幅值单位 already used ``SegmentedChoice``. Users still expected
one-click toggles for binary choices.

Rule: For a fixed two-option vocabulary, bind a hidden ``QComboBox`` to
``SegmentedChoice`` and keep the combo as the state API. Refresh button labels
via ``refresh_from_bound_combo`` when context renames an item. Do not leave a
visible dropdown solely because labels are Chinese four-character words.

Verification: ``tests/ui/test_batch_slice_panel.py::test_slice_axis_uses_segmented_choice_not_dropdown``.
