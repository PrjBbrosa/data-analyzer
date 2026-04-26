# Order + Batch Preset Design

**Date:** 2026-04-26
**Status:** implemented first pass

## Goal

Bring order analysis closer to the FFT vs Time architecture and add batch
generation for two workflows:

- capture the current one-off FFT/order calculation as a batch preset;
- define a free-config preset that selects signals by rule and runs FFT or
  order analysis across loaded files.

## Implemented Shape

### Order Analysis

`mf4_analyzer/signal/order.py` now keeps the legacy tuple-returning API but
routes through structured result objects:

- `OrderAnalysisParams`
- `OrderTimeResult`
- `OrderRpmResult`
- `OrderTrackResult`

Order extraction now uses `one_sided_amplitude()` from `signal/fft.py`, so
windowing and amplitude normalization match FFT and FFT vs Time. The UI
callers can continue using:

- `compute_order_spectrum_time_based`
- `compute_order_spectrum`
- `extract_order_track`

### Batch Presets

`mf4_analyzer/batch.py` owns the GUI-free batch model:

- `AnalysisPreset.from_current_single(...)`
- `AnalysisPreset.free_config(...)`
- `BatchOutput`
- `BatchRunner`

Supported methods:

- `fft`
- `order_time`
- `order_rpm`
- `order_track`

Batch output supports data export (`csv` / `xlsx`) and PNG chart generation.

### UI

The toolbar exposes a new `批处理` action. `MainWindow` remembers the most
recent successful FFT/order calculation as a current-single preset. The
batch dialog has two tabs:

- `当前单次`: reuse the remembered/current preset;
- `自由配置`: choose method, signal match rule, RPM channel, parameters, and
  output options.

## Verification

- `tests/test_order_analysis.py`
- `tests/test_batch_runner.py`
- `tests/ui/test_toolbar.py`
- `tests/ui/test_drawers.py`

Full suite command used:

```bash
QT_QPA_PLATFORM=offscreen /Users/donghang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests -q
```
