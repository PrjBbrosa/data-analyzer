---
id: pyqt-heatmap-slice-curve-aa-interaction-guard
status: active
owners: [codex]
keywords: [pyqtgraph, heatmap, slice, antialias, PlotDataItem, InfiniteLine]
paths:
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - tests/ui/test_pg_heatmap_canvas.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q
---

# Pyqt Heatmap Slice Curve AA Interaction Guard

Trigger: Touching `PgHeatmapCanvas` slice-curve rendering, slice marker
dragging, or heatmap ViewBox pan/wheel interaction quality.

Past failure: The FFT-vs-Time / Order slice row drew its 1D `PlotDataItem`
with `antialias=False`, so the current slice looked jagged at rest. A naive
fix can also be undone immediately because programmatic
`InfiniteLine.setValue(...)` inside `_apply_slice()` emits
`sigPositionChanged` and can masquerade as a user drag.

Rule: Apply slice AA to both the `PlotDataItem.opts` and the rendered child
`PlotCurveItem.opts`. A rebuild returns with AA off and an independent 0 ms
discrete timer armed; after that timer a cheap slice (ink inside the borrowed
spectrum band, not blacklisted) is AA-on again. Drop AA only for real
interactive movement, and restore it from the 150 ms `_slice_aa_idle_timer`
(`interval()` stays 150; never `start(0)` on that timer). Guard programmatic
`InfiniteLine.setValue` inside `_apply_slice` with `_slice_marker_updating`
so it cannot cancel the discrete settle or leave a resting cheap slice AA-off.

Verification: Cover rebuild AA-off with the discrete timer armed, cheap
settle AA-on, high-ink refusal, backstop blacklist, manual range/marker drag
AA-off, Ctrl/Shift wheel AA-off, and idle restoration in
`tests/ui/test_pg_heatmap_canvas.py`; run the heatmap canvas suite plus
`git diff --check`.
