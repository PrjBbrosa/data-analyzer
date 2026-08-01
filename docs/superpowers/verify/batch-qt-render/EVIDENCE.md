# Batch 2–6 Qt Render Evidence (macOS/source scope)

## Bound evidence

- Result: **PASS (14/14 parity cases; 84/84 integration combinations)**
- Parity page size: 1920 × 1080 px at 144 DPI
- Integration matrix: 14 cases × white/transparent/dark × 1920×1080/3840×2160
- Qt platform: `offscreen` (Qt 5.15.14, pyqtgraph 0.14.0)
- Acceptance commit: `40ed2128f5fd669f8f78b9eca4174a3157f60deb`
- Source-state SHA-256: `5277a2805b1f94a4550c601e72d425886cb4c89fd8a108373a6b2efa15e12a23`
- Machine-readable record: [evidence.json](evidence.json)

The source-state digest binds the accepted Qt facade, producer contract,
four-kind renderer, tests, and parity tool. Each
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
| Batch 4 CLI GREEN | Source smoke generated four PNGs; artifact-only frozen verifier returned `ok=true`; grouped time-domain acceptance exited 0 with source/channel grouping, subplot, and custom-X coverage. |
| Batch 4 focused GREEN | All touched batch/render/GUI tests → **605 passed, 1 warning**. Producer-shaped group tests render a real Qt scene while the spool is alive and validate final PNG metadata; menu/navigation mutation tests prove the chrome guards fail closed. |
| Batch 4 integration GREEN | `tools/verify_batch_qt_render_parity.py --width 1920 --height 1080 --full-matrix` → **PASS, 14/14 parity cases and 84/84 theme/resolution combinations**. Every combination asserts exact pixels, DPI/text metadata, plot ink, no text overlap, no native chrome, and no main navigation. |
| Batch 4 full-suite Gate | **62 failed, 4137 passed, 19 skipped, 3 deselected** in 768.52 s, no SIGSEGV. JUnit failed-nodeid set is exactly equal to the Batch 1 baseline: `new=[]`, `missing=[]`. |
| Gate 4.5 real Cocoa | Real 7-case/9-PNG matrix PASS; production `TimeDomainCanvasPG` vs production BatchRunner two-case comparison PASS. Foreground heartbeat max gaps: 20 PNG 66.64 ms; interactive 500 PNG 75.12 ms; stress 1000 PNG 88.35 ms, with zero >100 ms gaps. |
| Batch 5 focused GREEN | Packaging/runtime plus renderer/thread regression set: **292 passed, 1 skipped in 10.80 s**. Product AST guard reports zero matplotlib imports; Windows packaging contract source check PASS. |
| Batch 5 post-prune parity | Final `40ed212` run: **14/14 parity cases and 84/84 combinations**, bound to the acceptance commit and source-state digest above. |
| Batch 5 final full-suite Gate | **61 failed, 4149 passed, 20 skipped, 3 deselected** in 987.44 s, no SIGSEGV. JUnit set comparison against the 62-nodeid Batch 1 baseline: `new=[]`; the only missing failure is the native `powershell.exe` test now correctly skipped on non-Windows. |

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

## Heatmap worker offscreen visual sign-off

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

- [FFT vs Time parity contact sheet](fft_time-contact-sheet.png)
- [Order parity contact sheet](order_time-contact-sheet.png)

## Main-agent offscreen visual sign-off

The coordinating agent independently reopened all four final contact sheets
and the full `time-subplot8`, `fft-db`, `fft-time-db-manual`, and
`order-time-linear-manual` batch PNGs at original
detail. Result: **PASS**. The batch pages contain only the approved report
header/facts/footer/legend, plot area, and heatmap colorbar; no main navigation
tabs, pyqtgraph auto-range button, color-map menu, context-menu affordance,
toolbar, scrollbar, focus frame, or other Qt chrome is visible. The dual-Y
right axis and FFT legend are complete, all eight subplot curves/titles are
present without clipping, and both heatmap kinds preserve the single-file
orientation, axis coverage, color levels, and complete colorbar labels. This
is an offscreen render review, not a foreground macOS/Windows acceptance claim.

The 640×360 frozen smoke pages were also inspected as coherent small report
pages, but they are deliberately **not** used as visual parity proof. Formal
visual parity is bound to the 1920×1080 cases above; 4K/theme coverage is an
integration geometry/chrome gate.

## Gate 4.5 / Batch 6 native Cocoa sign-off

The coordinating agent ran the production paths on Qt platform `cocoa`, not the
offscreen plugin, and opened the resulting images at original detail.

- Real matrix: `.state/gate45/real-matrix-cocoa-final/run-20260801T190812Z-0b72be23/gate45-real-matrix.json`
  binds commit `40ed212` and reports 7/7 cases, 9 PNGs, all four kinds,
  source/channel grouping, custom-X, dual-Y, 8-panel 4K, and all three themes.
  All nine images were opened; no navigation tabs, auto button, menu, toolbar,
  scrollbar, focus rectangle, or other Qt chrome was visible.
- Real single-file parity:
  `.state/gate45/singlefile-cocoa-final/run-20260801T190747Z-45270f98/gate45-singlefile-parity.json`
  identifies the reference as the production
  `TimeDomainCanvasPG.plot_channels -> grab_pixmap` surface. The high-variation
  channel retained the same 3,924-point envelope on both sides from 25,509 raw
  points; the smooth case retained all 1,800 points and AA on both sides. Both
  cases have identical X ranges and `#2563eb` curve colour. The contact sheet
  was opened by the coordinating agent and the waveform geometry is equivalent.
- Foreground heartbeat evidence is under `.state/gate45/`: 20 PNG max gap
  66.64 ms; 500 PNG interaction proof 75.12 ms with two window-move events,
  one no-button mouse-move and one tooltip-response call; 1000 PNG stress max
  gap 88.35 ms. No run recorded a gap above 100 ms. The interaction counter
  proves event delivery and the probe response; it is not claimed as an AX
  capture of a native tooltip window.

Result: macOS Gate 4.5 and post-prune T6.1 are **PASS**.

## Residual gates

- The Qt facade is connected to `BatchRunner`; PNG-only preset normalization,
  warning propagation, grouping display names, GUI-thread marshal, and atomic
  rollback are covered by the focused suite.
- Product source and Windows build contracts no longer declare or import
  matplotlib. Qt PNG verification uses `QImage`; full/lite builders require
  both qoffscreen and qwindows plugins and separate smoke evidence.
- Fresh Windows full/lite onedir builds, pre/post package footprint, and the
  four required full/lite × offscreen/windows evidence JSON files cannot be
  produced on this Mac. Therefore the truthful final boundary remains:
  **源码实施完成 / Windows 发布 NO-GO**.
