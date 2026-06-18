---
id: signal-time-window-heatmap-coverage-extents
status: active
owners: [codex]
keywords: [spectrogram, order, heatmap, frame-centers, coverage, fft-time]
paths:
  - mf4_analyzer/signal/spectrogram.py
  - mf4_analyzer/signal/order_cot.py
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - mf4_analyzer/ui/main_window.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_spectrogram.py tests/signal/test_order_cot.py tests/ui/test_pg_heatmap_canvas.py tests/ui/test_main_window_smoke.py -q
---

# Signal Time-Window Heatmap Coverage Extents

Trigger: Touching FFT-vs-Time, Order/COT, or any heatmap that plots a matrix
whose X coordinates are frame center times.

Past failure: FFT-vs-Time and Order heatmaps used `times[0]..times[-1]` as
the image rectangle. Those values are frame centers, so low-sample-rate or
large-NFFT renders visibly stopped before the selected time range's right edge.

Rule: Keep frame centers for cursor/slice selection, but render the image and
ViewBox against coverage extents. Prefer analyzer-provided
`coverage_start` / `coverage_end`; when metadata is absent, derive a display
extent from the window length or center spacing instead of treating centers as
cell edges.

Verification: Add or run tests that separately assert frame-center semantics,
coverage metadata, heatmap `_extents`, and slice time-axis alignment.
