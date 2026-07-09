---
role: pyqt-ui
tags: [qpainter, sparkline, live-cards, perf, raster-fill, band-fill, antialiasing, column-cap, stroke-count, repaint, cocoa, benchmark, downsampler]
created: 2026-07-10
updated: 2026-07-10
cause: insight
supersedes: []
---

# A live QWidget sparkline's per-frame cost is the QPainter band column-count + antialiasing, not the per-sample downsample loop; and macOS `repaint()` times the real raster while pyqtgraph offscreen `grab()` does not

## Context
Cockpit live cards (Task A-6): five 1 ms signals each hold a 30 s @ 1 ms
buffer (30 000 raw samples). The plan pre-nailed a `RollingDisplayBuckets`
(10 ms min/max/last, ≤3001 buckets) so the paint never scans the raw
deque. That correctly bounded the per-frame *Python* work, but the
measured 5-card `refresh+paint` p95 was still ~81 ms (30 fps budget 33 ms)
— the raw-scan was never the bottleneck.

## Lesson
For a plain `QWidget`/`QPainter` sparkline the dominant per-frame cost is
the RASTER of the min/max band, and it scales with the band polygon's
COLUMN (edge) count and with antialiasing — exactly the stroke-count axis
of `2026-06-22-narrow-y-overlay-cost-is-stroke-count-not-data`, but here in
a hand-rolled QPainter widget rather than pyqtgraph. On an 860 px card:
one-column-per-pixel band + AA = 16.5 ms/card; AA off = 9.4 ms; AA off +
cap the bucket→column merge to ~400 columns (mapped `col_px = w/columns`
so the band still spans the full width) = ~3.4 ms; 5-card p95 dropped
81 → 24 ms. The fill AREA is unchanged by the cap, so the win is purely
fewer polygon edges to scan-convert. Two traps: (1) reducing columns via
`painter.scale()` BACKFIRES — the device transform plus AA-under-transform
cost more than the edges you saved; reduce the column COUNT inside the
geometry builder instead. (2) keep the low-density (≤2·W raw points)
polyline branch fully antialiased — AA-off only helps the dense envelope,
and the sparse line needs the crisp edges. Also: on macOS `cocoa`,
`QWidget.repaint()` runs the real synchronous CPU raster into the backing
store, so a `perf_counter` bracket around `repaint()` on a live display is
a VALID paint-frame measurement — unlike pyqtgraph's offscreen `grab()`
(a cached blit, per `2026-06-23-paintevent-hook-needs-class-level-override`).
The benchmark must therefore run `--onscreen`; the offscreen number
understates the raster wall and is smoke-only.

## How to apply
When a QWidget QPainter live chart is slow but you already bounded the
per-frame data loop, profile the PAINT (bracket `repaint()` on a real
cocoa display, or a class-level `paintEvent` timing wrapper) and attack the
band/line geometry: turn antialiasing off for the dense branch and cap the
number of output columns in the path builder (never via `painter.scale()`),
keeping `col_px = w / columns` so the shape still spans the full width.
Prove it with an onscreen 5-card p95, not an offscreen `grab()`.
