---
id: codex-analysis-section-state-needs-pane-local-sources
status: active
owners: [codex]
keywords: [analysis_views, fft, split, navigator, project-save]
paths:
  - mf4_analyzer/ui/main_window.py
  - tests/ui/test_analysis_multiview_integration.py
checks:
  - "rg -n \"capture_sources|_analysis_channel_color_map|analysis_views\" mf4_analyzer/ui/main_window.py tests/ui/test_analysis_multiview_integration.py"
tests:
  - "TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py"
---

# Analysis Section State Needs Pane-Local Sources

Trigger: Work on analysis View tabs, split panes, FFT source colors, or project
save/load of `analysis_views`.

Past failure: FFT split panes stored sources per pane, but render color lookup
used only the current global navigator checked rows. Saving also captured every
analysis section from live widgets, letting an inactive section's pane sources be
overwritten by the current navigator selection.

Rule: Treat `AnalysisViewState.panes[*].sources` as the source of truth for
inactive or non-focused analysis panes. Use the full navigator channel color map
for swatch colors, and only let the currently displayed section overwrite pane
sources from live controls during project save.

Verification: Add focused tests where the current navigator selection differs
from an inactive FFT pane/source, and assert both split render colors and saved
`analysis_views` preserve the pane-local source state.
