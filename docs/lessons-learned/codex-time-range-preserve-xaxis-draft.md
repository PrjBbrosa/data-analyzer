---
id: codex-time-range-preserve-xaxis-draft
status: active
owners: [codex]
keywords: [time-range, xaxis, inspector, view-state, draft, capture_controls_into]
paths: [mf4_analyzer/ui/main_window.py, mf4_analyzer/ui/view_bridge.py, tests/ui/test_main_window_smoke.py]
checks: [rg -n "_on_time_range_enabled_changed|_capture_range_change_into_view|_snapshot_xaxis_controls" mf4_analyzer/ui/main_window.py]
tests: [tests/ui/test_main_window_smoke.py -k "time_range or custom_xaxis", tests/ui/test_view_switch_integration.py, tests/ui/test_split_routing.py]
---

# Codex Time Range Preserve Xaxis Draft

Trigger: Changing time-range toggles, custom X-axis controls, or time-domain
view-state capture/restore.

Past failure: Toggling "use selected time range" captured and restored the
whole view state. If the user had selected "channel X axis" but had not clicked
Apply, the restore used the last applied X-axis state and reset the dropdown
back to time.

Rule: Time-range changes may update `range_filter` and replot immediately, but
must preserve any unapplied X-axis UI draft. Do not let range capture commit or
overwrite `x_axis`; keep applied X-axis state separate from inspector draft
controls.

Verification: Add or run a regression where `chk_range.setChecked(True)`
preserves an unapplied `combo_xaxis == channel` selection while
`_custom_xaxis_fid/_custom_xaxis_ch` and saved `axis_opts["x_axis"]` remain
the applied time-axis state.
