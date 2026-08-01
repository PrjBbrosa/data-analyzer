# Batch Qt 渲染迁移 Batch 1 基线

**日期：** 2026-08-01
**起点提交：** `612bdd595bdfcecd41a7bedab1259f5c7f1d9383`
**测试提交：** `920fc1510e719e905cebe1924ceea81c4edfa71a`
**结论：** A1 专项 PASS；完整门禁已固定为非绿色基线；默认裸 pytest 完整退出且未发生 SIGSEGV。

## 1. 测试树说明

Batch 1 从包含已确认 Spec/Plan 的 `612bdd5` 开始。A1 修复及回归测试由主协调 agent
统一提交为 `920fc15`（`fix: expand path-only batch sources consistently`）。最终完整门禁
使用的源文件字节与该提交一致；长测试运行期间主协调 agent 将同一工作树提交，测试涉及
文件在提交前后没有再次修改。

## 2. A1 RED → GREEN

修复前专项命令：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest \
  -p no:randomly tests/test_frozen_batch_acceptance.py \
  tests/test_batch_source_integration.py -q
```

RED 基线：`4 failed, 46 passed`。失败为三个 frozen acceptance 用例以及
`test_legacy_file_paths_migrate_to_all_registry_logical_sources`。新增的显式
`target_signals` + 纯 `source_paths` + 单物理文件多逻辑源用例也稳定复现
`result.status == "blocked"`。

审查追加的 identity 红测在修复前得到 `preview.task_count == 1`（期望 2），证明
metadata-cost 纯路径 preview 使用 provisional 物理路径、fresh run 使用逻辑 source ID，
两者身份分裂。

GREEN（最终 `920fc15`）：

```text
tests/test_frozen_batch_acceptance.py + tests/test_batch_source_integration.py
54 passed, 1 warning in 1.70s

上述两文件 + tests/test_batch_runner.py
253 passed, 1 warning in 5.31s
```

最终行为：metadata-cost 路径只 probe 一次并缓存同一物理文件的全部 descriptor、locator、
channel/group facts；preview 不加载样本，preview/fresh run 使用相同逻辑 source ID 与
task ID。full/unknown-cost 纯路径 preview 仍不 probe、不加载。renderer probe 之前不进行
样本加载；缺后端时保留既有 provisional failed-item producer contract。

## 3. frozen_batch_acceptance CLI 实跑

当前 macOS 不能执行仓库中的 Windows PE，因此本次通过真实应用入口参数解析和 production
`BatchRunner` 路径实跑 CLI，并用临时的 frozen runtime/SHA 绑定模拟冻结前置证据；这不是
真实 Windows onedir 验收，Windows 冻结发布状态仍为 **UNVERIFIED**。

```text
evidence: /private/tmp/tracelab-batch1-cli-final.4whZz7/acceptance.json
evidence sha256: aa46d382a5b10edc8cfafc2a495d0614033a16eacdacf6a0da1bcb7389e1ca7b
exit code: 0
ok: true
source_count: 3
source_identity_count: 3
artifact_count: 6 (3 CSV + 3 PDF)
manifest: done=3, total=3
residual_paths: []
```

## 4. 完整门禁基线

命令：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest \
  -p no:randomly --ignore=tests/acquisition_ui -q
```

结果：

```text
62 failed, 4117 passed, 19 skipped, 3 deselected, 33 warnings
1017.61s (0:16:57)
SIGSEGV: 未发生
日志: /tmp/tracelab-batch1-full-gate-final.log
日志 sha256: 856b50b7cdcfb5661ce7393493774bb56681cf1a083bd2065853a9b4d634c49c
```

失败集合由 2 个非 UI 环境/资产失败和 60 个 `tests/ui` 失败组成。后续 Batch 的完整
门禁要求 failed nodeid 集合不得超出下列集合。

## 5. 完整 failed nodeid 集合（62）

```text
tests/test_gen_help_screenshots.py::test_import_screenshot_uses_real_checked_in_samples
tests/test_windows_build_script.py::test_windows_builds_reject_failed_pyinstaller_before_reusing_old_exe_or_evidence
tests/ui/test_channel_widget_setters.py::test_set_checked_channels_roundtrip
tests/ui/test_channel_widget_setters.py::test_set_hidden_channels_keeps_only_checked_known_channels
tests/ui/test_channel_widget_setters.py::test_file_navigator_delegates_channel_state
tests/ui/test_chart_stack.py::test_time_toolbar_has_no_loc_label_to_jostle_right_controls
tests/ui/test_db_reference_controls.py::test_dialog_layout_insets_toggle_content_and_bounds_compact_columns
tests/ui/test_head_hdf_rail.py::test_channel_tree_check_raster_selects_all_channels
tests/ui/test_head_hdf_rail.py::test_get_checked_channels_returns_fid_ch_color
tests/ui/test_head_hdf_rail.py::test_flat_get_checked_channels_works
tests/ui/test_hints.py::test_axis_group_menu_open_retires_coaxis_merge_discovery
tests/ui/test_main_window_smoke.py::test_fft_checked_channel_change_refreshes_auto_db_reference
tests/ui/test_main_window_smoke.py::test_entering_fft_mode_resolves_auto_db_reference_for_checked_channel
tests/ui/test_pg_dense_raster.py::test_dense_raster_is_transform_only_until_100ms_settle
tests/ui/test_pg_dense_raster.py::test_dense_raster_visibility_color_and_revision_invalidate
tests/ui/test_split_focus_routing.py::test_focused_canvas_is_primary_when_not_split
tests/ui/test_split_focus_routing.py::test_enter_split_seeds_primary_focus
tests/ui/test_split_focus_routing.py::test_click_secondary_focuses_it_and_lights_border
tests/ui/test_split_focus_routing.py::test_click_primary_returns_focus_to_primary
tests/ui/test_split_focus_routing.py::test_re_click_same_card_does_not_re_emit
tests/ui/test_split_focus_routing.py::test_exit_split_resets_focus_to_primary
tests/ui/test_split_focus_routing.py::test_channel_check_routes_to_focused_secondary
tests/ui/test_split_focus_routing.py::test_channel_check_routes_to_primary_when_primary_focused
tests/ui/test_split_focus_routing.py::test_channel_eye_routes_only_to_focused_view
tests/ui/test_split_focus_routing.py::test_secondary_range_changes_write_back_to_original_view_state
tests/ui/test_split_focus_routing.py::test_tick_density_change_routes_to_focused_secondary_view
tests/ui/test_split_focus_routing.py::test_split_cursor_mode_applies_to_both_panes_and_states
tests/ui/test_split_focus_routing.py::test_focus_switch_captures_previous_focused_inspector_state
tests/ui/test_split_focus_routing.py::test_split_layout_change_shows_focused_pane_hint
tests/ui/test_split_focus_routing.py::test_split_home_shows_focused_pane_hint
tests/ui/test_split_focus_routing.py::test_split_xaxis_apply_shows_focused_pane_hint
tests/ui/test_split_focus_routing.py::test_split_pan_does_not_toast
tests/ui/test_split_focus_routing.py::test_layout_change_single_view_no_toast
tests/ui/test_split_per_pane_controls.py::test_cursor_mode_targets_primary_when_not_split
tests/ui/test_split_per_pane_controls.py::test_split_cursor_mode_targets_both_panes_when_secondary_focused
tests/ui/test_split_per_pane_controls.py::test_secondary_own_cursor_control_acts_on_secondary
tests/ui/test_split_per_pane_controls.py::test_secondary_controls_disabled_when_primary_focused
tests/ui/test_split_per_pane_controls.py::test_focusing_secondary_keeps_shared_controls_enabled_and_secondary_disabled
tests/ui/test_split_per_pane_controls.py::test_exit_split_restores_primary_controls
tests/ui/test_split_per_pane_controls.py::test_plot_mode_for_canvas_resolves_per_pane
tests/ui/test_split_per_pane_controls.py::test_secondary_plot_mode_toggle_relayouts_secondary_only
tests/ui/test_split_per_pane_controls.py::test_shared_plot_mode_control_targets_focused_secondary
tests/ui/test_split_per_pane_controls.py::test_secondary_plot_mode_toggle_uses_secondary_view_state_not_active
tests/ui/test_split_per_pane_controls.py::test_programmatic_primary_plot_mode_does_not_rewrite_focused_secondary
tests/ui/test_split_per_pane_controls.py::test_programmatic_primary_cursor_mode_does_not_rewrite_focused_secondary
tests/ui/test_split_per_pane_controls.py::test_secondary_canvas_cursor_readout_reaches_secondary_pill
tests/ui/test_split_per_pane_controls.py::test_split_dual_cursor_results_show_on_both_pane_pills
tests/ui/test_split_per_pane_controls.py::test_pill_formats_detail_using_emitting_pane_cursor_mode
tests/ui/test_split_per_pane_controls.py::test_split_secondary_single_cursor_mini_detail_stays_on_secondary_pill
tests/ui/test_split_per_pane_controls.py::test_user_placed_secondary_pill_preserves_right_edge_after_dual_rows_resize
tests/ui/test_split_per_pane_controls.py::test_shared_nav_pan_zoom_arm_both_split_panes
tests/ui/test_split_per_pane_controls.py::test_shared_nav_back_forward_runs_each_pane_toolbar
tests/ui/test_split_per_pane_controls.py::test_shared_nav_highlight_reflects_broadcast_mode
tests/ui/test_split_per_pane_controls.py::test_split_save_image_combines_both_panes
tests/ui/test_split_per_pane_controls.py::test_split_copy_image_combines_both_panes
tests/ui/test_split_per_pane_controls.py::test_shared_options_button_opens_focused_pane
tests/ui/test_split_routing.py::test_directional_merge_only_host_splits
tests/ui/test_split_routing.py::test_split_render_does_not_pollute_active_view_ui
tests/ui/test_split_routing.py::test_split_render_preserves_active_cursor_pill
tests/ui/test_split_routing.py::test_secondary_pane_keeps_its_own_plot_mode_across_switches
tests/ui/test_split_routing.py::test_split_none_exits
tests/ui/test_split_routing.py::test_switch_to_cursor_off_view_clears_pill
```

## 6. 默认裸 pytest 诊断

命令：

```bash
"/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q
```

结果：**COMPLETE，但非绿色**。

```text
63 failed, 4471 passed, 19 skipped, 3 deselected, 33 warnings
1023.10s (0:17:03)
SIGSEGV: 未发生
日志: /tmp/tracelab-batch1-default-pytest.log
日志 sha256: d8cea3f5d65a769149fb5d7ce896cc395982814caf9dcecdaaf2755dd8bfc9bd
```

相对正式的 `--ignore=tests/acquisition_ui -p no:randomly` 基线，默认裸测多出的 failed
nodeid 是：

```text
tests/acquisition_ui/test_review_handoff.py::test_analyzer_load_file_delegates_to_load_one
```

本诊断证明本次默认聚合顺序没有复现既有 Qt SIGSEGV；它不把 63 个普通失败写成 PASS，
也不取代第 4–5 节的正式 failed-nodeid 基线集合。
