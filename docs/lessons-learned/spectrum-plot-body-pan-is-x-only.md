---
id: spectrum-plot-body-pan-is-x-only
status: active
owners: [codex]
keywords: [fft, PgLineCanvas, ViewBox, pan, auto-y, viewport_origin]
paths:
  - mf4_analyzer/ui/pg_canvas/viewbox.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - tests/ui/test_spectrum_interaction.py
checks:
  - rg -n "force_spectrum_x_only|force_time_x_only" mf4_analyzer/ui/pg_canvas/viewbox.py
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_spectrum_interaction.py::test_spectrum_plot_body_left_pan_is_x_only_keeps_auto_y tests/ui/test_spectrum_interaction.py::test_spectrum_shift_wheel_pauses_auto_y tests/ui/test_spectrum_interaction.py::test_programmatic_auto_y_is_not_user_y_intent -q
---

# Spectrum Plot-Body Pan Is X-Only

Trigger: Changing FFT spectrum ViewBox pan/zoom, `_on_interactive_range_changed`, or `viewport_action_committed` axis detection.

Past failure: T2 tests emitted `sigRangeChangedManually([True, False])` and passed, but a real MainWindow left-drag with `dy=0` still moved Y because `_ModifierWheelViewBox` only forced X-only pan on the time-preview ViewBox. Auto-Y was then labeled `viewport_origin.y=user`.

Rule: FFT amplitude plot-body left-pan must use the same temporary `setMouseEnabled(x=True, y=False)` as the time preview. Do not treat a synthetic X-only `sigRangeChangedManually` mask as proof of real mouse drags. Keep Y on Shift-wheel, Y gutter (`axis is not None`), RectMode, and explicit Y autofit.

Verification: Run the plot-body FakeDrag/`QMouseEvent` X-only test and the viewport Shift+`QWheelEvent` Y-pause test.
