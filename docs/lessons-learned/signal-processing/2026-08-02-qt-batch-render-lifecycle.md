---
id: signal-processing/2026-08-02-qt-batch-render-lifecycle
status: active
owners: [codex]
keywords: [batch, qt, qapplication, gui-thread, qimage, png, dpi, cocoa, qsettings, chrome]
paths:
  - mf4_analyzer/batch_render_qt/_dispatch.py
  - mf4_analyzer/batch_render_qt/_builder.py
  - mf4_analyzer/batch_render_qt/_export.py
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_batch_render_qt.py -q
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python tools/verify_batch_qt_render_parity.py --full-matrix --output-dir <path>
  - native Cocoa 50 ms heartbeat with max gap <= 200 ms
tests: [tests/test_batch_render_qt.py, tests/test_batch_qt_render_parity.py]
role: signal-processing
tags: [batch, qt, qapplication, gui-thread, qimage, png, dpi, cocoa, qsettings, chrome]
created: 2026-08-02
updated: 2026-08-02
cause: insight
supersedes: []
---

# Qt Offscreen Batch Rendering Owns GUI Thread And Application Lifecycle

## Context

Trigger: Changing Qt batch scene construction, dispatch, image export, or
headless/native render probes. Past failure: treating all `QImage` work as
worker-safe moved QWidget layout/paint off the GUI thread; moving all work back
blocked the event loop, while setting PNG DPI before paint changed cached
`AxisItem` `QPicture` scaling.

## Lesson

Rule: Build, settle, lay out, and paint the standalone report scene into a
`QImage` on the `QApplication` thread; return the image so a batch worker can
encode/write PNG on its own caller thread. Reuse an existing `QApplication`,
reject a bare `QCoreApplication`, create only on the main thread, retain it, and
reject new renders after `aboutToQuit`. Set dots-per-meter only after
`QPainter.end()` so `AxisItem` records paint commands at the normal device DPI.

## How to apply

Keep the report scene free of auto buttons, menus, mouse interaction, frames,
scrollbars, focus rects, toolbars, status bars, and other Qt chrome; prove this
structurally and with corner pixels. Isolate all probe `QSettings`. Use
offscreen for deterministic functional coverage, but require a real
`QT_QPA_PLATFORM=cocoa` run that confirms `platformName()=="cocoa"` and records
the 50 ms heartbeat; offscreen timing never substitutes for that native gate.
