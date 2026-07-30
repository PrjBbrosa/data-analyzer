---
id: codex-tick-label-truthfulness-before-compactness
status: active
owners: [codex]
keywords: [ticks, labels, formatting, truthfulness, scientific-notation, per-div]
paths:
  - mf4_analyzer/ui_kit/ticks_math.py
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
checks: [git diff --check]
tests:
  - tests/ui/test_overlay_grid_ticks.py
  - tests/ui/test_pg_line_canvas.py
---

# Tick Label Truthfulness Comes Before Compactness

Trigger: Changing tick formatting, explicit `AxisItem.setTicks()` labels, axis
gutter width policy, or scientific-notation precision.

Past failure: `_fmt_tick` formatted a zero-decimal integer and then blindly
called `rstrip("0")`, so `100`, `800`, `2000`, and `101330` displayed as smaller
numbers. Length and uniqueness tests stayed green because the corrupted strings
were short and could still differ. A fixed `%.2e` also missed a tick by 45.6% of
one division at `1.23456e-5 / 1e-7` and collapsed high-offset ladders.

Rule: For every explicit tick label, assert that `float(label)` is within a
stated fraction of the real tick value before asserting compactness. Strip
trailing zeros only when a decimal point exists. When `per_div` is known,
generate fixed and adaptive-scientific candidates, discard candidates outside
the error bound, and choose the shortest valid one. Truthfulness and
distinctness are universal; character caps belong only to named fixtures until
axis-offset notation exists.

Verification: Sweep the full nice-step ladder across phase offsets and small,
engineering, and high-offset magnitudes. Require <=1% division value error,
unique labels, and <=2% division parsed-gap error. Include direct significant-
zero cases and run the real overlay and PgLineCanvas label fixtures plus
`git diff --check`.
