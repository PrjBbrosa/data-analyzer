# Cockpit 实时卡片就地 Focus 与有限视口利用 Spec

Date: 2026-07-10  
Status: Implemented and verified  
Plan: `docs/analyzer/acquisition/plans/2026-07-10-cockpit-live-card-inplace-focus-implementation.md`  
Interaction reference: `docs/analyzer/acquisition/reports/2026-07-10-live-monitoring-interaction-model.html`  
Parent: `docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-preview-first-principles-spec.md`

## 1. 决策与第一性原理

笔记本采集界面的稀缺资源是**中间曲线区的有效像素高度**，不是额外的
标题栏、槽位说明区或第二张同源曲线。

因此，“查看某路细节”不能切换到一张孤立的 Focus 页面，也不能在同一卡内
并排/上下重复绘制缩略趋势和放大趋势。最终交互是：

- 中央仍是现有的纵向 `QScrollArea` 卡片流；不新增顶部槽位条、左侧管理面或
  独立 Focus 页面。
- 单击任一实时卡后，**同一个** `Sparkline` 在原卡内扩高；卡片流不丢其余卡。
- 被选卡最多占卡片滚动视口的 80%，目标为 78%；剩余高度用于露出其上下相邻卡，
  使用户知道自己仍位于同一组实时信号。
- 相邻卡以低对比度“退后”，而非昂贵的 `QGraphicsBlurEffect`；不得新增每帧扫描、
  第二个曲线 widget 或第二份样本缓存。

当前实现不符合该目标：`focus_channel()` 重新渲染后只保留目标名
（`live_cards.py:1615-1638`），并在滚动区上方显示额外 `liveFocusShell`
（`1397-1410`）。现有单击测试也锁定了“只剩一张卡”的旧行为
（`tests/acquisition_ui/test_live_cards.py:365-396`）。本 spec 有意替换这项
Cockpit 行为；Replay 的既有隔离式 Focus 保持不变。

## 2. 目标

1. 让已选实时卡可以在原有卡片流中放大查看，不浪费有限笔记本视口。
2. 放大卡只绘制一条、同一数据源的趋势线；颜色、30 秒时间语义、Y 轴语义与
   紧凑态一致。
3. 放大时仍保留相邻卡的弱上下文，收起后回到同一滚动位置与完整卡序。
4. 不改变采集、写盘、pin 集、状态机、阈值、样本刷新或 Replay 的产品契约。

## 3. 明确非目标

- 不做滚轮缩放、框选、游标 dt/dy、手动 Y 范围、暂停显示、overlay 共轴或
  10/30/60 秒切换。
- 不实现非 pin 已选通道的驻留显示缓存或新的左栏“Focus 打开”入口；本波的
  上一/下一通道仅遍历当前实时卡流（有效 pin 集）。
- 不新增顶部“槽 1–5”说明条，不卡片流外再放 Focus 标题条，不增左侧管理 UI。
- 不改 `ReplayTab` 的布局或交互；它保持当前隔离式 Focus，除非后续单独立 spec。
- 不改 `CaptureController`、`sample_tap`、writer、recording ring、预检、健康
  band、`SessionConfig` 或 pin 的有效计算逻辑。

## 4. 范围与架构边界

| 层 | 责任 | 文件 |
| --- | --- | --- |
| Cockpit 装配 | 显式启用就地 Focus；Replay 不启用 | `main_window/_toolbar_mixin.py` |
| 卡片 | 单一 Sparkline、内联 Focus 控制、动态状态 | `widgets/live_cards.py` |
| 卡片流 | 保留卡序、分配焦点高度、滚动定位、上下文弱化 | `widgets/live_cards.py` |
| 样式 | `focusState` 的边框/文字/控制状态；保留 Replay 的 isolated shell 样式；不得造第二张曲线 | `ui_kit/style.qss` |
| 自动证明 | 几何、单 trace、顺序、返回、模式隔离 | `tests/acquisition_ui/test_live_cards.py`、`test_pinned_monitoring.py` |
| 运行证明 | 焦点截图、几何断言、录制态不回流 | `scripts/cockpit_ui_tour.py` |

`LiveCardGrid` 新增 presentation 区分：默认 `isolated` 保持 Replay 旧行为；
Cockpit 中央 grid 明确设为 `inplace`。这是显示层开关，不得传入采集层。

## 5. 交互与状态契约

### F1 — 卡序保持

**不变量：Cockpit 的就地 Focus 不会把其他实时卡从 layout 或 `grid.cards` 中移除。**

- overview：所有有效 pin 卡按当前顺序纵向排在 `liveCardGridScroll` 中。
- 单击卡 A：`focused_channel == A`，卡序、卡实例、`Sparkline` 实例和 buffer 均保留。
- 收起：`focused_channel is None`，卡序和用户进入 Focus 前的垂直滚动位置恢复。
- 若 `set_signals()` 后 A 不再是有效 pin，清空 Focus；不得持有隐藏/已删除卡。

### F2 — 单一曲线契约

**不变量：任一 `LiveSignalCard` 始终只有一个 `Sparkline` child；Focus 不得创建、
复制、叠加或缓存第二条趋势。**

- 现有 `LiveSignalCard._spark`（`live_cards.py:1161-1166`）是唯一绘制面。
- 普通态使用其紧凑高度；Focus 态只改变该 widget 的几何和可用绘图区。
- 放大曲线颜色沿用该卡的 `_trace_color`；录制态仍遵守现有红色 swatch/红左边框
  语义，不能把曲线伪装为第二种颜色。
- Focus 态使用 TimeDomain 同类的数值化网格密度：`10×10` visual divisions；紧凑态
  与 context 卡保持原有 `4×4`，不新增全局 Inspector/toolbar 设置，也不改变坐标范围。
- 顶部 name / raster / unit / current value 仍只有一份；Focus 控制并入现有 header，
  不额外占用一行垂直空间。Focus 态隐藏 stats，优先把高度交给曲线。

### F3 — 视口预算与滚动定位

**不变量：Focus 卡的外部高度 `H_focus` 满足
`H_focus <= floor(0.80 × H_viewport)`；实现目标为 78%。**

- `H_viewport` 是 `liveCardGridScroll.viewport().height()`，不包含窗口 toolbar、
  summary bar 或任何已移除的 Focus shell。
- 焦点卡布局完成后取 `floor(0.78 × H_viewport)`；卡 header 和 controls 包含在该预算
  内，`Sparkline` 获取所有剩余高度。
- 中间目标卡至少保留上、下各一段相邻卡可见区域；可见卡带至少 24 logical px。
  首尾目标仅要求现有邻侧可见，绝不伪造不存在的前/后卡。
- 焦点切换后将目标卡居中滚入视口；不得水平滚动。
- 960px 窄窗口仍保留 name/current value 优先级和 `<430px` 的 Y 文本让位规则，
  不以增加最小窗口高度解决空间问题。

### F4 — 上下文弱化

**不变量：Focus 时相邻卡可见、可识别为同组信号，但不得与目标卡竞争。**

- 非焦点卡设置 `focusState="context"`；焦点卡设置 `focusState="active"`；无 Focus
  时设为 `normal` 或清除属性。
- context 卡使用低对比度/约 45% opacity 的显示效果；不使用
  `QGraphicsBlurEffect`，避免模糊文本、扩大离屏合成成本或引入渲染伪影。
- context 仅是视觉状态：曲线仍按原频率刷新、样本仍进入原 buffer、点击任一 context
  卡可将其变为新的焦点。

### F5 — 内联控制与可达性

- Focus 控制在活动卡 header 右侧：`上一通道`、`下一通道`、`收起`；Cockpit 的
  `inplace` 路径不显示 `liveFocusShell` / `liveFocusBar` / `liveFocusBackButton`。
  这些旧对象与其 QSS 仍服务于 Replay 的 `isolated` 路径，不能全局删除。
- 上一/下一按当前 `_all_signals`（即有效 pin）顺序循环；不访问未渲染的已选通道。
- `Esc` 在 Cockpit 处于 Focus 时等价于“收起”；卡片和 controls 维持键盘可达。
- 单击活动卡本体不隐式收起，防止误触；收起只能来自显式按钮或 Esc。

### F6 — 状态与性能

- idle↔recording 的 body 宽度零位移契约保持；Focus 不改变 splitter 宽度。
- Focus 期间 `push_sample()` / `refresh_all()` 继续驱动五张卡；不得复制 raw deque、
  display buckets 或统计扫描。
- 只允许一次 layout/geometry 调整（布局稳定后排队执行）；禁止每帧根据视口高度重算
  Focus 布局。
- 容量仍为默认五张实时卡；`liveMonitorSummary` 仍是一行紧凑事实提示，不能演变为
  槽位管理 strip。

### F7 — 模式隔离

- Cockpit 调用 `set_focus_presentation("inplace")`；Replay 默认 `isolated`，并继续满足
  当前“只显示目标卡 + 返回全部”测试/视觉行为。
- pin/unpin/reset 或 selection 更新不能重启 backend / idle stream；Focus 只改中心显示。
- 断开态与零卡占位维持现状；Focus 不能让 ECU 语义泄漏到 Replay placeholder。

## 6. 验收矩阵

| 场景 | 自动验收 | 真机/渲染验收 |
| --- | --- | --- |
| Cockpit 3/5 卡 overview | 卡序、单 Sparkline、focus shell 隐藏不占位 | 无额外标题/槽位/左侧管理面 |
| 中间卡 Focus | 五张仍在、目标高 ≤80% viewport、上下 context 可见 | 一张放大曲线；上下卡淡化不消失 |
| 首/尾卡 Focus | 仅现有邻侧保留 context | 不出现空白假卡 |
| 上一/下一/收起/Esc | 顺序循环、返回原滚动位置、实例/buffer 不丢 | 控制在 header 内，不额外吃一行高度 |
| 960px 窄窗 | name/value 与窄宽规则不回归 | Focus 不溢出、不迫使窗口变高 |
| 录制切换 | center 宽度不变、样本仍刷新 | recording 红色语义仍正确 |
| Replay | 保留隔离式 Focus | Replay 视觉零回归 |

## 7. Execution record (2026-07-10)

- Cockpit explicitly selects `LiveCardGrid.set_focus_presentation("inplace")`;
  Replay keeps the default `isolated` presentation and its existing return bar.
- Focus evidence: the active card retains its sole `Sparkline`, uses exactly 78%
  of the settled scroll viewport (capped at 80%), and leaves real sibling context
  bands above/below for a middle card. Esc, previous/next, and explicit collapse
  preserve card/buffer identity and restore the prior scroll position.
- Focused pytest regression passed: `71 passed in 1.67s` across live cards,
  pinned monitoring, Replay, and visual-shell suites.
- Tour evidence passed both offscreen and macOS on-screen. Focus screenshots:
  `/tmp/cockpit-inplace-focus-offscreen/03c-inplace-focus-card.png` and
  `/tmp/cockpit-inplace-focus-onscreen/03c-inplace-focus-card.png`.
- The on-screen tour uses the repository's FAKE demo backend. ECU hardware
  transport remains outside this display-layer scope and was not asserted here.
- Follow-up: Focus-only grid density is `10×10`; compact/context cards remain
  `4×4`, using TimeDomain's numeric-density principle without adding a second
  user-facing chart setting.

验收命令一律用项目 venv；offscreen 用于结构/几何，macOS on-screen tour 截图才是
最终视觉证据。
