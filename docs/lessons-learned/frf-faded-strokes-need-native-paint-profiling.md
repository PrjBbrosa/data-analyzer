---
id: frf-faded-strokes-need-native-paint-profiling
status: active
owners: [codex]
keywords: [FRF, low coherence, alpha, drawPath, drawLines, Cocoa, cursor]
paths:
  - mf4_analyzer/ui/pg_canvas/frf_canvas.py
  - mf4_analyzer/ui/pg_canvas/frf_plot_host.py
checks:
  - Native Cocoa original-data cursor and zoom A/B with the same display parameters
  - git diff --check
tests:
  - tests/ui/test_frf_faded_render.py
  - tests/ui/test_frf_canvas.py
---

# FRF Faded Strokes Need Native Paint Profiling

Trigger: FRF cursor or zoom stalls although curve antialiasing is already off.

Past failure: Alpha-70 wide faded curves forced pyqtgraph's drawPath path; moving a cursor repainted those paths. Lookup and readout layout were small costs compared with native painting. Changing only AA or visible-X clipping did not remove the bottleneck.

Rule: Profile real native painting before selecting an optimization. On the explicitly white FRF surface, opaque preblended pale ink can retain the low-coherence distinction while using drawLines. The faded base contains all finite bins: stack it below trusted curves and use the same pale ink for isolated low-coherence points. Do not change analysis values, NaN gaps, thresholds, or numerical resolution to conceal paint cost.

Verification: Test actual painter calls, finite-gap segments, singleton styling and captured trusted/pale pixels. Compare exposed Cocoa cursor/zoom timings and images on the same result, phase wrapping, viewport and DPR; Windows frozen acceptance remains separate.
