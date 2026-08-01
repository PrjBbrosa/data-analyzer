# Batch 2 Qt Render Evidence

## Bound evidence

- Result: **PASS (8/8 cases)**
- Requested page size: 1920 × 1080 px at 144 DPI
- Qt platform: `offscreen` (Qt 5.15.14, pyqtgraph 0.14.0)
- Commit base: `6afe3662beabe9ce9d762f5e3691a4d0cd886ed7`
- Source-state SHA-256: `0d455a650a89cf44f8166dac294ae4f6627ec1eb55838536d40ed1123631b0bf`
- Machine-readable record: [evidence.json](evidence.json)

The source-state digest binds the uncommitted Batch 2 implementation, tests,
and parity tool in addition to the base commit. Each case records the full
batch/reference PNG hashes, geometry-derived crop hashes, effective viewport,
axis ranges, curve tokens, plot ink, and all machine assertions.

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

## Main-agent offscreen visual sign-off

The coordinating agent independently reopened both final contact sheets and
the full `time-dual-y`, `time-subplot8`, and `fft-linear` batch PNGs at original
detail. Result: **PASS**. The batch pages contain only the approved report
header/facts/footer/legend and plot area; no main navigation tabs, pyqtgraph
auto-range button, context-menu affordance, toolbar, scrollbar, focus frame, or
other Qt chrome is visible. The dual-Y right axis and FFT legend are complete,
and all eight subplot curves/titles are present without clipping. This is an
offscreen render review, not a foreground macOS/Windows acceptance claim.

## Residual gates

- This Batch 2 proof is a real `QApplication` exercise on Qt's offscreen
  platform. Native macOS/Windows foreground acceptance remains a later project
  gate and is not claimed here.
- The new renderer is intentionally not connected to `BatchRunner` in Batch 2.
  Wiring, recipe/preset propagation, and legacy matplotlib removal belong to
  later plan batches.
- Time/FFT white-theme parity is complete here. Cross-module 4K and the final
  four-kind contact-sheet matrix remain part of the later integration gate.
