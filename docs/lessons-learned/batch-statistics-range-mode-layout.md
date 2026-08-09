---
id: batch-statistics-range-mode-layout
status: active
owners: [codex]
keywords: [batch, pyqt, qboxlayout, hidden-widget, statistics, range-mode, offscreen]
paths: [mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_chart_statistics.py, tests/ui/test_batch_smoke.py]
---

# Batch Range Modes Need Exclusive Layout Pages

Trigger: Adding a compact Batch setting that changes a one-line control group
between an automatic summary and manual numeric inputs.

Past failure: Hiding expanding spin boxes directly in a shared `QHBoxLayout`
left their layout allocation behind under Qt 5. The automatic “全范围” fact was
visually separated from its mode control even though the hidden widgets were
not interactive.

Rule: Put mutually exclusive automatic and manual range content in separate
pages of a `QStackedLayout` (or an equivalent exclusive container). Do not rely
on `setVisible(False)` alone to reclaim a shared horizontal layout's space.
The visible binary mode control may be a `SegmentedChoice`; keep `auto_range`
as the boolean state owner and expand manual spins *below* the segment when
the drawer is too narrow for an inline pair.

Verification: Show the panel under the shipped QSS in both modes; assert the
automatic summary page vs manual spin page exclusivity, SegmentedChoice sync
with `auto_range`, and both spin boxes use `QAbstractSpinBox.NoButtons`. Run
`tests/ui/test_batch_chart_statistics.py`, the Batch UI smoke suite, and
`git diff --check`.
