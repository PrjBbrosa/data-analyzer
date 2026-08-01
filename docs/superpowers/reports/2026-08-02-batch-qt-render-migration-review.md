# Batch Qt/pyqtgraph Render Migration — Final Review

**Date:** 2026-08-02

**Branch:** `codex/batch-qt-render-migration`

**Accepted source commit:** `40ed2128f5fd669f8f78b9eca4174a3157f60deb`

**Decision:** **源码实施完成 / Windows 发布 NO-GO**

## 1. Scope delivered

- Batch image export is PNG-only and uses the standalone
  `mf4_analyzer/batch_render_qt/` Qt/pyqtgraph renderer through the thin
  `batch_render.py` facade. `batch.py` retains its no-top-level-Qt contract.
- `time`, `fft`, `fft_time`, and `order_time` all render without matplotlib.
  Product source has zero static matplotlib imports; the runtime requirement,
  old frozen contract, and mpl-data/font pruning path were removed.
- Report PNGs contain the approved header/facts/footer/legend/axes/colourbar
  only. They do not copy the main navigation shown in the UI reference and do
  not expose pyqtgraph auto buttons, menus, toolbars, scrollbars, focus frames,
  or other Qt chrome.
- QWidget creation/layout/paint stays on the `QApplication` thread; lossless
  QImage PNG encoding runs on the BatchRunner caller/worker thread. PNG DPM is
  written only after `QPainter.end()` to prevent AxisItem QPicture replay from
  scaling ticks/grid across panels.
- Dense/high-raster time data uses a display-only min/max envelope based on
  the realized ViewBox width. Raw `BatchSeries`, analysis values, and data
  export are unchanged. Smooth/low-density lines keep antialiasing.

## 2. Single-file visual parity

The final offscreen evidence is bound to source commit `40ed212` and source
digest `5277a2805b1f94a4550c601e72d425886cb4c89fd8a108373a6b2efa15e12a23`.

- Formal parity: **14/14 cases PASS**.
- Integration matrix: **84/84 combinations PASS** (14 cases × three themes ×
  1920×1080/3840×2160).
- The coordinating agent opened all four final contact sheets at original
  detail: time, FFT, FFT-vs-Time, and Order. Curves, ranges, grid/axis tokens,
  8-panel layout, heatmap orientation/levels/LUT, and colourbars align with the
  production single-file plot crops.
- A separate real-data Cocoa probe directly compares production
  `TimeDomainCanvasPG.plot_channels -> grab_pixmap` with production
  `AnalysisPreset -> BatchRunner -> batch_render_qt`. Both cases use colour
  `#2563eb` and identical X ranges. The high-variation signal preserves the
  same 3,924 envelope points from 25,509 raw points; the smooth case preserves
  all 1,800 points and AA on both sides. The coordinating agent opened the
  contact sheet and signed off the waveform geometry as equivalent.

Tracked evidence:

- `docs/superpowers/verify/batch-qt-render/evidence.json`
- `docs/superpowers/verify/batch-qt-render/time-contact-sheet.png`
- `docs/superpowers/verify/batch-qt-render/fft-contact-sheet.png`
- `docs/superpowers/verify/batch-qt-render/fft_time-contact-sheet.png`
- `docs/superpowers/verify/batch-qt-render/order_time-contact-sheet.png`

Local native evidence:

- `.state/gate45/singlefile-cocoa-final/run-20260801T190747Z-45270f98/`
- `.state/gate45/real-matrix-cocoa-final/run-20260801T190812Z-0b72be23/`

## 3. Native Cocoa and responsiveness

The post-prune real matrix ran on `platformName()=="cocoa"`: **7/7 cases,
9/9 PNGs PASS**. It covers dual-Y, 8-panel 4K, source/channel grouping,
custom-X, all four kinds, and white/transparent/dark themes. The coordinating
agent opened all nine PNGs at original detail and found no Qt/main-window
chrome, clipping, lost curves, transposed heatmap, or incomplete colourbar.

Foreground 50 ms heartbeat results:

| Run | Result | Maximum event-loop gap | >100 ms gaps |
|---|---:|---:|---:|
| Real 20-PNG acceptance | 20/20 | 66.64 ms | 0 |
| Interactive 500-PNG run | 500/500 | 75.12 ms | 0 |
| Stress 1000-PNG run | 1000/1000 | 88.35 ms | 0 |

During the interactive run, Computer Use moved the visible status window while
progress continued. The probe recorded two window-move events, one no-button
mouse-move event, and one tooltip-response call. This proves GUI event delivery
and application response; it is not presented as an accessibility capture of a
native tooltip window.

## 4. Tests and packaging contract

- Focused renderer/thread/packaging regression set: **292 passed, 1 skipped in
  10.80 s**.
- Windows packaging source contract: PASS. Both full/lite scripts exclude
  matplotlib, require `qoffscreen.dll` and `qwindows.dll`, and request separate
  offscreen/windows frozen-smoke evidence bound to one EXE SHA per flavour.
- Frozen PNG inspection uses `QImage`/`QImageReader`, not Pillow. In a fresh
  product environment, contourpy, kiwisolver, cycler, fontTools, and Pillow no
  longer arrive as matplotlib-only dependencies. Development-only matplotlib
  comparison scripts explicitly state that it must be installed manually;
  the two remaining Pillow imports are also confined to `tools/` helpers.
- Final full-suite result: **61 failed, 4149 passed, 20 skipped, 3 deselected in
  987.44 s**, with no SIGSEGV.

## 5. Full-suite gate

The final command is:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest \
  -p no:randomly --ignore=tests/acquisition_ui -q
```

Final result: **Gate PASS under the fixed baseline rule** — 61 failed, 4149
passed, 20 skipped, 3 deselected, 33 warnings in 987.44 s, with no SIGSEGV.
JUnit evidence is `.state/batch-qt-final-full.xml`.

The acceptance rule is set inclusion against the 62-nodeid Batch 1 baseline;
failure count alone is not sufficient. Exact comparison:

```text
baseline=62
current=61
new=[]
missing=[tests/test_windows_build_script.py::test_windows_builds_reject_failed_pyinstaller_before_reusing_old_exe_or_evidence]
```

The one missing baseline failure is intentional: this is the only test that
actually launches `powershell.exe` against a native `.cmd`, so it is now skipped
on non-Windows. All PowerShell text/contract tests still run cross-platform.

## 6. Windows release boundary

This Mac cannot produce or execute fresh Windows full/lite onedir artifacts.
The following required evidence is absent:

- full-offscreen and full-windows smoke JSON;
- lite-offscreen and lite-windows smoke JSON;
- trustworthy pre/post `_internal` bytes/files from fresh builds.

Those four platform/flavour runs must use fresh executables and bind both
platform records for a flavour to the same EXE SHA. Until they exist, Gate 6 is
not a total PASS even though implementation, macOS native rendering, offscreen
parity, tests, and source packaging contracts are complete.

**Final decision: 源码实施完成 / Windows 发布 NO-GO.**
