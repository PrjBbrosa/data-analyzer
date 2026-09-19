---
id: pinned-axis-label-release-and-outer-geometry
status: active
owners: [codex]
keywords: [pinned-cursor, axis-label, drag-release, QFontMetrics, geometry]
paths:
  - mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py
  - mf4_analyzer/ui/chart_stack/pinning/presentation.py
checks: [git diff --check]
tests:
  - tests/ui/test_pinned_cursor_geometry.py
  - tests/ui/test_pinned_cursor_interaction.py
---

# Pinned Axis Labels Must Commit Release And Share Outer Geometry

Trigger: Changing bottom pinned-cursor labels, their drag handling, or their
layout size.

Past failure: A quick press then release at a new X position had no intervening
`MouseMove`, so the label cancelled the pending edit and toggled its panel;
separately, layout measured bare text while the QFrame painted a larger caption
surface, allowing the border and hit target to disagree.

Rule: Treat a release past `QApplication.startDragDistance()` as a drag and
commit its final global coordinate exactly once. Use one outer-size helper for
the layout and QFrame: polished caption metrics, layout margins, and the painted
frame. Apply the solver size as-is; do not silently enlarge the widget afterwards
and do not add an unmeasured extra pixel as a cross-platform rule. Keep
panel-to-line tethers separate from label-avoidance leaders and persist neither
their target nor their graphics.

Verification: Run the focused pinned geometry and interaction tests with the
production style, including the overlay-metrics/hit-rect contract, and
`git diff --check`.
