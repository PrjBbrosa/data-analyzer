# UltraView：指针/激光笔、蓝色状态与统一弹层计划

**状态：REVISED — follow-up 计划（基线为 `1df1714d`，尚未执行本次修订的产品改动）**
**日期：2026-08-22**
**视觉基准：** [B2 图标对比原型](../ui-prototypes/2026-08-22-ultraview-miro-icon-directions.html)、[指针与弹层原型](../ui-prototypes/2026-08-22-ultraview-pointer-and-popup-options.html)

## 0. 2026-08-22 最新修订（优先于下文旧描述）

`1df1714d feat(ultraview): switch selected chrome to blue and document pointer`
已经完成了本计划的首轮蓝色 chrome、Pointer 可见和基础 popup。本次不是重做该提交，而是只修正用户刚确认的三项行为与视觉细节：

| 已有实现 | 本次修订目标 |
| --- | --- |
| Pointer tile 被切成主点击区 + 右侧窄 caret 区 | **整块 Pointer tile 单击就开 popup**；移除 split hit area、caret 绘制和“点击应用上次模式”分支。 |
| Laser 清空选择、吞掉 card/author 点击，并绘制 `LaserFocusOverlay` 红色聚焦环 | Laser 只换 `TOOL_SELECT` 的 **QCursor 视觉**；选择、框选、移动、缩放、编辑、快捷键、undo/history 与 Mouse 完全一致。删除/停用 overlay 与事件吞噬路径。 |
| 所有 rail 图标仍以 `20/18px` icon target 绘制 | 不改 `64/52px` rail 与 `40/36px` hit target；将全套 icon-only glyph target 提升为 desktop `24px`、compact `20px`，并重绘路径的 optical ink box。 |

这一节覆盖本文中任何 “箭头区域”“Laser 只聚焦”“red halo”“20/18px 保持不变” 的旧说法。

## 1. 决策与范围

本计划将 UltraView 从当前的 **Titanium Amber 常规视觉** 收敛为更接近 Miro 的蓝色、单层级操作状态，同时维持 TraceLab 已有 rail 的尺寸、间距和圆角节奏。

已确认的产品决策：

| 主题 | 决定 |
| --- | --- |
| 指针入口 | 在 FreeGrid 创作 rail 中正式露出 Select（视觉名称为“指针”），排在 Sticky 前。它不是标注工具。 |
| 两种指针模式 | 普通鼠标与激光笔均是 Select：两者都可选择/移动/缩放；区别只在 OS 光标的形状，不创建标注对象。 |
| 图标方向 | 采用原型 B2-Readable：整套 icon-only rail 都按同一更大的 optical grid 重绘，保留现有自绘 QPainter 语法，不混用 qtawesome。 |
| 常规状态色 | 选中、当前工具、已开面板、展示模式全部改为蓝色系统；不用琥珀渐变或铜色作装饰。 |
| 琥珀色边界 | 只保留真正的注意/警告：未放置数量、数据不一致、需同步、风险提示。不能再表示“已选中”“当前模式”或背景装饰。 |
| 弹层 | 所有 UltraView 内嵌菜单/下拉/工具 flyout 统一由 `CanvasHost` 承载、定位和抬升；不可被 Board、卡片、选择框或 GhostOverlay 遮盖。 |

“全局移除琥珀色”在本计划中的精确范围是 **UltraView 的常规视觉全域**，而不是删掉整个 Analyzer 的 warning token，也不改变图表的分析分类色。

本计划取代以下历史计划中与上述决定冲突的内容：

- `2026-08-20-ultraview-miro-operation-ui-restoration-plan.md` 的“保留 Titanium Amber 常规主视觉”；
- `2026-08-21-ultraview-miro-popup-shape-rail-draw-correction-plan.md` 的“发布 rail 隐藏 Select”。

两份历史记录保持原样，不回写。

## 2. 已核实的实现基线

- `1df1714d` 已在 `chrome.py:100` 将 Select 放进发布 rail，并新增 `_PointerToolButton`（split caret）和 `PointerPopover`；本 follow-up 将它收敛为整块单击 popup。
- rail 几何是既有契约：桌面按钮 `40px`、紧凑按钮 `36px`、既有 group gap、divider clear、外框半径都不变。唯一尺寸变化是 icon target 从 `20/18px` 提至 `24/20px`。
- `BoardInteractionController`（`author_tools.py:833`）是工具、选择、草稿的唯一会话 owner；其状态不会进入持久化 Board payload。
- `UltraViewPage._on_author_tool_requested()`（当前约 `3660` 行）是 rail intent 的汇聚点，`_sync_tool_cursor()`（当前约 `3884` 行）是光标投影入口。
- `CanvasHost`（`chrome.py:451`）已经以“Board 置底、overlay 为直接子组件”的方式工作，并在 `open_overlay()` 中执行互斥关闭、边界夹取和 `raise_()`；`page.py` 已登记 Sticky、Shapes、Connector、Draw 与 Format picker。
- 图标来自 `mf4_analyzer/ui_kit/icons.py` 的 QPainter 线性图标（`_line_icon()`，约 `62` 行，圆角 `1.7` 笔触），不是 qtawesome。
- `mf4_analyzer/ui_kit/ultraview_style.py` 是 QSS token 与 QPainter 色彩的共同来源；当前琥珀色同时存在于 rail、canvas glow/horizon、Library 类别材质、presentation island 和测试契约中。

## 3. 交互合同

### 3.1 指针控件

在 rail 创作分组首位保留 `Pointer` 控件，沿用现有 `40/36px` 轨道单元，不增加 rail 宽度或改变卡片区可用面积。

- **每次单击整块 Pointer tile 都打开/关闭 `PointerPopover`**；不再切出箭头区域、没有 caret、也不因点击直接切换到“上一次 mode”。
- popup 只含两个 36px 高的行项目：`Mouse`、`Laser pointer`。每行都有 B2-Readable 对齐的图标、主标题和一行短说明；不要做彩虹色、渐变色或大面积装饰背景。
- `V`：始终回到 `Mouse + TOOL_SELECT`；不从快捷键直接进入激光笔。
- `Esc`：先终止编辑/草稿/临时 flyout；若当前为 Laser，则退出 Laser 回到 Mouse；不会生成任何 author object。
- rail 禁用时（非 FreeGrid、overview、template、presentation）Pointer 与其他创作工具一同禁用，不在不可编辑模式留下假的可编辑入口。

### 3.2 两个 mode 的行为边界

| 维度 | Mouse | Laser pointer |
| --- | --- | --- |
| interaction owner | `TOOL_SELECT` + `pointer_mode="mouse"` | `TOOL_SELECT` + `pointer_mode="laser"` |
| 点击卡片/作者对象 | 现有选择、拖动、缩放、框选和快捷键合同 | 与 Mouse **完全相同** |
| 点击空白处 | 既有选择清除/视口操作规则 | 与 Mouse **完全相同** |
| 光标呈现 | 标准 arrow / resize cursor，沿用现有 hit routing | 自绘 laser-shaped `QCursor`，按现有 resize/hit cursor 优先级正常切换 |
| 数据与历史 | 不写 author object；选择为会话态 | 与 Mouse **完全相同**，不新增 Board payload 或历史副作用 |

Laser 不绘制红点、halo、屏幕聚焦 overlay，也不拦截输入。第一次从 Sticky/Text/Shapes/Draw 选择 Pointer 时仍按 Select 既有合同取消 creation draft；**在已经是 Select 时切换 Mouse ↔ Laser 必须保留 selection、handles、编辑合同和当前 board 状态。**

### 3.3 单一状态来源

1. 保留已存在、受校验、默认 `mouse` 的 `BoardInteractionController.pointer_mode`；不在 `ToolRail`、`UltraViewPage`、`FreeGridGesture` 各自缓存一份。
2. `ToolRail` 只发出 `pointer_menu_requested`，`PointerPopover` 只发出 `pointer_mode_requested(mode)`；`UltraViewPage` 收敛二者并同步 rail/cursor。
3. `FreeGridGesture` / viewport router 不因 Laser 改变 hit routing；Laser 只在既有 Select cursor 投影中选择 custom cursor pixmap。删除 `_consume_laser_pointer()`、`LaserFocusOverlay` 及所有吞掉 card/author event 的分支。
4. 现有 `TOOL_SELECT` 不重命名，防止持久化、快捷键、测试或兼容 import 受影响；“Pointer”仅是 rail 的用户可见名称。

## 4. B2 图标与状态视觉合同

### 4.1 图标实现

- 所有 icon-only UltraView 控件共用 `24px desktop / 20px compact` target：Library、FreeGrid、Layout、Filter、Unplaced、Sync/Reset/Presentation、Pointer、Sticky、Text、Shapes、Draw，以及 DrawPopover 的 Pen/Highlighter/Eraser/Lasso。
- 每枚自绘路径重心落在新的 24px 坐标网格中央；desktop 的可见 ink box 目标约 `18px`，compact 约 `16px`。通过重画 path 的留白，而不是仅将 20px pixmap 粗暴拉伸。
- 复用并细修 `Icons.ultraview_author_select()` 与 `Icons.ultraview_author_laser()`：两者都是鼠标指针形态，Laser 只增加可识别的光标视觉细节，不能呈现红色 board dot。
- 保持统一的圆端/圆角线性语言；必要时将局部笔画校准到约 `1.9px`，但不把任一图标改成实心块或字体图标。
- 新增/更新像素测试：导航、作者、Draw 子工具与 Mouse/Laser 在 `24px`、`20px` 下均满足 optical bound、中心线与可识别性断言。

### 4.2 蓝色状态矩阵

使用 `ultraview_style.py` 中独立命名的语义 token，令 QSS 和 QPainter 共享同一来源。推荐基准为 Miro 蓝 `#4262FF`，其 wash 为低饱和蓝白；最终数值以 B2 原型的 foreground 截图校准。

| 状态 | 外观 | 允许的用途 |
| --- | --- | --- |
| 默认 | 透明/雾白 rail，深灰绿线性图标 | 所有 idle 控件 |
| hover / keyboard focus | 很浅蓝灰底或 1px 蓝 outline；图标深蓝 | 可点击提示，不代表已经选择 |
| 当前 pointer / 当前创建工具 | 非渐变的浅蓝 wash + `#4262FF` 图标/边框；只允许一个 `primaryFill` owner | 当前编辑工具 |
| 面板打开、FreeGrid、presentation | 轻蓝 outline 或浅蓝 wash；与“当前工具”可区分但不抢主状态 | 模式/面板反馈 |
| warning / attention | 保留 `UV_WARNING` 的琥珀 badge/wash | unplaced、stale、数据/同步风险 |
| error / destructive | 保留 danger token | 删除、不可恢复错误 |

实施时移除常规用途的 `UV_AMBER`、`UV_RAIL_ACTIVE_START/END/HOVER` 和 copper/glow 依赖；不要把 `UV_WARNING` 改蓝。`QFrame#ultraViewGlobalIsland[presentation="true"]`、Board create CTA、Library selected category material、canvas background glow/horizon 也一并改为蓝/中性系统。所有相关命名与注释从 “Titanium Amber” 改为中性的 UltraView visual/style contract，避免下一次回归。

## 5. 统一菜单与下拉层

### 5.1 层级合同

在 `CanvasHost` 内明确并集中维护下面的 z-order；不让任意页面代码直接散落调用 `raise_()` 来碰运气：

```text
Board canvas / author layer / GhostOverlay
  < persistent selection toolbar and card-context island
  < CanvasHost active transient overlay
      (Pointer, Sticky, Shapes/Connector, Draw, Format, Library,
       Layout, Filter, Unplaced, Display, Export, Boards)
  < native context menu / modal dialog
```

约束：

1. 所有 app-contained flyout 均登记到 `CanvasHost`，并由一个 `open_overlay()` 路径打开；它们不得作为 Board/card 的子控件，也不得加入布局。
2. `CanvasHost` 提供一个集中式的“重申层级”方法；resize、projection rebuild、selection toolbar 重建、card/ghost overlay raise 后只调用该方法。active overlay 必须总在最终顶层。
3. 同一时刻只允许一个 transient overlay；打开新的 dropdown 时关闭旧的，恢复 trigger 的键盘 focus；点击 canvas、Esc、切换工具都按既有 `close_on_canvas_click` 与 pinned 语义收口。
4. `QMenu`（selection “more”、card context、board menu）在显示前关闭 CanvasHost transient overlay，并以其触发控件的全局坐标弹出；关闭后把焦点还给 trigger。若平台原生 `QMenu` 仍遮挡异常，才把该具体菜单转换为 `ToolFlyoutSurface`，不做无证据的大规模替换。
5. 定位始终在 host 坐标完成、以 safe rect 夹取。桌面 rail 右侧优先；右侧不足则向左翻转；底部不足则上移。绝不靠负坐标或 child clipping 显示“半张菜单”。
6. 弹层消费其内部 pointer event；点击最后一行选项后，事件不得穿透到 card/board 触发选择、拖动或创建。

### 5.2 覆盖清单

本次必须逐项验证：Pointer、Sticky palette、Shapes/Connector、Draw、FormatChoice、Library、Layout、Filter、Unplaced、Display、Export、Boards、selection More、card context More。任何新增 flyout 必须走相同 registry/geometry/close 合同。

## 6. 分阶段实施

### 阶段 A：冻结基线与状态语义

**文件所有者：** `ui_kit/ultraview_style.py`、`ui_kit/style.qss`、`chart_stack/ultraview/chrome.py`、现有 focused tests。

1. 对 UltraView 的 `UV_AMBER`、`rail_active_*`、`glow_amber`、`copper` 和 “Titanium Amber” 做完整使用清单，逐条标记为常规视觉或真实 warning。
2. 建立蓝色 `selected/focus/hover` token；删除常规选中态的渐变依赖，保留 `UV_WARNING` 与 danger/success 的语义。
3. 将 canvas、Library 类别、presentation、Board CTA、rail/global island 的常规装饰改为中性/蓝色。保持 canvas 点阵、网格、frost 和现有几何，不重绘整个页面。
4. 用更新后的状态矩阵替换旧的 `primaryFill`、`modeActive`、`panelOpen` 像素断言；保留“最多一个 primary owner”的约束。

**完成条件：** 在无 warning 的 FreeGrid 中，不再出现琥珀/橙/铜色的普通背景、选中块或渐变；有 unplaced/stale 时，才出现琥珀提示。

### 阶段 B：B2 图标与 Pointer popup

**文件所有者：** `ui_kit/icons.py`、`chart_stack/ultraview/chrome.py`、`chart_stack/ultraview/author_chrome.py`、对应 chrome/icon tests。

1. 保持已经可见的 `TOOL_SELECT` /“指针”入口；将 `_PointerToolButton` 替换为普通 `_AuthorToolButton` 或等价的完整 tile，不再覆写 caret hit/paint。
2. 保持现有 `ToolFlyoutSurface` 的 `PointerPopover` 与两行 Mouse / Laser；单击 tile 发出 `pointer_menu_requested`，再由页面打开/关闭 popup。
3. 同时把 rail 所有 icon-only 图标 target 升为 `24/20px`，修订自绘 path，并保持外框、`40/36px` hit tile 和 compact 布局原样。
4. 以同一 `_line_icon` / custom-cursor pixmap 抽象实现 Mouse/Laser；不引入 qtawesome。

**完成条件：** B2 的 pointer、Sticky、Text、Shapes、Draw 在桌面和 compact rail 中垂直中心一致；Pointer popup 在两个目标尺寸内完整可见，当前 mode 只有一行被蓝色标出。

### 阶段 C：鼠标/激光笔模式与 hit routing

**文件所有者：** `chart_stack/ultraview/author_tools.py`、`page.py`、`widgets.py` / FreeGrid gesture owner、必要时 `ghost_overlay.py`。

1. 保留 `pointer_mode` 的校验、默认和 session-only projection，但修正 `set_pointer_mode(laser)`：不得清 selection、不得撤销正在编辑的 Select state。
2. 接入 `UltraViewPage` 的 rail intent 与快捷键，单点处理 popup 开闭、仅在从 creation tool 进入 Pointer 时取消 draft、以及 cursor/rail 同步。
3. Mouse 与 Laser 都执行同一 Select hit routing。Laser 仅在 `_sync_tool_cursor()` / `FreeGrid.sync_tool_cursor()` 中投影 custom `QCursor`，并尊重 resize handle 的标准 cursor 优先级。
4. 删除 `LaserFocusOverlay`、`sync_laser_overlay()`、`_consume_laser_pointer()` 及其 card/board press/move/leave special cases；在 presentation/FreeGrid 退出、board restore、clear/teardown 中只复位 cursor/style session state。

**完成条件：** Mouse 与 Laser 在同一组卡片/作者对象/空白画布手势下得到完全相同的 selection、几何与 history 结果；唯一可观察差异是箭头光标与激光笔光标的形状。

### 阶段 D：统一弹层归口与遮挡修复

**文件所有者：** `chart_stack/ultraview/chrome.py`、`page.py`、`author_chrome.py`、`author_selection.py` 和 overlay focused tests。

1. 补齐 CanvasHost 的 z-order coordinator 与 “active overlay re-raise” 单一路径。
2. 将 Pointer 与现有 author/format/panel flyout 纳入同一 registry，清除特例 `show()/raise_()` 分支。
3. 审计所有 `QMenu` 入口，落实“native menu 打开前先关闭 app flyout”的顺序及焦点归还。
4. 为各目标尺寸的右边、下边和四角选择工具栏建立测试：几何在 safe rect 内、最后一个菜单项不被裁切、点击不穿透、卡片/ghost overlay 不得越过下拉层。

**完成条件：** 用户截图中的“菜单在卡片/背景后面、选项区域被错误的父层截断或遮挡”的情形无法复现；所有覆盖清单项都在其触发物之上。

### 阶段 E：说明、回归与前台验收

**文件所有者：** `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`，必要时 UltraView 用户指南；测试与前台验收记录。

1. 增加 Pointer、Mouse、Laser、`V`、`Esc` 的短帮助；明确 Laser“仅改变光标外观，仍可选择、移动和缩放”。
2. 运行 focused owner tests，修复必要的 token/geometry/pixel assertions；不因为 UI 改动直接跑整套 `tests/ui`。
3. 在真实 macOS 前台启动 TraceLab，按第 7 节脚本进行交互验证并截图。

## 7. 验证矩阵

### 自动化门禁

先为每个新行为写失败的 focused test，再实现。建议分组运行：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui_kit/test_ultraview_style.py \
  tests/ui/test_ultraview_icons.py \
  tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_author_chrome.py \
  tests/ui/test_ultraview_author_tools.py \
  tests/ui/test_ultraview_selection_toolbar_contract.py \
  tests/ui/test_ultraview_page.py

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_ultraview_board_hit_routing.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_author_integration.py \
  tests/ui/test_ultraview_floating_layout.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py
```

要新增/更新的断言至少包括：

- Release rail 可见 Pointer，且 rail 尺寸、group gap、divider gap 在 desktop/compact 不变；
- Mouse/Laser 默认、单击整块 Pointer tile 开/关 popup、`V`/`Esc`、draft cancel、无 payload/undo 写入；
- Mouse/Laser 对同一点击、框选、拖动、resize、文字编辑和 history transaction 的结果完全相同；只断言 cursor pixmap/style 不同；
- 不存在 LaserFocusOverlay 或 Laser event swallowing，且 pointer/mouse/laser/导航/Draw 子工具在 `24/20px` 的 ink-bound 和颜色一致性；
- 正常 selected/open/presentation 只含蓝色状态 token，warning 才含 `UV_WARNING`；
- 每个 overlay 的 geometry、z-order、canvas-click close、Esc、焦点回归、边缘夹取、内部点击不穿透；
- CanvasHost 的 overlay 开启后 board viewport 尺寸完全不变。

### 前台 macOS 验收（不可由 offscreen 代替）

使用：

```bash
./.venv/bin/python -m mf4_analyzer.app
```

在一张含卡片和 author object 的 FreeGrid board 中，分别于 `1280×720` 与 `800×560` 执行：

1. 打开 Pointer popup，切换 Mouse / Laser；确认 rail/菜单 B2 对齐、蓝色状态且无琥珀装饰。
2. Mouse：选卡、框选、拖动、四边缩放；切入 Sticky/Draw 后再按 `V`，确认 creation 已取消且进入 Mouse。
3. Laser：确认只看到激光笔鼠标形状；与 Mouse 分别对卡片、作者对象和空白处执行点击、框选、拖动、四边缩放、文字编辑，确认 selection、尺寸、history 结果一致；空间键/中键仍可平移。
4. 逐一打开第 5.2 节全部菜单，在 rail 右侧、底部和选择工具栏靠边的位置重复；确认末项完整、点击不穿透、卡片/ghost overlay 无法遮挡。
5. 制造一个真实 unplaced/stale 状态，确认它仍是唯一琥珀 attention；消除风险后，所有常规 chrome 恢复中性/蓝色。
6. 退出 FreeGrid、切换 Board、进入/退出 presentation、关闭页面再打开；确认没有残留 popup、custom cursor 或错误的选中状态。

将两种窗口尺寸的截图和结果放到 `.state/`，作为本次产品实现的前台证据；它们不是 Git 提交物，除非后续明确要求归档。

## 8. 非目标与风险控制

- 不替换整个应用的图标系统，不引入 qtawesome，不重构 rail 的布局宽度。
- 不改变 top-left 既有全局导航区域，也不增加暗色模式。
- 不把 Laser 当作新的标注对象、协作光标或持久化 presentation 数据；那是后续独立功能。
- 不因为本次更改触及历史 “Titanium Amber” 测试就删除测试；要把它们改写成蓝色选择与 warning 语义的正向保护。
- 不在完成 focused tests 前运行全套测试；若后续合并里程碑需要全量门禁，按仓库约定由唯一协调者在稳定 worktree 上运行一次。

## 9. 实施完成定义

满足以下全部条件才可交付实现：

1. Pointer 在 FreeGrid rail 中可见，Mouse/Laser 行为符合第 3 节，且没有生成/保存标注。
2. B2 图标、现有图标、rail 几何在两个断点下视觉对齐；所有常规 active state 为蓝色系统。
3. UltraView 无 warning 时不再有琥珀/铜色的渐变、glow、类别材质或 presentation 装饰；真正 warning 仍明确可见。
4. 覆盖清单中的全部 dropdown/flyout 不被遮挡、不裁切、不穿透，且不挤压 Board。
5. focused 自动化门禁通过，并有两种窗口尺寸下的真实前台交互证据。
