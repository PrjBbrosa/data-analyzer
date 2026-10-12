---
id: comparison-implicit-end-reprojects-host
status: active
owners: [codex]
keywords: [analysis, comparison, inspector, view, delete]
paths:
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
  - mf4_analyzer/ui/main_window/analysis_comparison.py
checks: []
tests:
  - tests/ui/test_analysis_view_comparison_regressions.py
---

# Ending A Comparison Must Reproject The Surviving View

Trigger: Deleting a comparison peer, closing other views, or closing all files while a peer holds focus.

Past failure: Only the explicit close path restored the host onto the Inspector. Delete and close-others relied on `ViewManager.active_changed`, which does not fire when the host index is below the peer. The next capture wrote the peer's parameters into the host.

Rule: After the relation ends, if the peer held focus, project the surviving state onto the Inspector. Do not wait for a conditional `active_changed`. Range edits resolve the canvas's `AnalysisViewTarget` and write only that view's axis keys.

Verification: Parameterize fft, fft_time, order, and frf. Peer-focused delete and close-others leave the host `window` unchanged after capture.
