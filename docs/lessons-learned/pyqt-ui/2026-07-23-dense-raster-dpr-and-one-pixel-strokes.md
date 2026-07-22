# Dense cached rasters need post-paint DPR metadata and only 1-device-pixel passes

Trigger: Replacing a dense-discrete pyqtgraph vector curve with a cached
`QGraphicsPixmapItem`, especially on Retina/high-DPI displays.

Past failure: Painting physical pixel coordinates into a `QImage` whose DPR
was already set made `QPainter` interpret those coordinates as logical, so the
waveform was cropped and stretched even though the item transform was exact.
A cosmetic `QPen` wider than one device pixel also re-entered Qt's pathological
full-height CRC stroker: on Cocoa, width 2 cost about 1.6 seconds while one-pixel
polyline passes cost a few milliseconds. An extra DPR2-to-DPR2 smooth image
resize was worse (about 3.5 seconds p95).

Rule: Paint the at-least-logical-2x `QImage` in physical coordinates first and
set its DPR only after `QPainter.end()`. Preserve visual width using 2–4 offset
`QPolygonF` passes whose pens are each exactly one device pixel; never widen the
pen itself. Transform the resulting pixmap from `item.boundingRect()` into data
coordinates, including the negative Y scale. Keep native AA off.

Verification: Add an image-level test proving a `(0,0)→(1,1)` trace reaches
both opposite physical image corners at DPR2, then compare the real BLF/DBC
`EPS_CRC1` fallback and raster screenshots for identical peaks/timing. Benchmark
the complete settle and transform+grab paths on Cocoa; transform+grab p95 must
stay below 16 ms and the full settle (including envelope and axis tail work)
must stay below 25 ms.
