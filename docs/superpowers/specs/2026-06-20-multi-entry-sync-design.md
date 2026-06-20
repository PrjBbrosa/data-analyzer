# 图表多入口输入同步修复 — Design Spec

- 日期：2026-06-20
- 状态：待实现（brainstorming 已定稿）
- 来源：对「工具内多入口输入功能交叉/同步」的 review（pan/zoom、坐标轴范围、其他控件三路调查）

## 1. Decision

整体走 **针对性补丁 + 抽少量公共小工具**，**不动**「ViewBox 显示态 / inspector 参数 / 持久化(ViewState·PaneState)」三套存储的现有分层。否决「统一显示-参数一致性层」的大重构——它会推翻下面用户明确要保留的「临时查看」语义。

本设计修六个多入口不一致点。用户拍板的三个产品选择（边界，执行时不得越界）：

1. **P0 分析图手动缩放：不改行为，只加提示。** 拖动/滚轮缩放仍是「临时查看」，重算/查看全部回到 inspector 设定范围；不做「缩放粘住 / 回写 inspector」。
2. **网格：对话框保持单勾**（X+Y 联动「全部显示/全部不显示」），不拆成 X/Y 两勾。
3. **色图：移除对话框色图下拉**（不做色图持久化）。

## 2. Scope & Non-Goals

### In scope（6 点，分两批）

- Phase 1（高影响）：① P0 临时缩放提示、② 分屏右键鼠标模式广播、③ 网格双入口覆盖
- Phase 2（杂项显示一致性）：④ 移除对话框色图下拉、⑤ idle 态菜单口径、⑥ 对话框「自动范围」读真实状态

### Non-Goals（明确不做，防跑偏）

- 不让分析图手动缩放「粘住」，不把缩放回写到 inspector 的 自动/最小/最大。
- 不引入统一的显示-参数绑定/一致性层。
- 不把网格对话框拆成 X/Y 两个勾选；不削弱右键菜单的 X/Y 独立能力。
- 不做色图持久化（不把 cmap 存进 params/PaneState）。
- 不重构 pan/zoom 状态机；② 仅补「右键路径也广播 peer」。
- 不触碰数值算法（无 signal-processing-expert 参与）。

## 3. 修复契约（逐点：现状 → 改动 → 验收）

### ① P0 — 分析图临时缩放提示（不改行为）

- **现状**：分析画布拖动/滚轮只改 pyqtgraph ViewBox；重算时 `plot_spectra` 用参数 `xlim` 重设范围（`mf4_analyzer/ui/pg_canvas/line_canvas.py:716`），手动缩放被丢弃。已核实：右键「查看全部」`reset_view_to_data_extents` 用的是 `_last_xlim`（`line_canvas.py:857-861`），而 `_last_xlim` 在 `plot_spectra` 里被设为参数 xlim（`line_canvas.py:712`）——**一键回到参数范围已经能用，无需改动 view-all**。
- **改动**：
  - 分析画布（`line_canvas.py` 的 FFT 线图；`heatmap_canvas.py` 的阶次/fft_time）监听用户手动改范围信号 `sigRangeChangedManually`（与 toolbar 历史捕获同源，参见 `chart_stack/toolbar.py:407`），置「临时缩放」态标志。
  - 提示载体复用现有 hint 基础设施：`_ChartCard.flash_hint`（`mf4_analyzer/ui/chart_stack/cards.py:610`）+ 底部 `_hint_context`，显示一句「临时缩放 · 重算/查看全部将回到设定范围」。**不新建浮层**，避免又一处需嵌入透明背景的自定义 widget。
  - 清除时机：`plot_spectra` 被调用（重算）或「查看全部」触发后清「临时缩放」态、撤下提示。
  - **inspector 的 自动/最小/最大 一律不动**（保「参数面板」语义）。
- **验收**：拖动分析图 → 出现「临时缩放」提示；重算或点「查看全部」→ 提示消失且范围回到参数；inspector 数字全程不变。

### ② 分屏右键鼠标模式广播

- **现状**：右键菜单切 pan/zoom 走 `controller.set_pan_mode()/set_zoom_mode()`（`mf4_analyzer/ui/chart_stack/toolbar.py:580/590`），**不广播 peer**；toolbar 按钮走 `_click_pan/_click_zoom` 显式广播 peer（`toolbar.py:693-701`）并触发共享图标刷新（`chart_stack/stack.py:373` `_sync_shared_nav_highlight`，挂在 action-triggered 上 `stack.py:188-193`）。分屏下两入口行为不一致。
- **改动**：
  - 给鼠标模式 controller 增加一条「等价于按钮点击」的广播入口（如 `set_mouse_mode_broadcast(mode)`）：本面板 set + 遍历 `_peers()`（`toolbar.py:600`）广播 + 触发共享图标刷新。
  - 右键菜单的 `_select_pan/_select_zoom`（`mf4_analyzer/ui/pg_canvas/context_menu.py:371-392`）改调该广播入口。
  - **防递归（硬约束）**：不得让 `set_pan_mode/set_zoom_mode` 本身广播——peer 广播循环里会调 `set_mouse_mode → set_pan_mode`（`toolbar.py:610-618`），自广播会成环。广播只能在新入口里做一层、对 peer 调用非广播的 setter。
  - 更新 `register_mouse_mode_controller` 的契约注释（`mf4_analyzer/ui/pg_canvas/canvas.py:620-631`）说明新方法。
- **验收**：分屏下右键切模式 → 两面板 ViewBox 都切换 + 共享 toolbar 图标刷新；单画布右键（`_peers()` 为空）行为不变、不报错。

### ③ 网格双入口覆盖

- **现状（已核实纠正）**：对话框入口 `_axis_interaction.py:113` **每次新建** `ChartOptionsDialog` 实例，`self._initial = self._read_axes()` 在 `__init__`（`mf4_analyzer/ui/dialogs.py:508`）现读——**不存在跨打开过期**（review 中「对话框缓存过期」一说不成立）。真正的两个问题是：
  1. `apply_changes` 第 `mf4_analyzer/ui/dialogs.py:844` `self.handle.grid(self.chk_grid.isChecked())` **无条件写**：用户来改标题/轴标签等无关项、点确定也会把网格按 chk_grid 当前值重写一遍，X+Y 联动（`mf4_analyzer/ui/_axis_handle.py:629-637`），抹平右键菜单里独立设的 X/Y 状态。
  2. `_axis_handle.grid()` 走 `pi.showGrid()` **无 alpha**、不做 top/right 清理；菜单/canvas 走 `show_major_grid_left_bottom_only(alpha=0.28)`（`mf4_analyzer/ui/pg_canvas/_shared.py`），两路视觉不一致。
- **改动**（保对话框单勾语义）：
  - **脏检查**：`apply_changes` 仅在 `chk_grid.isChecked() != self._initial["grid"]` 时才调 `handle.grid(...)`。用户没碰网格勾 → 不写网格（保护菜单的独立 X/Y）；确实拨动了 → 按单勾 X+Y 一起写（符合用户选的「全部显示/全部不显示」）。
  - **统一应用函数**：`_axis_handle.grid()` 改走 `show_major_grid_left_bottom_only(pi, x=enabled, y=enabled if allow_y else False, alpha=0.28)`，与菜单/canvas 同一路径、同一 alpha、同一 top/right 清理。
- **验收**：菜单设 X 开 Y 关 → 打开对话框改标题、点确定 → X/Y 网格状态不被改动；在对话框拨动「显示网格线」→ X+Y 一起开/关，alpha 与右键菜单一致。

### ④ 移除对话框色图下拉

- **现状**：对话框 `_mappable_group` 的 `combo_cmap` 提供 8 种色图（`mf4_analyzer/ui/dialogs.py:710-719`），`apply` 实时 `mappable.set_cmap`（`dialogs.py:973` → `heatmap_canvas.py:151-159`），但 render 路径硬编码 turbo（如 `mf4_analyzer/ui/main_window/_order_mixin.py:416`），不持久化，重算静默回 turbo。已核实：该下拉仅在 `handle.get_mappables()` 非空时启用（`dialogs.py:725-726`），对 heatmap（阶次/fft_time）可达、对 FFT 线图自动禁用——即「选非 turbo 回退」确发生在 heatmap 路径。
- **改动**：从 `_mappable_group` 移除 `combo_cmap`（**保留**色阶 min/max 与 `chk_color_auto`）；相应清掉 `reset_fields`（`dialogs.py:817`）与 `apply`（`dialogs.py:973`）中的 cmap 读写，及 `_read_axes` 里的 `cmap` 字段（`dialogs.py:794`）。
- **验收**：对话框不再显示色图下拉；色阶 min/max 仍可用且与 colorbar/inspector Z 三方同步不受影响；无 `cmap` 残留引用。

### ⑤ idle 态菜单口径

- **现状**：idle（`mode == ''`）时 toolbar pan/zoom 按钮都不高亮，但右键菜单 `btn_pan.setChecked(current != _PG_MOUSE_MODE_ZOOM)`（`mf4_analyzer/ui/pg_canvas/context_menu.py:362-368`，复用路径 `:319-322`）会高亮「平移」。两入口对 idle 的口径不一。idle 可达：pan 按钮点两次 toggle 回 idle（`toolbar.py:543-550`），或 overlay 选中曲线时 `_on_overlay_channel_selected` 主动切 idle（`cards.py:882-897`）。
- **改动**：菜单改为按真实模式判定——`btn_pan.setChecked(current == 'pan')`、`btn_zoom.setChecked(current == 'zoom')`；idle 时两按钮都不高亮，与 toolbar 一致。`QButtonGroup` 为 exclusive，需临时 `setExclusive(False)` 以允许「都不选」（参照 toolbar 同款处理 `chart_stack/toolbar.py:156-162`）。
- **验收**：idle 态下右键菜单两按钮都不高亮；pan/zoom 态下分别高亮对应按钮，与 toolbar 一致。

### ⑥ 对话框「自动范围」读真实 autorange 状态

- **现状**：`_read_axes` 硬编码 `x_auto/y_auto/color_auto = False`（`mf4_analyzer/ui/dialogs.py:784/789/797`），因为 `PgAxisHandle` 无 autorange 查询；而分析图 Y 常处 `enableAutoRange(axis='y')`（`line_canvas.py:720/868`），对话框却恒显示「手动」。
- **改动**：`PgAxisHandle` 增 `is_autorange(axis='x'|'y') -> bool`，读 `self._view_box.state['autoRange']`（pyqtgraph ViewBox 标准状态，`_view_box` 已在 `mf4_analyzer/ui/_axis_handle.py:377` 持有）；`_read_axes` 用它填 `x_auto/y_auto`（color/Z 维持现有 `get_clim` 逻辑，本点不扩 Z）。
- **验收**：对处于 autorange 的轴打开对话框，「自动范围」勾选反映真实状态；手动设过范围的轴显示未勾。

## 4. Implementation Structure

### Phase 1 — 高影响（①②③）

- 改动文件：`pg_canvas/line_canvas.py`、`pg_canvas/heatmap_canvas.py`、`chart_stack/cards.py`（①）；`chart_stack/toolbar.py`、`pg_canvas/context_menu.py`、`chart_stack/stack.py`、`pg_canvas/canvas.py`（②）；`dialogs.py`、`_axis_handle.py`、`pg_canvas/_shared.py`（③）。
- 建议执行专家：`pyqt-ui-engineer` 为主（纯 UI/交互/信号槽），无数值算法。

### Phase 2 — 杂项（④⑤⑥）

- 改动文件：`dialogs.py`、`pg_canvas/heatmap_canvas.py`（④）；`pg_canvas/context_menu.py`（⑤）；`_axis_handle.py`、`dialogs.py`（⑥）。
- 建议执行专家：`pyqt-ui-engineer`（④⑤），`_axis_handle.is_autorange` 涉及共享抽象，可 `pyqt-ui-engineer` 或 `refactor-architect`（⑥）。

两批可独立交付；Phase 1 内 ①②③ 互不耦合，可并行。

## 5. Acceptance Criteria（汇总）

- [ ] ① 分析图手动缩放出现临时提示，重算/查看全部后撤下且范围回参数；inspector 数字不变。
- [ ] ② 分屏右键切 pan/zoom 两面板同步 + 共享图标刷新；单画布不受影响、无递归。
- [ ] ③ 对话框改无关项不再误伤网格（脏检查）；拨动网格勾 X+Y 联动且 alpha 与菜单一致。
- [ ] ④ 对话框无色图下拉；色阶 min/max 与三方同步不变。
- [ ] ⑤ idle 态菜单两按钮都不高亮，pan/zoom 态正确高亮。
- [ ] ⑥ 对话框「自动范围」反映真实 autorange。
- [ ] 既有用例全绿（除记录在案的 codex baseline 既有失败）。

## 6. Test / Verification Requirements

- **单元/集成（pytest）**：
  - ② 防递归与 peer 广播：mock 双面板 toolbar，断言右键路径后两 toolbar `mode` 一致且无重入；单画布 `_peers()` 为空时不报错。
  - ③ 脏检查：未改 `chk_grid` 调 `apply_changes` → `handle.grid` 不被调用（用 spy）；改了 → 调用一次且参数正确。
  - ⑤ 菜单 checked 逻辑：构造 `current ∈ {'', 'pan', 'zoom'}` 三态，断言两按钮 checked 组合。
  - ⑥ `is_autorange`：构造 autorange / 手动两态 ViewBox，断言返回值；`_read_axes` 填值正确。
  - ④ 移除后无 `combo_cmap`/`cmap` 引用（import/属性扫描），色阶用例不回归。
- **真机渲染验证（①②⑤ 属视觉/交互，按本仓库惯例必做）**：截图或 objc 读原生属性确认，**不接受「属性设上了 + 单测过」即判定修好**（历史教训：offscreen 渲染 ≠ 真机）。

## 7. Risks & Guardrails

- **②防递归**：唯一高危点。广播只在新入口做一层，对 peer 调非广播 setter；务必加重入测试。
- **③语义边界**：脏检查的动机是「不误伤」，不是「让对话框表达 X/Y 独立」——对话框仍是单勾总开关，用户主动拨动时按 X+Y 联动写，符合既定选择。
- **①不越界**：只加提示、只读手动缩放态；严禁顺手回写 inspector 或改 view-all（那会变成被否决的「缩放粘住」）。
- **真机验证**：UI 改动（尤其 macOS 原生渲染）必须验真实渲染结果。
- **环境**：项目位于 `~/Downloads`，子进程（codex 等）跑过后 agent 对项目目录可能 EPERM；必要时授 Full Disk Access 或移出 Downloads。harness Read/Write 工具不受影响。
- **既有 baseline**：codex baseline 有记录在案的既有失败（`_CaptureCanvas` 缺 `set_tick_density`），勿误判为本次回归。

## 8. 经核实纠正的 review 偏差

- 「ChartOptionsDialog 网格状态缓存过期」**不成立**：对话框每次新建实例、`_initial` 现读（`_axis_interaction.py:113` + `dialogs.py:508`）。③ 因此不含「实时重读」改动，只含脏检查 + alpha 统一。
- 「分析图查看全部回到数据极值」**不成立**：实际回到参数 xlim（`line_canvas.py:857-861/712`）。① 因此不改 view-all。
