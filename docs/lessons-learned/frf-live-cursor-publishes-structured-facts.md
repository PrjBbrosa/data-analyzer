---
id: frf-live-cursor-publishes-structured-facts
status: active
owners: [codex]
keywords: [cursor pill, FRF, ChartStack, mini labels, structured facts]
paths:
  - mf4_analyzer/ui/pg_canvas/frf_canvas.py
  - mf4_analyzer/ui/chart_stack/stack.py
  - mf4_analyzer/ui/chart_stack/cursor_display.py
checks:
  - git diff --check
tests:
  - tests/ui/test_frf_cursor_layout.py
  - tests/ui/test_cursor_single_pipeline.py
---

# FRF live cursor publishes structured facts

Trigger: Wiring an analysis cursor into the shared ChartStack pill, or changing full/mini labels for a domain whose rows are different quantities.

Past failure: The FRF activity cursor emitted one pipe-joined string. The pill's numeric/full toggle rebuilds only from a structured projection, so magnitude, phase, and coherence disappeared after full → numeric → full. Treating FRF as an FFT canvas, or reusing FFT's mini "hide the name, keep the dot" policy, would also drop the short metric labels.

Rule: A managed analysis cursor publishes one Qt-free facts payload in the same sample as the frequency title. Legacy `cursor_info` / `dual_cursor_info` strings stay for compatibility and must not paint that canvas. Full/mini rebuilds from the cached facts and does not re-run the analysis. Mini name hiding and the overflow noun (`channels` vs `项指标`) are explicit presentation fields; FRF mini keeps `|H|`, `φ`, and `γ²`. A hidden clear drops only that canvas cache.

Verification: `tests/ui/test_frf_cursor_layout.py` and the FRF cases in `tests/ui/test_cursor_single_pipeline.py`, with production QSS and the painted pill document. Record Cocoa and Windows frozen separately from offscreen.
