---
id: chart-statistics-ui-keep-param-wiring
status: active
owners: [codex]
keywords: [batch, chart-statistics, SegmentedChoice, UI-only, auto_range, params]
paths: [mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_chart_statistics.py]
---

# Chart Statistics UI Redesigns Keep Param Wiring

Trigger: Restyling Batch 图内统计 (SegmentedChoice, chips, field bars) or any
"UI-only" pass on ``ChartStatisticsPanel``.

Past failure: A layout redesign can be tempted to replace ``auto_range`` /
metric ``QCheckBox`` widgets or reshape ``get_params`` / ``apply_params``.
AnalysisPanel, sheet context wiring, and presets still depend on those owners.

Rule: Keep ``enabled``, ``auto_range``, ``maximum`` / ``minimum`` / ``mean``,
``x_min`` / ``x_max``, ``range_summary``, ``context``, ``changed``, and the
``chart_statistics`` param shape. Put SegmentedChoice behind a hidden combo that
mirrors ``auto_range``; style metrics with objectName, do not swap control types
used as state owners.

Verification: ``tests/ui/test_batch_chart_statistics.py`` (except unrelated
render-marker sizing) and assert SegmentedChoice click flips ``auto_range``.
