---
id: heatmap-natural-window-from-current-matrix
status: active
owners: [codex]
keywords: [heatmap, color, auto, view, natural window]
paths:
  - mf4_analyzer/ui/heatmap_color_coordinator.py
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
checks: []
tests:
  - tests/ui/test_heatmap_color_state_integration.py
  - tests/ui/test_heatmap_color_coordinator.py
---

# Heatmap Natural Window Comes From The Current Matrix

Trigger: Changing automatic heatmap color windows, view switching, or split color-scale lock.

Past failure: `complete()` treated `canvas._last_auto_levels` as the data's natural window. `project_color_levels(auto=True)` wrote the previous union into that field, and the Order / linear paint paths never refreshed it. The next View inherited the previous window.

Rule: The automatic window is `_automatic_color_window()` on the matrix just drawn. A locked union is only a projection. Do not cache that projection in a field the next render reads as truth.

Verification: Two auto-scale Views whose cached results differ by 1000× keep their own windows across Order dB, Order linear, FFT-Time dB, and FFT-Time linear.
