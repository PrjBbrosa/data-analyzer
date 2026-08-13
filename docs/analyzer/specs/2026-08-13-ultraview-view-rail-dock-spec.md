# UltraView View 栏右侧固定入口规格

- 日期：2026-08-13
- 状态：已实施（自动门禁已通过；UVR-A15 真实 macOS 前台仍为 UNVERIFIED）
- 对应计划：
  `docs/analyzer/plans/2026-08-13-ultraview-view-rail-dock-implementation.md`
- 视觉探索稿：
  `docs/analyzer/ui-prototypes/2026-08-13-ultraview-entry-options.html`
- 基线语义：
  `docs/analyzer/specs/2026-08-12-ultraview-p0-spec.md`

## 1. 已确认决策

UltraView 的主入口从顶部文件操作区移到每个源工作区底部 **View 栏整行的最右侧**。
入口显示英文品牌字标 `UltraView`，图标与文字采用用户确认的 **Electric Spectrum**
配色：

```text
#0969DC  →  #734EE6  →  #BD299F
electric blue   violet   magenta
```

“固定在右侧”指的是：无论 View 数量、是否合并/分屏，以及分析对比按钮是否出现，
UltraView 始终是整行最后一个可点击项；临时动作全部出现在它左侧。窄宽度时允许
`UltraView` 文字退化为仅图标，但右锚点、点击语义和 tooltip 不变。

本规格只改变 **入口位置、视觉与发现性**，不改变 UltraView 的产品语义：它仍是独立
Board 工具窗、只读对照已有预览、不重新计算，也不是第六种分析算法。

## 2. 对旧文档的增量覆盖

本规格覆盖 2026-08-12 P0 规格和计划中以下已经过时的入口描述：

- “顶部第六入口 `总览`”；
- “用户点击顶栏‘总览’”；
- Toolbar `总览` 按钮及其点击验收。

旧文档中的 Board、快照、稳定引用、零隐式计算、独立工具窗、持久化与导出契约保持
不变。历史文档不回写；实现与验收遇到入口冲突时，以本规格为准。

## 3. 当前真实结构与问题

### 3.1 共享 ViewTabBar 内部

当前 `mf4_analyzer/ui/view_tabbar.py::ViewTabBar` 的顺序是：

```text
[section 锚点] [View tabs] [» overflow?] [+] [stretch] [split clear?]
```

- 高度固定 28px；section 锚点、`»`、`+`、split clear 都是受保护的固定 sibling；
- View 标签按真实 `sizeHint()` 依次走 `roomy → compact → overflow`；
- `»N` 仅在 compact 后仍放不下时出现；
- `+` 始终保留，到当前 manager 的 `max_views` 后禁用并提示“View 数量已达上限”；
- 当前 View 永不因缩放被藏入 overflow。

因此 UltraView 不能简单作为一个新 sibling 塞入 `ViewTabBar` 后就结束：分析页还有
`ViewTabBar` 之外的右侧动作。

### 3.2 两种 split clear 语义

同一个 `_split_clear` 控件根据挂载模式复用为两个动作：

| 工作区 | 出现条件 | 文案 | 语义 |
|---|---|---|---|
| 时域 | 当前 View 与另一个 View 已配对 | `✕ 取消合并` | 解除两个 View 的并排配对 |
| 四个分析区 | 当前 View 有两个 pane | `✕ 关闭对比窗格` | 关闭当前 View 的第二个分析 pane |

两者都在 `ViewTabBar` 内部最右侧，并已计入 `_tabs_budget()`。它们不是同一种状态，
实现不得把时域“两个 View”与分析“一个 View 的两个 pane”混成一个模型。

### 3.3 分析页的外部动作

`mf4_analyzer/ui/analysis_section_page.py::AnalysisSectionPage` 当前的宿主行是：

```text
[ViewTabBar, stretch=1] [联动缩放?] [锁定色阶?]
```

- `联动缩放`：仅双 pane 时出现；
- `锁定色阶`：仅双 pane 且 section 为热图时出现；
- `关闭对比窗格` 位于 `ViewTabBar` 内，另外两个动作位于外部宿主行。

若 UltraView 只加在 `ViewTabBar` 内，它会落在“联动缩放 / 锁定色阶”左边，无法成为
整行右锚点。

### 3.4 宽度事实

- MainWindow 最小尺寸当前为 1100×640；ChartStack 最小宽度为 400px；
- 当前五个 View manager 的默认上限来自 `ui/view_state.py::MAX_VIEWS`，当前为 12，
  但入口实现只允许读取 `manager.max_views`，不得再写死第二个上限；
- 2026-08-13 的 offscreen Qt 几何探针显示，在热图双 pane 的最大右侧动作组合下，给
  compare row 520px 宽度时，layout 的最小宽度会把实际行撑到 583px。该探针只说明
  需要测量式降级，不是前台 macOS 视觉验收，也不得把 520/583 写成产品阈值。

## 4. 目标布局与显隐矩阵

### 4.1 固定顺序

宿主行统一遵循：

```text
[ViewTabBar, stretch=1]
[分析 compare toggles?]
[14px 高分隔线]
[UltraView Dock]
```

`ViewTabBar` 内部仍保留自身的 `取消合并 / 关闭对比窗格`。这样完整视觉顺序为：

```text
[section] [tabs] [»?] [+] ... [split clear?]
                              [联动缩放?] [锁定色阶?] | [UltraView]
```

分隔线属于 UltraView Dock 的边界，不属于某个分析动作；Dock 可见时分隔线始终可见。

### 4.2 状态矩阵

| 场景 | `»N` | `+` | split clear | 联动缩放 | 锁定色阶 | 最右项 |
|---|---:|---:|---|---|---|---|
| 时域，单 View/未合并 | 按宽度 | 显示 | 无 | 无 | 无 | UltraView |
| 时域，两个 View 合并 | 按宽度 | 显示 | `取消合并` | 无 | 无 | UltraView |
| FFT/FRF，单 pane | 按宽度 | 显示 | 无 | 无 | 无 | UltraView |
| FFT/FRF，双 pane | 按宽度 | 显示 | `关闭对比窗格` | 显示 | 无 | UltraView |
| 时频/阶次，单 pane | 按宽度 | 显示 | 无 | 无 | 无 | UltraView |
| 时频/阶次，双 pane | 按宽度 | 显示 | `关闭对比窗格` | 显示 | 显示 | UltraView |
| 任一 manager 达上限 | 按宽度 | 显示但禁用 | 按状态 | 按状态 | 按状态 | UltraView |

View 删除不是右侧常驻按钮：它仍只在 View 右键菜单中出现，且仅剩一个 View 时禁用。
本任务不新增“关闭 View”按钮。

## 5. UltraView Dock 视觉规格

### 5.1 组件形态

- 用户可见字标：`UltraView`，大小写固定；
- 正常态：2×2 rounded tiles 图标 + `UltraView` 文字；
- 极窄态：仅保留 2×2 图标；
- 行高不变：Dock 不得把现有 28px View 栏增高；
- 点击热区高度与现有 `+` / split clear 一致，不能只让彩色字形可点；
- 默认不显示数量 badge，本次不引入 Board 卡片数量状态和额外宽度抖动。

### 5.2 Electric Spectrum

图标和文字共用从左到右的线性渐变：

```text
0%   #0969DC
52%  #734EE6
100% #BD299F
```

- 2×2 图标使用同一渐变坐标，不把四格随机染色；
- 文字使用真实 glyph path 填充渐变，不以三段纯色字符模拟；
- 在 `#FFFFFF` 与 View 栏 `#FBFCFF` 背景上，三个色标的静态对比度均高于 5:1；
- 渐变只用于品牌图标/文字，背景、边框、hover 和 focus 仍使用安静的 TraceLab 中性色，
  避免成为大面积彩色 CTA。

### 5.3 交互状态

| 状态 | 表面 | 边框/焦点 | 品牌字形 |
|---|---|---|---|
| normal | 透明或 `#FFFFFF` | `#D2DDEA` 1px | Electric Spectrum |
| hover | `#F6F8FF` | `#B8BDEA` 1px | 渐变不位移、不闪烁 |
| pressed | `#EEF1FF` | `#9FA8E8` 1px | 渐变不变 |
| keyboard focus | normal/hover 表面 | 使用既有可见蓝色 focus ring | 渐变不替代焦点提示 |
| disabled | 仅应用于 teardown 等不可用状态 | 中性灰 | 保留可辨识轮廓，不彩色高亮 |

按钮不做 checkable：UltraView 是“打开或置前工具窗”的动作，不是 source mode，也不
把窗口显示状态写回任一 View manager。

### 5.4 Qt 绘制约束

Qt QSS 不支持可靠的渐变文字。实现应新增一个小型 `QAbstractButton`/`QPushButton`
子类，以 `QPainterPath.addText()` + `QLinearGradient` 绘制字标，并以向量路径绘制 2×2
图标。不得把渐变烘焙成单倍图 PNG；必须在 Retina/devicePixelRatio 下保持清晰。

组件仍要提供完整 QWidget 语义：

- `setAccessibleName("打开 UltraView")`；
- tooltip：`打开 UltraView（跨 View 只读对照，不重新计算）`；
- Tab 可聚焦，Space/Enter 可触发；
- 自定义 `paintEvent` 不能吞掉标准 `clicked`、enabled、hover、pressed、focus 状态；
- 字体从当前应用字体继承，不硬编码平台字体。

## 6. 宽度与稳定性合同

### 6.1 优先级

从最不应被牺牲到最先退化：

1. UltraView 的最右位置和完整点击热区；
2. `+`、当前场景的 split clear、分析 compare toggles；
3. 当前 View 标签可见；
4. UltraView 文字（可退化为仅图标）；
5. 全部 View 的完整名称；
6. 非当前 View 标签（可进入 `»N`）。

出现临时动作时，它们只从 `ViewTabBar` 的可用宽度中取空间；UltraView 的右边缘不得
移动，当前 View 不得静默切换。

### 6.2 禁止固定像素断点

Dock 的 full/icon-only 切换必须基于 live widget 的 `sizeHint()` /
`minimumSizeHint()`、layout margins、spacing 与当前可见 fixed actions 实测，不得使用
诸如 `if width < 760` 的常量。

建议由宿主行使用一个可单测的纯判定 helper：

```text
full_required = non_dock_min + full_dock_hint + margins + visible_spacings
compact = available_width < full_required
```

其中 `non_dock_min` 来自当前实际 layout/item hints。恢复 full 模式也使用同一 intrinsic
测量值；若实测出现边界抖动，只允许加入由字体度量推导的小滞回，不得引入凭经验的
窗口宽度阈值。

### 6.3 与 ViewTabBar 预算的关系

UltraView Dock 位于宿主行、`ViewTabBar` 之外。Qt layout 先为 Dock 和分析外部动作
分配其测量宽度，`ViewTabBar` 再用自身实际 width 执行既有 `_tabs_budget()`。因此：

- 不把 UltraView 重复加入 `_tabs_budget()` sibling 列表；
- 现有 section/`»`/`+`/split clear 预算逻辑保持单一 owner；
- 宿主行 resize、split 控件显隐和 Dock full/compact 变化后，必须触发一次 bar 的
  `_sync_tabbar_width()` 公共化入口（建议使用现有 `refresh_split_controls()` 或新增
  具名 `refresh_fit()`，不从外部调用私有函数）。

## 7. 所有权、挂载与信号

### 7.1 组件 owner

新增复用组件建议放在：

```text
mf4_analyzer/ui/widgets/ultraview_entry.py
```

`ui/widgets/` 只拥有绘制、尺寸模式、accessibility 和 `clicked` 表现，不 import
`MainWindow`、UltraView coordinator 或 Board 状态。

### 7.2 两个挂载点

- 时域：`ChartStack.attach_view_tabbar()` 不再把 bar 单独直插 QVBox；建立一个 28px
  水平 host row，按 `[ViewTabBar stretch=1] [separator] [Dock]` 挂载；hint bar 顺序不变；
- 分析：`AnalysisSectionPage._compare_row` 在 `btn_link`、`btn_lock_levels` 后追加
  `[separator] [Dock]`，确保它真的是整行最后一项。

五个 source section 都显示 Dock；UltraView 工具窗内部不显示这条 source View 栏，
因此不出现递归入口。

### 7.3 单一打开信号

`ChartStack` 新增无参数信号：

```python
open_ultraview_requested = pyqtSignal()
```

五个 Dock 的 `clicked` 都转发到该信号，MainWindow 只连接一次到现有
`MainWindow.open_ultraview()`。不得为五个 section 写五组带 section 的 lambda；打开
动作不需要 source identity。现有 `add_to_ultraview_requested(str, str)` 保持原样，它
仍负责 View 右键“加入总览”的稳定 `(section, view_id)` intent。

### 7.4 顶栏迁移

- 移除 Toolbar 左组当前可见 `btn_ultraview` 及其 `ultraview_requested` wiring；
- 不改 `MainWindow.open_ultraview()` 的“已有则置前、没有则创建”语义；
- 当前隐藏的 `btn_mode_ultraview` 不是用户入口。若兼容测试/旧调用仍需要属性，可继续
  隐藏保留，但不得加入 layout、mode mapping 或可见焦点链；后续有证据后再单独清理；
- 顶部只保留文件/项目与批处理动作，避免同一功能两个同等级入口。

## 8. 文案与帮助同步

这是用户可见入口迁移，实施必须同步：

- `ui/hints.py`：增加“View 栏右侧 UltraView 可打开只读总览”的发现提示；
- `ui/quickref.py`：把“顶部/顶栏总览”改成“各工作区 View 栏最右侧 UltraView”；
- UltraView help guide 中的打开路径；
- toolbar 与 View rail 相关测试中的可见文案。

保留“加入总览”中文动作；品牌入口显示 `UltraView`。文档首次出现时写
“UltraView（总览）”，之后不混用不同大小写。

## 9. 验收标准

- **UVR-A01**：时域和四个分析区均只有一个可见 UltraView 主入口，且它是宿主行最后
  一个可点击项。
- **UVR-A02**：顶部 Toolbar 不再显示 `总览` / UltraView 主入口。
- **UVR-A03**：全部状态组合严格符合 §4.2，`取消合并` 与 `关闭对比窗格` 语义不串线。
- **UVR-A04**：分析双 pane 时，顺序为 `关闭对比窗格 → 联动缩放 → 锁定色阶(若有)
  → 分隔线 → UltraView`。
- **UVR-A05**：点击任一 Dock 都调用现有 `open_ultraview()`；已有窗口被置前，不创建
  第二个窗口。
- **UVR-A06**：View 右键“加入总览”的 `(section, view_id)` signal 不变。
- **UVR-A07**：图标和字标使用 §5.2 Electric Spectrum；正常/hover/pressed/focus
  像素与 geometry 有确定性检查。
- **UVR-A08**：Dock 保持 28px 行高；其右边缘在 split/compare 控件显隐前后保持宿主
  右 margin 对齐。
- **UVR-A09**：full/icon-only 由 live hints 决定，没有固定窗口宽度断点；compact 时
  tooltip、accessible name 和点击热区完整。
- **UVR-A10**：View 标签仍按 `roomy → compact → overflow` 退化，当前 View 永远可见，
  `+` 与临时动作不被压缩或挤出边界。
- **UVR-A11**：manager 达上限时仅 `+` 禁用；UltraView 仍可打开。
- **UVR-A12**：Dock 打开 UltraView 的完整序列不触发任何分析计算，既有零计算探针
  继续通过。
- **UVR-A13**：键盘可达、focus 可见、Space/Enter 可触发，三个渐变色标在目标浅色
  背景上的对比度均不低于 4.5:1。
- **UVR-A14**：hints、quickref 和 UltraView help guide 的打开位置与本规格一致。
- **UVR-A15**：前台 macOS 截图覆盖普通时域、时域合并、FFT 双 pane、时频双 pane、
  宽/窄两档；offscreen 测试不能替代该门禁。

## 10. 非目标

- 不改变 UltraView Board、卡片、布局、快照和导出能力；
- 不在入口上显示卡片数量或 fresh/stale 状态；
- 不新增 View 关闭按钮，不重做 `联动缩放` / `锁定色阶`；
- 不提高 MainWindow 最小宽度；
- 不改 View 上限、View identity、split state 或项目 schema；
- 不把 UltraView 重新做成第六分析 mode；
- 不借此清理隐藏的 legacy 属性或重构整个 Toolbar。
