---
id: axis-adapter-range-commit-must-settle-owner-envelope
status: active
owners: [codex]
keywords: [chart-options, axis-handle, viewport-envelope, autorange, debounce]
paths:
  - mf4_analyzer/ui/_axis_handle.py
  - mf4_analyzer/ui/dialogs/chart_options.py
  - tests/ui/test_dialogs.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_axis_handle.py -q
---

# Axis Adapter Range Commits Must Settle The Owner Envelope

Trigger: Changing a generic chart-options or axis-adapter path that mutates a
TimeDomain X range or enables X autorange.

Past failure: `ChartOptionsDialog` correctly changed the pyqtgraph ViewBox, but
the TimeDomain `PlotDataItem` still contained only the old viewport envelope.
Manual ranges briefly painted a partial curve, while Auto-X repeatedly derived
larger bounds from that clipped curve and needed several timer cycles to reach
the full data extent.

Rule: Treat dialog Apply/OK as one programmatic axis transaction. Complete all
axis mutations first, then synchronously flush any pending owner-envelope work
at the redraw tail. Before enabling TimeDomain Auto-X, prime the curve from the
owner's raw X union; never calculate whole-data bounds from a viewport-clipped
`PlotDataItem`.

Verification: Start from a narrow X window, expand it manually and through
Auto-X, and assert immediately after `apply_changes()` that the rendered curve
covers the raw data extent. For manual range commits also assert that the
refresh pending flag and timer are both cleared.
