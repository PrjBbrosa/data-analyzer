# 多 Pin 面板随 View 整体呈现的小计划

状态：已实施。2026-09-22；时域 View 恢复把 Pin 收成一次提交，转场在画布自然绘制和 Pin 提交都到齐后才淡入。

## 目标与范围

切回含多个固定 cursor 面板的 View 时，曲线、面板数值、P 标签和连线作为一个完整画面出现，避免面板抢先显示、数值替换和位置跳动。第一轮处理截图对应的时域 View 切换；共享 Pin 层的调整必须保护分析页与分屏行为。保留 P 编号、用户拖放位置、折叠状态、数值/完整模式、源通道身份和采样语义。

本轮仅写计划，没有修改产品代码，也未运行测试或逐帧复现。截图证明最终布局，用户反馈描述动态问题；下面的时序与层级依据来自当前源码，具体可见帧和重复采样次数仍需探针确认。

## 已定位的路径

1. **Pin 在曲线恢复前被投影。** `_view_mixin.py:1043` 先调用 `apply_controls_from_state`；`view_bridge.py:305` 随即恢复 Pin 集合。`pinned_cursor_controller.py:363` 的 `set_collection()` 清理旧面板后，立即执行 `_mark_records_pending()` 并安排 0 ms 重投影。
2. **待更新状态也会显示面板。** `pinning/presentation.py:388` 的 `project_record()` 创建 `CursorPill(stack)`，根据展开状态显示并 `raise_()`；pending 内容与最终数值内容不同（同文件 `pill_content()`），数值到达还会重新排版。`_on_chart_rebuilt()` 又同步重投影，随后另有几何重排队列。
3. **画布抑制刷新不能覆盖面板。** `_view_mixin.py:1054` 才进入画布刷新抑制范围；`canvas.py:3252` 只禁止 canvas 子树更新。面板与底部 P 标签是 `stack` 的直接子控件，不属于 canvas 子树。
4. **现有转场没有等待完整目标画面。** `stack.py:1742` 只收集 canvas 的自然绘制确认，然后启动淡入。转场遮罩也位于 `stack`，Pin 的 `raise_()` 可以改变它们之间的堆叠关系。缺少“目标 Pin 内容和布局已提交”的就绪条件。

上述组合足以解释当前结构为何会暴露中间状态；不能据此直接断言采样算法错误。另需确认 0 ms 回调是否在绘图过程的事件循环让步中提前执行。

## 方案选择

| 方案 | 效果与代价 | 决定 |
| --- | --- | --- |
| 每张面板独立延迟、渐入 | 多个动画时钟；数据和布局中间态仍可能泄露，Pin 越多越拖沓 | 不采用 |
| View 恢复期间暂存目标呈现，全部就绪后整体转场 | 复用现有转场，统一层级和提交时机 | 推荐 |

视觉节奏：**保留旧 View 的完整画面 → 在遮罩下准备目标曲线、全部 Pin 内容与最终布局 → 整体淡入一次**。沿用当前 `motion.py` 的 `page_transition=240 ms` 与 motion policy，不先调时长；不加错峰、位移或数值滚动。motion 关闭或分屏等原有直接呈现路径也应一次提交完整画面，不强行动画。

## 实施步骤

### 1. 固定时序证据

- 用真实 MainWindow 构造 0、1、3、5 个展开 Pin 的 View，以及有不同通道/范围的第二个 View，记录切换前至转场结束的事件和帧。
- 记录请求/View 身份、集合 scope、canvas generation/revision、pending/最终内容投影、面板尺寸与位置、layout flush、自然 paint 和转场接受。区分程序调用与实际曝光，不仅检查最终截图。
- 在 `test_pinned_cursor_lifecycle.py` / `test_page_transition_integration.py` 增加能失败的边界测试：首个可见目标帧不得包含 pending→数值的替换，也不得显示部分目标 Pin；保持现有普通重算的 pending 状态反馈。

### 2. 把 Pin 呈现纳入现有 View 恢复事务

- `_view_mixin.py` 只负责开始/结束本次恢复；`PinnedCursorController` 管理每个 canvas 的短期呈现批次，`pinning/presentation.py` 负责内容、排版、层级与批量提交。避免新增跨 mixin 状态簇。
- 集合替换与采样仍按原身份规则运行；在恢复事务内合并无效化与重投影请求，暂存目标面板内容，不曝光逐条 pending/ready 更新。最终采样必须匹配目标绑定，禁止对旧 canvas 绑定作提前采样或通道裁剪。
- 保持既有 X→Y→ticks→`settle_view_restore()` 顺序和 150 ms 交互 quiet timer。最终 Pin 内容排版、面板排布、P 标签和连线在目标几何确定后统一 flush，保留用户锚点。
- Pin 的 `raise_()` 与可见性服从当前呈现批次，不能越过有效转场遮罩；旧端点捕获仍应包含离开 View 时的 Pin。直接呈现路径在同一批次结束时发布。

### 3. 接入完整画面的就绪与取消

- `ChartStack` 在当前 token 的“Pin 最终内容/布局提交”与“目标 canvas 自然绘制确认”均满足后，才交给现有 `PageTransitionController.accept_target()`。提前到来的确认应记账并校验身份，不能误接受另一轮请求。
- 先提交遮罩下的目标，再请求/确认自然绘制，避免等待被自身禁用的绘制形成死锁。就绪包括“确定不可用/不兼容”等合法终态，不能永远等待每个 Pin 都有数字。
- 快速 A→B→C、空集合、删除 View、切区、分屏、缩放/resize、关闭和异常都必须释放暂存、输入限制与等待；过期回调不能复活旧面板。沿用现有 watchdog 的退出机制，超时不得冒充 ready；退出时展示当前有效状态，不长期遮挡界面。
- 恢复中的交互覆盖面板、P 标签和曲线，保持现有“未就绪拦截、就绪后首个输入结束转场并正常处理”规则；不引入事件重放或可持久化动画状态。

## 验收与检查

- **视觉**：切回 3/5 Pin View，目标首帧包含最终文字、尺寸、位置和连线；不逐张出现，不在淡入后再次跳数值/挪位置。A→B→C 无串台和残影，空 View 无遗留 Pin。
- **行为**：采样值与原路径一致；P 编号、展开/折叠、数值/完整、拖动锚点保持；导航不产生额外 project dirty。普通重算仍能明确报告 pending/不可用。
- **focused**：`tests/ui/test_pinned_cursor_lifecycle.py`、`test_pinned_cursor_geometry.py`、`test_pinned_cursor_interaction.py`、`test_page_transition.py`、`test_page_transition_integration.py`、`test_view_switch_integration.py`。如共享桥接改动，补 `test_analysis_view_bridge.py` 与 `test_section_page_transition.py`。
- **boundary**：`test_pinned_cursor_architecture.py`、`test_main_window_state_ownership.py`；若改 canvas collaborator 则补 `test_pg_canvas_backref_invariants.py`；触及恢复结算则补 `test_pg_timedomain_canvas.py::TestViewRestoreSettlement` 与 `::TestDiscreteSettle`。
- **原生**：macOS Cocoa 与 Windows 各做真实切换的连续帧检查，包括多 Pin、快速重定向及 125%/150% Windows 缩放；离屏测试不能代替原生动效验收。比较切换到最终画面的耗时与重投影次数，不通过固定 sleep 换取视觉稳定。
- 本次文档交付仅检查引用、范围、一致性及 `git diff --check`；没有可执行行为改动，不运行 runtime/full suite。后续实施先跑相关 focused；本任务不要求全套或发布构建。
