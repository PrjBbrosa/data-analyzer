---
id: pyqt-ui/2026-09-25-chart-options-restore-commits-opening-snapshot
status: active
owners: [codex]
keywords: [chart-options, restore, range, color-policy, dirty]
paths: [mf4_analyzer/ui/dialogs/chart_options.py, tests/ui/test_dialogs.py]
checks: []
tests: [tests/ui/test_dialogs.py]
---

# Chart Options Restore Commits The Opening Snapshot

Trigger: Changing ChartOptionsDialog reset, apply, axis range, or color-scale commit.

Past failure: Refilling the opening values cleared `_range_axes_edited` and
`_color_policy_dirty`. Title and grid came back on the next apply because they
diff `_committed`, but X/Y limits and the heatmap color policy returned early.
The chart stayed on the applied edit while the form showed the old numbers.

Rule: Footer 还原 commits the opening snapshot through the existing apply path
in the same click. Construction may only fill widgets. Do not clear the range
or color dirty marks and expect a later apply to infer the restore. An
unapplied draft reloads fields and does not write the chart.

Verification: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py::test_chart_options_restore_writes_applied_title_and_ranges tests/ui/test_dialogs.py::test_chart_options_restore_reverts_heatmap_scale_and_cmap tests/ui/test_dialogs.py::test_pg_chart_options_restore_flushes_x_and_leaves_the_other_axis -q`
