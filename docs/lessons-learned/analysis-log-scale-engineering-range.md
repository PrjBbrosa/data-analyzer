---
id: analysis-log-scale-engineering-range
status: active
owners: [codex]
keywords: [fft, log, chart options, plot_spectra, engineering]
paths:
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - mf4_analyzer/ui/_axis_handle.py
  - mf4_analyzer/ui/dialogs/chart_options.py
checks: []
tests:
  - tests/ui/test_pg_line_canvas.py
  - tests/ui/test_analysis_multiview_integration.py
---

# Analysis Log Ranges Are Engineering Values

Trigger: Changing FFT or spectrum log scale, `plot_spectra`, or chart-options range apply.

Past failure: `PgAxisHandle.set_engineering_ylim` converted to log10, but `plot_spectra` wrote the engineering limits straight into the log ViewBox. Manual 1..100 became engineering 10..1e100, and auto range collapsed to the float extremes.

Rule: Spectrum and preview range writes go through `set_engineering_xlim` / `set_engineering_ylim`. Log auto-range uses the minimum positive sample, not 0. Persist `x_scale` / `y_scale` on the appearance spec; a missing key is linear. An unchanged chart-options OK does not replay the range policy.

Verification: `test_plot_spectra_log_y_manual_range_stays_engineering` and `test_fft_log_manual_range_round_trips_in_engineering_units`. `plot_spectra` still returns with AA off.
