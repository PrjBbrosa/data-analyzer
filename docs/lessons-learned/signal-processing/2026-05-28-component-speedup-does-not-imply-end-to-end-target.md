---
role: signal-processing
tags: [perf, envelope, end-to-end, micro-bench, target, hot-path, pyqtgraph]
created: 2026-05-28
updated: 2026-05-28
cause: insight
supersedes: []
---

# A 76× component speedup did not move the end-to-end pan target

## Context
The pyqtgraph TimeDomain migration replaced `build_envelope` (numpy,
~1.8 ms/channel) with `positions_envelope` (asammdf C path,
~0.025 ms/channel) — a measured ~76× win confirmed live with
`c_path=True`. The whole migration's stated target was pan refresh
P50 ≤ 8 ms. Yet the end-to-end production pan P50 measured ≈ 10.7 ms —
at parity with the old matplotlib path, NOT under target.

## Lesson
A micro-bench win on one stage of a pipeline only moves the end-to-end
number if that stage was the dominant term. Here the envelope was ~0.12 ms
of a ~10.7 ms frame; the real per-frame cost had migrated to the
canvas's pure-Python `QPainterPath.moveTo/lineTo` loop over ~2×pixel_width
points × N channels (`pg_canvases.py:_build_painter_path`) plus a
per-channel `QPainter.drawPath` into a fresh `QPixmap`. Optimizing the
component you happened to instrument, while the adjacent
un-instrumented step dominates, produces "false performance
confidence" — exactly the design's R3 risk. The fix for the canvas was
to replace the interpreted per-point loop with a vectorized builder
(`pyqtgraph.functions.arrayToQPath`, numpy→QPainterPath in C), but the
diagnostic discipline is what matters: measure the END-TO-END target,
not just the stage you changed.

## How to apply
When a task's headline target is end-to-end latency, the perf test MUST
time the full target path (here: `set_xlim` → cache rebuild → path →
pixmap), not only the stage you optimized — and if the headline target
is missed, profile the remaining stages before claiming the win. A
component micro-bench (`positions_envelope` p50) is necessary but never
sufficient evidence for an end-to-end SLA. Report the real end-to-end
number even when the component number looks great.
