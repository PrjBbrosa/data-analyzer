---
id: codex-fft-spectrum-time-preview
status: active
owners: [codex]
keywords: [fft, PgLineCanvas, plot_spectra, source-summary, time-preview, psd]
paths: [mf4_analyzer/ui/main_window.py, mf4_analyzer/ui/pg_canvas/line_canvas.py, mf4_analyzer/ui/inspector_sections.py, tests/ui/test_pg_line_canvas.py, tests/ui/test_analysis_multiview_integration.py, tests/ui/test_inspector.py]
checks: [rg -n "combo_psd_y|psd_y|_plot_psd|_psd_curves|psd_label" mf4_analyzer/ui tests]
tests: [tests/ui/test_pg_line_canvas.py, tests/ui/test_inspector.py -k fft, tests/ui/test_analysis_multiview_integration.py]
---

# Codex FFT Spectrum Time Preview

Trigger: Load when changing the FFT spectrum UI, FFT overlay source routing, or `PgLineCanvas.plot_spectra`.

Past failure: The FFT canvas kept the old PSD second row and single-signal inspector emphasis after the PyQtGraph migration, even though FFT overlay sources come from left-side checked channels.

Rule: The FFT canvas top row overlays spectrum amplitude curves; the lower row is the selected source's time-domain preview. Do not reintroduce a visible PSD row or `psd_y` inspector control. When navigator channels are checked, the inspector must show a source summary and hide the fallback single-signal combo.

Verification: Grep for old PSD UI hooks, and run the FFT line-canvas, FFT inspector, and FFT multiview tests.
