# WWT 最小首帧契约简化实施计划

- 日期：2026-09-01
- 状态：**IMPLEMENTED — FINAL PLATFORM/FULL ACCEPTANCE UNVERIFIED**
- 计划基线：`main@79ea59a2`
- 任务性质：删除已证实过重的 WWT 显示生命周期，只保留正确首帧所需的最小导入事实
- 本计划阶段：Task 0–6 的实现与测试迁移已完成；最终综合 focused/boundary 为
  **1069 passed, 1 deselected**。当前快照尚无有效 full gate，且 macOS 已锁定，Cocoa
  前台/客户样例 A/B 验收仍为 **UNVERIFIED**。
- 首帧基线：用户在 2026-09-01 提供的 TraceLab v8.2.0 前台截图；实现者必须在改动前用同一客户样例重建一份本机基线证据

### 2026-09-01 最终执行台账

| Task | 当前状态 | 已证实的范围 | 尚未关闭的门禁 |
| --- | --- | --- | --- |
| T0 | **已实施，focused/boundary 通过** | 合成首帧合同 fixture 与 owner tests 已迁移进工作树，并纳入最终综合 **1069 passed, 1 deselected**。 | 改动前 RED 记录、客户样例基线与 Cocoa A/B。 |
| T1 | **已实施，focused/boundary 通过** | ordinary channel-backed proposal 不再产生 `native_ticks`/viewport intent；早期 owner 回归 **68 passed**，最终已纳入综合门禁。 | 当前快照 full gate 与 Cocoa A/B。 |
| T2 | **已实施，focused/boundary 通过** | 普通 restore 单事务及 Canvas display policy 移除已完成并纳入综合门禁。 | 当前快照 full gate 与 Cocoa A/B。 |
| T3 | **已实施，focused/boundary 通过** | Home、Y Fit、density、filter、Custom-X、resize 的 WWT 显示分叉/物理样式清理已完成并纳入综合门禁。 | 当前快照 full gate 与 Cocoa A/B。 |
| T4 | **已实施，focused/boundary 通过** | WWT 自动 UltraView 原生排版移除已完成并纳入综合门禁。 | 当前快照 full gate，以及手动 Smart Layout 的 Cocoa 前台验证。 |
| T5 | **已实施，focused/boundary 通过** | legacy native 字段读取后规范化清理及 project restore/remap tests 已完成并纳入综合门禁。 | 当前快照 full gate 与 Cocoa A/B。 |
| T6 | **已实施，focused/boundary 通过** | native-only tests 已迁移/清理；本计划、历史链接与 active lesson 已同步，`rg` 审计和 `git diff --check` 已完成。 | 当前快照 full gate 与 Cocoa/客户样例 A/B。 |

full gate 的可用性必须按快照判断：`main` full gate 在修复前快照结束为
**20 failed, 8756 passed, 35 skipped, 3 deselected**；后续已修复其中 7 条本计划相关问题，
故该结果不能作为当前快照的 full 证据。`tests/acquisition_ui` 在同一前一快照为
**359 passed**，同样不能替代当前 full gate，均标为 **UNVERIFIED / stale for current snapshot**。
macOS 已锁定，Cocoa 前台与客户样例 A/B 也保持 **UNVERIFIED**。用户无关的 asset、Inspector
等 dirty scope 均未纳入本计划。

## 1. 结论

本轮不再优化“WWT 原生模式”，而是删除这层模式。

WWT 导入只负责生成一个普通 `ViewState` 所需的首帧事实：要画哪些曲线、初始横坐标、
初始 X/Y 范围、overlay、颜色和必要标签。首帧绘制完成后，不得留下 WWT 专属刻度策略、
Home 目标、物理线宽、resize/zoom 重投影或 UltraView 原生排版所有权。

目标事务固定为：

```text
parse WWT
→ build ordinary ViewState
  (checked / colors / overlay / x_axis / xlim / ylims / exceptional XY only)
→ normal Canvas plot
→ restore committed X/Y ranges once
→ apply TraceLab density without re-framing those committed ranges
→ settle once
→ ordinary Canvas owns everything afterwards
```

完成后，用户看到的初始图面仍与当前正确截图基本一致；随后使用密度、Draw、Custom X、
Home、Y Fit、zoom/pan、滤波、View 切换和项目保存/恢复时，全部走现有 TraceLab Canvas 合同。

## 2. 用户确认的产品合同

### 2.1 必须保留的首帧

以用户截图中的 `SFNS_20_X04-CSER_000009` 为第一优先前台基线：

- TimeDomain 普通 View，`plot_mode="overlay"`；
- 底部 View 名类似 `WinWert 1 · Rack travel`；
- X 使用 `Rack travel [mm]`，可见范围约 `-100..100 mm`；
- Y 可见范围约 `-1500..1500 N`；
- 当前可见曲线内容、数量、颜色和基本叠加关系不变；
- 使用 TraceLab 当前图面、字体、背景、轴样式和普通密度，截图中为 `X=20 / Y=15`；
- 不要求复刻 WinWert 的固定 tick cadence、无标签 grid、物理毫米线宽或窗口物理位置。

“基本一致”在本计划中的可测定义是：

```text
curve identities + visible curve count + X source/label
+ initial xlim + initial per-axis ylim + overlay + colors
```

不把 tick 数值序列、grid 间隔、pen 物理宽度、像素级图面和 UltraView 卡片矩形纳入 WWT
保真合同。它们由 TraceLab 当前 Canvas 决定。

### 2.2 首帧后必须是普通 Canvas

首帧结束后必须成立：

- canvas 上不存在 active WWT/native tick policy；
- ViewState 中不存在会改变 Home/zoom/resize 的 WWT viewport intent；
- 用户修改密度只是普通密度修改，不再同时承担“退出原生模式”；
- Home 回到普通 Canvas 的数据范围合同，不回到 WWT 固定 home range；
- Y Fit、zoom/pan、resize settle 不调用 WWT tick projector；
- 可表达为普通通道的曲线走普通 Custom-X、时间范围和滤波路径；
- 项目保存的是用户当前普通 View 范围，不保存一个等待重新激活的 WWT 显示策略；
- 多窗口 WWT 仍可创建多个普通 View，但不自动创建 WWT 专属 UltraView Board 或物理布局。

## 3. 当前实现额外做了什么

| 层 | 当前行为 | 冲突/成本 | 目标 |
|---|---|---|---|
| WWT proposal | 为所有 visible 曲线生成 exact `curve_bindings` | 普通通道被 binding claim，绕过普通 X 和滤波 | 只为真正 exceptional XY 生成 binding |
| WWT proposal | 写入 `axis_opts["native_ticks"]` | ViewState 持久化第二套 tick/grid 事实 | 不再生成；旧字段仅容错读取后丢弃 |
| WWT proposal | 写入 `x_viewport_intent=wwt_native` | Home 与普通 Canvas 分叉 | 不再生成；删除运行期行为 |
| WWT proposal | 保存 `line_width_mm`、`rect_mm` | 把 WWT 物理样式/排版带入运行期 | parser 可保留原始事实，View/Canvas 不再消费 |
| View restore | 安装 native policy，再 density/project/settle | restore 有 generic/native 双路 | 统一普通 restore 事务 |
| Canvas tick controller | 持有 `native_tick_policy`，缩放和 resize 后重投影 | Canvas 出现第二套 tick owner | 删除 policy 与 projector |
| Canvas Home | X 读 WWT intent、Y 读 native policy | Home/Y Fit 语义分裂 | 只保留普通 data-extents 行为 |
| 密度入口 | 先清 View/canvas native policy，再应用 density | 一个 UI 动作有两层语义 | 只应用并保存普通 density |
| curve pen | `line_width_mm → logical px` | WWT 样式覆盖普通 Canvas 线宽/强调逻辑 | 使用普通 Canvas pen 规则 |
| UltraView | 多 View 自动创建 dedicated Board/native layout | 导入图形被扩大为画板编排功能 | 只创建普通 Views；手动 Smart Layout 仍可用 |
| persistence | 被动 capture 保留 native facts | 旧模式跨 View/项目持续复活 | 只持久化普通 View 状态 |

这些行为不是彼此独立的小功能，而是一条完整生命周期；只删除某个按钮分支会留下 stale
policy 或旧项目复活问题，因此本计划按所有权顺序删除，但不重写 WWT 数据解析。

## 4. 范围边界

### 4.1 保留

- 完整 WWT 文档/window/curve 解析；
- 公式计算、record store、diagnostics 和禁止伪造时间轴等数据正确性合同；
- 一个 WWT window 对应一个普通 TimeDomain View；
- visible 曲线集合、可用曲线颜色、普通 overlay 和初始范围；
- 共享的 channel-backed X 可转换为 `PER_SOURCE_NAME` 普通 X 规格；
- record-only Y、record-only X、独立 XY 或同一 View 中无法用一个普通 X 规格表达的曲线；
- `hidden_curve_binding_ids` 对 record-only 行的 View-local 可见性；
- 文件关闭、通道删除、fid remap 和 degraded restore 对保留 binding 的清理；
- 现有手动 UltraView、Smart Layout、Board Fit 和普通 View 引用能力。

### 4.2 删除或退出运行期

- `axis_opts["native_ticks"]` 的生产、持久化和消费；
- `TickDensityController.native_tick_policy`、native tick/grid enumeration 和 projector；
- `set_native_tick_policy()`、`project_native_ticks()` 及交互 settle/resize/Home 接线；
- WWT `XViewportIntent`、trusted WWT Home 和 canvas `_x_viewport_intent`；
- WWT physical `line_width_mm` 的 Canvas/DPI 路径；
- tick/grid 作为曲线能否共享 Y 轴的判定条件；
- 密度动作中的“退出 native mode”分支；
- WWT import 后自动调用 `add_time_views_from_native_layout()`；
- placement counts/board id/native rect 作为 WWT 导入成功摘要的一部分；
- 帮助文案中的“恢复原生刻度/原生排版/同步加入 UltraView”承诺。

### 4.3 明确不顺带做

- 不增加 `WWT 原生`、`WWT 兼容` 等新模式、badge 或开关；
- 不增加另一套 View schema 或 Canvas；
- 不修改 WWT 导出格式；
- 不重做 Batch 选择记忆、Custom-X cursor path statistics 或其他相邻功能；
- 不重构整个 `TimeCurveBinding`/project schema；旧字段可先保留为兼容解码字段但不得再驱动显示；
- 不把普通 overlay 的 density nice-frame 全局关闭；仅在有明确 committed ranges 的 restore
  事务中禁止它二次改写范围；
- 不要求所有客户 WWT 都成为 required test fixture。

## 5. 数据分类：普通曲线与 exceptional XY

这是最小化能否成功的关键边界。

### 5.1 普通 channel-backed 曲线

满足以下条件时，不生成 `TimeCurveBinding`：

1. Y 已物化为普通 `(fid, channel)`；
2. X 也是普通 channel；
3. 该曲线的 X 可由当前 View 的一个普通 `CustomXAxisSpec` 诚实解析；
4. X/Y 长度和 acquisition 归属已由正常数据层证明。

这些曲线只写入 `ViewState.checked/colors`，并通过普通 `_build_time_plot_data()` 产生。这样：

- Inspector 的横坐标设置与实际 plot 一致；
- 切换回时间或指定其他通道会真实改变 X；
- filter 能生成原始/滤波后 companion；
- Draw、时间范围、颜色和 Navigator 可见性都使用已有路径；
- 不再被 `binding_claimed` 提前跳过。

### 5.2 必须保留最小 binding 的曲线

只有以下情况保留：

- Y 是 `wwt_record`，没有 Navigator identity；
- X 是 `wwt_record` 或独立 XY 数据，不能伪装成 time/channel；
- 同一 View 的逐曲线 X 不同，无法用一个普通 X spec 无损表达；
- 删除 binding 会改变曲线 X/Y 数据或导致曲线丢失。

这些 binding 只携带解析曲线需要的数据身份、显示名、颜色、axis group 和初始 Y range。
它们不再携带/驱动 native tick cadence、grid 或 physical line width。对于确实是独立 XY 的
曲线，普通 time filter/Custom-X 不适用是数据语义限制，不再伪装成一个 WWT Canvas 模式。

### 5.3 分类停止条件

若实现者无法证明某条 channel-backed 曲线可由一个普通 X spec 表达，必须保留为 exceptional
binding 并新增定向测试；不得为了减少 binding 猜 X、截断数组或发明采样率。

## 6. 目标状态与恢复事务

### 6.1 新建 ViewState

一个普通 WWT proposal 只应提交：

```text
name
attached_file_ids
checked
colors
plot_mode="overlay"
xlim
ylims
axis_opts["x_axis"]
curve_bindings = exceptional XY only
hidden_curve_binding_ids = record-only visibility only
```

不提交：

```text
axis_opts["native_ticks"]
x_viewport_intent
native Home range
line_width_mm display policy
UltraView native rect ownership
```

### 6.2 普通 restore 的单事务

`_render_view_onto_canvas()` 继续是 View restore 的唯一 finalizer：

```text
build rows/axes with defer_axis_finalize=True
→ restore_visible_xlim(state.xlim)
→ restore_visible_ylims(state.ylims, initial_axis_ranges=exceptional ranges)
→ set_tick_density(xt, yt, reframe_overlay_y=False when committed range exists)
→ settle_view_restore() exactly once
```

约束：

- `initial_axis_ranges` 是一次性范围 fallback，不是 active policy；
- persisted/live `state.ylims` 优先于 import initial range；
- 普通 channel-backed Y 的初始 WWT range 直接写入 `state.ylims`；
- record-only/exceptional axis 可从 binding `axis_id + y_range` 取得首次 fallback；
- density 仍生成 TraceLab 普通 X/Y ticks 和 overlay grid；
- 不允许“先 nice-reframe、再把 WWT range 写回”的双重工作；
- settle 后 canvas 不持有任何 WWT 显示状态。

### 6.3 首帧后的普通行为

- capture 把当前 X/Y ranges 和普通 controls 写回 ViewState；
- Home 从实际曲线数据 union 计算；
- Y Fit 使用普通 visible/raw extent；
- density 使用普通 reframe 合同；
- zoom/pan/resize 使用普通 adaptive target ticks；
- 切 View、split 和项目恢复只恢复各自普通 state；
- ordinary View 与由 WWT 创建的 View 在 Canvas 上不可区分。

## 7. 历史合同的退役范围

以下历史文档保留为当时设计记录，不回溯改写，但实现后不再作为当前产品合同：

- `docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md`
  - 退役 D1 中 tick/grid/physical line width/UltraView position 的“相同”要求；
  - 退役 §7.2 `native_ticks`、§8.2 native cadence、§8.3 physical line width；
  - 退役 §9.3 的自动 UltraView projection、§10 native layout、§12 native facts persistence；
  - 保留 parser、formula、record-only/independent XY、diagnostics、identity 和禁止伪造数据。
- `docs/analyzer/plans/2026-08-30-wwt-native-axis-range-and-tick-lifecycle-optimization-plan.md`
  - 整体由本计划取代；不再维护 native policy 生命周期。
- `docs/analyzer/plans/2026-08-31-wwt-single-owner-axis-finalization-plan.md`
  - 保留“View restore 只 finalise 一次”的通用结论；删除 native policy 安装/project 部分。
- `docs/analyzer/plans/2026-08-31-cursor-display-followup-2-plan.md` 的 W1 native tick follow
  - 不再是产品验收项。

实现收尾必须更新 active lesson
`view-restore-range-and-ticks-need-full-transaction.md`：保留“完整事务后断言 range/ticks”的通用
规则，删除“被动 capture 必须保留 native_ticks / 只有 density 才退出”的已退役规则，防止以后
又把第二套 owner 加回来。

## 8. 实施任务

### Task 0 — 在改代码前冻结当前正确首帧和目标红测

**执行状态（2026-09-01）**：已实施，已纳入最终综合 focused/boundary（**1069 passed,
1 deselected**）；改动前 RED 记录与客户样例/Cocoa 基线仍为 **UNVERIFIED**。

**Owner files**

- `tests/_helpers/wwt_factory.py`
- `tests/ui/test_wwt_view_import.py`
- `tests/ui/test_wwt_import_flow.py`
- 新增或重写为最小合同的 `tests/ui/test_wwt_initial_view_contract.py`
- 仅保留仍相关测试后的 `tests/ui/test_wwt_native_render.py`

**步骤**

1. 用 committed synthetic fixture 建立截图同族的 owner fixture：
   - `Rack Travel [mm]`；X `-100..100`；
   - `Rack Force [N]`；Y `-1500..1500`；
   - 当前截图同样的 overlay 和颜色；
   - 不依赖 `testdoc/`。
2. 在产品改动前运行真实 `MainWindow`，记录：
   - proposal facts；
   - plot rows/curve data hashes；
   - ViewState/canvas/AxisItem X/Y ranges；
   - generic density `20/15`；
   - 前台 Cocoa screenshot，放在 `.state/wwt-minimal-baseline/`，不提交 Git。
3. 新增以下必须先红的目标测试：
   - `test_channel_backed_wwt_proposal_is_ordinary_view_with_initial_ranges`
     - `native_ticks` 不存在；`x_viewport_intent` 不存在；普通 Y 不在 binding 中；
   - `test_wwt_first_frame_keeps_imported_ranges_with_generic_density`
     - X/Y 为 `-100..100`、`-1500..1500`；controller 没有 native policy；
   - `test_channel_backed_wwt_filter_builds_normal_companion`
     - 打开 filter 后原始/滤波后两条均走普通通道路径；
   - `test_channel_backed_wwt_custom_x_change_is_not_binding_pinned`
     - 从 Rack Travel 切 time/另一合法 X 后数据真实变化；
   - `test_record_only_and_independent_xy_still_render_exact_arrays`
     - exceptional binding 保留长度、NaN、颜色和逐曲线 X；
   - `test_multiple_wwt_windows_create_views_without_native_board_projection`
     - 创建普通 Views，但不调用 `add_time_views_from_native_layout()`；
   - `test_legacy_project_native_fields_do_not_reactivate_wwt_policy`
     - 旧 JSON 可加载，首帧后只剩普通 View 行为。
4. 现有“当前首帧正确”的范围/曲线用例必须在改动前绿色；上述“无 native policy/普通
   filter/无自动 Board”用例应因当前实现真实失败。fixture/import error 不算红测。

**Task 0 停止条件**

- 当前真实客户样例无法稳定重建用户截图；
- synthetic fixture 与客户样例曲线结构不同到无法代表首帧；
- 红测只能通过像素容差掩盖数据/range 差异；
- 需要把客户 `testdoc/` 文件变成 required owner fixture。

### Task 1 — 简化 WWT proposal，先切断新状态的产生

**执行状态（2026-09-01）**：已实施；早期 owner 回归为 **68 passed**，并已纳入最终综合
focused/boundary（**1069 passed, 1 deselected**）。当前快照 full/Cocoa 门禁仍为 **UNVERIFIED**。

**Owner files**

- `mf4_analyzer/ui/wwt_view_import.py`
- `mf4_analyzer/ui/time_curve_bindings.py`（只做分类/兼容所需最小改动）
- `tests/ui/test_wwt_view_import.py`
- `tests/ui/test_wwt_import_flow.py`

**修改**

1. 新增纯函数分类：ordinary channel-backed 与 exceptional XY；不得在 MainWindow 判断扩展名。
2. `_x_axis_opts()` 从 ordinary 曲线的共享 channel X 建立 `PER_SOURCE_NAME`；若存在无法表达的
   per-curve X，使用诚实 fallback，不显示一个与实际数据矛盾的 global source。
3. ordinary Y 只进入 `checked/colors/ylims`，不进入 `curve_bindings`。
4. exceptional 曲线保留 binding 的 exact X/Y ref、axis id、color、unit、display name、初始
   y range；停止产生 tick/grid/physical width display policy。
5. `_plan_axes()` 共享条件只使用数据/显示确实需要的 unit + range；删除 tick/grid 相等条件。
6. proposal 不再生成 `native_ticks` 或 `x_viewport_intent`。
7. `WwtViewProposal.rect_mm/line_width_mm` 若无其他消费者则移除；parser DTO 仍可保留原始值。
8. 不改变公式计算、record store 或 warnings taxonomy。

**验收**

- screenshot-family proposal 的 `x_axis/xlim/ylims/checked/colors/overlay` 与目标一致；
- ordinary curve bindings 为零；
- YP-like tolerance、whole-window record-only gap 和 heterogeneous X fixture 仍有 exact binding；
- 同名多 source 的 X 继续使用 each source's own channel；
- 不新增 MainWindow mutable state。

### Task 2 — 将 View restore 收敛为普通 Canvas 单事务

**执行状态（2026-09-01）**：已实施，已纳入最终综合 focused/boundary（**1069 passed,
1 deselected**）；当前快照 full/Cocoa 门禁仍为 **UNVERIFIED**。

**Owner files**

- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/view_bridge.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/tick_density.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/pg_canvas/native_axes.py`
- `tests/ui/test_pg_timedomain_canvas.py`
- `tests/ui/test_overlay_grid_ticks.py`
- `tests/ui/test_view_bridge.py`
- `tests/ui/test_wwt_initial_view_contract.py`

**修改**

1. `_render_view_onto_canvas()` 删除 intent 安装、native policy 安装和 tick project 分支。
2. `restore_visible_ylims(..., native_axis_ranges=...)` 改为中立的 initial/fallback axis range
   合同；输入只来自 exceptional binding 的初始 `axis_id/y_range`，不含 cadence。
3. 恢复 committed X/Y 后调用普通 `set_tick_density()`；当本次已恢复明确范围时使用现有
   kw-only `reframe_overlay_y=False`，避免首帧 `-1500..1500` 被 nice-frame 二次修改。
4. `TickDensityController` 删除 `native_tick_policy` owner、deep copy、native imports 和
   native branches；普通 density/target-X 行为保持。
5. Canvas/overlay interaction 删除 `_project_native_ticks_after_commit()` 接线。
6. `native_axes.py` 只保留仍被通用 axis grouping 使用的 neutral helper；删除 tick enumeration
   和 line-width runtime。若移动 `tag_axis_group` 会扩大改动，可暂留在原模块，但不得保留
   active policy 或 Canvas delegate。
7. `_CanvasBackref._owned_names/_delegate_names` 与真实状态同步，必须通过 invariant test。

**验收**

- restore 只出现一次 `settle_view_restore()`；
- final ViewState range、`PgAxisHandle.get_*lim()`、`AxisItem.range` 一致；
- ticks/grid 来自普通 density，且覆盖最终范围；
- screenshot-family 首帧 range 不变；
- ordinary non-WWT View restore、direct Draw 和 overlay density 既有行为不回归；
- Canvas rebuild/clear 后不存在 native-related mutable state。

### Task 3 — 删除交互层的 WWT 分叉和物理样式

**执行状态（2026-09-01）**：已实施；Home、Y Fit、density、filter、Custom-X 与 resize
已纳入最终综合 focused/boundary（**1069 passed, 1 deselected**）。当前快照 full/Cocoa
门禁仍为 **UNVERIFIED**。

**Owner files**

- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/view_state.py`
- `tests/ui/test_wwt_initial_view_contract.py`
- 相关 Home/Y Fit/filter/custom-X tests

**修改**

1. `_update_all_tick_density_pair()` 删除 `native_ticks` pop 和 canvas clear；只保存并应用普通 density。
2. 删除 `X_VIEWPORT_WWT_NATIVE`、`trusted_wwt_native_intent`、Canvas intent 和 WWT Home 分支；
   `reset_view_to_data_extents()` 只保留普通 data union / raw Y extent。
3. 删除 `_native_line_width_px`、logical DPI 换算和 overlay pen override；使用普通 Canvas 线宽。
4. 保留 axis group 仅用于多 Y 轴/共享范围，不再暗含 native tick 所有权。
5. 不改变真正 independent XY 的数据数组；只删除其显示政策。

**验收**

- screenshot-family 打开后点击 Home 得到普通 data union，不是固定 `-100..100` native home；
- Y Fit、zoom/pan、resize 不调用不存在的 projector；
- density `20/15 → 其他值 → 20/15` 与普通 View 一致；
- filter companion 对 ordinary WWT-created curve 正常出现；
- record-only curve 仍可显示/隐藏且不污染 Navigator identity；
- 普通 overlay 默认线宽/强调宽度不因 WWT 来源变化。

### Task 4 — 取消 WWT 自动 UltraView 原生排版

**执行状态（2026-09-01）**：已实施，已纳入最终综合 focused/boundary（**1069 passed,
1 deselected**）；手动 Smart Layout/Cocoa 前台证据与当前快照 full gate 仍为 **UNVERIFIED**。

**Owner files**

- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`（只有无其他 caller 时才删除兼容入口）
- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`（原则上不改）
- `tests/ui/test_wwt_import_flow.py`
- `tests/ui/test_ultraview_native_layout.py`
- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`

**修改**

1. coordinator 只批量插入 ordinary Views 并激活首个；不再调用
   `add_time_views_from_native_layout()`。
2. import outcome 删除 WWT placement counts、board id、generated/unplaced/native-layout warnings；
   保留 View created/cap/degraded data diagnostics。
3. 对话框文案从“按 WinWert 原排版并同步 UltraView”收敛为“按 WinWert 窗口创建时域 View
   并绘图”；Reject 仍是仅加载数据。
4. 不删除 UltraView 通用 Smart Layout/Board Fit；只有 `rg` 证明 native-layout API 完全无其他
   caller 时才删除 WWT 专用兼容入口和专属 tests。
5. hints/quickref 同步新边界，不再承诺 native tick/physical layout。

**验收**

- 多 window WWT 创建相同数量的普通 Views；
- 不新建 dedicated Board，不改变当前 Board，不产生 unplaced refs；
- 用户之后仍可手动把 Views 加入 UltraView 并执行 Smart Layout；
- Accept/Reject/project restore/View cap 行为和错误 taxonomy 不回归。

### Task 5 — 旧项目兼容与状态清理

**执行状态（2026-09-01）**：已实施；legacy decode、save/reopen、remap 和 degraded
diagnostics 已纳入最终综合 focused/boundary（**1069 passed, 1 deselected**）。当前快照
full/Cocoa 门禁仍为 **UNVERIFIED**。

**Owner files**

- `mf4_analyzer/ui/view_state.py`
- `mf4_analyzer/ui/project_io.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/time_curve_bindings.py`
- `tests/ui/test_view_state.py`
- `tests/ui/test_project_session.py`
- `tests/ui/test_time_curve_bindings.py`

**兼容策略**

1. 旧 `.tlproj` 中的 `axis_opts.native_ticks` 可被读取但立刻规范化丢弃，不激活任何 Canvas policy，
   再保存时不复写。
2. 旧 `x_viewport_intent` 字段由 `ViewState.from_dict()` 忽略；旧 JSON 不报错，不需要 schema bump。
3. 旧 ordinary channel-backed bindings：
   - 若可由 View `x_axis`/per-source X 诚实表达，迁移为 ordinary checked/colors；
   - 若无法证明，继续保留为 exceptional binding；
   - 不允许迁移时改错 X 或静默回退 Time-Y。
4. record-only/independent XY binding、hidden ids、fid remap、close/remove diagnostics 保持。
5. `TimeCurveBinding` 的旧 tick/grid/line-width 字段可暂时兼容 decode，但 renderer 不消费；
   若本波删除字段会扩大 migration 风险，记录为后续无行为 schema cleanup，不阻塞本轮。

**验收**

- 新项目 JSON 不含 active native display policy；
- 含旧 native fields 的 fixture 打开后首帧正常、Home/density/filter 均为普通行为；
- record-only 项目 save/reopen 不丢曲线；
- missing owner/remap 仍产生既有 degraded diagnostics；
- project restore 不弹 WWT import prompt，也不自动创建 Board。

### Task 6 — 清理旧测试、文档和 lesson，完成前台对标

**执行状态（2026-09-01）**：已实施；native-only tests、文档和 lesson 已完成迁移/清理，
并纳入最终综合 focused/boundary（**1069 passed, 1 deselected**）。当前快照 full gate、
Cocoa A/B 与客户样例 smoke 仍为 **UNVERIFIED**。

**修改原则**

- 删除只证明 native tick enumeration/policy lifecycle 的 tests；不要把它们改成无意义空断言。
- 把仍有价值的 range/AxisItem/full-transaction tests 迁移到普通 restore owner tests。
- 保留 record-only、same-name per-source X、diagnostics、project remap 和 data correctness tests。
- 更新本计划状态、相关当前帮助和 active lesson；历史 spec/plan 仅加“由本计划取代”的链接时，
  不改写历史结论或版本。

**前台 A/B 验收**

在真实 macOS Cocoa、相同窗口尺寸、相同客户文件上：

1. 改动前捕获当前正确首帧（A）；
2. 改动后清空旧项目/QSettings 影响，用同一路径打开并捕获首帧（B）；
3. 自动/人工共同核对：
   - curve count/identity/hash；
   - X source/label；
   - xlim/ylims；
   - overlay/颜色；
   - 没有明显新增空白、裁切或轴错位；
4. tick/grid/line width 允许采用 TraceLab 普通 Canvas 当前结果，不按 WinWert 数值逐项比较；
5. 在 B 上继续操作 density、Home、Y Fit、Custom X、filter、zoom/pan、View switch、save/reopen，
   证明它们不触发 WWT 专属路径；
6. 另外检查 YP-like record-only tolerance 和 U-Can independent XY，确保精简没有丢内容；
7. Cocoa、offscreen、optional customer smoke 分开报告，不能互相替代。

## 9. 验证门禁

### 9.1 每个 Task 的 focused owner tests

优先运行精确 node id；波次结束补齐：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_wwt_view_import.py \
  tests/ui/test_wwt_initial_view_contract.py \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_time_curve_bindings.py \
  tests/ui/test_view_bridge.py \
  tests/ui/test_view_state.py \
  tests/ui/test_project_session.py \
  tests/ui/test_overlay_grid_ticks.py \
  tests/ui/test_pg_timedomain_canvas.py
```

若 `test_wwt_initial_view_contract.py` 尚未创建，Task 0 必须先创建，不能继续依赖名称已经与
目标相反的 `test_wwt_native_render.py` 作为唯一 owner。

### 9.2 边界门禁

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_native_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py \
  tests/ui_kit/test_qss_border_shorthand.py
```

并运行：

```bash
rg -n "native_ticks|native_tick_policy|project_native_ticks|x_viewport_intent|line_width_mm" \
  mf4_analyzer/ui tests/ui
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

`rg` 的允许命中只包括明确的 legacy decode/migration fixture、parser DTO 或历史兼容注释；任何
Canvas policy、Home 分支或新 proposal 生成命中都阻止完成。

### 9.3 稳定集成 full gate

本次横跨 ViewState、Canvas、project restore 和 import coordinator，稳定集成里程碑允许且只运行
一次 full gate。开始前记录 `HEAD`、dirty scope 并确认同一 checkout 无其他 full pytest：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

两个进程串行运行。异常退出、crash、timeout、中断或测试期间相关源码变化一律记
`UNVERIFIED`，不从已完成的 dots 推断 PASS。

### 9.4 外部样例规则

- required owner tests 只使用 `tests/_helpers/wwt_factory.py` committed synthetic fixtures；
- 用户/客户文件只做 optional smoke 和 Cocoa A/B；缺失时 `SKIP`，不 `pytest.fail`；
- 不把本次临时截图路径写成可移植 fixture。

## 10. 实施顺序与提交边界

建议单一实现 owner 顺序完成，因为 Task 1–3 会共同触及 proposal、View restore 和 Canvas：

```text
T0 baseline + red tests
→ T1 stop producing native state
→ T2 remove Canvas policy / generic restore
→ T3 remove interaction and pen branches
→ focused gates
→ T4 remove automatic UltraView projection + copy
→ T5 legacy migration
→ T6 test/docs/lesson cleanup
→ boundary gates
→ one stable full gate
→ Cocoa A/B acceptance
```

建议按可回滚边界提交：

1. `test(ui): freeze minimal WWT initial view contract`
2. `refactor(ui): emit ordinary WWT view state`
3. `refactor(ui): remove WWT canvas display policy`
4. `refactor(ui): stop automatic WWT native board layout`
5. `fix(project): migrate legacy WWT display state`
6. `docs(ui): retire WWT native display contract`

每个提交只 stage 本 Task 文件。当前工作树含用户的资产删除、Inspector/time-filter 修改和
未跟踪文件；实现者不得 checkout/revert/清理或带入这些变化。

## 11. 全局停止条件

出现任一情况立即停止并回报，不用兼容补丁掩盖：

1. 简化后 screenshot-family 首帧 curve identity、X source、xlim 或 ylim 与基线不一致。
2. 删除 ordinary binding 导致任何曲线丢失、错 X、长度截断、伪造时间或采样率。
3. 保住首帧必须全局关闭普通 overlay nice-reframe，导致非 WWT View 行为变化。
4. record-only/independent XY 无法在不保留 native Canvas policy 的情况下恢复初始范围。
5. 旧项目只有继续激活 native policy 才能打开；此时先设计一次性 migration，不复活模式。
6. 需要新增/扩大 MainWindow 多文件 mutable state 或放宽 ownership whitelist。
7. Task 4 发现 `add_time_views_from_native_layout()` 还有非 WWT 产品 caller；只停止删除 API，
   仍可停止 WWT 自动调用，不得破坏通用 UltraView。
8. required tests 需要 gitignored customer file。
9. 只能通过放宽/删除当前首帧 range 或 record-only correctness assertions 才能转绿。
10. 同一 checkout 已有 full pytest，或 full gate 期间相关源文件变化。

## 12. 完成定义

只有同时满足以下条件才能宣称完成：

- 用户截图同族首帧的曲线、X source/label、X/Y ranges、overlay 和颜色保持；
- 首帧使用 TraceLab 普通 density/ticks，Canvas/View 中无 active WWT display policy；
- ordinary channel-backed WWT 曲线不在 `curve_bindings` 中，不再被 binding claim；
- filter、Custom X、density、Home、Y Fit、zoom/pan 和 resize 与普通 View 同路；
- record-only/independent XY 曲线及其精确数据不丢失；
- 多 window 创建普通 Views，但不自动创建 dedicated UltraView Board/native layout；
- 旧项目含 native fields 时可打开并迁移，不复活模式；
- focused/boundary/full gates 有正常最终摘要；未运行的 Cocoa/Windows gate明确标为
  `UNVERIFIED`；
- Cocoa A/B 对标完成，B 首帧无明显视觉回归，后续交互证明由 Canvas 接管；
- `rg` 不再发现 active native policy 运行期路径；
- hints/quickref/active lesson 与新合同一致；
- `git diff --check` 通过，lesson 状态清晰；
- 提交不包含用户当前不相关 dirty/untracked 文件。
