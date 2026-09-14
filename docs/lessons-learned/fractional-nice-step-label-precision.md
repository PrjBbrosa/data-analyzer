---
id: fractional-nice-step-label-precision
status: active
owners: [codex]
keywords: [ticks, precision, nice-step, fractional, bounded]
paths: [mf4_analyzer/ui_kit/ticks_math.py, mf4_analyzer/qt_plot_helpers.py]
checks: [git diff --check]
tests: [tests/ui_kit/test_ticks_math.py, tests/ui/test_tick_label_precision.py, tests/ui/test_y_axis_label_length.py]
---

# Fractional Nice Steps Need Label Precision Independent Of Step Selection

Trigger: Formatting explicit 2.5-family ticks or changing common linear axis labels.

Past failure: The target tick chooser correctly placed 2.5-spaced grid lines but
pyqtgraph formatted them with zero decimals, producing 2, 5, 8, 10. Its six-digit
general format also collapsed 100000.2 and 100000.4 into 100000.

Rule: Preserve nice-step and grid positions. Keep accurate legacy strings; repair
inaccurate ladders using one precision within the existing significant-digit
budget. Preserve the residue cap instead of adding long floating-point tails.
Formatting compatibility tests must not require known inaccurate stock labels.

Verification: Assert unchanged production tick positions and parsed label values,
scaled fractional steps, phased ladders, large offsets, short residue labels and
log-axis bypass. Check real Cocoa drawn labels and narrow-window interaction.
