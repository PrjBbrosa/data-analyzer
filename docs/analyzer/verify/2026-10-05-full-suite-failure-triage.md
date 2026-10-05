# 2026-10-05 全量失败归因与修复

结论：54 项历史失败对应的当前用例定向回归全部通过。并非 54 个软件缺陷：39 项属于测试契约、构造、断言或隔离问题；3 项是产品 UI 缺陷；4 项来自验收/样本工具；3 项属于样式维护；5 项历史根因仍为 UNKNOWN。分类按用例计数，不等于独立根因数。

## 快照与证据边界

- 原全量快照：`6306b3b1`，原日志 `/tmp/analysis-view-validity-full-main.log`、`/tmp/analysis-view-validity-full-acq.log`。接受原运行期间产品代码稳定的证据，没有把这些失败归因于运行中修改。
- 本次修复基于当前 `67d88ee1bd7a43eb375262c44db5c4f6422fea28`。修改前回放 54 项为 **48 failed、6 passed**；本报告归因结合旧日志与当前重现，不声称是对两个提交之间每项变更做了二分。
- 保留开始前及并发会话的无关变更，包括另一条 FRF 校验恢复工作。未提交或推送。
- 原始节点、重命名映射、日志、运行前后 SHA256 比对结果、截图位于 `.state/full-failure-triage/`，不纳入 Git。各下表 gate 的 Python/QSS 源与测试快照运行前后无差异。

## 修复与逐项归因

| 原失败编号 | 分类 | 原因和处理 |
| --- | --- | --- |
| 1 | 测试实现 | 渲染器已自动缩小大字号；旧负例没有制造文字碰撞。改为渲染后确定性注入重叠，保留碰撞检测断言。 |
| 2 | 测试契约 | 自动 dB 上限已有有限峰值封顶；预期只计算 percentile + 5。同步预期，不改算法。 |
| 3 | 测试契约 | nfft_facts_signature 是有效参数来源签名，不是 SpectrogramParams 的 DSP 字段。 |
| 4, 5, 6 | 验收工具 | 把有来源证据的正常 MF4 时间轴说明误判为降级。仅放行匹配来源诊断的精确说明；新增无证据说明、未知 warning 的拒绝测试。 |
| 7 | 样本工具 | 帮助截图生成器写出的 ZFGE2 头部、记录布局不符合实际解析器。修复样本字节布局。 |
| 8 | 产品 UI | FRF 局部排队的对齐定时器覆盖页面跨 pane 的轴宽，造成约 3 px 左边距差。跨 pane 对齐时取消旧局部 settle。 |
| 9 | 产品 UI | FFT-time 两栏未统一 colorbar 刻度轴宽，主图相差约 7.86 px。把 colorbar 轴宽纳入共享几何对齐。 |
| 10, 11 | 测试实现 | 选中 pill 是按钮的兄弟控件；只 grab 按钮漏掉选中背景。改采集父容器后裁剪，等待 pill 到位，并处理 Retina 像素比例。 |
| 12 | 产品 UI | 局部 checked 透明规则覆盖按下反馈。补充 checked:pressed 样式，保留真实像素差断言。 |
| 13, 14, 15, 16 | 测试契约 | 批处理默认只输出图片；需要 CSV+PNG 数量的测试必须显式启用数据输出。 |
| 17, 18 | 测试契约 | 工具栏现在经过滚动宿主，间距为 1；更新结构断言，仍检查 toolbar/canvas/hintbar 顺序。 |
| 19, 20, 21 | 测试构造 | 分析页面延迟创建，测试直接读取尚未创建的 canvas；先建立对应分析页面。 |
| 22 | 测试契约 | 后台计算提交携带 pane_token；spy 使用旧参数列表。保留进度与取消令牌断言。 |
| 23, 24 | 测试构造 | 计算使用已提交 pane.time_range，旧测试仅修改 Inspector 草稿。 |
| 25 | 测试契约 | 提示队列已有六条新增项，旧完整顺序预期缺项。 |
| 26, 27, 28, 33, 34, 35 | 测试契约 | 自动频率轴采用完整结果范围，旧断言仍要求能量带裁剪；手动范围断言继续保留。 |
| 29, 30, 31 | 测试构造 | 伪造 preset kind/mode 被当前 schema 拒绝，apply fake 也未更新 live 状态；改用真实 FFT/window 参数和有状态 apply。 |
| 32 | 测试构造 | 叠加风险计算读取保存的视图滤波配置，旧测试只 mock 隐藏 Inspector 控件。 |
| 36, 37 | 测试构造 | 缓存测试缺注册数据源、pane 意图及有效参数来源，触发真实缓存有效性防线；补齐真实请求，保留命中不重算断言。 |
| 38 | 测试构造 | 测试在非活动分析页面修改选择；先切换到对应模式再操作。 |
| 39, 40, 41, 42, 43 | UNKNOWN | 两个 hover、三个 pin 用例在修改前即通过，后续模块回归也通过。输入按键泄漏可独立复现，但不能证明它是这五项历史失败的完整原因。 |
| 44 | 测试构造 | close-all 的分析 pin 用例缺延迟页面初始化；补齐页面后原清理断言通过。 |
| 45 | 测试实现 | 共享历史导航改走分组 _step_history，旧 spy 挂在不再调用的方法上；改断言实际历史位置和前进后退结果。 |
| 46, 47 | 测试构造 | dispatch fake 缺真实 AnalysisMixin 请求路径；补齐 owner，继续比较主路径与 fallback 的缓存键。 |
| 48 | 测试构造 | 热路径 fake 缺视图索引、当前曲线绑定及显示更新 scope；补齐 seam，保留禁止全数组统计断言。 |
| 49 | 测试契约 | 公开方法冻结表缺已采用的 capture_before_section_hidden。 |
| 50 | 样式维护 | 重复选择器超过只减不增的白名单；合并四处重复规则，保留最终声明。 |
| 51 | 样式维护 | 新增颜色字面量超过 ratchet；提取已有共享/交互色 token，原始颜色数降到 208，收紧门槛。 |
| 52 | 样式维护 | 删除真正停用的 PopoverSurface/cursorPillToggle 规则；有效参数卡片 objectName 改为显式映射，供静态活性检查识别。 |
| 53 | 测试契约 | 批处理方法已采用工具栏 pill 渐变，旧测试仍要求已废弃下划线。 |
| 54 | 测试隔离 | 消息处理器恢复测试把此前 Qt 平台消息也算入哨兵结果；发哨兵前清空无关历史消息，仍严格验证原 handler 恢复。 |

## 额外隔离问题与采集 error

确认 QTest 在 mousePress 后遇到断言失败，会把进程级鼠标按下状态带给后续用例，即使原 widget 已删除。新增有界子进程回归：第一项故意失败，第二项必须看到 NoButton；修复前两项均失败，修复后保持第一项失败而第二项通过。UI teardown 向私有 sink 释放残留按键，不点击存活的产品控件，也不吞掉原失败。注入按下状态能破坏 pin 用例，但五项历史间歇失败的确切污染链尚未证明。

采集 error 的触发点虽在 `test_a2l_raster_freeze_during_recording` 拆除，来源是前面的 `test_dropped_frames_prompt_shown_over_threshold` 遗留 50 ms QTimer 回调：提示框已变为非模态，测试结束后回调再访问已删除 QMessageBox。移除过时定时器，在当前测试中断言提示并同步关闭，采集目录完整独立回归已通过。

## 验证

| 范围 | 实际结果 | 说明 |
| --- | --- | --- |
| 原 54 项当前对应节点 | **54 passed**，9.10 s | `final54.log`；包含必要的语义重命名，无 xfail 或跳过 |
| 原失败 owner 模块及 ui_kit | **1286 passed、1 failed**，322.42 s | 唯一失败是本轮误删宽带测试仍使用的 import；已恢复并由下一 gate 覆盖，未把这次 run 改写为全通过 |
| 后续 owner/隔离回归 | **584 passed、6 skipped**，32.08 s | 包含修正后的宽带测试、鼠标隔离子进程、QSettings/fixture、按钮、pin、ui_kit、验收工具 |
| 几何、owner 和导入/状态边界 | **350 passed、1 skipped**，18.43 s | `boundaries.log` |
| 采集界面完整独立回归 | **369 passed、2 skipped、0 error**，14.58 s | `acquisition.log` |
| macOS Cocoa 真实 MainWindow 分栏几何 | **2 passed** | FRF 与 FFT-time，1500×1000，生产 QSS、字体及合成结果，已检查截图 |
| macOS Cocoa 真实 BatchSheet 按下反馈 | **1 passed** | 父容器真实渲染像素差，已检查截图 |
| 批处理 header 最终跨平台像素测试 | **offscreen 5 passed；Cocoa 5 passed** | Cocoa 扩展检查发现逻辑/设备像素混用，统一截图坐标后重跑；`header-final.log`、`header-cocoa-final.log` |
| QSS 声明等价 | 通过 | 解析 token 和 border 后，所有保留选择器的最终声明与 HEAD 相同；仅删除停用选择器。该检查不包含独立修复的局部按钮 pressed QSS |

这些是定向回归和原生几何证据。本次没有重跑约四小时的主体全套，不能宣称全库全绿；没有运行新构建 Windows Full/Lite 冻结 EXE，源码验收工具测试不等同于冻结包验收。原生 probe 使用合成数据，不等同于用户项目的完整前台验收。

## 原始 54 个失败节点索引

1. `tests/test_batch_qt_render_parity.py::test_text_overlap_guard_measures_ink_not_layout_boxes`
2. `tests/test_batch_render_qt_heatmap.py::test_heatmap_auto_levels_are_exact[order_time-params1-None]`
3. `tests/test_cache_key_dataclass_binding.py::test_fft_time_analysis_key_field_set_equals_spectrogram_params`
4. `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_uses_batch_runner_for_three_mf4_csv_png_sets`
5. `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_rejects_manifest_source_not_in_requested_set`
6. `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_binds_executable_sha_to_frozen_smoke`
7. `tests/test_gen_help_screenshots.py::test_import_screenshot_builds_clean_checkout_parser_samples`
8. `tests/ui/test_analysis_section_page.py::test_split_frf_plot_areas_align_all_three_rows`
9. `tests/ui/test_analysis_section_page.py::test_split_fft_time_heatmap_and_slice_plot_areas_align`
10. `tests/ui/test_batch_header_render.py::test_method_accent_persists_after_selection`
11. `tests/ui/test_batch_header_render.py::test_method_selection_and_keyboard_focus_have_visible_feedback`
12. `tests/ui/test_batch_header_render.py::test_selected_method_still_responds_visually_when_pressed`
13. `tests/ui/test_batch_runner_thread.py::test_runner_thread_marshals_real_render_to_gui_and_returns_complete_result`
14. `tests/ui/test_batch_toolbar.py::test_run_click_uses_real_group_preview_artifact_count[none-8]`
15. `tests/ui/test_batch_toolbar.py::test_run_click_uses_real_group_preview_artifact_count[source-6]`
16. `tests/ui/test_batch_toolbar.py::test_run_click_uses_real_group_preview_artifact_count[channel-6]`
17. `tests/ui/test_chart_card_construction.py::test_toolbar_chrome_and_action_widgets`
18. `tests/ui/test_chart_card_construction.py::test_card_layout_order_is_toolbar_canvas_hintbar`
19. `tests/ui/test_compute_progress_integration.py::test_fft_multi_source_progress_wraps_cache_misses_only`
20. `tests/ui/test_compute_progress_integration.py::test_fft_time_do_begins_progress_for_cache_miss_only`
21. `tests/ui/test_compute_progress_integration.py::test_order_do_begins_progress_for_cache_miss_only`
22. `tests/ui/test_compute_progress_integration.py::test_order_job_closure_passes_progress_callback_and_cancel_token`
23. `tests/ui/test_fft_fetch_signal.py::test_range_enabled_masks_signal_inclusive`
24. `tests/ui/test_fft_fetch_signal.py::test_range_bounds_are_inclusive`
25. `tests/ui/test_hint_nudges.py::test_view_compact_tabs_ranks_between_coaxis_custom_action_and_batch_export`
26. `tests/ui/test_inspector.py::test_fft_auto_xlim_keeps_low_frequency_spectrum_tight`
27. `tests/ui/test_inspector.py::test_plot_fft_entries_auto_xlim_includes_all_overlay_sources`
28. `tests/ui/test_inspector.py::test_plot_fft_entries_auto_xlim_uses_raw_amp_in_db_mode`
29. `tests/ui/test_inspector.py::test_builtin_preset_second_left_click_reapplies_or_noops`
30. `tests/ui/test_inspector.py::test_recommended_only_builtin_click_still_loads_preset`
31. `tests/ui/test_inspector.py::test_recommendation_change_does_not_clear_baseline_selection`
32. `tests/ui/test_main_window_overlay_risk.py::test_estimate_overlay_risk_uses_checked_range_and_effective_filter`
33. `tests/ui/test_main_window_smoke.py::test_fft_time_render_auto_frequency_range_uses_energy_band`
34. `tests/ui/test_main_window_smoke.py::test_plot_fft_entries_auto_xlim_uses_energy_band_and_manual_stays_fixed`
35. `tests/ui/test_main_window_smoke.py::test_render_fft_time_on_auto_freq_range_uses_energy_band`
36. `tests/ui/test_main_window_smoke.py::test_fft_time_analysis_cache_hit_status`
37. `tests/ui/test_main_window_smoke.py::test_fft_time_primary_hit_skips_nonuniform_preflight_and_service`
38. `tests/ui/test_main_window_smoke.py::test_fft_panel_keeps_signal_selection_across_channel_edit`
39. `tests/ui/test_pill_switch.py::test_pill_switch_hover_and_pressed_change_ink_not_geometry[False]`
40. `tests/ui/test_pill_switch.py::test_pill_switch_hover_and_pressed_change_ink_not_geometry[True]`
41. `tests/ui/test_pinned_cursor_panels.py::test_live_consumed_after_single_pin_returns_on_next_move`
42. `tests/ui/test_pinned_cursor_panels.py::test_dual_pin_hides_live_and_keeps_placement`
43. `tests/ui/test_pinned_cursor_panels.py::test_live_p_button_pins_current_readout_not_button_coords`
44. `tests/ui/test_session_reset_on_last_close.py::test_close_all_clears_pins_while_restoring_project`
45. `tests/ui/test_split_per_pane_controls.py::test_shared_nav_back_forward_runs_each_pane_toolbar`
46. `tests/ui/test_task4_cache_invalidation.py::TestFallbackKeyAlignsPrimaryKey::test_fft_time_dispatch_key_equals_lookup_key_for_each_pane`
47. `tests/ui/test_task4_cache_invalidation.py::TestFallbackKeyAlignsPrimaryKey::test_fft_time_single_path_uses_same_key_builder_as_main_path`
48. `tests/ui/test_timedomain_hotpath_perf.py::test_disabled_stats_strip_skips_full_array_statistics`
49. `tests/ui/test_ultraview_compatibility.py::test_coordinator_public_methods_are_frozen`
50. `tests/ui_kit/test_qss_duplicate_selectors.py::test_duplicate_selectors_match_shrink_only_whitelist`
51. `tests/ui_kit/test_qss_palette_ratchet.py::test_distinct_hex_literals_may_only_shrink`
52. `tests/ui_kit/test_qss_selector_liveness.py::test_dead_object_names_match_shrink_only_whitelist`
53. `tests/ui_kit/test_selection_signature.py::test_batch_method_tabs_are_not_in_the_shared_pill_family`
54. `tests/ui_kit/test_stylesheet_parses.py::test_live_stylesheet_parse_keeps_preexisting_qt_message_handler`
