# Y 轴刻度标签丢失（"纵坐标只显示一半"）——整体排查与修复计划

日期：2026-08-04
状态：**T1/T2/T3 全部已实施并合入工作树；待真机视觉验收**（见 §8）
关联现象：新增 View、合并 View、切换通道后，时域分屏某一行的纵轴刻度值大面积消失；
FFT / 阶次 / 时频图也有顶端与底端刻度值缺失。

---

## 0. 结论速览

用户报的"纵坐标只显示一半"不是一个 bug，是**三个独立缺陷**叠加，共同表现为
"纵轴刻度值缺了一片"。三个都已在本机 offscreen 环境复现，非推测。

| # | 缺陷 | 影响面 | 证据 |
|---|---|---|---|
| **D1** | 左轴钉宽是**自己的不动点**，一旦定死就再也不会变宽，宽标签被整条丢弃 | 时域分屏、FFT/阶次线图、时频图 | 已复现，见 §2 |
| **D2** | 开了网格的左轴，**首尾两个刻度值**必定被丢 | 全部启用网格的图表（几乎全部） | 已用**裸 pyqtgraph** 复现，见 §3 |
| **D3** | `batch_render_qt` 早就修好了 D1，交互式 GUI 从未同步 | 修复方案已在仓库内现成 | 见 §4 |

关键机制（三个缺陷共用）：pyqtgraph 的 `AxisItem.generateDrawSpecs` 在
`AxisItem.py:1691` 有一道过滤——

```python
br = self.boundingRect()
if br & rect != rect:
    continue          # 文本矩形没完整落进包围盒 → 这条标签直接不画
```

放不下的刻度标签**不是被裁一半，是整条不画**。所以症状是"少了一片刻度"，
而不是"字被切了一半"。宽标签（多一位数、多一个负号）先死，窄标签活下来 →
看起来像纵轴只剩半截量程。

---

## 1. 复现脚本

三份 probe 已写在 scratchpad，实施时应固化成回归用例（见 §6）：

- `probe_all.py` —— 遍历四个画布类型，比对 `axis.width()`（钉宽）与
  `_left_axis_width_for_ticks(axis)`（真实需求），并记录哪些标签被丢
- `probe_line_growth.py` —— FFT 线图先窄后宽的钉宽冻结场景
- `repro_fix.py` —— 验证修法（释放 → 激活**全部**布局 → 测量 → 钉 → 激活）

> **本机限制**：这台 Windows 机器的 Qt 没有字体
> （`QFontDatabase: Cannot find font directory`），offscreen 渲出来的图**没有文字**。
> 上述 probe 走的是 `generateDrawSpecs` 返回的 textSpecs 与 `QFontMetrics` 数值，
> **不依赖像素**，所以结论有效；但**任何视觉验收必须回真机**，
> 禁止以 offscreen 截图声称"看过图、修好了"。

---

## 2. D1：钉宽是自己的不动点

### 2.1 现场

`mf4_analyzer/ui/pg_canvas/canvas.py:3918` `_unify_subplot_left_axis_widths()`：

```python
for ax_item in left_axes:
    ax_item.setWidth(None)          # ① 释放钉宽
max_w = max(float(ax_item.width()) for ax_item in left_axes)   # ② 立刻测量
for ax_item in left_axes:
    ax_item.setWidth(max_w)         # ③ 钉回去
layout = self._glw.ci.layout        # ④ 只激活外层布局
layout.invalidate(); layout.activate()
```

### 2.2 两个叠加的错误

**(a) ② 读到的是旧几何。**
`setWidth(None)` 只调 `setMinimumWidth/setMaximumWidth` 改**尺寸提示**；
`QGraphicsWidget.width()` 返回的是**已实现的几何**，要等所属布局 `activate()` 之后才更新。
①②之间没有任何 activate，所以 `width()` 仍然是上一次钉的值 →
`max_w = max(旧钉宽) = 旧钉宽`。**这个值是它自己的不动点，永远长不大。**

**(b) ④ 激活错了布局。**
真正决定 AxisItem 格子宽度的是**每个 PlotItem 自己的内部 layout**，不是外层
`self._glw.ci.layout`。只激活外层，轴的几何不会重算。

实测对照（同一个已 paint 的 canvas，rack force 行 ±5000 N）：

| 释放后激活的布局 | 量到的自然宽度 | 该行实际画出的标签 |
|---|---|---|
| 只 `ci.layout`（现状） | 53.4 / 53.4 / **53.4** | `['0']` |
| `ci.layout` + 各 PlotItem 的 layout | 53.4 / 53.4 / **88.4** | `['-4000','-2000','0','2000','4000']` |

**(c) 第一次的值从哪来 —— 首帧之前测量。**
`AxisItem.textWidth` 只在 `paint()` → `generateDrawSpecs()` → `_updateMaxTextSize()`
里更新（`AxisItem.py:1698`）。而 `_settle_subplot_layout()` 在绑完数据后立刻 unify，
此时新建的轴一次都没画过，`textWidth` 还是构造默认值 `30`（`AxisItem.py:99`）——
三行量出来全是 53.4，而 rack force 行真实需要 88.4。之后即使 paint 把 `textWidth`
修正成 65，`_updateWidth()` 也因 `fixedWidth` 非 None 直接返回钉宽（`AxisItem.py:642`），
几何纹丝不动。

### 2.3 为什么"新增 view / 合并"必现且不自愈

四个入口走同一个坏 unify：

- `canvas.py:818`（分屏构建）
- `canvas.py:3858`（`_settle_subplot_layout`）
- `canvas.py:4073`（`_on_resize_settled`）
- `tick_density.py:61`（`set_tick_density`）

新增 view / 合并都会重建 PlotItem+AxisItem → 触发首帧前测量。
因为 resize 路径调的是**同一个**函数，**拉窗口也修不好**（实测确认）。
53.4 px 够放 3~4 个字符，所以扭矩（±2.5 Nm）没事，
rack force（±5000 N，5 字符带负号）翻车 —— 这就是"经常触发但不是每次"。

### 2.4 同一缺陷的其它现场

| 位置 | 状态 |
|---|---|
| `ui/pg_canvas/canvas.py:3918` `_unify_subplot_left_axis_widths` | **已复现**（时域分屏） |
| `ui/pg_canvas/line_canvas.py:1549` `_unify_stacked_left_axes` + `_activate_graphics_layout:1711`（只激活 `ci.layout`） | **已复现**：先画 0~0.8 Nm 频谱钉成 62.4，再画 0~480000 N 频谱需要 101.4，仍是 62.4，只剩 `['0']` |
| `ui/pg_canvas/heatmap_canvas.py:2398` `_unify_stacked_left_axes` | 结构同上；其 `_activate_graphics_layout:2552` **已经**遍历各子 layout（写法正确），但释放与测量之间仍无 activate → 待实施时确认 |
| `ui/analysis_section_page.py:455` `sync_heatmap_layouts` | 跨 pane 取 `max(left_axis_width)`，喂进来的 metrics 来自上面这些 `width()` 读数 → 同源污染 |
| `ui/pg_canvas/overlay_axes.py:662` | **正常**：`setWidth(None)` 后不钉，走 pyqtgraph 自动宽度。已验证叠加模式标签完整 |

---

## 3. D2：开网格的左轴必丢首尾刻度

### 3.1 证据（裸 pyqtgraph，零项目代码）

y 量程精确 `[0, 1]`，刻度落在 0 与 1.0 上：

```
grid=False  drawn=['0', '0.2', '0.4', '0.6', '0.8', '1.0']
grid=True   drawn=['0.2', '0.4', '0.6', '0.8']       ← 首尾被丢
```

> 这段是**裸 pyqtgraph**（`GraphicsLayoutWidget` + `addPlot` + `showGrid`，
> 不碰项目任何代码），2026-08-04 在本机复核过两次，逐字复现。
>
> **但在项目画布内部观察不到这么干净的对照**：项目会给轴装中文图表字体，
> 而本机 Qt 无字体 → `QFontMetrics` 宽度失真 → 标签在 D2 生效之前就已经被
> **横向**丢掉一批。所以给 D2 写用例时必须 `setTicks` 钉死刻度字符串、
> `setWidth()` 钉死轴宽，把横向因素排除掉，否则量到的是 D1 的噪声。

### 3.2 机制

左轴构造时固定拿到 `hideOverlappingLabels = False`（`AxisItem.py:66-68`，
注释明说"allow labels on vertical axis to extend above and below"），
对应 `boundingRect()` 里 `m = 15` 的上下留白，首尾标签探出轴端也放行。

但 `boundingRect()` 开头有一条**提前返回**（`AxisItem.py:956-961`）：

```python
linkedView = self.linkedView()
if linkedView is not None and self.grid is not False:
    return (self.mapRectFromParent(self.geometry()) |
            linkedView.mapRectToItem(self, linkedView.boundingRect()))
```

**网格一开，这条分支直接返回，`m = 15` 的上下留白根本没机会加上。**
于是任何探出轴端的首尾标签在 `AxisItem.py:1691` 被判出局。

### 3.3 影响与取舍

本项目图表默认开网格，所以**每一张图**的纵轴顶端/底端刻度值都可能缺。
截图里右上 rack force 子图曲线冲到 ~5500 却没有 4000 以上的刻度值，
与此吻合。

修法（实施时二选一，倾向 A）：

- **A. 给左轴的包围盒补回上下留白** —— 子类化 `AxisItem`（项目已有轴定制点），
  重写 `boundingRect()`：走网格分支时，在返回的矩形上补 `adjusted(0, -15, 0, 15)`。
  改动面小、与非网格分支行为一致。
- **B. 收紧刻度取值**，让首尾刻度不落在视图边缘。会改变刻度分布，
  与 `tick_density` 的既定语义冲突，**不推荐**。

> 注意 D2 与 D1 无关：probe 里 FFT 时间预览行钉宽 88.4 > 需求 62.4（明显偏宽），
> 首尾照样被丢。两个缺陷必须分别修、分别验。

---

## 4. D3：修复方案仓库里已有现成的

`mf4_analyzer/batch_render_qt/_builder.py:589` `_left_axis_width_for_ticks()`
**已经解决了 D1**，其 docstring 描述的正是同一个失败：

> "…on an axis that has never been painted it is pyqtgraph's initial
> `textWidth = 30`, which is where a pinned 57.4 px left axis came from
> against the 95.4 px the same ticks get when nothing pins them.
> Measuring the strings makes the answer independent of paint history."

做法是**直接用 `QFontMetricsF` 量当前刻度字符串**，完全绕开 `textWidth` 的 paint 依赖，
并逐项复刻 `_updateWidth` 会加的 `tickTextOffset` / `tickLength` / 旋转 label 余量。
配套的 `_axis_tick_texts()`（`_builder.py:548`）负责把 `setTicks` 显式标签与
自动刻度两种情况都取出来。

`_slice_alignment_callback`（`_builder.py:685`）还给出了正确的钉宽姿势：

```python
target = max(max(_left_axis_width_for_ticks(axis), float(axis.width()))
             for axis in left_axes)
```

即**字体度量下界与已实现几何取大**，使钉宽单调不减，既不会因首帧未绘而偏窄，
也不会把已经画好的轴缩窄。

**所以本次不是发明新方案，是把 batch 导出路径的既有正确实现提升为共享件、
让交互式 GUI 用上。** 这也解释了为什么批处理导出的图没人报这个问题。

---

## 5. 修复方案

### Step 1 —— 提升共享件（无行为变更）

把 `_axis_tick_texts` / `_left_axis_width_for_ticks` / `_TICK_TEXT_PROBE` /
`_axis_tick_font` 从 `batch_render_qt/_builder.py` 移到一个中立模块
（建议 `mf4_analyzer/ui/pg_canvas/axis_metrics.py`；若担心 GUI→batch 依赖方向，
放 `mf4_analyzer/ui_kit/` 亦可，实施时按现有依赖图定）。
`_builder.py` 改为从新位置导入，**保留原名再导出**以免动到批处理测试。

约束：新模块**不得** import `PyQt5.QtWidgets` 之外的 GUI 主窗体件，
且**不得**被 `mf4_analyzer/signal/` 引用（`tests/test_signal_no_gui_import.py` 的边界）。

### Step 2 —— 统一"钉左轴宽"的姿势

新增一个共享 helper（放在同一个新模块），语义固定为：

```
target = max( max(_left_axis_width_for_ticks(ax), ax.width()) for ax in axes )
钉 target → 激活 ci.layout 与每个相关 PlotItem 的 layout
```

要点：
1. **不再依赖"释放后重测"** —— 字体度量直接给出真值，`setWidth(None)` 的
   释放-重测两步可以整个去掉，D1(a)/(b) 一并消失。
2. **单调不减** —— 与 `_builder.py` 现有语义一致，接受"标签变短后不自动收窄"这个取舍。
   若后续需要收窄，必须在释放与测量之间插入完整的 layout 激活，并补回归用例。
3. **激活全部相关 layout**，不能只 `ci.layout`。可参照
   `heatmap_canvas._activate_graphics_layout:2552` 的遍历写法。

替换以下调用点：
- `canvas.py:3918` `_unify_subplot_left_axis_widths`
- `line_canvas.py:1549` `_unify_stacked_left_axes`
- `line_canvas.py:1711` `_activate_graphics_layout`（补齐子 layout 遍历）
- `heatmap_canvas.py:2398` `_unify_stacked_left_axes`
- `analysis_section_page.py:455` 的 `left_axis_width` 来源
  （`line_layout_metrics:1573` / `heatmap_layout_metrics:2427` 改为返回
  字体度量下界与 `width()` 的较大值）

保持不变：`canvas.py:3918` 的短路条件（`_subplot_label_specs`、`len < 2`）、
`_settle_subplot_layout` 里"bottom 先、left 后"的既定顺序及其 docstring 理由。

### Step 3 —— D2 修复

按 §3.3 方案 A 处理，作用于全部左轴。

**实测的构造点只有 3 个**（`grep addPlot(/PlotItem(/setAxisItems/axisItems=` 全包核对）：

| 构造点 | 覆盖范围 |
|---|---|
| `ui/pg_canvas/heatmap_canvas.py:684` `_make_analysis_plot` | **线图与时频图共用**——FFT/阶次的 amp+time 两个 plot（`line_canvas.py:172/174`）与时频的 map+slice 两个 plot（`:831/1008`），一处即覆盖四个 |
| `ui/pg_canvas/canvas.py:1930` `_add_plot_item` | 时域 |
| `batch_render_qt/_builder.py:1265` `_new_plot` | 批处理导出——**已实测确认同样受 D2 影响**，不是推测 |

§3.3 括注的"项目已有轴定制点"只对一半：现成的 `_BoundaryGridAxisItem`
（`heatmap_canvas.py:621`）只服务分析类画布，改它的基类即可；
时域与批处理导出用的是裸 `addPlot`，必须新增两处 wiring。

---

## 6. 验证要求

### 6.1 回归用例（必须新增）

放 `tests/ui/`，全部走 `generateDrawSpecs` 返回的 textSpecs 或 `QFontMetrics` 数值，
**不得断言像素墨迹**（本机无字体）：

1. **D1-时域分屏**：先 2 个窄标签通道 → settle；再加 1 个 ±5000 的宽标签通道 → settle；
   断言该行 `_left_axis_width_for_ticks(ax) <= ax.width()`，且全部刻度字符串都出现在
   drawn 列表里。**改前必红。**
2. **D1-线图**：先 0~0.8 频谱钉宽，再 0~480000 频谱；同样断言。**改前必红。**
3. **D1-时频图**：同构场景。
4. **D2**：开网格的左轴，y 量程取到刻度恰好落在边缘，断言首尾刻度字符串都被绘制。
   **改前必红**（裸 pyqtgraph 已证）。
5. **不动点回归**：连续调用两次 unify，宽度不得比第一次窄（单调性）。

### 6.2 既有套件

改动涉及分屏几何，**必须先取基线再对比**。本机 `main` 上已知就红的用例见
`~/.claude/.../memory/known-red-tests-this-machine.md`，其中与本次高度相关的有：
`tests/ui/test_split_*`、`tests/test_batch_render_qt.py` 的三条几何用例、
`tests/test_batch_qt_render_parity.py` 全部 —— **都是本机无字体导致，不是本次改动引入。**

pytest **必须带** `--basetemp=<scratchpad 下目录>`，否则默认临时目录的 Windows
权限问题会伪造出十几条 ERROR。

### 6.3 真机视觉验收

offscreen 只能当排版草稿。合并前需在有字体的真实环境里，用截图确认：
时域分屏加 View 后每行纵轴刻度完整、顶端底端刻度值都在、各行左边缘仍对齐。

---

## 7. 实施切分

| Task | 范围 | 依赖 |
|---|---|---|
| **T1** | Step 1 提升共享件 + Step 2 时域分屏（`canvas.py`）+ 用例 1、5 | 无 |
| **T2** | Step 2 线图与时频图（`line_canvas.py`/`heatmap_canvas.py`/`analysis_section_page.py`）+ 用例 2、3 | T1 的共享模块 |
| **T3** | Step 3 D2 + 用例 4 | 独立，可并行 |

T1 与 T3 可并行；T2 等 T1 的共享模块落地。

---

## 8. 实施结果（2026-08-04）

三个 task 全部完成，T3 的独立 worktree 已合入主工作树。**未提交**，改动留在工作树。

### 落地清单

| 文件 | 来源 | 内容 |
|---|---|---|
| `mf4_analyzer/ui_kit/axis_metrics.py`（新，201 行） | T1 | 共享件：`left_axis_width_for_ticks` / `axis_tick_texts` / `activate_item_layouts` / `pin_left_axes_to_common_width` |
| `mf4_analyzer/ui/pg_canvas/axis_metrics.py`（新，28 行） | T1 | 纯 re-export shim |
| `mf4_analyzer/qt_plot_helpers.py` | T3 | `GridLabelSlackAxisItem` + `_vertical_label_margin` |
| `mf4_analyzer/ui/pg_canvas/_shared.py` | T3 | re-export |
| `mf4_analyzer/ui/pg_canvas/canvas.py` | T1 + T3 | unify 改用共享件；`_add_plot_item` 接 D2 轴 |
| `mf4_analyzer/ui/pg_canvas/line_canvas.py` | T2 | unify / metrics / `_activate_graphics_layout` 补齐子 layout |
| `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` | T2 + T3 | unify / metrics；`_BoundaryGridAxisItem` 改继承 D2 轴 |
| `mf4_analyzer/batch_render_qt/_builder.py` | T1 + T3 | 改为导入共享件（保留私名别名）；`_new_plot` 接 D2 轴 |
| `tests/ui/test_subplot_left_axis_metrics.py`（新） | T1 | 2 例 |
| `tests/ui/test_stacked_left_axis_metrics.py`（新） | T2 | 4 例 |
| `tests/ui/test_axis_grid_label_slack.py`（新） | T3 | 5 例（含 1 例 bottom 轴负向对照） |

`ui/analysis_section_page.py` **未改**：T2 实测确认 metrics 诚实之后，
它的跨 pane `max()` 本来就是对的。

### 验证

合并后 13 个文件跑：**1 failed, 932 passed, 1 skipped, 1 deselected**。
唯一的红是既有的
`tests/ui/test_pg_timedomain_canvas.py::test_x_tick_target_count_backs_off_before_label_overlap`
（干净树上就红，位置与断言均未变）。

probe 全绿（改前 → 改后）：

| 场景 | 改前 | 改后 |
|---|---|---|
| 时域分屏 +1 宽标签行 | `drawn=['0']` | 全部 5 个刻度，且各行仍钉同宽 |
| 线图先窄后宽 | 62.4 冻结，`drawn=['0']` | 101.4，全部刻度 |
| 时频图单窗 | 首尾缺失 | 全部刻度 |
| 叠加模式 | 本来就正常 | 未回归 |

### 与原计划的偏差（三条，均已核实）

1. **共享件落在 `ui_kit/` 而非 `ui/pg_canvas/`**。`mf4_analyzer/ui/__init__.py`
   会 `from .main_window import MainWindow`，从 `_builder.py` 导入
   `ui.pg_canvas.*` 会把主窗体拖进批处理路径。原路径留 shim。
2. **§6.1 第 5 条"单调性"用例做不红**。坏掉的钉宽是*冻结*的，而冻结平凡满足单调；
   `setWidth` 只动 min/max hint，不存在变窄路径。已改成"结算宽度必须覆盖字体度量需求"
   才有牙齿。T2 也踩到同类问题（首版用例对旧代码就是绿的），已改成先窄后宽。
3. **§2.4 对时频图的猜测错了**。`prepare_split_layout_alignment` 结尾**已经**调用
   会遍历子 layout 的 `_activate_graphics_layout`，释放确实生效；真正的成因是
   机制 (c) 首帧前测量 —— 两个入口都走 `QTimer.singleShot(0, ...)`，
   可能早于新刻度的首次绘制。症状比线图更重：**整条 Y 轴刻度全没**（`drawn=[]`），
   不是只丢宽的。

另：§3.1 的裸 pyqtgraph 片段本机复核**逐字复现**，未过期；
它在项目画布内观察不干净是因为本机无字体（已在 §3.1 注明）。

### 遗留

- **真机视觉验收未做**，本机 Qt 无字体，offscreen 渲不出文字。需在有字体的环境截图确认：
  时域分屏加 View 后每行纵轴刻度完整、顶端底端刻度值都在、各行左边缘仍对齐。
- 钉宽为**单调不减**（标签变短不自动收窄）。线图/时频图靠
  `prepare_split_layout_alignment` 的 `setWidth(None)` 释放做跨 pass 重置；
  时域分屏没有对应的释放点，长会话里可能残留偏宽的左轴。目前只是留白，不是缺陷。
