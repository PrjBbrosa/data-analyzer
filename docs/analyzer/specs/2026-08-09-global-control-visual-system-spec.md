# 全局操作控件视觉系统 — 产品与技术规格

日期：2026-08-09

状态：**P0 已于 2026-08-09 本地实现，P1 未实施**。P0 的产品与自动化证据已落地；
全局按钮高度种类 ≤4、macOS 前景和 Windows 冻结包仍为退出条件，不以离屏回归替代。

实施计划：`docs/analyzer/plans/2026-08-09-global-control-visual-system-implementation.md`

审计基线：`main@e782adcf` 加 2026-08-09 当前在途工作区；本文不整理、不覆盖这些在途修改

修订：2026-08-09 第二稿。第一稿只按**构造数量**审计，据此判定「几何已经协调，只需
提升绘制质感」。第二稿补做了**运行期实测**（`.state/global-control-refinement/
audit_controls.py` · `audit_search.py` · `audit_border_jitter.py`），结论相反：几何本身
就是最大的失配来源。受影响的章节为 §1 §2 §3 §5 §7.2 §9 §12.2 §15，并新增 §6.1
（高度轨道）、§7.3（选中签名）、§9.1（SearchField）、§9.2（二选一控件）。

## 1. 结论

TraceLab 已经具备统一的浅色仪器界面语言。真正拉低精致度的不是配色，而是**同一件事在
不同页面有不同的量度**：同一个 `role="primary"` 渲染成 32 / 36 / 40 px 三种高度，同一个
「选中」概念有五种画法三种蓝，同一个「搜索」有三种高度八种文案。这些差异逐个看都很小，
叠在一屏里就是「不像一个产品」。

因此本轮在共享 `ui_kit` 中建立的是一套**操作控件系统**，四条工作线：

1. **角色**：用 `primary / secondary / quiet / icon / danger / choice` 六种语义角色覆盖
   通用操作，兼容旧角色后逐点迁移，尤其先拆开当前混用的 `role="tool"`；
2. **量度**：建立 `compact 24 / base 32 / cta 36` 三档高度轨道（§6.1），让输入框、下拉框、
   步进器和普通按钮在同一行落在同一条基线上；这是本轮**收益最大**的一项；
3. **签名**：五族选择控件收敛到同一个选中签名（§7.3），几何可以按各自密度不同，
   「什么叫被选中」只能有一种画法；
4. **控件选型**：同一语义只用一种控件——一个共享 `SearchField`（§9.1）替代八处各自为政的
   搜索框；域层硬校验为二值的参数用分段控件而不是下拉（§9.2）。

外加一组共享控件色阶驱动 QSS 与手绘 `PillSwitch`，减少近似蓝在页面间漂移。同一份全局
QSS 同时影响 Analyzer 和 Cockpit，两个运行路径都必须做真实窗口验收。

P0 实施上述四条工作线加 `PillSwitch` 精修。复选框细节是 P1 候选，只有 P0 前景对比确认
整体密度仍协调后才进入；菜单、标签页、滑块和图表内部控件不属于本轮重做范围。

## 2. 当前代码事实

### 2.1 构造清单（界定影响面）

本文以当前 checkout 的真实构造与 QSS 为依据。数量用于界定影响面，不作为长期硬编码
指标；实施时须重新运行同一审计。

| 控件/契约 | 当前观察 | 影响 |
| --- | ---: | --- |
| `QPushButton` 构造 | 约 117 | 通用按钮改动的影响面最大 |
| `QToolButton` 构造 | 约 38 | 既有图标工具栏和文本工具操作不能混为一类 |
| `QCheckBox` 构造 | 约 36 | 数量多，但 P0 不改变其结构和交互语义 |
| `PillSwitch` 实例化 | 7 | 已有唯一共享 painter，适合一次性精修 |
| `QComboBox` / `QLineEdit` | 约 57 / 18 | 已有统一圆角和焦点状态，作为保护基线 |
| `QSlider` | 2 | 使用面小，本轮无重做收益 |
| 运行时 `QRadioButton` 构造 | 0 | 选择型 UI 已由专用可选按钮组承担 |

当前通用 `role` 使用约为：`primary` 19、`tool` 15、`destructive` 6、`create` 3、
`danger` 2、`accent` 2、`secondary` 1；另有 `panel-toggle`、`chart-choice`、
`tick-density-preset`、`frf-segment`、`frf-swap`、`slice-seg`、`preset-load` 等专用角色。

### 2.2 运行期实测（本轮的真正判据）

构造计数说明不了「看起来对不对」。以下数字来自 offscreen 加载真实 `style.qss` 后
实例化 Inspector、五个 contextual section、六个 Batch 面板、ChannelTree、FileNavigator、
QuickRef、Cockpit LeftPane，再读 `sizeHint().height()`。**实施时必须重跑同一脚本并对账。**

| 控件族 | 实测不同高度 | 具体值 |
| --- | ---: | --- |
| `QComboBox` | 1 | 32 —— 已经统一，作为轨道基准 |
| `QSpinBox` / `QDoubleSpinBox` | 1 | 32 —— 同上 |
| `QLineEdit`（搜索框） | 3 | 32 · 34 · 36 |
| `QPushButton` | **12** | 16 · 20 · 21 · 23 · 24 · 30 · 32 · 33 · 34 · 36 · 37 · 40 |

其中最能说明问题的三条：

- **同一个 `role="primary"` 有三种高度**：ChannelConfig 的「保存/应用」32、contextual
  section 的「计算 FFT / 计算频响」36、PersistentTop 的「应用 / 绘图」40。差异来自
  `Inspector QPushButton[role="primary"] { min-height: 30px }` 这类**更高特异性**的局部
  覆盖，不是调用方设的固定高度——所以只改全局规则不会收敛，必须逐条处理这些覆盖。
- **同一个 `role="tool"` 有三种高度**：20 · 21 · 23，且同时承载图标控件与「全选 / 全不 /
  已选 / 编辑通道 / + 添加配对组 / 删除」等文本动作。这条与第一稿判断一致。
- **Batch 方法选择器选中项比未选中项高 2 px**：`时域/时频/阶次/频响` 34，被选中的
  `频谱` 36。原因是 `QWidget#BatchMethodGroup QPushButton[batchMethod]` 静止态写
  `border: none`，`:checked` 却加 `border: 1px solid #2d7ff9`——加了一圈 1 px 边就把
  sizeHint 撑高 2 px。**每次切换分析方法这一排的高度都会跳一次。**
  `audit_border_jitter.py` 静态扫全表，同类缺陷还有 `QPushButton#BatchGroupingCard`
  （静止 1 px、`:checked` 2 px）。这直接违反 §8.1 自己写的「状态切换不得改变 border
  width」，而第一稿 §12.2 把这个区域列为「保持现状不动」，等于把缺陷冻结进合同。

### 2.3 「选中」有五种画法

同一个语义，五套 QSS，互不引用：

| 族 | 高度 | 选中态 |
| --- | ---: | --- |
| `frf-segment`（Inspector FRF） | 26 | 底 `#e8efff` + 字 `#1769e0` |
| `role="choice"`（Inspector） | 28 | 底 `#1769e0` 实心 + 白字 |
| `tick-density-preset` | 28 | 底 `#e7f1ff` + 字/边 `#0b7af3` |
| `chart-choice`（图表工具条） | 22 | 底 `#e8efff` + 边/字 `#2563eb` |
| `slice-seg` | 18（字号 9） | 底 `#2563eb` 实心 + 白字 |

三种强调蓝（`#1769e0` · `#2563eb` · `#0b7af3`），两种范式（浅底描边 vs 实心反白），
四种高度。`style.qss` 全表里强调蓝有 7 个近似值（`#1769e0` 42 次、`#2563eb` 11、
`#0a6de7` 9、`#0b7af3` 5、`#135abd` 5、`#2d7ff9` 4、`#1d4ed8` 1），浅蓝底 8 个。

### 2.4 搜索框八处、无一相同

| 位置 | 高度 | 清除键 | 放大镜 | 占位文案 |
| --- | ---: | :-: | :-: | --- |
| ChannelTree | 34 | — | — | `Filter channel...` |
| FileNavigator | 34 | — | — | `Filter channel...` |
| QuickRef | 34 | 有 | — | `搜索操作…` |
| Cockpit LeftPane | 34 | — | — | `搜索 name / 0x40A...` |
| Batch SignalPicker | 32 | — | — | `搜索信号…` |
| Cockpit HistoryTab | 32 | — | — | `搜索 name / id` |
| ConfigManager 配置 | 36 | 有 | — | `搜索配置或通道` |
| ConfigManager 通道 | 36 | 有 | — | `搜索此配置中的通道` |

三种高度、八种文案（中/英/中英混排，`...` 与 `…` 混用，有的带省略号有的不带）、
3/8 有清除键、**0/8 有搜索图标**。摆放位置也从容器首槽到第五槽都有。

### 2.5 二选一被塞进下拉

实测 18 个活的二选一 `QComboBox`。其中多数在**域层就被硬校验成恰好两个值**——
`signal/weighting.py:_validate_weighting` 限定 `{'None','A'}`，
`signal/frf.py` 限定 `estimator ∈ {'h1','h2'}`——不存在「以后会变多」的余地。
另有 `OutputPanel._combo_image_format` 只有 **1 个** 选项（`PNG`），是个点不开的下拉。

同一个 FRF 面板内部就自相矛盾：`频率轴`（对数/线性）与 `相位`（展开/包裹）已经
用 `_make_choice_row` 做成了分段控件并把 combo 隐藏起来当状态 API，而同样二选一的
`幅值`（dB/线性）、`NFFT 模式`（自动/手动）、`估计器`（H1/H2）仍是下拉。
**结论：这条不是新发明，是把已经验证过的做法补齐。**

例外（不属于本条）：`channelConfigCombo` 表面上也是两项，但第二项 `管理通道配置…`
是**动作**不是选项，且第一项列表随保存的配置增长——保持 combo。

### 2.6 局部样式复制

`ui/` + `ui_kit/` + `acquisition_ui/` 共 83 处 `setStyleSheet()`，集中在
`signal_picker.py`(13) · `markup/toolbar.py`(10) · `output_panel.py`(9) ·
`context_menu.py`(5) · `time_filter.py`(4) · `pipeline_strip.py`(4)。
`output_panel.py` 内联的 `#1769e0 / #eaf2ff / #cfe0f8` 就是一份手抄的按钮配色。
这些是 §G4「页面只声明语义」的反例，本轮不要求清零，但新增局部 QSS 必须有理由。

### 2.7 第一稿已确认、本稿保留的问题

- `primary`、`accent`、`destructive` 有全局 QSS，`secondary` 没有完整全局合同；
- `create`、`danger` 只在个别对话框下定义，跨页面同义操作不能稳定复用；
- `PillSwitch` 已固定为 44 × 24，行为合同正确，但目前轨道和滑块层次偏平；
- 全局 `style.qss` 由 Analyzer 与 acquisition/Cockpit 共用，Analyzer 中看起来正确不代表
  Cockpit 的密集工具条仍然正确。

## 3. 目标

### G1 — 建立稳定的操作层级

用户在不阅读按钮文字前，也能区分当前区域的主动作、辅助动作、低优先级工具动作和
危险动作。一个操作组原则上最多只有一个 `primary`。

### G2 — 同语义同外观，专用语义保留差异

通用动作通过共享角色复用；顶部模式选择、Batch 分析方法、图表分段和 Inspector
专用选择器继续使用各自命名空间，不被通用角色抹平。

### G3 — 用高度轨道换质感，不改页面布局

**本稿修订了第一稿的 G3。** 第一稿写「P0 不修改控件固定高度、最小高度」，但 §2.2 实测
说明高度失配正是精致度的主要缺口：在光栅上把 12 种按钮高度盖上更漂亮的渐变，得到的
是同样歪的排版加更贵的绘制。

P0 的边界改为：

- **允许改**：控件自身的 `min-height` / padding，使其落到 §6.1 的三档轨道；
  以及 §2.2 列出的那些更高特异性的局部高度覆盖；
- **不允许改**：布局 `margin` / `spacing` / 列宽 / 面板宽度 / 字体大小 / 图标尺寸 /
  卡片与浮层尺寸；
- **不允许**：靠缩小字体、负 margin 或裁剪来让文字塞进新高度（§9 仍然有效）。

净效果是行高变整齐、行数与面板尺寸不变。任何一处若不缩小面板就放不下，按 §9 处理，
不得压字。视觉提升来自对齐、边框、轻微层次和完整状态反馈，不依赖大阴影、发光或动画。

### G4 — 统一来源可维护

角色名、共享色阶、QSS token 与角色设置 helper 有明确的低层所有者；页面只声明语义，
不复制整段通用按钮样式。

### G5 — 可由真实渲染证明

验收同时覆盖几何、文字完整性、像素状态和前景观感。offscreen 截图只能证明确定性
渲染，不能替代 macOS 前景 TraceLab/Cockpit 验收。

## 4. 非目标

本轮明确不做：

- 不改变顶部分析模式区和 Batch 分析方法区的**结构**：居中、自适应分割线、mode-zone
  容器、选中标记的存在与位置都保持。**例外**：§2.2 实测出的选中项高 2 px 的抖动属于
  缺陷，必须修（做法是给静止态补 `border: 1px solid transparent`，不改任何可见尺寸）；
- 不重做 `QLineEdit` / `QComboBox` / `QSpinBox` 的**选择器结构、箭头、圆角族与 gutter
  几何**（§12.1 仍然是保护基线）。**不属于「重做」因而在范围内的**：让它们的高度参与
  §6.1 轨道（它们本来就已经是 32，实际是别人向它们对齐）、给搜索用途的 `QLineEdit`
  加共享 `role="search"`（§9.1）、以及把域层二值参数从 combo 换成分段控件（§9.2）
  ——后者改的是**控件选型**，不是 combo 的样式；
- 不重做菜单、标签页、滚动条和滑块；
- 不统一所有业务色、图表序列色、告警色、卡片圆角和浮层圆角；
- 不给每个按钮加蓝点、外发光、大面积投影或明显动画；
- 不把 checkbox 改成 switch，也不把 switch 改成 checkbox；
- 不增加新的产品功能、保存字段、QSettings、项目 schema 或快捷键；
- 不因本视觉调整修改 `APP_VERSION`、发布包或历史规格；
- 不顺手重构各页面布局和局部组件。

## 5. 视觉方向：Precision Light Controls

整体继续使用当前 Precision Light 语言：白色/冷白表面、蓝灰边界、深色正文和受控的
工程蓝。精致感来自微小而一致的材质差异：

- 默认按钮保持白色，仅有非常轻的顶部高光和底部冷灰；
- hover 只提升一个层级，不大幅变色；
- pressed 产生轻微内收感，不能表现成另一个主按钮；
- **`primary` 保持实心蓝填充**（见下方修订说明）；精致度来自 1 px 内侧顶部高光、
  更实的边界色和完整的 hover/pressed/disabled，而不是把它变淡；
- **`secondary` 用「白底 + 蓝字 + 蓝边」的描边式强调**，不是第二块浅蓝填充；
- quiet/icon 在静止时尽量融入背景，hover 后才出现边界；
- danger 静止时白底红字红边，hover 才填淡红；
- switch 的轨道、边界和滑块有一层可辨识的材质关系，但不做动画。

**本稿修订了第一稿的 primary/secondary 方向。** 第一稿写「primary 使用克制的浅蓝纵向
层次，不做高饱和实心大色块」「secondary 使用极浅蓝表面」。按那个方案落地会得到三块
互相打架的浅蓝：primary 浅蓝、secondary 更浅的蓝、以及全局既有的
`QPushButton:checked`（底 `#e8efff`、边 `#1769e0`、字 `#0f3f8f`）也是浅蓝。三者亮度差
只有几个百分点，G1 想要的「不读文字就能分主次」反而做不到，`:checked` 还会被误读成
主按钮。层级要单调，必须靠**材质范式**而不是同一范式内的明度微差：

```
实心填充(primary) > 描边强调(secondary) > 中性描边(默认) > 纯文字(quiet)
```

这四级在灰阶下依然可分（§14 要求），也把浅蓝填充这块领地干净地留给「选中」（§7.3）。

顶部模式选择器的蓝色竖向标记是“模式边界”的专用签名，不复制到普通按钮、开关或
checkbox，否则视觉语言会从精致变成装饰性重复。

## 6. 共享色阶

以下 token 只约束操作控件，不替代图表、数据序列、状态和品牌颜色。

| Token | 值 | 用途 |
| --- | --- | --- |
| `CONTROL_ACCENT` | `#1769E0` | primary 主色/开关开启态终点 |
| `CONTROL_ACCENT_HI` | `#2D7FF9` | hover、高光、开关开启态起点 |
| `CONTROL_ACCENT_DARK` | `#135ABD` | pressed 或强调边界 |
| `CONTROL_ACCENT_BORDER` | `#0F5FD2` | primary/on 边界 |
| `CONTROL_ACCENT_WASH` | `#EDF5FF` | secondary/hover 浅底 |
| `CONTROL_SURFACE_TOP` | `#FFFFFF` | 默认控件顶部 |
| `CONTROL_SURFACE_BOTTOM` | `#F8FAFD` | 默认控件底部 |
| `CONTROL_LINE` | `#D5DEEA` | 默认边界 |
| `CONTROL_LINE_HOVER` | `#AFC4DF` | hover 边界 |
| `CONTROL_TEXT` | `#253247` | 默认正文 |
| `CONTROL_TEXT_MUTED` | `#64748B` | quiet/disabled 文本 |
| `CONTROL_DANGER` | `#B42335` | danger 文字/边界 |
| `CONTROL_DANGER_WASH` | `#FFF2F3` | danger 表面 |
| `CONTROL_DISABLED_BG` | `#F3F5F8` | disabled 表面 |
| `CONTROL_DISABLED_LINE` | `#E2E7EE` | disabled 边界 |
| `CONTROL_ACCENT_LINE_SOFT` | `#A9C9F2` | secondary 描边（§5 修订新增） |
| `CONTROL_TRACK` | `#EEF1F6` | 选择族凹槽底（§7.3） |
| `CONTROL_TRACK_LINE` | `#DDE3EC` | 选择族凹槽边（§7.3） |
| `CONTROL_SELECT_LINE` | `#CDD8E8` | 选中药丸边（§7.3） |
| `CONTROL_TEXT_ON_SELECT` | `#12437F` | 选中药丸文字（§7.3） |

所有颜色值由 `mf4_analyzer/ui_kit/control_style.py` 的 `CONTROL_COLORS` 提供；
`CONTROL_QSS_TOKENS` 由这份映射派生，不能再手写第二份色值。`stylesheet.py` 将 QSS
token 与现有图标路径 token 合并后交给当前模板替换器，`PillSwitch` 直接读取
`CONTROL_COLORS`。QSS 和手绘控件不得再各自复制一套近似颜色。

§2.3 数出来的 7 个强调蓝里，只有下面三个进入操作控件：`CONTROL_ACCENT`（默认）、
`CONTROL_ACCENT_HI`（hover/渐变起点）、`CONTROL_ACCENT_DARK`（pressed）。
`#2563eb` · `#0b7af3` · `#1d4ed8` · `#0a6de7` 在操作控件里归零；它们若仍出现在图表、
状态或采集卡片等非操作控件语境，不在本轮范围内。

### 6.1 高度轨道

高度和颜色一样是共享 token，同样只有一个来源：`CONTROL_HEIGHTS`（同文件，同样派生出
QSS token）。只有三档：

| Token | 值 | 用途 |
| --- | ---: | --- |
| `CONTROL_H_COMPACT` | 24 | 密集工具条按钮、chip、图标按钮、行内动作 |
| `CONTROL_H_BASE` | 32 | **默认**：所有表单字段、搜索框、下拉、步进器、普通按钮 |
| `CONTROL_H_CTA` | 36 | 分区的唯一提交动作（计算 / 运行 / 应用） |

选 32 作为 base 不是新发明：`QComboBox` / `QSpinBox` / `QDoubleSpinBox` 现在**已经全是
32**（§2.2），是按钮没跟上。所以这一档是让按钮向既有基线对齐，不是把输入族推到新值。

落地要点：

- QSS 里写 `min-height` 而不是 `max-height`。`min-height` 是内容高下限，Qt 再叠加
  padding 与 border 得到实际高；`max-height` 会在 125% / 150% 缩放下裁掉中文。
  换算关系是 `实际高 = min-height + 上下 padding + 上下 border`，即
  base 32 = 22 + 4×2 + 1×2。改任一项都要重算另一项。
- 只有**有证据**的例外可以留在轨道外，且必须在 §12 或调用点注释里写明理由。已知的
  合理例外：`PillSwitch` 44 × 24（自绘几何）、view tab bar 26 / 28、
  `#plotSplitDivider` 一类分隔条、图表内部控件。
- §2.2 那批更高特异性的覆盖（`Inspector QPushButton[role="primary"]`、
  `QWidget#BatchCompactFooter QPushButton`、`QWidget#BatchCompactToolbar QPushButton`、
  `QLineEdit#channelConfigManagerSearch`、`QPushButton#channelConfigManagerCreate`、
  `Toolbar QPushButton`、`role="preset-load"`、`inspectorCollapser` 等）逐条判定：
  归入某一档就删掉局部数值改引 token；确属例外就保留并注明。**不允许原样留着不判定。**

## 7. 通用角色合同

### 7.1 六种标准角色

| 角色 | 适用语义 | 静止态 | 高度档 | 迁移来源 |
| --- | --- | --- | --- | --- |
| `primary` | 提交、计算、运行、确认等当前区域主动作 | **实心蓝填充**、深蓝边界、白字 | `cta`（分区提交）或 `base` | 保留现有 `primary` |
| `secondary` | 可见且非危险的辅助动作，如预览、重新生成、创建/导出 | 白底、蓝字、浅蓝边界 | `base` | `accent`、经审核的 `create`、现有 `secondary` |
| `quiet` | 文本型低优先级工具动作，如全选、编辑、取消 | 全透明，hover 才出现底与边 | `base` 或 `compact` | 文本型旧 `tool` |
| `icon` | 仅图标的紧凑工具操作，如关闭、更多、折叠 | 透明静止态，正方形 | `compact` | 图标型旧 `tool` |
| `danger` | 删除、终止等有破坏或中断含义的动作 | 白底、红字、浅红边界；hover 才填淡红 | `base` | `destructive`、现有 `danger` |
| `choice` | 互斥/可选状态；见 §7.3 的统一签名 | 未选透明，选中白色浮起药丸 | 由所在轨道决定 | 通用选择 + 收敛后的专用 choice 角色 |

`primary` 的高度档由所在区域决定，但**一个区域内的所有 `primary` 必须同档**——现在
Inspector 里 32 / 36 / 40 并存正是这条被违反的结果。

角色由 `set_control_role(widget, role)` 设置，并保留标准 Qt `setProperty("role", ...)`
结果，避免引入自定义 widget 基类。helper 必须在属性变更后安全触发 style repolish，供
动态角色/状态场景复用。

### 7.2 不进入标准角色的专用控件

以下角色继续由其组件/容器拥有：

- `panel-toggle`：顶部左右面板开关；
- Toolbar 顶部 mode buttons 与 Batch `MethodButtonGroup`：模式选择区；
- `chart-choice`、`tick-density-preset`：图表工具条选择；
- `frf-segment`、`frf-swap`、`slice-seg`：有固定几何的分析专用控件；
- `preset-load` / `preset-save`：包含 filled/applied 状态的预设交互；
- `link`：链接式文字入口；
- `messageBoxRole`：系统消息框按钮的独立角色命名空间。

这些控件可以引用共享色阶，但不得改名为标准角色来换取表面上的统一。

**但「保留命名空间」不等于「保留画法」。** 第一稿只说了名字归属，没约束这些角色的
选中态长什么样，结果就是 §2.3 的五种画法。本稿加一条硬约束：

> 命名空间、几何（高度、字号、内边距）可以按各自密度不同；
> **「什么叫被选中」只能有一种画法**，见 §7.3。

### 7.3 统一选中签名

所有互斥选择族——`choice`、`frf-segment`、`chart-choice`、`tick-density-preset`、
`slice-seg`、`cockpitMode`、Batch `batchMethod`——共用同一个签名：

```
容器（track）：凹陷冷灰底 CONTROL_TRACK  + 1px CONTROL_TRACK_LINE + 圆角
未选 segment ：完全透明，字 CONTROL_TEXT_MUTED
选中 segment ：白色浮起药丸 + 1px 冷灰边 + 字 CONTROL_TEXT_ON_SELECT，字重加一档
hover        ：只提字色，不加底
```

选这套「凹槽 + 白药丸」而不是「浅蓝底 + 蓝字」有三个理由：

1. 浅蓝填充这块领地已经给了 `QPushButton:checked`，再给选择族会撞车；
2. 它和 `primary` 的实心蓝在同屏时不争夺注意力——蓝色永远只意味着「主动作」，
   凹槽永远只意味着「在这几个里选一个」；
3. 白药丸自带 macOS 原生分段控件的语感，用户不需要学。

顶部 Toolbar mode zone 的**蓝色竖向标记**是 §5 定义的模式专用签名，与本条不冲突：
它标的是「当前处于哪个分析模式」这一全局状态，不是区域内的普通互斥选择。mode zone
继续保留该标记，其余六族一律不得复制。

Batch `MethodButtonGroup` 收敛到本签名时，顺带修掉 §2.2 的 2 px 抖动：静止态改为
`border: 1px solid transparent`，选中态换边色，几何不变。

### 7.4 旧角色兼容

切换顺序固定为：先增加兼容 QSS，再迁移 call site，最后删除旧规则。

| 旧角色 | 兼容映射 | 删除条件 |
| --- | --- | --- |
| `accent` | `secondary` | 所有 call site 已迁移且 grep 为零 |
| `destructive` | `danger` | 所有 call site 已迁移且 grep 为零 |
| `create` | 默认 `secondary`，逐个确认是否为局部主动作 | Channel Editor 实机与文字宽度通过 |
| `tool` | 不设单一别名；逐个分为 `quiet` 或 `icon` | 15 个现有 call site 全部有分类证据 |

`tool` 不能继续作为永久兼容别名，因为同一个名字同时承载两种相反的几何合同。

## 8. 状态合同

### 8.1 默认、hover、pressed、checked、disabled

- 每个标准角色都必须显式定义默认、hover、pressed 和 disabled；可检查角色还必须定义
  checked 与 checked:hover；
- 状态切换不得改变 padding、border width、字体或最小尺寸，避免 hover 时跳动；
- `pressed` 只改表面/边界，不通过位移或 margin 模拟下压；
- disabled 同时降低文字、边界和表面对比度，不能只把文字变灰；
- danger 的 hover/pressed 仍保持红色语义，不能变成 primary 蓝；
- checked 必须与 hover 可区分，不能只靠 1 px 边框颜色；
- 图标颜色若由现有资源决定，P0 不为每个状态生成新的图标资产。

### 8.2 焦点

当前 Qt5 中 `:focus` 也会在鼠标点击后持续存在，不能直接把强蓝色 focus ring 全局加到
按钮上。P0 保留既有键盘焦点与输入框焦点表现，不新增全局按钮 focus ring。

后续如要增加键盘专用焦点环，必须先建立独立的 `focusVisible` 输入模态机制，并通过
鼠标/键盘切换和前景测试；不能仅靠 QSS `:focus` 猜测用户输入来源。

## 9. 尺寸与几何合同

P0 的通用 QSS 改变**控件自身高度**（按 §6.1 轨道）与绘制，不改变页面布局合同：

- 普通按钮的 min-height / padding 改为引用 §6.1 token，圆角保持 8 px；
- 输入控件继续使用 7 px 外圆角；combo 右侧 gutter 继续使用 6 px；高度本来就是 base，
  不变；
- 图标按钮统一到 `compact` 正方形；调用方若已有 24 / 28 px 固定几何，以调用方为准
  且不因全局 `icon` 角色被改写；
- **Inspector 的 `role="primary"` 30 px 局部覆盖需要重新判定**：它是 §2.2 中 40 px 那一档
  的成因。判定结果要么归入 `cta`，要么保留并写明为什么该区域必须与其他 primary 不同；
- Batch 页脚、预览窗口和 Channel Editor 的显式高度同样逐条判定，规则同上；
- 文字不得通过缩小字体、负 margin、极小 padding 或裁剪来适应按钮；应先验证按钮的
  size hint 和所在布局宽度；
- 所有中文按钮在 100%/125%/150% 缩放与当前应用字体下必须完整显示；
- 因此高度一律用 `min-height` 表达，禁止用 `max-height` 卡死可变文字的控件。

圆角不做全局归一化。输入 7 px、combo gutter 6 px、普通按钮 8 px、专用 segment 6 px、
卡片 9 px、浮层 12/14 px 是有意的层级差异。

### 9.1 共享 `SearchField`

§2.4 的八处搜索框改为共用 `mf4_analyzer/ui_kit/widgets/search_field.py:SearchField`
（`QLineEdit` 子类，与 `SearchableComboBox` 同层）。合同：

- 高度 `CONTROL_H_BASE`（32），`role="search"`，圆角与输入族一致；
- **前置放大镜图标**，走现有 `ui_kit/icons.py` 缓存机制（与 combo 箭头同一条路径，
  不新引资源加载方式）；
- **`setClearButtonEnabled(True)` 常开**——现在 3/8 有、5/8 没有，属于随机差异；
- 占位文案统一为 `搜索<对象>…`：`搜索通道…` · `搜索信号…` · `搜索配置…` ·
  `搜索操作…`。中文、U+2026 省略号、无英文。Cockpit 那两处需要提示可搜 ID 的，
  用 tooltip 承载 `name / 0x40A`，不塞进占位文字；
- 摆放位置不由本控件规定（各面板信息架构不同），但**同一个列表上方**是默认；
  §2.4 里 ConfigManager 把搜索放在第五槽属于个案，实施时按面板实际结构判定，
  不为统一而重排布局；
- 不改变各调用点的过滤逻辑、防抖、快捷键与信号名。

### 9.2 二选一控件

§2.5 的判据是**域层是否把取值硬校验成恰好两个**，不是「现在只有两项」：

| 参数 | 位置 | 域层约束 | 处置 |
| --- | --- | --- | --- |
| 计权 None/A | FFT · FFTTime · Order · Batch Analysis | `weighting.py` 硬校验 | → 分段 |
| 幅值 dB/线性 | FFT · FFTTime · Order · FRF · Batch Output | 显示口径二值 | → 分段 |
| 估计器 H1/H2 | FRF · Batch | `frf.py` 硬校验 | → 分段（短标签 + tooltip） |
| NFFT 模式 自动/手动 | FRF | 二值 | → 分段 |
| 转速来源 通道/手动 RPM | Order | 二值 | → 分段 |
| X 轴来源 自动/指定通道 | PersistentTop | 二值 | → 分段 |
| 区间 全时段/指定 | Batch Analysis | 二值 | → 分段 |
| 切片轴 固定时间/固定频率 | Batch Slice | 二值 | → 分段 |
| 图片格式 PNG | Batch Output | **只有 1 项** | → 去掉下拉，改静态文本 |
| 目标策略 所有来源共有/按来源可用 | Batch Input | 二值但标签很长 | 先量宽度；288 px 下放不下就留 combo 并记录理由 |
| 配置选择器 | ChannelTree · FileNavigator | 列表可增长 + 含动作项 | **保持 combo** |

#### 9.2.1 字段槽宽度合同（不可协商）

Inspector 表单的字段列是**共享右边缘的等宽列**，由
`_helpers.py:_fit_field()` 加上 `_SHORT_FIELD_MAX_WIDTH == _LONG_FIELD_MAX_WIDTH == 260`
实现。该文件注释明确写着这是用户选定的 A1 布局：

> "inputs should fill the form's field column instead of keeping short numeric
> values in visibly shorter boxes"

因此分段控件**必须走同一个 `_fit_field()`**、占满同一个 260 px 槽、内部按选项数
等分。绝不允许因为「只有两个字」就让它收缩成一个短药丸——那会把这一列打散成
参差不齐的右边缘，损失比换控件带来的收益大得多。

已实测验证（`.state/global-control-refinement/render_panel_compare.py`，
真实 `FFTContextual` @ 288 px）：

| 行 | 现状 左..右 / 高 | 提案 左..右 / 高 |
| --- | --- | --- |
| 窗函数 | 71..277 / 32 | 71..277 / 32 |
| NFFT | 71..277 / 32 | 71..277 / 32 |
| 平均模式 | 71..277 / 32 | 71..277 / 32 |
| **幅值轴** | 71..277 / 32 | **71..277 / 32** |
| **频率加权** | 71..277 / 32 | **71..277 / 32** |

标签列、字段列、右边缘、行高、行数、卡片高度全部不变；变的只是那两行**同时显示
两个选项**而不是把其中一个藏在下拉里。分段容器的高度换算固定为：

```
track 32 = button 26 + 2×2 容器 margin + 2×1 容器 border
button 26 = min-height 20 + 2×2 padding + 2×1 border
```

实现沿用 `contextual_frf.py:_make_choice_row` 已经验证的做法，把它提升成
`ui_kit/widgets/segmented_choice.py:SegmentedChoice`：

- **原 `QComboBox` 保留但隐藏**，继续作为状态与 API 表面。预设、项目读写、批处理
  recipe 和现有测试都通过 `currentData()` / `setCurrentIndex()` 访问，这样迁移
  **不触碰任何持久化格式，也不改任何信号契约**；
- `SegmentedChoice` 与 combo 双向绑定，容器用 §7.3 的统一签名；
- 每个 segment 保留原 combo item 的 tooltip；
- 标签超过两个汉字宽度时优先缩短显示文字（`H1（输出噪声）` → `H1`）并把全文放进
  tooltip，**不缩小字体**。

FRF 面板里 `频率轴` / `相位` 已经是这个形态，本条只是把 `幅值` / `NFFT 模式` /
`估计器` 补齐，让同一张面板内部先自洽。

### 9.3 幅值单位（dB / Linear）的归属

这与 §9.2 是**两件事**：§9.2 说的是「用什么控件」，本条说的是「放在哪个区」。
用户 2026-08-09 指出 Inspector FFT 把它放错了区，核对属实。

| 面板 | 现在放在 | 控件 | 判定 |
| --- | --- | --- | --- |
| Inspector 时频 | 坐标轴设置 → 色阶(Z) 行内联 | `combo_amp_unit` | ✅ 正确 |
| Inspector 阶次 | 坐标轴设置 → 色阶(Z) 行内联 | `combo_amp_unit` | ✅ 正确 |
| Batch 输出 | 坐标轴设置 → 辅助行「幅值单位:」 | `combo_amp_unit` | ✅ 正确 |
| **Inspector FFT** | **谱参数 → 「幅值轴:」** | `combo_amp_y` | ❌ **要改** |
| Inspector FRF | 显示与可信度 | `combo_magnitude_scale` | ⚠️ 见下 |

**归属规则**：dB/Linear 是**显示口径**，不是计算参数——改它不需要重算，只换坐标轴
标注方式。所以它属于「坐标轴设置」，跟着承载幅值的那根轴走：

- 幅值在 Y 轴（FFT 线图）→ 坐标轴设置的幅值单位辅助行；
- 幅值在 Z 轴/色阶（时频、阶次图）→ 色阶行内联。

放在「谱参数」里会暗示它参与频谱计算（窗函数、NFFT、重叠都在那一区），语义是错的。

**这套机制项目里已经存在，Inspector FFT 只是没接上。**
`_helpers.py:_make_axis_settings_group()` 有 `amplitude_unit_row_label` 参数，
`ui/drawers/batch/output_panel.py:424` 已经在用（`amplitude_unit_row_label="幅值单位:"`），
其实现注释就是为这个场景写的：

> "Batch FFT line plots use an amplitude unit but no colour scale. Keep this
> control outside the heatmap-only Z row so changing the method cannot hide
> the control or force a widget reparent."

阻碍只有一个：该分支被关在 `if include_z:` 里，而 Inspector FFT 传
`include_z=False`。所以改动是：

1. 把幅值单位辅助行从 `if include_z:` 里**提出来**，让它对 `include_z=False` 也成立；
2. 允许调用方**传入已有 widget**，而不是强制使用 helper 自建的 `combo_amp_unit`；
3. `contextual_fft.py` 传入它现有的 `self.combo_amp_y`，并从 `谱参数` 表单里移除该行。

**持久化零影响是硬约束**：`combo_amp_y` 与 `combo_amp_unit` 是两个不同对象——
键不同（`amp_y` vs 由 `combo_amp_unit` 派生的 `amplitude_mode`）、
选项顺序不同（`['Linear','dB']` vs `['dB','Linear']`）、默认值不同（`Linear` vs `dB`）。
**只准搬 widget，不准换 widget**；换掉会同时改预设键、默认值和项目读写语义，
超出本轮范围且会静默改变已保存工程的行为。

FRF 的 `combo_magnitude_scale` 判定为**可接受**：FRF 面板结构不同，没有
`坐标轴设置` 组，`显示与可信度` 就是它的显示口径区，`频率轴` / `相位` 也在同一张卡里，
内部是自洽的。本轮不动，但要在代码注释里记下这个判定，避免下次又被当成不一致。

净效果：`谱参数` 少一行，`坐标轴设置` 在 `幅值 (Y)` 行下方多一行「幅值单位:」，
总行数不变。**面板总高不是不变，实测 748 → 740 px（矮 8 px）**——两个组的
内边距/行距不同，搬迁必然带来这一点差值。原型证据：
`.state/global-control-refinement/evidence/ampunit-placement-before-after.png`。
验收断言要写这个**实测差值**，不要写「容差 0」，否则测试必红。

实现注意（原型撞到过）：`QFormLayout.removeRow()` 会**销毁**该行的 widget。
真实改动是「一开始就不 `addRow`」，不存在这个问题；但任何走运行时拆行路线的
代码或测试必须用 `takeRow()`，否则 `combo_amp_y` 连同 `amp_y` 预设键一起没了。

## 10. `PillSwitch` 合同

`mf4_analyzer/ui/widgets/pill_switch.py:PillSwitch` 继续作为即时启用/停用设置的共享控件，
不迁移到页面局部 QSS，也不复制新的开关类。

### 10.1 保持不变

- 外部几何固定 44 × 24；
- `isChecked()/setChecked()`、clicked/toggled 和现有 signal 行为不变；
- 左右滑块位置、hit area、enabled/disabled 与键盘切换语义不变；
- 不增加动画 timer，不增加持久化字段，不读取 QSettings；
- 所有现有七处实例化无需修改布局。

### 10.2 绘制精修

- off 轨道使用极轻冷灰纵向层次和 1 px 边界；
- on 轨道使用 `CONTROL_ACCENT_HI → CONTROL_ACCENT` 的轻微纵向渐变，边界为
  `CONTROL_ACCENT_BORDER`；
- 白色 knob 增加 1 px 冷灰阴影/下沿与轻微顶部高光，不做模糊大阴影；
- disabled 同时降低轨道、边界和 knob 对比度；
- hover/pressed 只能做一个色阶变化，不能改变 knob 几何；
- DPR 1 和 DPR 2 下边缘、圆角和 knob 中心均需像素验证。

## 11. Checkbox P1 候选

Checkbox 保持“多选/纳入/选项”的语义；立即生效的 feature enable 才使用 `PillSwitch`。
P1 候选只做：

- 16 × 16 几何不变；
- 圆角从当前视觉上的约 4 px 精修到 5 px；
- 未选边界更安静，hover 使用极浅蓝 wash；
- checked 继续使用缓存的 check glyph，不运行时绘制文字字符；
- disabled 和 partial/tri-state（如有）必须保留可辨识状态。

P1 不是 P0 默认实施内容。只有 P0 contact sheet 和真实窗口显示按钮/开关提升后，checkbox
仍明显失配，才由用户确认进入实施。

## 12. 保护基线与边界

### 12.1 输入框和下拉框

当前输入族已具备 7 px 父控件圆角、combo 6 px gutter、缓存箭头和焦点边界，并有
`tests/ui_kit/test_combo_corner_radius.py`。P0 不改其选择器、箭头、圆角或高度
（高度本来就是 base=32，是别人向它对齐）。padding 只在与 §6.1 换算冲突时才动，
且动完必须让 `test_combo_corner_radius.py` 与其派生的 gutter 半径推导仍然成立。

### 12.2 顶部与 Batch 模式选择区

顶部 Toolbar 和 Batch 方法按钮是“分析模式导航”，不是普通 action buttons：

- 保留居中、后续增删按钮时自适应、两侧分割线对称的合同；
- 保留 mode-zone 容器；顶部 Toolbar 保留其蓝色竖向模式标记（§7.3）；
- 通用 control token 可被它们引用，但标准按钮 QSS 不得覆盖其选择器。

**修订：第一稿写「保留当前等高」，但实测该区域现在并不等高。**
`QWidget#BatchMethodGroup QPushButton[batchMethod]` 未选 34、选中 36（§2.2），
每次切换方法整排跳 2 px。「保留」在这里会把缺陷写成合同。正确表述是：

> 该区域**必须**等高，且状态切换不得改变几何。当前不满足，属于本轮要修的缺陷。
> 修法是给静止态补 `border: 1px solid transparent`——可见外观不变，只让盒模型对齐。
> `QPushButton#BatchGroupingCard`（静止 1 px / `:checked` 2 px）同理。

这条不是「顺手扩大范围」：§8.1 本来就写了「状态切换不得改变 border width」，
§12.2 的豁免与它直接矛盾，两者只能留一个。

### 12.3 QMessageBox

`messageBoxRole="primary|warning|danger|neutral"` 继续由
`ui_kit/message_box_buttons.py` 管理，不能折叠进普通 `role`。允许与共享操作色阶对齐，
但必须保留：

- 根据中文文字计算内容宽度的 `fit_message_box_buttons_to_text()`；
- QSS `min-width` 是内容宽、padding 另计的现有修复；
- warning 与 danger 的不同语义；
- 长中文按钮真实渲染不裁字的回归测试。

### 12.4 Analyzer 与 Cockpit

`ui_kit/style.qss` 是跨入口共享资源。任何全局按钮选择器改变都必须同时检查：

- Analyzer 主窗口、Inspector、文件导航、Batch、预览与对话框；
- Cockpit/acquisition 的主工具条、overflow 行为和密集窗口；
- shared stylesheet import/load 边界。

## 13. 代码所有权与复用结构

新增低层模块：

```text
mf4_analyzer/ui_kit/control_style.py
├── 标准角色常量
├── CONTROL_COLORS（唯一色值来源）
├── CONTROL_HEIGHTS（唯一高度来源，§6.1）
├── CONTROL_QSS_TOKENS（由上面两份映射派生）
├── set_control_role(widget, role, *, size=None)
└── 角色/档位有效性校验 + 轻量 repolish

mf4_analyzer/ui_kit/widgets/search_field.py      # §9.1
mf4_analyzer/ui_kit/widgets/segmented_choice.py  # §7.3 + §9.2
```

职责分配：

| 文件 | 单一职责 |
| --- | --- |
| `ui_kit/control_style.py` | 角色、高度档、唯一操作色阶、派生 QSS token、设置 helper |
| `ui_kit/style.qss` | 通用按钮各状态、统一选中签名和兼容 aliases |
| `ui_kit/stylesheet.py` | 将 control token 与图标 token 合并后渲染 QSS |
| `ui_kit/widgets/search_field.py` | 搜索框几何、图标、清除键、占位文案约定 |
| `ui_kit/widgets/segmented_choice.py` | 分段控件构造 + 与隐藏 combo 的双向绑定 |
| `ui/widgets/pill_switch.py` | 开关几何、交互和 painter，引用共享色阶 |
| 页面/对话框 | 只声明动作语义和保留必要的局部几何例外 |

`search_field.py` / `segmented_choice.py` 放 `ui_kit/widgets/` 与既有
`searchable_combo.py` 同层，遵守 §13 的依赖方向：只依赖 Qt 与 `ui_kit`，
不得 import `mf4_analyzer.ui`，由 `tests/ui/test_import_boundaries.py` 看守。

依赖方向固定为 `ui/* → ui_kit/*`。`ui_kit` 不得 import `mf4_analyzer.ui`、MainWindow、
Batch drawer 或 acquisition UI。P0 不新增通用按钮 subclass；QSS 属性足以表达的内容不
封装成新的 widget 层。

## 14. 可访问性与文案

- 图标-only 控件必须有非空 tooltip 和 accessible name；
- 文本按钮保留清楚的动词，不能只靠颜色表达危险或主次；
- primary 与 secondary 在灰阶下仍要靠边界/表面层次区分；
- danger 同时使用文字和颜色语义，不能只有红色；
- disabled 文字对比度应可读，但必须明显不可操作；
- 不缩小中文字体来解决密集布局；
- 开关必须保留可检查状态，旁侧标签负责说明业务含义。

本轮不新增或重命名用户交互，因此正常情况下不需要修改 `ui/hints.py`、
`ui/quickref.py` 或帮助文档。若实施中确实改变可见命名/操作方式，则必须同步这两处。

## 15. 验收合同

### 15.1 自动化/确定性渲染

必须生成同尺寸 before/after contact sheet，至少包含：

- default/hover/pressed/disabled 的普通、primary、secondary、quiet、icon、danger；
- checkable choice 的 off/on/hover/disabled；
- `PillSwitch` 的 off/on/hover/pressed/disabled；
- 长中文按钮、图标-only 按钮、文本型工具按钮；
- QMessageBox 长中文按钮；
- Analyzer 与 Cockpit 各一个密集操作区。

自动检查：

- **控件高度收敛**（本稿新增，是主 gate）：重跑 §2.2 的 `audit_controls.py`，
  `QPushButton` 的不同高度数从 12 降到 ≤ 4（三档轨道 + 明确记录的例外集合），
  且 `role="primary"` 在全应用只剩一个高度值；
- **状态切换 geometry 不变**：`audit_border_jitter.py` 静态扫描 0 命中；
  运行期对每个可检查控件断言 `sizeHint(checked) == sizeHint(unchecked)`；
- **选中签名唯一**（本稿新增）：§7.3 列出的七族，选中态的底色/边色/字色三元组
  必须相等；测试直接比较渲染像素，不是比较 QSS 文本；
- **搜索框统一**（本稿新增）：重跑 `audit_search.py`，八处高度全为 32、全部有
  clear button 与放大镜、占位文案匹配 `^搜索.+…$`；
- **二选一收敛**（本稿新增）：§9.2 表里标为「→ 分段」的项，运行期不再有可见
  `QComboBox`；隐藏 combo 的 `currentData()` 与 `SegmentedChoice` 选中项保持同步；
  全应用不存在 `count() == 1` 的可见 combo；
- before/after 页面**布局** spacing、面板宽度、行数不变（行高允许按 §6.1 变化）；
- 每个标准角色在所有必需状态下存在非透明边界/表面合同；
- 四级层级在灰阶下仍单调（§5）：把 before/after 转灰后，
  primary / secondary / 默认 / quiet 的平均表面亮度严格递增；
- DPR 1/2 的 switch 边缘、圆角、knob 中心和 disabled 状态符合采样规则；
- QSS 模板不存在未解析的 `{{CONTROL_*}}`；
- 旧角色迁移后，标准业务 call site 不再产生未分类 `tool/accent/create/destructive`。

所有 render probe 必须隔离 QSettings。生成证据放 `.state/`，不默认提交 Git。
方向锁定用的第一张对比图已生成：
`.state/global-control-refinement/evidence/control-system-before-after.png`
（五段：操作层级 / 高度基线 / 选中签名 / 搜索框 / 二选一），生成脚本
`.state/global-control-refinement/render_compare.py` 与草案覆盖
`.state/global-control-refinement/proposal.qss`。

### 15.2 窗口矩阵

| 入口/区域 | 至少验证 |
| --- | --- |
| Analyzer 1440 × 900 | 顶部、文件导航、Inspector、图表工具条 |
| Analyzer 1080 × 760 | 窄窗口下文字完整、无按钮挤压 |
| Inspector 约 288 px 宽 | 主次动作和文本工具按钮不裁字 |
| Batch sheet/preview | 预览、运行、终止、重新生成、取消层级明确 |
| Channel Editor/Config Manager | 创建、保存、批量操作、删除层级稳定 |
| QMessageBox | 长中文按钮完整，默认/危险语义明确 |
| Cockpit 常规与密集宽度 | 工具条和 overflow 不回归 |

### 15.3 前景验收

macOS Cocoa 前景 TraceLab/Cockpit 必须确认：

1. 按钮没有高度、基线和间距变化；
2. primary 醒目但不成为大面积高饱和蓝块；
3. secondary、quiet、icon 的层级从强到弱连续；
4. switch 提升材质感但没有动画、锯齿或 knob 偏心；
5. Batch/Inspector 的中文文字没有压缩或裁切；
6. 顶部与 Batch 模式区未被通用 QSS 误伤；
7. Cockpit 工具条、overflow 和密集窗口仍可用。

offscreen Qt 通过不等于本项通过。Windows frozen 外观属于后续发布门；本轮本地实施只能
记录 source/offscreen 结果，不能宣称 Windows 前景已验收。

## 16. 退出条件

只有同时满足以下条件，P0 才可标记完成：

- 六种标准角色和兼容/迁移合同都有测试；
- 旧 `tool` 15 个 call site 已按文字/图标语义逐个分类；
- **§6.1 三档轨道落地，`audit_controls.py` 重跑后按钮高度数 ≤ 4，
  `role="primary"` 全应用单一高度，例外集合有清单和理由**；
- **§7.3 统一选中签名覆盖七族，`audit_border_jitter.py` 零命中**；
- **§9.1 `SearchField` 替换八处搜索框，`audit_search.py` 全绿**；
- **§9.2 表中标为「→ 分段」的项全部完成，1 项下拉已消除，隐藏 combo 的持久化
  与信号契约未变（现有 preset / project IO 测试不改一行仍通过）**；
- `PillSwitch` 七处实例化保持原几何和行为；
- Analyzer、Batch、对话框、MBox 和 Cockpit 的确定性证据完成；
- focused tests、import boundaries、shared stylesheet tests 通过；
- macOS 前景验收完成，未完成项明确标为 `UNVERIFIED`；
- 无无关源码改动、无版本升级、无自动提交/推送。

P0 完成后再决定是否执行 §11 的 Checkbox P1；不得在首期实施中顺手带入。
