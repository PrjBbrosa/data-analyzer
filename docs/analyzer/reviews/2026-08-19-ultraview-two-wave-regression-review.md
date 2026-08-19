# UltraView 最近两波回归 Review

- 日期：2026-08-19
- 结论：**NO-GO；当前两波不能作为可用功能交付**
- 审查范围：`a4d6c904..98636b3f`
  - Wave A：`83ad8e4e feat(ultraview): add authoring canvas foundation`
  - Wave B：`98636b3f style(ultraview): deepen card frost`
- 非范围：未跟踪的 `ssh-keygen` / `ssh-keygen.pub`，以及其他分析模块
- 配套恢复 Spec：`docs/analyzer/specs/2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md`
- 配套恢复 Plan：`docs/analyzer/plans/2026-08-19-ultraview-recovery-interaction-resize-autofit-plan.md`

## 1. 执行摘要

这两波不是“完成度差一点”，而是交付顺序和验收边界整体失守：

1. 创作工具的状态、DTO、绘制、导出和外观大量落地，但用户入口只走到
   `ToolRail.tool_requested.emit()`，Page 没有订阅，画布也没有交互控制器。因此五个可见按钮中，
   除 Select 之外都没有端到端产品行为。
2. 原实施计划写明“待授权执行”，并规定五个硬门缺一即 `BLOCKED`；提交却绕过硬门，先落了
   约 6,870 行变更。计划明确要求的 `author_tools.py` / 单一
   `BoardInteractionController` 反而缺失。
3. Resize 的既有热路径没有被性能化：每个 pointer move 都重新规划、重建 ghost 数据、请求整层
   repaint，并用 `SmoothPixmapTransform` 把原始 `QImage` 画到变化中的目标矩形。磨砂波又把卡片壳
   改成透明，拖动时原卡 0.4 opacity、ghost 0.45 opacity 叠加，放大了闪烁感。
4. 当前 Autofit 只是“固定 chrome 假设下的局部离散搜索”，不是对 live card 的真实
   `contentsRect()` 求解，也不是 Board 的全局最优布局；它只能先在当前 span 内缩小，再沿一个轴
   有限增长，随后还可能用 collision planner 挪动邻卡。
5. Frost 只改变卡片壳和 label 背景；抓图 `QImage` 仍是不透明白底。真实项目中占视觉主体的白色
   来自预览像素时，这一波不可能消除它。现有样式测试也只断言 token 值，没有验证 Cocoa 合成、
   圆角 backing、拖动状态或真实图表可读性。

建议不是继续补按钮或继续调 alpha，而是先做恢复波：默认隐藏未闭环创作入口，保住现有
UltraView；随后以一个完整 Sticky 垂直切片重新建立交互 owner、端到端测试和前台门，再扩到其他工具。

## 2. Findings

### [P0] 可见创作按钮是断路入口，用户无法创建任何对象

**证据**

- `chrome.py:1092-1094` 定义 `tool_requested` / `tool_pinned_changed`；
  `chrome.py:1497-1513` 点击后只更新 rail 状态并 emit。
- `page.py:486-518` 的实际 wiring 没有连接上述两个信号；Page 只连接 panel、FreeGrid、Sync、
  Board、Global 和 CardContext 行为。
- `page.py:3234-3245` 在 FreeGrid 中把全部创作按钮设为 enabled，因而向用户承诺它们可用。
- `author_layer.py:56-70` 明确是 mouse-transparent、non-interactive renderer；
  `widgets.py:3101-3108` 只创建投影 layer 和默认隐藏的 text editor。
- 计划要求 `author_tools.py`（plan `:36-44`）和单一 `BoardInteractionController`
  （plan `:145-160`），当前文件/owner 均不存在。

**前台复现**

- 真实 macOS Cocoa，打开 `testdoc/1.tlproj` → UltraView → 点击“添加便签贴纸 (N)” → 点击画布空白。
- rail 状态会变化，但画布无便签、无编辑器、无创建反馈；再次点其他创作按钮同样没有产品行为。

**用户影响**

这是确定的主路径失败，不是边缘交互。任何“新增按钮点出去没反应”的报告都会稳定复现。

**必须修复**

- 在完整交互闭环通过前，产品默认不展示/不启用这些入口。
- 引入唯一交互 owner，完成 tool → draft → commit/cancel → history/dirty → projection 的事务。
- 增加真实 Page 级端到端测试，不再用“rail 能 emit”代表“功能可用”。

### [P0] 计划硬门被绕过，提交内容与计划状态自相矛盾

**证据**

- authoring plan `:3-6` 状态为“待授权执行”；Task 0 的所有 checkbox 仍未完成。
- plan `:72-96` 明确写出五个硬门，任一缺失均为 `BLOCKED`。
- spec `:3-4` 状态仍为 “DRAFT，未授权产品执行”。
- 实际提交 `83ad8e4e` 一次跨 42 个文件，新增/修改约 6,870 行；可见 rail 与底层对象模型同时落地，
  而负责交互闭环的 owner 缺失。

**用户影响**

工程获得了大量“可单测的部件”，却没有可使用的纵向功能；review 成本和回归面暴涨，用户目标没有交付。

**必须修复**

- 后续按垂直切片交付，不再以横向“state/render/chrome 都有了”作为完成度。
- 每一波只有在对应用户手势、回滚、持久化和前台证据齐全后才可标记 Implemented。

### [P1] Resize 热路径每个鼠标事件都做整层高质量合成，磨砂透明又放大闪烁

**证据**

- `widgets.py:3854-3859` 每个 card mouse move 直接进入 `_update_gesture_at()`；
  `gesture.py:261-330` 每次都重新 snap 并调用 `plan_layout()`，没有“candidate 未变化即返回”或帧合并。
- `widgets.py:3989-4050` 每次重建 ghost/highlight，并把 card 的原始 `_raw_image` 交给 overlay。
- `ghost_overlay.py:198-248` 每次 `set_move_previews()` 最终调用无 dirty rect 的 `update()`；
  `ghost_overlay.py:300-325` repaint 整个 overlay，并对原始图执行
  `SmoothPixmapTransform + drawImage(target_rect, image)`。
- `widgets.py:4094-4113` gesture 开始及 displaced set 改变时创建/替换
  `QGraphicsOpacityEffect`，原卡 opacity 为 0.4；`ghost_overlay.py:26` ghost opacity 为 0.45。
- Wave B 又把卡片壳改为 alpha 118 的 `UV_FROST`（`ultraview_style.py:22-24`、
  `style.qss:4884-4898`）。原卡、ghost、透明壳在移动边界上反复合成，视觉稳定性进一步下降。

**诊断边界**

- 24-card 纯 planner 诊断 600 次：p50 0.306 ms、p95 0.430 ms、max 14.813 ms。
- 这说明常态 planner 不是唯一主耗时；偶发 spike 仍能丢帧，但当前最明显的未控成本在 QWidget/
  overlay paint 路径。此次没有帧级 Cocoa trace，因此不能把具体毫秒归因给某一条 paint 调用。

**用户影响**

拖动/调整大小时 ghost 跳、卡片忽隐忽现、输入跟手性差；DPR=2、大预览和多卡时更明显。

**必须修复**

- pointer input 只记录最新样本；每帧最多求解/paint 一次。
- candidate GridRect 未变化时不重跑 planner、不重建 ghost。
- drag 使用预生成低成本 pixmap/mipmap 或轮廓；settle 后才 Smooth 重采样。
- overlay 只更新 old/new ghost union；拖动中不创建/替换 GraphicsEffect。

### [P1] Autofit 的目标函数与 live card 不同，也把“单卡适配”和“全板优化”混为一谈

**证据**

- `free_grid.py:346-409` 先只在当前 span 内枚举 shrink；如余量仍大，只选择一个轴再增长最多
  `FIT_SHORT_SIDE_GROW_MAX`。它不枚举两轴增长，也不结合空闲矩形决定候选。
- `_plot_size_px()` / `CARD_FIT_CHROME_HEIGHT` 使用固定 34+24+16 px（`layouts.py:26-35`）；
  live widget 的 footer 会随 LOD/设置隐藏并变为 0（`widgets.py:2169-2186`），实际预览槽来自
  `QLabel.contentsRect()`（`widgets.py:2319-2336`）。所以 solver 和用户看到的槽不总是同一个矩形。
- coordinator 先独立求 `wanted`，再调用 `plan_layout(..., LAYOUT_RESIZE)`
  （`ultraview_coordinator.py:1728-1765`）。这可能为了单卡 Fit 挪动其他卡，但 UI 文案没有说明它是
  Board 重排操作。
- 细网格 plan 的 G1 只写“显著低于”，没有数字；Wave 0 要求的用户样本
  `QLabel.contentsRect()` / unused-area 基线也没有对应的 `.state/ultraview-fine-grid-*` 量化记录。

**用户影响**

- 同一张图在不同 zoom/LOD/show-title/show-source 下可能得到不一致的“最佳”外框。
- 局部 Fit 可能无变化、过度缩小，或为了适配一张卡而挪动别的卡。
- 对每张 View 依次 greedy Fit 不能得到全板最优结果。

**必须修复**

- 明确拆成三个命令：Board Fit（只动 camera）、Fit Card Preview（默认不动邻卡）、
  Optimize Board Layout（显式全局重排）。
- 单卡求解使用真实 live chrome/contents box 的纯 DTO，并用 brute-force oracle 测试最优性。
- 全板优化使用独立、显式、可预览/撤销的全局目标，不能重复调用单卡 greedy Fit 冒充最优。

### [P1] “磨砂卡片”只改壳，无法解决真实图表白底；验证也只到 token

**证据**

- `style.qss:4307-4310` 只把 `QLabel#ultraViewCardImage` 背景设透明；
  `widgets.py:2326-2365` 仍把完整原始不透明 `QImage` 缩放成 pixmap。
- `style.qss:4884-4898` 只让 outer card/selected/drop shell 半透明。
- 细网格计划 `:38-39` 和 `:201` 明确不处理预览图白底；如果用户红框位于抓图像素内部，
  此方案从设计上就不会改变它。
- `tests/ui_kit/test_ultraview_style.py:22-25` 仅断言两个 rgba 字符串；没有实际卡片像素、Cocoa
  backing、hover/drag 状态或高 DPI 圆角测试。

**前台观察**

真实 `1.tlproj` 中多张 View 的大面积白色仍由预览图主导；卡片边缘略透，但整体仍是白色图块，
且不同卡片的内部留白/比例差异明显。

**必须修复**

- 先判定白色属于 shell letterbox 还是 QImage 内容；两者不能用同一 alpha 修复。
- QImage 内容不做阈值抠图。若问题在图表自身 paper/margin，应在 capture/render contract 中提供
  明确、可重放的 UltraView presentation profile，而不是后处理像素。
- 视觉 gate 必须包含真实数据卡、selected/hover/drag、圆角四角和 1×/2× DPR 像素检查。

### [P1] 选择状态仍是多份真相，违反本轮自己的核心设计

**证据**

- Page 仍保存 `_selected: UltraViewRef | None`（`page.py:300-309`）。
- FreeGridGesture 继续单独保存 card selection；FreeGridBoard 又新增
  `_author_selection_ids`（`widgets.py:3101-3104`）。
- `page.py:2160-2176` 的 `clear_card_selection()` 通过同时清三处状态来维持表面一致，而不是单一 owner。
- spec D5/D7（`:76-78`）与 plan Task 4（`:147-156`）明确禁止“两套真相”。

**用户影响**

一旦 author hit/move 接上线，Shift、多选、Esc、Delete、context toolbar、mixed undo 都会在不同状态源间漂移；
当前只因为作者对象尚不可交互而没有完全暴露。

**必须修复**

在实现第二个可用工具前先收敛到一个 `BoardItemKey` selection owner；现有 Page/Card/Overlay 都只做投影。

### [P2] 测试名称给出“集成”假象，但没有覆盖用户事务

**证据**

- `test_ultraview_author_chrome.py:22-61` 只证明 rail emit 和属性变化。
- `test_ultraview_author_integration.py:40-89` 只把预制对象投影到 layer；`:128-154` 只验证按钮启停。
- 没有测试执行：点击 Sticky → 点击/拖画布 → 创建对象 → 进入编辑 → commit/cancel → undo/redo →
  dirty → save/reopen。

**用户影响**

聚焦测试可以全绿，同时主路径为零。此次 82 个相关测试全部通过，正说明现有 gate 对“按钮没反应”没有探测能力。

## 3. 两波提交的保留/回退建议

| 区域 | 建议 | 理由 |
|---|---|---|
| DTO、normalization、render/compositor 基础 | 暂时保留但隔离 | 有较完整纯逻辑测试；尚未证明真实编辑链路 |
| 可见 creation section | 默认隐藏/编译期关闭 | 当前是确定的 dead affordance |
| author selection 临时集合 | 不继续扩展 | 应先被单一 interaction owner 替代 |
| 2× micro-grid migration | 保留前先做旧项目像素/保存重开门 | 跨 schema 风险大，现有计划证据不完整 |
| 当前 Autofit cost/search | 替换为明确的单卡 solver contract | 不是 live-geometry 最优解 |
| 半透明 shell token | 可实验保留，不作为问题已解决 | 只影响壳；前台/Cocoa 未验收 |
| 创建工具的后续 Shape/Draw 扩展 | 暂停 | Sticky 完整纵切未过门前禁止扩大表面 |

## 4. 验证记录

### 已执行

- 真实 macOS Cocoa：`testdoc/1.tlproj`，UltraView 打开、Sticky→blank、card select、一次 resize。
- focused Qt：author chrome/integration、free-grid、placement history、UltraView style：
  **82 passed, 28 warnings, 5.49 s**。
- author 全组与 import/no-lambda/state-ownership boundary gate：
  **56 passed, 6 warnings, 5.83 s**。
- 纯 planner 诊断：24 cards、600 次 resize targets；p50 0.306 ms、p95 0.430 ms、max 14.813 ms。

### 未执行 / 不得冒充已验证

- 没有 Cocoa frame timeline，因此 resize 各 paint 子项的毫秒归因仍为高可信源码诊断，不是正式性能测量。
- 没有保存被交互修改的 `1.tlproj`；本次前台只做临时操作。
- 没有 fresh Windows Full/Lite frozen 验收。
- 没有 full suite；本次是 review/文档工作，且 focused evidence 已足以判定 NO-GO。

## 5. 最终裁决

当前 `98636b3f` 不满足作者工具 spec，也不满足细网格 plan 自己的完成定义。最危险的不是某个视觉 token，
而是“横向基础设施很多、纵向用户事务缺失”被绿色单测和 `Implemented` 文案掩盖。

恢复顺序必须是：**先隐藏 dead affordance → 单一交互 owner → Resize 帧预算 → 真实 Autofit contract →
Sticky 纵切 → 其余工具逐个扩展 → Cocoa/Windows 独立验收**。
