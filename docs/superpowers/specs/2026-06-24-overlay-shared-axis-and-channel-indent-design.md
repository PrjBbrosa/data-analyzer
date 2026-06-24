# 叠加模式·手动共轴组 + 通道缩进调整 设计

## 背景与目标

时域叠加（overlay）模式当前是 twinx 风格的「多轴叠加」：每个通道一根独立
Y 轴，各自按自身数据范围自动缩放，**只有网格线位置对齐、数值量程互不统一**
（`canvas.py:573-632`、`overlay_axes.py`）。两个本应可比的信号（例如两路扭矩）
叠在一起时，看似刻度对齐，实际尺度各管各的，无法直接比较幅值。

目标：让用户**手动**把若干通道指定为一个「共轴组」，组内通道画在**同一根
Y 轴、同一量程**上，从而可直接比幅值；未入组的通道保持现有独立轴行为。

同时捎带修一处 UI 浪费：通道树子项左侧有一大块纯空白缩进，将其收窄并改造成
「共轴组指示槽」。

## 范围

**做：**
- 叠加模式下，手动共轴组（支持多个组，组①/组②… 各一根轴）。
- 通道树多选 + 右键「合并为共轴 / 拆分共轴组」。
- 共轴组在通道树勾选框左侧的小徽标指示（不同组不同徽标）。
- 通道树缩进收窄并复用为指示槽。

**不做（YAGNI）：**
- 图上拖 Y 轴吸附合并。
- 共轴分组持久化存盘（仅当前会话内有效）。
- subplot / single 模式下的共轴（只在 overlay 生效）。
- 按单位自动分组（用户手动负责，允许异单位合并）。

## 关键现状（实现依据）

- 通道树：`mf4_analyzer/ui/widgets/__init__.py`，类 `MultiFileChannelWidget`，
  内部树 `_CheckTolerantTree`（继承 `QTreeWidget`），objectName `"channelTree"`。
- 树**当前为默认 `SingleSelection`**（未设 selectionMode）→ 必须改
  `ExtendedSelection` 才能 Ctrl/Shift 多选。这是本特性的**前置步骤**。
- 树已有右键菜单：`_on_context_menu`（`widgets/__init__.py:423-446`），目前仅
  「设为左轴」一项；通道项以 `setData(0, Qt.UserRole, ('channel', fid, ch))`
  标识。
- 勾选框状态（`checkState`，决定是否绘制）与行选中状态（selection，本特性用于
  分组操作）是**两套独立机制**。
- 绘图层用复合键 `json.dumps([fid, name])`（`pg_canvas/_shared.py`
  `_view_state_channel_key`）唯一标识曲线/轴。
- plot 数据行结构：`(name, visible, t, sig, color, unit, fid[, meta])`，**带
  `unit` 字段**；overlay 绑定在 `overlay_axes.py:292-356` `_bind_channel`。
- companion / 滤波叠加曲线当前靠「meta 是否存在」分流（需修，见下）。

## 数据模型

在 `MultiFileChannelWidget` 内新增视图状态（不触碰测量数据）：

```python
self._axis_groups: dict[tuple[str, str], int] = {}   # (fid, ch) -> group_id
```

- 键沿用树现有的 `(fid, ch)` 标识。
- `group_id` 从 1 自增；解散的组号不复用（避免徽标颜色跳变）。
- 不变量：任一 `group_id` 的成员数 < 2 时**自动解散**（单成员＝普通独立轴，
  从 `_axis_groups` 中移除）。

新增信号 `axis_groups_changed = pyqtSignal()`，分组变更后发出，触发上层重绘。

## 交互设计

1. **多选（前置）**：构造时
   `self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)`。
   勾选框语义不变（是否绘制）；行选中仅服务分组操作。
2. **右键菜单**（扩展 `_on_context_menu`）：
   - 收集 `self.tree.selectedItems()` 中的通道项（`data[0] == 'channel'`）。
   - 选中 ≥ 2 个通道项 → 显示「合并为共轴」。
     - 若选中项里已含某个组的成员 → 文案为「并入共轴组 ①」（并入该组；若选中
       涉及多个已有组，则合并为编号最小的那个组）。
     - 否则新建组（取当前最大 group_id + 1）。
   - 选中项里含已分组通道 → 额外显示「拆分共轴组」（把选中通道移出组；触发
       <2 自动解散）。
   - 单选或无通道项时，菜单维持原「设为左轴」。
3. 变更后 `emit axis_groups_changed` → 上层按现状重新 `plot_channels`。

## 视觉标识

### 通道树（勾选框左侧的指示槽）

- `_CheckTolerantTree` **重写 `drawBranches(painter, rect, index)`**：
  - 文件（顶层）行 → `super().drawBranches(...)`，保留默认展开箭头。
  - 通道行：若该通道在某组中，于 `rect` **右端**（紧贴勾选框前）画一个组徽标；
    否则该槽留空。
  - 画在 `rect` 右端，与树深度无关——天然规避「文件→采样率分组→通道」可能的
    多层缩进导致的徽标错位问题。
- 组徽标：约 12×12 px 圆角小方块，填充取自**固定组色板**（独立于通道色板，
  循环使用），块内叠加组号 ①②③…（白色）。**不同组 = 不同填充色 + 不同组号**，
  双重区分。
- 组色板与「绘图层共享轴」共用同一映射（见下），保证树徽标色与图上该组的归属
  视觉一致。

### 绘图层

- 组内通道塌成**一根共享轴**——这是最强的「已共轴」信号。
- 共享轴单位标签：组内同单位 → 显示该单位；异单位 → 标「(混合单位)」。
- 共享轴轴线颜色用**该组的组色**（与树徽标一致），不再用单通道颜色（因为一根
  轴对应多条不同色曲线）；曲线各自保留原色。

## 绘图层改动（核心）

**方案：共享 ViewBox（推荐，采用）。**
同一 `axis_group` 的通道绑进**同一个 aux ViewBox + 同一根 Y AxisItem**，量程取
组内成员数据并集自动缩放；每条曲线保留自身颜色。

**否决备选：给各通道各自的 ViewBox 做 `setYLink`。** 仓库为规避 pyqtgraph
linked-view 的像素级偏移，X 轴已刻意不用 `setXLink`（`canvas.py:549-556`），
Y-link 会重蹈同一问题。

落地要点：
1. **meta 透传**：在 plot 数据行 `meta` 中加 `axis_group`（int 或 None）。
   `_build_time_plot_data`（`window.py`）从 `_axis_groups` 查表填充。
2. **修分流隐患（必做）**：当前 companion/滤波叠加靠「meta 存在与否」分流；
   primary 一旦携带 `axis_group` 的 meta 会被误判为 companion。把分流判据改为
   `meta.get("companion_of")` 精确匹配，而非 meta 真值。
3. **overlay 绑定**（`canvas.py:573-632` + `overlay_axes.py`
   `_add_overlay_axis_handle` / `_bind_channel`）：
   - 遍历 primary 通道时，按 `axis_group` 归并：同组首个通道创建 aux ViewBox +
     共享 axis；同组后续通道复用该 ViewBox/axis，仅 `addItem` 曲线，不新建轴。
   - 未分组通道维持「一通道一 aux ViewBox/轴」现状。
   - 共享轴量程 = 组内全部成员数据的并集自动范围。

## 量程 / 拖拽 / 缩放 / 网格

- 共享轴沿用现有单轴的拖拽/缩放交互，作用于整组（组内一起平移/缩放）。
- overlay 网格对齐（`_repin_overlay_channel_ticks`、`_snap_overlay_channel_to_grid`）
  把「一个共享轴」当作一根轴参与对齐，而非按组内每个成员重复对齐。

## 生命周期与边界

- 分组随通道存活；通道被取消勾选 / 移除时，从 `_axis_groups` 摘除其键；触发组
  <2 自动解散。
- companion / 滤波叠加曲线**跟随其源通道所在的轴**（沿用现状）；分组只作用于
  primary。源通道入组 → 其 companion 一并落到共享轴。
- 切换其他通道导致的重绘，分组保持不变。
- 退出 overlay（切到 subplot/single）时，分组信息保留在 `_axis_groups`，但不影响
  绘制；回到 overlay 时重新生效。

## 通道缩进调整

- 在树构造里 `self.tree.setIndentation(N)`，N 取「刚好容纳组徽标」的小值
  （约 16–18px，替代默认约 20px 的多级纯空白）；文件节点展开箭头保留。
- 与上文 `drawBranches` 协同：收窄后的缩进槽不再是纯空白，而是组指示槽。

## 风险与真机验证点（遵循 CLAUDE.md：UI/渲染必须真机验真）

1. **缩进与徽标真机渲染**：截图确认子通道缩进收窄、徽标位置紧贴勾选框且不与
   勾选框/色点/文字重叠；macOS 原生渲染下尤其要验。
2. **树层级**：核对实际显示是「文件→通道」两层还是含「采样率分组」三层，确保
   `drawBranches` 在通道行（而非分组中间行）画徽标；靠 `rect` 右端定位规避层级
   差异，但仍需真机确认。
3. **共享轴塌缩**：验证组内曲线落同一量程、可比幅值；异单位组标签为「(混合单位)」。
4. **分流回归**：确认给 primary 加 meta 后，companion/滤波叠加未被误判、显示正常。
5. **拖拽/缩放**：共享轴拖动整组同步，未分组轴互不影响。

## 测试要点（pytest-qt）

- `_axis_groups` 的增/删/自动解散（<2 成员）逻辑单测。
- 右键菜单：≥2 选中显示「合并为共轴」；含已分组项显示「拆分」；单选回退原菜单。
- meta 透传：`_build_time_plot_data` 为分组通道填 `axis_group`。
- 分流判据改 `companion_of` 后，companion 仍正确分离（防回归）。
- 共享 ViewBox：同组通道 `addItem` 到同一 ViewBox、只有一根对应 Y 轴。

## 涉及文件

- `mf4_analyzer/ui/widgets/__init__.py`：多选、右键菜单、`_axis_groups`、信号、
  `drawBranches`、`setIndentation`。
- `mf4_analyzer/ui/main_window/window.py`：`_build_time_plot_data` 透传
  `axis_group`。
- `mf4_analyzer/ui/pg_canvas/canvas.py`：overlay 分支按组归并 ViewBox/轴；分流
  判据改 `companion_of`。
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`：共享 ViewBox/轴的创建与复用、共享
  轴标签/颜色、网格对齐按一根轴处理。
- `tests/`：上述测试要点。
```
