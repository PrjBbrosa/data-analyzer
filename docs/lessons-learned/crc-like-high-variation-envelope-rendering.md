---
id: crc-like-high-variation-envelope-rendering
status: active
owners: [codex]
keywords: [pyqtgraph, envelope, antialias, raster, crc, performance]
paths:
  - mf4_analyzer/ui/pg_canvas/render_profile.py
  - mf4_analyzer/ui/pg_canvas/dense_raster.py
  - mf4_analyzer/ui/pg_canvas/renderer.py
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
  - mf4_analyzer/ui/pg_canvas/quality.py
  - mf4_analyzer/ui/pg_canvas/canvas.py
checks:
  - dense_discrete RenderProfile
  - high-raster-cost AA gate
  - interactive/settled buffer coverage
  - dense raster preserves PDI visibility and bounds
  - QPixmap and scene mutation stay on the GUI thread
tests:
  - tests/ui/test_high_variation_envelope.py
  - tests/ui/test_pg_dense_raster.py
  - tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA
  - tests/ui/test_timedomain_hotpath_perf.py
---

# CRC-like curves need raw profiling, an AA gate, and a cached smooth layer

Trigger: A modest-size CRC, rolling counter, byte-valued, or dense discrete
time-domain channel is slow to select, pan, or zoom, especially when the UI
reports that antialiasing is active.

Past failure: The renderer first treated the issue as envelope size and later
as repeated `setData()` work. Both mattered, but the dominant real-data cost
was Qt antialias rasterization: the supplied `EPS_CRC1` displayed only about
714 capped points and therefore passed the point-count AA gate, yet AA-on
repaint cost about 1.0 s versus about 2.2 ms with AA off. Classification from
the displayed envelope also changed between full and zoomed windows, while
evenly spaced bounded sampling could phase-alias a long modulo counter into an
apparently constant signal.

A first smooth-layer prototype then repeated the same mistake at a different
level: on a Retina display it rendered a 4x temporary QImage and called
`QImage.scaled(..., SmoothTransformation)` back to DPR2. Offscreen this looked
cheap, while a real Cocoa foreground run cost about 3.5 seconds. A cosmetic
pen wider than one device pixel also sent the full-height CRC polyline back
into a roughly 1.6-second stroker path.

Rule: Split measurement into raw profiling, envelope computation, `setData`,
and actual Qt paint with AA on and off. Classify dense-discrete geometry once
from raw samples using dispersed contiguous blocks; never calculate transition
statistics across sparse sampling gaps. Choose the bucket width before the
single envelope pass. A visible `dense_discrete` curve must hard-block both
idle AA and temporary export AA regardless of its capped displayed point
count; ordinary smooth low-density curves keep idle AA. During X interaction,
reuse buffered geometry, rate-limit coarse buffer refills, and settle only the
latest viewport. Preserve full raw arrays for cursor, statistics, analysis,
and export data.

If jagged native-AA-off output is not acceptable, do not re-enable native AA
or destroy geometry until it fits a point-count budget. Use a two-layer model:
the PDI remains visible and authoritative for data bounds, cursor, statistics,
and raw export, while a data-coordinate QGraphicsPixmapItem presents the
settled dense curve. Suppress only the PDI pen after the pixmap is ready and
restore its saved native pen on fallback. Render at `logical_size * max(2,
DPR)` with multiple offset one-device-pixel non-AA polylines; never use a
wider cosmetic pen or a DPR2 4x-to-2x smooth QImage scale. Transform the cached
pixmap during interaction and regenerate only after the quiet window. QPixmap,
QGraphicsPixmapItem, and scene changes stay on the GUI thread. The pixmap must
ignore bounds, accept no mouse buttons, include X/Y/DPR/color/source revision
in its key, and fail back to native-AA-off rendering under a hard byte budget.
In mixed subplots, exclude only ready raster-covered dense curves from native
AA accounting; ordinary curves may still enable idle/export AA. An uncovered
or failed dense curve keeps the hard scene-wide AA block.

Verification: Run
`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest
tests/ui/test_high_variation_envelope.py
tests/ui/test_pg_dense_raster.py
tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA
tests/ui/test_timedomain_hotpath_perf.py -q`. With the supplied real BLF/DBC,
confirm `EPS_CRC1` resolves to `dense_discrete`, idle/export AA remain off, the
raw length stays 5,727, native idle/export AA remain off, and the ready quality
tooltip reports the high-resolution smooth cache rather than claiming native
AA. Confirm transform+grab stays below 16 ms and the complete settled tail
stays below 25 ms on a real Cocoa foreground run; offscreen timing alone cannot
validate QImage scaling or stroker behavior. Also retain a long-period
modulo-counter regression that would fool evenly spaced sampling.
