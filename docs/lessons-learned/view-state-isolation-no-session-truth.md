---
id: view-state-isolation-no-session-truth
status: active
owners: [codex]
keywords: [viewstate, coaxis, time-filter, channel-colors, isolation]
paths:
  - mf4_analyzer/ui/view_state.py
  - mf4_analyzer/ui/view_bridge.py
  - mf4_analyzer/ui/widgets/channel_tree.py
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
checks:
  - Capture, apply, plot, and UltraView fingerprints read the target View, not leftover session maps or the live filter panel.
  - Empty-View apply clears co-axis projection; color restore replaces overrides then uses palette defaults.
tests:
  - tests/ui/test_view_state_isolation.py
---

# Time-domain drawing intent belongs only to ViewState

Trigger: Changing time-domain co-axis merge/split, filter intent, channel color
overrides, View switch/split/duplicate, project save/load, or UltraView capture
fingerprints.

Past failure: Ordinary co-axis lived in session `_axis_groups` while capture
only saved the restored projection, so A merge leaked into B and B split
destroyed A. Filter was a project-level panel read by plot and UltraView.
Color capture dropped unchecked keys and restore merged, so A inherited B.

Rule: `ViewState` is the only persistent owner of co-axis membership, time
filter intent, and explicit color overrides. Navigator, Inspector, and canvas
are projections of the bound `(view_id, state, canvas)`. Do not dual-write a
session map. Plotting and UltraView `_filter_payload` must use the requested
View snapshot, not the focused panel. Color restore replaces the override set
and fills uncovered channels from the file palette; incremental recolor stays
merge.

Verification: Run
`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_state_isolation.py -q`.
