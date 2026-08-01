# Batch 2 + 3 Qt Render Evidence

## Bound evidence

- Result: **PASS (14/14 cases; 6/6 heatmap cases)**
- Requested page size: 1920 × 1080 px at 144 DPI
- Qt platform: `offscreen` (Qt 5.15.14, pyqtgraph 0.14.0)
- Commit base: `9875eb3a75d8626acbf4262d6ff03b264cc825db`
- Source-state SHA-256: `5a89a0cfa5c08f9edb280959d3d16912a96ff100f2b0d09d44fcc7b31efcf0c4`
- Machine-readable record: [evidence.json](evidence.json)

The source-state digest binds the uncommitted Batch 3 producer contract,
four-kind renderer, tests, and parity tool in addition to the base commit. Each
heatmap case records the full display matrix, exact LUT SHA-256 plus frozen
samples, levels, QRectF, four matrix-corner values, live-geometry cell-centre
pixels, labels, warnings, full/crop hashes, viewport, and machine assertions.

## RED to GREEN

| Stage | Evidence |
|---|---|
| Initial RED | `tests/test_batch_render_qt.py`: 17 failures because the Qt renderer package did not exist and the line-width default was still 1.0. |
| Contract RED | Raw + filtered style test: 1 failure because the companion initially used a second color instead of the source color plus dashed style. |
| Parity RED | `tests/test_batch_qt_render_parity.py`: parity tool absent; after the first tool pass the real canvases exposed axis-frame and subplot-geometry differences. |
| 1920 RED | Formal evidence isolated `time-raw-filtered/axis_ranges_match=false`: batch `[-1, 1]`, reference `[-1.25, 1.25]`. The fix now uses the real canvas data-extent + 5% + 10-division frame semantics, independent of viewport width. |
| Evidence-guard RED | A forced-visible pyqtgraph auto-range button remained undetected when the probe sampled only the upper-right PlotItem corner. The pixel guard now samples all four corners and the forced lower-left button makes the negative test fail as intended. |
| Final GREEN | `pytest tests/test_batch_render_qt.py tests/test_batch_qt_render_parity.py -q` → **25 passed**. |
| Formal GREEN | `tools/verify_batch_qt_render_parity.py` at 1920 × 1080 → **PASS, 8 cases, 0 failed**. The 960 × 640 parity run embedded in pytest also remains PASS. |
| Regression GREEN | `pytest tests/test_batch_renderer.py tests/test_signal_no_gui_import.py -q` → **62 passed in 1.33s** after updating the two planned 1.0 → 1.5 default expectations. |
| Batch 2 full-suite Gate | Frozen commit `9875eb3` ran **64 failed, 4140 passed, 19 skipped, 3 deselected**. Two extra failures were caused solely by the temporary worktree lacking the project-local `.state/` directory and passed 2/2 after that directory was created; the remaining **62 failed nodeids exactly equal** the Batch 1 baseline set, with no SIGSEGV. |
| Batch 3 initial RED | `tests/test_batch_render_qt_heatmap.py` → **9 failed** because `fft_time` and `order_time` were not yet supported. |
| Batch 3 parity RED | All six heatmap cases initially failed only the single-pixel corner comparison: bilinear subpixel blending mixed the cell-centre colour with white despite matrix/LUT/levels/extent parity. The probe now searches a bounded 13×13 device-pixel patch around each scene-mapped corner-cell centre for the expected LUT colour. |
| Batch 3 focused GREEN | Producer + Qt renderer + parity + old-renderer/no-GUI-import regression set → **104 passed in 5.27s**. |
| Batch 3 formal GREEN | `tools/verify_batch_qt_render_parity.py --width 1920 --height 1080` → **PASS, 14 cases, 0 failed**; source-state digest reproduced exactly. |

## Worker visual sign-off

Both final contact sheets were opened with original-pixel inspection. The full
dual-Y, 8-panel subplot, and FFT linear report pages were also opened to check
page chrome, header/facts/footer placement, legends, and outer-axis clipping.

| Case | Machine | Visual | Observation |
|---|---:|---:|---|
| `time-single` | PASS | PASS | Signal, time range, graticule, axis frame, and plot ink align with the single-file canvas crop. |
| `time-raw-filtered` | PASS | PASS | Original and filtered traces share the source blue, remain distinguishable by solid/dashed style, and the report legend is complete. |
| `time-dual-y` | PASS | PASS | Blue acceleration and green speed traces align; the combined legend and the full right-axis ticks/title are visible without clipping. |
| `time-subplot8` | PASS | PASS | All eight panels, colors, inside titles, and traces are present; adjacent text does not intersect and only the bottom row has the X label. |
| `time-custom-x` | PASS | PASS | Absolute angle-domain X data and `Angle (deg)` labeling align with the reference crop. |
| `fft-linear` | PASS | PASS | Both spectral peaks, automatic range, frame/grid tokens, and explicit report legend are present and unclipped. |
| `fft-db` | PASS | PASS | dB conversion, visible range, peaks, axis labeling, and crop geometry align with the single-file path. |
| `fft-manual-range` | PASS | PASS | Manual X/Y limits are applied exactly and both in-range peaks retain the reference geometry. |

Contact sheets:

- [Time parity contact sheet](time-contact-sheet.png)
- [FFT parity contact sheet](fft-contact-sheet.png)

## Batch 3 worker offscreen visual sign-off

The final heatmap contact sheet and representative full `fft_time` / `order_time`
batch PNGs were opened at original pixels after the formal 1920×1080 run.

| Case | Machine | Visual | Observation |
|---|---:|---:|---|
| `fft-time-linear-auto` | PASS | PASS | Non-square 2×3 orientation, time coverage, frequency endpoints, turbo gradient, auto levels, and single-file crop align. |
| `fft-time-db-manual` | PASS | PASS | Unclipped analyzer dB matrix and exact manual `[-32,-2]` colour window align; dB label and bar are complete. |
| `fft-time-invalid-cmap` | PASS | PASS | Invalid map warning is recorded and visible output falls back to the same turbo LUT without changing geometry. |
| `order-time-linear-manual` | PASS | PASS | Order endpoint range, asymmetric corner colours, exact `[0.03,0.50]` levels, and foreground crop align. |
| `order-time-db-auto` | PASS | PASS | 99th-percentile ceiling with 30 dB span matches; no transpose, flip, clipping, or colourbar drift is visible. |
| `order-time-invalid-cmap` | PASS | PASS | Invalid map warning and turbo fallback match the FFT-time path; order/time axes remain intact. |

The complete batch pages contain only the approved report header/facts/footer,
heatmap, axes, grid, and read-only colorbar. No main-window navigation tabs,
pyqtgraph auto-range button, context-menu affordance, scrollbar, focus frame,
toolbar, or other native Qt chrome is visible.

- [Heatmap parity contact sheet](heatmap-contact-sheet.png)

## Main-agent offscreen visual sign-off

The coordinating agent independently reopened all three final contact sheets
and the full `time-dual-y`, `time-subplot8`, `fft-linear`,
`fft-time-db-manual`, and `order-time-linear-manual` batch PNGs at original
detail. Result: **PASS**. The batch pages contain only the approved report
header/facts/footer/legend, plot area, and heatmap colorbar; no main navigation
tabs, pyqtgraph auto-range button, color-map menu, context-menu affordance,
toolbar, scrollbar, focus frame, or other Qt chrome is visible. The dual-Y
right axis and FFT legend are complete, all eight subplot curves/titles are
present without clipping, and both heatmap kinds preserve the single-file
orientation, axis coverage, color levels, and complete colorbar labels. This
is an offscreen render review, not a foreground macOS/Windows acceptance claim.

## Residual gates

- This Batch 2 proof is a real `QApplication` exercise on Qt's offscreen
  platform. Native macOS/Windows foreground acceptance remains a later project
  gate and is not claimed here.
- The new renderer is intentionally not connected to `BatchRunner` in Batch 2.
  Wiring, recipe/preset propagation, and legacy matplotlib removal belong to
  later plan batches.
- White-theme 1920×1080 parity is complete for all four kinds. Cross-theme and
  4K proof remain part of the later integration gate.
