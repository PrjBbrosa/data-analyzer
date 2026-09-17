# 页面切换动效安全性与性能 Follow-up 验证

日期：2026-09-16。计划：`docs/analyzer/plans/2026-09-16-page-transition-safety-performance-followup-plan.md`。基线 HEAD：`0bcac91e1ceb39fd7ed709056ebfd10554b392c8`。工作区另有 FFT 游标在途修改，本补丁只追加过渡相关代码，未回退那些改动。

**结论：生命周期修复已落地；时域单 Pane Light 保持启用。** 原生 Cocoa/Windows 性能门为 **UNKNOWN**，不能把 offscreen 通过写成前台验收。

## 生命周期修复

根因：`PageTransitionController.eventFilter` 在 target ready 后把目标 `QEvent.Paint` 当成 `target-surface-invalidated`。生产路径监视真实 canvas/viewport；既有 `QObject` fence 与手工 `clock().setCurrentTime(300)` 测不到这条路径。F0 用真实 QWidget 自然 `update()` 复现：ready 后一次 expose 立即结束动效。

修复：

1. Paint 不再作为输入面失效事件。resize / move / hide / close / parent / DPR 仍取消。
2. `TimeDomainCanvasPG.presentation_content_invalidated` 覆盖 `clear()`、选择 delta、subplot reuse、显示原始/滤波可见性。ChartStack 在 fence 期间监听；`keep_target=True` 清掉 paint ack 后仍保留该监听。
3. ready 后冻结已承认目标的 `updatesEnabled`，避免半透明 overlay 每帧重放 GraphicsView。结束/取消/重定向后恢复；质量 `update()` 排队到揭盖后执行。

Offscreen 证据：`test_ordinary_ready_paint_does_not_cancel_live_fade`、`test_live_widget_natural_paint_completes_fade_without_manual_clock`、`test_time_tab_switch_completes_natural_fade`（`view_tabbar.switch_requested` → `_switch_view`）、内容失效 / 关闭 / 超时 / A→B→C。生产 MainWindow 在合成 CSV、两个 View 上自然 ack 并 `transition_finished`，取消原因为空。

## Off 原卡顿

本轮未分离 capture、restore/prepare、画布 paint 与捕获尾部的主线程阻塞。Light 仍在离开端点做一次 `QWidget.grab`；未改 `TimeRenderGate`、settle 顺序或 ink/AA。原卡顿 **未宣称修好**。

## Light 增量

| 观测 | 结果 |
|---|---|
| 冻结前 viewport Paint（offscreen MainWindow 切换） | 22 次，接近 300 ms × 60 Hz 量级 |
| 冻结后同一用例 | ≤8 次（断言 `test_time_tab_switch_completes_natural_fade`） |
| 目标 `grab` | 生产路径仍为 0 |
| 动画期间 plot/setData | 无新增计算路径 |
| overlay paint P95 / heartbeat / 64 MiB / 20 次反向 | **UNVERIFIED**（无 Cocoa 采样） |

未引入目标二次截图。冻结属于同一事务内对语义相同 expose 的去重，不是黑盒启发式准入。

## 平台门与启用范围

| 门 | 状态 |
|---|---|
| Offscreen focused + 边界 | 106 passed（owner / View 删除 / reentrancy / UltraView source reuse / split exit / restore+discrete settle+backstop+selection delta / lambda / 状态所有权 / import / backref） |
| Cocoa 前台自然动画、连点/反向、清晰度 | **UNKNOWN** |
| Windows 源码 / Full / Lite | **UNKNOWN** |
| 全量 suite | 未跑（无新证据要求扩展） |

启用范围不变：`set_page_transition_enabled_sections(("time",))`，单 Pane、有文件。FFT/FRF/热图、分屏、跨 Section 仍直接终态。hints/quickref 未改：这是已启用路径的修复，不是新交互。

## 未做

- 未提交、未 bump 版本。
- 未改采样/滤波/FFT/结果缓存。
- `stack.py` 中 FFT 游标在途 diff 保留；本补丁只动 page-transition 方法与 `_page_transition_content_slots` 初始化。

## 2026-09-17 后续台账

历史启用范围（仅 time）与上表保留为当时事实。当前生产已全开五个 Section（见扩展验证记录）。本轮 follow-up 生命周期合同未回退；新增的是审查修复 F1/F2 廉价准入，不重测 Cocoa。overlay paint P95 / Windows 仍 **UNKNOWN**。
