# 批处理稳定布局、屏幕内弹层与圆角绘制归属 —— 实施计划

**日期：** 2026-08-02

**状态：** 已实施并完成离屏验收；macOS 前台/多显示器人工验收待执行

**Follow-up to：**

- `docs/superpowers/plans/2026-08-02-batch-inline-file-manager-and-control-polish.md`
- `docs/superpowers/specs/2026-08-02-batch-inline-file-manager-and-control-polish-design.md`
- `docs/superpowers/specs/2026-06-19-surface-radius-alignment-design.md`

本计划不改写已完成计划的历史结果。它只覆盖上一轮“文件区随行数变化”的尺寸策略，
并补充预设字号、TimeDomain X 轴条件布局、Batch 刻度弹层屏幕边界及全局圆角绘制归属审计。

## 实施记录（2026-08-02）

- 文件管理框已固定为 `250px`；0/1/4/8 行不再推动下方目标区，长列表只在内部滚动，
  并在边界继续转交滚轮给外层 Input pane。
- 四张预设卡的自绘标题/摘要为 `10pt/8pt`；以 `compact=true` 的 QSS 配对保证实际外框
  高度为 normal `66px`、compact `40px`，窄栏 compact 模式隐藏摘要以免裁字。
- TimeDomain 的 `x_origin` / `x_channel` 已共用右列的同一 field host slot。
- `RenderStylePopover.show_at(anchor)` 已统一执行 screen-aware 8px clamp、下方优先、向上翻转、
  重开稳定定位和 anchor 移动/resize/scroll 后关闭。
- Batch 文件框的 parent 已是唯一的白底/边框/圆角绘制者，touching body/list/viewport/empty/row
  透明承接；DPR 1/2 arc profile 通过。全局审计见
  `docs/superpowers/reports/2026-08-02-rounded-surface-paint-ownership-audit.md`：除 Batch 外未确认
  第二个可离屏复现的缺陷，因此没有进行全局 QSS 批量修改。
- 集成离屏回归：`235 passed`（完整 Batch UI cluster + `test_surface_layering.py`）；
  `1080×760` / `1440×900` 渲染矩阵输出位于
  `/tmp/tracelab-batch-ui-20260802/`。这不是 macOS 前台验收的替代。

## 1. 用户需求与确定解释

本轮实施范围为五项：

1. 第一层文件管理区的**纵向可视高度**适当增大并固定；空态、少量文件和大量文件之间不再
   自动改变高度，溢出只由文件列表内部滚动承接；
2. 四张分析预设卡的名称和摘要字号增大；
3. TimeDomain 将 X 轴来源切换为“通道”时，`X 通道` 不再跳到左列；
4. `刻度与字体` 弹层每次从锚点重新定位，不能逐次向下漂移或越出当前屏幕；
5. 修复截图中圆角边线泛白/缺弧，并对全局同类控件按绘制路径审计，不能只给当前卡片
   加深边框，也不能给所有 QWidget 统一加透明属性。

第 1 项按截图解释为纵向高度问题，不调整 Input / Analysis / Output 三栏横向比例。

## 2. 当前源码与渲染证据

### 2.1 文件区域为何会变高

`FileListWidget._after_change()` 当前执行：

```python
self._list.setFixedHeight(min(row_count, 4) * 46 + 10)
```

空态由 88px minimum label 决定，加载 1–4 行时列表按行数逐级变高，超过 4 行后才固定。
所以“目标”区会随文件数上下移动，这与本轮固定视口要求直接冲突。

### 2.2 预设字号为何不受 QSS 控制

`_PresetCard.paintEvent()` 自绘文字并显式创建 9pt 标题和 7pt 摘要字体；
`QPushButton#BatchAnalysisPresetCard` 的 QSS `font-size` 不控制这两段自绘文字。

### 2.3 X 通道为何跳到左侧

TimeDomain 字段顺序为：

```text
render_layout -> x_source -> x_channel -> x_origin
```

两列网格把 `render_layout / x_source` 放在一行，把 `x_channel / x_origin` 放在下一行。
`_sync_x_source()` 再互斥隐藏 `x_channel` 和 `x_origin`：时间模式显示右侧 `x_origin`，
通道模式显示左侧 `x_channel`，因此发生截图中的横向跳位。

### 2.4 刻度弹层为何只向下

`OutputPanel._on_render_style_clicked()` 当前固定执行：

```python
origin = anchor.mapToGlobal(anchor.rect().bottomRight())
popover.move(origin.x() - popover.width(), origin.y() + 4)
```

它不读取锚点所在屏幕的 `availableGeometry()`，不判断下方空间，也没有向上翻转和四边
clamp。重复打开时还依赖当前全局锚点，缺少稳定的单一 `show_at(anchor)` 合同。

### 2.5 圆角“缺线”的已确认根因

截图中的外框由 `QFrame#BatchInlineFileManager` 绘制：1px `#d7e2f0` 边框、9px radius、
白色背景。其零 margin 布局内是同样显式绘白的
`QWidget#BatchInlineFileManagerBody`；空态 label、QListWidget 和 viewport 也沿用白底。

Qt QSS 的 `border-radius` 只约束当前 widget 的绘制，不会自动把子 widget 裁成同一圆角。
父框先画抗锯齿圆弧，子 body 随后从矩形 `(1,1)` 开始绘白，于是覆盖父圆弧的内侧像素。

已执行的只读 Qt 像素探针：

- 外框尺寸：`336×140`；
- 内层 body：`(1,1,334,138)`；
- 隐藏 body 时，左上 9px 圆弧的中间蓝灰像素连续可见；
- 显示 body 时，中间弧线像素变成纯白，只剩顶边和左边直线；
- 浅色 1px 边框的抗锯齿像素本来就接近白色，子层覆盖进一步放大了“泛白/缺角”观感。

因此本点的主因是**绘制归属和子层覆盖**，不是漏写 `border-radius`，也不是当前外框缺少
`WA_StyledBackground`；父框和 body 已经设置了该属性。

## 3. 全局圆角问题的分类

当前主 QSS 有 131 个包含 `border-radius` 的规则。并非 131 个都有问题，也不能用一个
全局 selector 修复。实施必须按以下绘制族路由：

| 绘制族 | 典型风险 | 正确修复方向 | 禁止做法 |
|---|---|---|---|
| 嵌入式圆角 shell | 贴边矩形 child 覆盖父圆弧 | 父层唯一负责 fill/border/radius；child 透明或真实 inset | 全局给 QWidget 加 mask/translucency |
| QScrollArea/QList/QTree | viewport/holder 再绘一个方形背景 | scroll、viewport、holder 分别核对 autoFill/QSS；让外层 shell 提供底色 | 只改 QScrollArea 自身 radius |
| 自绘控件 | paintEvent 半径与 QSS token 不一致 | 统一同一半径和同一 paint owner | 只改 QSS，不读 paintEvent |
| 顶层 popup/menu | 原生窗口 backing/shadow 是矩形 | translucent outer shell + frameless/no-shadow + rounded inner surface | 把 popup 方案照搬到普通嵌入卡片 |
| 叶子按钮/徽标/输入框 | 子控件或 subcontrol 覆盖右侧圆角 | 只修已证明的 subcontrol/paint 路径 | 因“全局很多”批量改全部 131 条规则 |

全局 `QWidget { background-color: #ffffff; }` 是放大器：任何未被更具体 selector 改为
transparent 的贴边 child 都可能重新绘白。但本计划不直接删除该全局规则，因为它同时
承担大量普通页面和控件的基础底色。

## 4. 实施原则

- 先用失败的几何/像素测试固定问题，再改产品控件。
- 每个圆角 surface 明确一个 paint owner；同一层不能由 parent 和 child 重复绘白。
- 嵌入式卡片优先用 transparent child / localized inset；`WA_TranslucentBackground` 只用于
  确认需要 alpha/native shell 的路径，不能成为全局万能补丁。
- 文件 source model、probe 生命周期、信号交集、预检和 BatchRunner 不变。
- X 轴只是布局槽位固定，`x_source / x_channel / x_origin` 的保存、校验和 legacy patch
  行为不变。
- Qt 离屏结构、像素证据与 macOS 前台观感分开报告。
- 不修改现有无关的 Batch renderer/SSAA 工作树文件，不自动 commit/push。

## 5. Phase 0 — 建立红色合同与审计清单

**Files**

- Modify: `tests/ui/test_batch_input_panel.py`
- Modify: `tests/ui/test_batch_method_buttons.py`
- Modify: `tests/ui/test_batch_output_panel.py`
- Modify: `tests/ui/test_surface_layering.py`
- Modify: `tools/render_batch_compact_ui.py`
- Create: `docs/superpowers/reports/2026-08-02-rounded-surface-paint-ownership-audit.md`

**工作**

- [ ] 为 0、1、4、8 个 source 显示真实 InputPanel，断言
  `BatchInlineFileManager.height()` 始终相同且为 `250px`；8 行时内部 scrollbar maximum > 0，
  外层 Input pane 仍能滚动到预处理末尾。
- [ ] 为四张 `_PresetCard` 断言 normal title=10pt、summary=8pt；compact title 仍为 10pt，
  文字 bounding rect 不越过 card content rect。
- [ ] 切换 `x_source: time -> channel -> time`，断言 `x_origin` 与 `x_channel` 占用同一个
  右列 geometry，左列始终不出现 X 轴 dependent field，`x_source` 本身不移动。
- [ ] 在屏幕四角构造 render-style anchor，断言 popup frame 全部位于当前 screen
  `availableGeometry()` 的 8px margin 内；下方不足时位于 anchor 上方。
- [ ] 连续开关 popup 三次，断言每次 global top-left 完全一致，不发生累计 y 偏移。
- [ ] 扩展 `tests/ui/test_surface_layering.py` 的透明 QImage helper，新增 border-arc profile：
  四角的弧线像素必须形成连续非白序列，中心保持不透明白色，直边不能丢失。
- [ ] 永久回归要求“显示真实 body 时圆弧连续”，并在当前代码上先红；另用不提交为长期
  合同的诊断 probe 记录“隐藏 body 时圆弧恢复”，作为 root-cause 证据。不得用“QSS 中
  存在 border-radius”作为视觉通过条件。
- [ ] 生成全局 paint-owner 清单，至少记录 selector、runtime widget、parent paint owner、
  贴边 child/viewport、风险类别、当前像素证据和拟议动作。

**Gate**

- 新的固定高度、稳定 X 槽位、screen clamp 和 Batch 圆弧测试在当前代码上按预期失败；
- 旧的文件 parity、X 通道校验和 slider 拖动测试仍绿色；
- 审计报告将“已证实缺陷”与“仅高风险候选”分开，不以 131 条 radius 数量冒充缺陷数。

## 6. Phase 1 — 固定文件视口与增大预设字体

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `tests/ui/test_batch_input_panel.py`
- Modify: `tests/ui/test_batch_method_buttons.py`

**工作**

- [ ] 为第一层文件 manager 建立单一常量/合同 `250px`；空态和 list body 都填满相同的
  剩余高度，不再在 `_after_change()` 中按 `row_count` 改 list height。
- [ ] 列表保留 46px row 和最多约 4 行的视觉密度；超过可视区只出现内部纵向滚动条。
- [ ] 0/1/4/8 行切换时“目标”标题的 global y 坐标不变。
- [ ] 文件列表滚到顶/底时继续把 wheel 交给外层 pane，现有 boundary forwarding 不回退。
- [ ] `_PresetCard.paintEvent()` 标题 9pt→10pt，摘要 7pt→8pt；normal card 61px→66px，
  compact card 38px→40px，保留居中、selected/dirty/disabled 和 slot 语义。
- [ ] 不用 QSS 假改字号；测试直接覆盖自绘 painter 使用的规范字体。

**Gate**

- 文件框在所有 row count 下固定 250px；长列表和外层 pane 两级滚动均可达；
- 288–320px Analysis pane 下四张预设没有裁字或重叠；
- 1080×760 的下方目标/预处理允许由外层滚动承接，但 footer 始终固定可见。

## 7. Phase 2 — X 轴 dependent field 使用稳定右侧槽位

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `tests/ui/test_batch_method_buttons.py`
- Modify: `tests/ui/test_batch_smoke.py`
- Modify: `tools/render_batch_compact_ui.py`

**布局合同**

```text
图内布局                  X 轴来源
[叠加              ▾]    [时间 / 通道        ▾]

                          [时间原点 / X 通道  ▾]
```

**工作**

- [ ] TimeDomain 渲染时将 `x_origin` 和 `x_channel` 的 field host 都放入同一个右列 grid
  cell；二者继续由 `_sync_x_source()` 互斥显示，不新增第二套参数模型。
- [ ] 左列第二行保持空白，不把 dependent field 挪到 `render_layout` 下方。
- [ ] `_GridFormAdapter.indexOf/labelForField`、`visible_field_names()` 和既有 active-field
  兼容表面继续可用；任意时刻 dependent host 恰好一个可见。
- [ ] 保留 channel candidates、partial-disabled、pending legacy value、missing/stale validation
  和一次用户动作一次 `paramsChanged` 的合同。
- [ ] 方法 round-trip `time -> fft -> time` 后恢复正确 dependent field 和原值，不出现两个
  host 重叠显示。

**Gate**

- time/channel 切换前后右侧槽位 x/y/width/height 差值 ≤1px；
- 左侧槽位没有 `X 通道`；长通道名在 288px pane 下不触发水平滚动；
- 现有 TimeDomain X channel 全套行为测试无回归。

## 8. Phase 3 — RenderStylePopover 屏幕内稳定定位

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/render_style_popover.py`
- Modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `tests/ui/test_batch_output_panel.py`

**工作**

- [ ] 给 `RenderStylePopover` 增加唯一入口 `show_at(anchor)`；OutputPanel 不再直接
  `mapToGlobal + move + show`。
- [ ] 每次打开先 `adjustSize()`，用 anchor center 选择 `QGuiApplication.screenAt()`；无结果
  时回退 primary screen。
- [ ] 水平默认保持 popup 右边缘与按钮右边缘对齐；左右均 clamp 在 available geometry
  内 8px。
- [ ] 垂直优先放在按钮下方 4px；若 bottom overflow，翻到按钮上方 4px；若上下均放不下，
  clamp 到屏幕可用区，不累加旧位置。
- [ ] host window move/resize 或 Output pane scroll 导致 anchor 脱离 popup 时关闭 popup，
  不让 top-level popup 留在旧屏幕坐标。
- [ ] 保留 slider/spin 双向同步、preset checks、一次 emit、外部点击关闭和按钮 checked 状态。

**Gate**

- bottom/right、top/left、双屏负坐标和重复打开 geometry 测试绿色；
- 弹层 frame 四边始终在 anchor 所在 screen 的 available geometry 内；
- 三条 slider 真实 mouse drag 与关闭重开持久化测试继续绿色。

## 9. Phase 4 — 修复 Batch 圆角 paint ownership

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `tests/ui/test_surface_layering.py`
- Modify: `tests/ui/test_batch_compact_contract.py`

**工作**

- [ ] `QFrame#BatchInlineFileManager` 成为该卡片唯一的白色 fill、border 和 radius owner。
- [ ] `BatchInlineFileManagerBody` 改为透明 backing，并关闭会重新填充白色矩形的
  auto-fill 路径；不要给嵌入式 body 使用 top-level popup 的 native-window flags。
- [ ] `BatchFileEmptyState`、`BatchFileList` 及 QListWidget viewport 不再绘制贴边矩形白底；
  parent 白底透出，内部 `border-top` 分隔线继续保留。
- [ ] 若透明 viewport 在某平台无法稳定显示 selection/scrollbar，只给内部 content 加
  localized 2–3px inset；不得恢复贴边 opaque rectangle。
- [ ] 先解决覆盖，再评估 1px `#d7e2f0` 的视觉对比度。只有完整圆弧仍过浅时，才在统一
  surface token 内小幅加深，不能用深色边框掩盖 child-overpaint。
- [ ] 四角均跑 border-arc profile；不仅断言 `(0,0)` alpha，还要证明中间圆弧像素连续，
  因为本缺陷的最外 corner 原本就是白/透明，单点 alpha 测试会漏报。

**Gate**

- 0 行空态、4 行、8 行+scrollbar 三种状态的四角曲线连续；
- top/bottom/left/right straight border 不断线，分隔线不穿出 outer radius；
- DPR 1 与 DPR 2 离屏像素 probe 均通过，并有实际 Qt crop 目视证据。

## 10. Phase 5 — 全局圆角绘制归属审计与分族修复

**Files**

- Modify: `docs/superpowers/reports/2026-08-02-rounded-surface-paint-ownership-audit.md`
- Modify only for confirmed cases: `mf4_analyzer/ui_kit/style.qss`
- Modify only for confirmed cases: owning widgets under `mf4_analyzer/ui/` and
  `mf4_analyzer/acquisition_ui/`
- Modify: relevant focused tests under `tests/ui/` / `tests/acquisition_ui/`

**工作**

- [ ] 从 131 个 radius QSS blocks 中先筛“带 child/viewport 的 surface owner”；叶子按钮、
  badge、纯 indicator 不因数量大而自动列为缺陷。
- [ ] 每个候选记录 parent/child geometry、paint 属性、QSS selector、是否贴边、截图/像素结果，
  分成 `confirmed / clean / unknown-live-only`。
- [ ] 嵌入式 shell：优先 transparent child 或 localized inset；保留一个 owner。
- [ ] scroll family：分别检查 QAbstractScrollArea、viewport、holder，不把三层当成一个控件。
- [ ] custom painter：核对 Python painter radius 与 QSS token 一致。
- [ ] popup/menu：继续走 `apply_popup_shell()` / combo popup shell；不重复添加 per-call-site
  修复。
- [ ] 至少覆盖 Batch 卡片、FileNavigator、ChartStack、Inspector、常用 drawer/dialog、
  QMenu/QCombo popup、图表 floating pill 七类代表；只修改像素证据确认有问题的路径。
- [ ] 全局 QSS 改动必须使用稳定 objectName/selector，不新增无边界的 `QWidget QWidget`
  透明规则。

**Gate**

- 审计报告中每个 `confirmed` 项都有对应测试、代码修复和 before/after crop；
- `unknown-live-only` 保持 UNKNOWN，不能被 offscreen 绿色结果宣称修好；
- 不删除全局 `QWidget` 白底，不造成普通页面透明洞、黑底或 macOS native backing 泄漏。

## 11. Phase 6 — 响应式、视觉矩阵与回归

**离屏矩阵**

- [ ] 1080×760：文件 0/1/4/8 行、内部/外部 scrollbar；
- [ ] 1080×760：预设 default/applied/dirty/disabled；
- [ ] 1080×760：Time X 来源 time/channel 往返；
- [ ] 1080×760：render-style popup 位于正常、右下、左上 anchor；
- [ ] 1440×900：上述各取代表总览；
- [ ] DPR 1 / DPR 2：Batch 文件框和全局 confirmed surface corner crops。

**测试命令**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_surface_layering.py \
  tests/ui/test_combo_popup_shell.py \
  -q
```

再运行审计报告中每个 confirmed family 的 focused module；完成后运行完整 batch cluster 与
Inspector focused suite。独立 Qt renderer parity 基线继续单列，不能混入本 UI 修复结论。

**macOS 前台 gate**

- [ ] 在 Retina DPR 下目视四个文件框圆角，不存在泛白、缺弧或矩形 backing；
- [ ] 反复添加/移除文件，文件框高度不变，两个 scrollbar 行为清晰；
- [ ] Time X 来源往返时字段只在右侧原位替换；
- [ ] 将窗口放到屏幕四边并反复打开刻度弹层，popup 不漂移、不越界；
- [ ] 对全局 audit 的 `unknown-live-only` 项逐一给出 PASS/FAIL/仍 UNKNOWN。

**检查**

```bash
git diff --check
git status --short --branch
/usr/bin/python3 scripts/lessons/check.py --status
```

## 12. 完成定义

只有同时满足以下条件才完成：

1. 文件管理外框固定 250px，0/1/4/8 行不改变目标区位置，溢出走内部 scrollbar；
2. 四张预设的 title/summary 分别为 10pt/8pt，所有状态无裁切；
3. `X 通道` 与 `时间原点` 始终在右侧同一槽位原位替换；
4. render-style popup 重复打开坐标稳定，并完全位于 anchor screen 可用区；
5. Batch 文件框四个圆弧的像素连续性在 DPR 1/2 和真实 macOS 截图中通过；
6. 全局圆角审计逐项区分 confirmed/clean/unknown，所有 confirmed 项有 routed fix 和证据；
7. 文件/probe/预设/X 轴/slider/export 行为无 feature 回退；
8. 未把 Qt 离屏证据当作 macOS 前台证据，未自动 commit/push。

## 13. 非目标

- 不改变三栏横向比例、Batch 窗口默认尺寸或 footer 高度。
- 不改变文件解析、source adapter、probe cost、信号交集或 BatchRunner。
- 不改变分析预设参数、slot 名称、applied/dirty 状态机。
- 不改变 X 轴参数格式、通道可用性规则或 legacy recipe schema。
- 不改变 render-style 数值范围、预设值、输出图片尺寸或导出算法。
- 不把所有 131 个 radius rules 批量改色、改半径、加 mask 或加透明窗口 flag。
