# 各 Section 页面切换动效扩展 — 验证记录

日期：2026-09-17。计划：[2026-09-16-all-sections-page-transition-expansion-plan.md](../plans/2026-09-16-all-sections-page-transition-expansion-plan.md)。前置 follow-up：[2026-09-16-page-transition-safety-performance-followup.md](2026-09-16-page-transition-safety-performance-followup.md)。

**结论：生产已启用五个 Section 的单图用户导航淡入。** 用户于 2026-09-17 明确要求全开，覆盖计划 §6 成本门。分屏、程序恢复、未计算 cache-miss 仍直接终态。plan §6 的 Cocoa 30 样本与 Windows 证据仍缺失，性能准入为 **UNKNOWN**，未填 P95。不得把 offscreen 通过写成前台验收。

## 总表

| 类别 | 已接线 | offscreen 功能验证 | 性能准入（§6） | 生产实际启用 | Cocoa | Windows |
|---|---|---|---|---|---|---|
| Time 内部 View | 是 | `test_time_single_pane_user_switch_keeps_light_and_matches_off_terminal`；follow-up `test_time_tab_switch_completes_natural_fade` | UNKNOWN | **是**（单 Pane、有文件、Light） | UNKNOWN | UNKNOWN |
| FFT 内部 View | 是 | `test_e1_fft_cache_hit_light_fade` / cache miss / preview / empty / retained reveal；`test_uncomputed_fft_preview_switch_is_direct_terminal` | UNKNOWN | **是**（单 Pane；未计算预览仍直接终态） | UNKNOWN | UNKNOWN |
| FRF 内部 View | 是 | `test_e3_frf_multi_subplot_internal_switch` | UNKNOWN | **是** | UNKNOWN | UNKNOWN |
| FFT vs Time 内部 View | 是 | `test_e4_heatmap_slice_and_colorbar_invalidation` 块 A（`plot_result`） | UNKNOWN | **是** | UNKNOWN | UNKNOWN |
| Order 内部 View | 是 | 同上，块 B（`plot_or_update_heatmap` + RPM / 缺 RPM） | UNKNOWN | **是** | UNKNOWN | UNKNOWN |
| 20 向跨 Section | 是（`_on_mode_changed` + 两端 enabled 且协议齐） | `test_e5_production_enables_directed_edge` ×20；`test_e5_directed_cross_section_user_navigation_matrix` | UNKNOWN | **是**（单 Pane、有文件、目标已计算） | UNKNOWN | UNKNOWN |
| 分屏 / 多 Pane | 是：不抓图、直接终态 | `test_split_view_switch_is_direct_terminal` | 不适用（本轮不扩大双 Pane） | 直接终态 | UNKNOWN | UNKNOWN |
| 程序恢复 | 是：不 begin | `test_programmatic_paths_do_not_begin_page_transition`；`test_e5_close_and_open_project_leave_no_residue` | 不适用 | 直接终态 | UNKNOWN | UNKNOWN |

offscreen 不是性能准入。无 30 样本 Cocoa 不得外推 Light 增量。Windows 源码 / Full / Lite / DPI 未跑，保持 UNKNOWN。

## 生产开关

`mf4_analyzer/ui/chart_stack/page_transition.py` 与 `mf4_analyzer/ui/main_window/window.py`：

```python
PAGE_TRANSITION_ENABLED_SECTIONS = ("time", "fft", "fft_time", "frf", "order")
self.chart_stack.set_page_transition_enabled_sections(
    PAGE_TRANSITION_ENABLED_SECTIONS,
)
```

ChartStack 层仍可只启用子集；`test_measured_policy_does_not_enable_an_unadmitted_section` 看守该门。未计算目标、分屏、`open_project` / 预设 / 同目标点击不抓图。

## 文案

真实启用范围 = **五个图表工作区的单 Pane、有文件、目标已就绪的用户导航淡入**。

- `hints.py` `time.view_fade`：`单图切 View：就绪后淡入`，`modes` 为五个图表分区。
- `quickref.py`「时域 View」：单图淡入；分屏与项目恢复直接终态。
- `quickref.py`「分析页 View」：分析页单图与跨区同样淡入；分屏、未计算页、项目恢复直接终态。
- 未写「所有场景都有动效」。

## 未做 / 仍 UNKNOWN

- 未跑 Cocoa 前台 5 预热 + 30 样本；未报 P95。
- 未跑 Windows。
- 未跑全量 pytest / 整个 `tests/ui`。
- 未启用分屏 / UltraView / Batch / 采集动效。
- 未 commit / 未 bump 版本。
