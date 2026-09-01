# 游标显示 Follow-up 2 + WWT 原生刻度视口跟随实施计划

- 日期：2026-08-31（晚）
- 状态：离屏实施完成（Cocoa 真机未验收，见 §5）
- 基线：`main@a36ef529`（followup-1 已合入：`fix(ui): land cursor-display followup contracts`）。
  本计划改动叠在该提交之上，**尚未单独提交**。
- 上游文档：[`2026-08-31-cursor-display-followup-spec.md`](../specs/2026-08-31-cursor-display-followup-spec.md) ·
  [`2026-08-31-cursor-display-settings-spec.md`](../specs/2026-08-31-cursor-display-settings-spec.md) ·
  [`2026-08-31-wwt-single-owner-axis-finalization-plan.md`](2026-08-31-wwt-single-owner-axis-finalization-plan.md)
- 验证范围声明：各 Task 只跑自己的 owner 聚焦用例 + 所列护栏，不安排
  全量。真机（Cocoa 前台）证据仅 W1（WWT 截图）与 C4（hover 状态）需要。
- **现行性说明（2026-09-01）**：本文 W1 的 WWT native tick/viewport follow-up 已由
  [`2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md`](2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md)
  取代；Cursor C1–C6 的历史计划与结论不回溯改写。

## 1. 本轮问题与根因（均已在当前工作区复现/定位）

### R7 WWT 原生 View：Home/缩放后 Y 轴只有中段有刻度标签

**复现**（离屏探针，真实客户文件
`testdoc/2024_3_17/SFNS_20_X04-CSER_000009.wwt`，完整 `_load_one` 路径）：

```text
initial:      ylim=(-1500, 1500)  majors=(-1500 … 1500, step 500)   ✓
after Home:   ylim=(-4200, 4800)  majors=(-1500 … 1500, step 500)   ✗ 上下无标签
after zoom:   ylim=(-6450, 7050)  majors=(-1500 … 1500, step 500)   ✗
```

用户截图（视口约 -4200..4800、标签只到 ±1500）与 Home 后状态完全吻合。

**根因**：`tick_density.py:project_native_ticks()` 本身就是按**当前有效
范围**投影 cadence 的（`test_native_ticks_project_over_persisted_user_viewport`
已证明持久化视口路径正确）。但它目前只在三处被调：View 恢复事务尾部、
`_on_resize_settled`、`set_tick_density`。**交互式范围提交（Home 的
autorange、滚轮缩放、平移、Y-Fit、Shift-wheel）没有任何一处在
native 模式下重投影**，于是 AxisItem 保留装载时枚举的 -1500..1500
明细刻度，视口一变就出现无标签区。首日 `ca844e5d/6de892f7` 修的是
「装载时二次终结」，没覆盖交互路径——这就是「优化过但没到位」的原因。

Home 后的 -4200..4800 本身是全序列数据 autorange + padding，数值上不是
bug；bug 是刻度不跟随（W1 修）。Home 在原生 View 上**应该**回到什么视口
是产品决策（见 D3）。

### R8 双游标 Custom-X full：X↑/X↓ 挤在同一行

`_custom_rows` 为每支路生成 `role="branch"` 标签行 + 指标行，但
`_block_html` 自然布局把一个 block 的全部行塞进**一个 `<tr>`**，于是
`X↑ Min Max Avg X↓ Min Max Avg` 连成一条（用户截图 2）。期望：每支路
独占一行。

### R9 双游标缺「差值」列，设置面板也没有差值开关

- 时间轴：Δ 存在但是**不可配置的常驻列**（上游规格 §5.2 把 Δ 定为
  invariant，§13 明确「No setting for Δ」——本计划推翻该条非目标）。
- Custom-X：完全没有 Δ（上游规格 §5.3 "does not invent a time delta"，
  但用户要的是**同支路上 A、B 两点的 Y 差值**，这是良定义的，不是臆造
  时间差）。
- 设置弹层只有 5 个开关，无差值项（用户截图 3）。

### R10 双游标 mini 面板显示 Avg，应显示差值

`_custom_rows` mini 优先级是 `Avg → Max → Min`（用户截图 4 显示
`X↑ Avg 545.6 N`）。时间轴 mini 已经显示 Δ，Custom-X 应一致。

### R11 设置按钮在弹层关闭后 hover 态残留

`CursorDisplayPopover` 是 `Qt.Popup`，弹出期间抓取鼠标；关闭时 Qt 不给
按钮补发 Leave 事件，QSS `:hover`（蓝框+底色）残留到鼠标再次掠过才消
（用户截图 5）。代码中无任何 `WA_UnderMouse` 清理。经典 Qt popup 坑。

### R12 窄面宽下工具栏按钮错位，且放不下的按钮不可用

- **错位**：`cards.py:_prioritize_time_controls` 在紧凑模式（<840 px）把
  分屏/叠加/游标按钮组用 `insertAction` 重排到 `pan` 锚点之前，导致这组
  控件插进导航工具中间（用户截图：`⌂ ← → | 分屏 叠加 | 游标… | ✛ 🔍 …`），
  与常规宽度下的顺序不一致。
- **不可用**：`PgNavigationToolbar` 是 QToolBar，放不下的 action 被 Qt
  收进 overflow 扩展钮（首日红测
  `test_time_card_settings_button_stays_beside_cursor_segment_and_emits_options`
  抓到的就是设置按钮在 500 px 下不可见）。
- **用户决策**：工具栏改为**横向滑动**——Windows 上空白区域按住左右拖动，
  macOS 上触摸板横向滑动；面宽不足时所有按钮保持原顺序、经滑动可达，
  不再重排。

## 2. 规格增量（对既有两份规格的修订）

1. **Δ 成为第六个偏好开关**（推翻上游规格 §13 「No setting for Δ」与
   §5.2 的 Δ-invariant）：
   - `CursorDisplayOptions` 增 `show_delta_value: bool = True`；
   - 存储键仍是 `charts/time_cursor/display_options_v1`——loader 对缺失
     字段已按默认 True 兜底，**无需换键或迁移**；
   - 弹层「双游标统计」组内新增「显示差值」，排在「显示平均值」后；
   - 六开关全关时 identity + 区间行仍在，面板永不空白（原契约保留）。
2. **值列顺序全场景统一为 `Min → Max → Avg → Δ`**（时间轴 full 现为
   Δ 在首，改为殿后；32 组合矩阵随第六位扩为 64 组合）。
3. **Custom-X 双游标 Δ 语义**：对每条被接受的支路，用与单游标相同的
   leg 内插值在 X=A 与 X=B 采样，`Δ = Y(B) − Y(A)`；任一端不在该支路
   有效范围内则该支路 Δ 显示 `—`，诊断口径不变。不引入任何时间差。
4. **布局**：Custom-X 双游标 full 每支路独占一行（header 行 + N 支路
   行）；constrained 降级与 `+N channels` 截断规则不变。
5. **mini 优先级改为 `Δ → Avg → Max → Min`**（Δ 被关掉时退回 Avg）。
   时间轴 mini 面貌不变（本就显示 Δ）。
6. **WWT 原生刻度视口跟随**：native 模式激活期间，任何**已提交**的
   视口变更（View 恢复、resize、Home、滚轮缩放、平移释放、Y-Fit、
   Shift-wheel）之后，刻度必须是原生 cadence 在**当前视口**上的投影；
   显式密度修改仍是唯一退出 native 模式的动作（既有契约不变）。
7. **图表工具栏滑动契约**：工具栏 action 的左右顺序在任何面宽下**恒定**
   （紧凑重排废除）；面宽不足时工具栏可横向滑动——空白处按住拖动
   （鼠标）与触摸板横向滚动（`QWheelEvent` 的水平 delta）两种手势；
   任何按钮在任何面宽下都保持可达且可点击，不进 QToolBar overflow
   扩展钮；滑动不得吞掉按钮点击（拖动判定需超过启动阈值）；有可滑动
   余量时给出边缘视觉暗示。紧凑密度**样式**（更窄 padding）可保留，
   但不再作为可用性的兜底手段。

## 3. 任务

### W1 原生刻度跟随交互视口（R7）

**改动**
- 在交互结算的既有 seam 上挂投影：范围提交后（Home/autorange 完成、
  缩放/平移进入 150 ms 静默窗结算、Y-Fit、Shift-wheel），若
  `native_policy_active()` 则调 `project_native_ticks()`。
- 实施约束：**不许动 150 ms idle timer 的 interval 契约与离散结算
  双计时器结构**（`TestDiscreteSettle` 钉死）；投影每次结算至多一次，
  不进 wheel 事件热路径；native 未激活时零成本早退。
- 不改 `ticks_math.py` / `native_axes.py` 的枚举算法（它们已按当前
  视口投影，改的只是调用时机）。

**owner 测试**（`tests/ui/test_wwt_native_render.py`）
- 合成 fixture 全 MainWindow：`toolbar.home()` 后 majors 以原生 cadence
  覆盖新 ylim（首/末 major 距边界 < 1 step），native 仍激活；
- `vb.scaleBy` 缩放 + 结算后同样成立；
- 非 WWT 普通 View 上 Home/缩放不触发投影（计数 mock 为零）；
- 客户样本 `SFNS_20_X04-CSER_000009.wwt` 存在时做同链路 smoke，缺失
  则 SKIP（不成为 owner 依赖）。
- 复用本轮诊断探针作为测试骨架（离屏探针脚本见本文件 §1 复现块）。

**护栏**：`test_pg_timedomain_canvas.py` 的 paint 计时器哨兵与
`TestDiscreteSettle`（证明没动静默窗）；`test_pg_canvas_backref_invariants.py`。

**真机验收**：Cocoa 前台开 SFNS_20 → Home → 截图确认全轴有标签，
证据归档 `docs/analyzer/verify/`。

**决策点 D3（可与 W1 并行拍板，不阻塞）**：原生 View 上 Home 是否
应恢复**原生初始视口**（-100..100 / -1500..1500）而非数据 autorange？
推荐恢复原生视口（Home = 初始视图，对 WWT View 初始即原生；全数据
另有 Y-Fit）。若采纳，追加一条 Home 语义测试；不采纳则 W1 已消除
无标签异常。

### C1 Custom-X 双游标支路分行（R8）

**改动**：`_block_html` 自然布局遇 `role == "branch"` 行时开新 `<tr>`；
header 行 + 每支路一行。constrained 分支已按行堆叠，不动。

**owner 测试**：custom-X 双游标 full 的 HTML `<tr>` 数 = 1(header) +
支路数；X↑ 与 X↓ 不同行；单支路径仍一行。

### C2 差值开关与 Custom-X 支路 Δ（R9）

**改动**
- `cursor_display_model.CursorDisplayOptions` 增 `show_delta_value`
  （默认 True）；`enabled_value_fields` 输出顺序改
  `Min → Max → Avg → Δ`（Δ 映射 time-X 的 `delta` 与支路的
  `delta_value` 字段）。
- `CursorDisplayBranch` 增 `delta_value: float | None`；
  `pg_canvas/cursor.py` 的 `_build_custom_x_dual_row` 对每条接受支路
  按 §2.3 采样 A/B 求 Δ（复用 followup-1 的路径缓存与 leg 插值，
  不新增第二份插值实现）。
- 时间轴 full/legacy html 的 Δ 列受开关控制；六关全关时保留
  identity + 区间。
- 弹层 `_LABELS` 增「显示差值」；hints/quickref 文案同步
  （owner：`test_hints.py` / `test_quickref.py`，改完跑
  `/update-hints` 核对）。

**owner 测试**
- 数值：`tests/test_custom_x_paths.py` 增支路 Δ 采样用例（两端在 leg
  内 / 一端出界 → `—` / 单支路径 / 非有限值）；
- 展示：64 组合矩阵更新（第六位）；Δ 关闭时 time-X 与 custom-X 均无
  Δ 列；列序 Min→Max→Avg→Δ 全场景一致断言；
- 持久化：旧 5 字段 JSON 载入后 `show_delta_value` 为 True（兼容性）。

**护栏**：`test_signal_no_gui_import.py`（若 Δ 采样工具进 `signal/`）。

### C3 mini 优先级 Δ 优先（R10）

**改动**：mini 优先级 `Δ → Avg → Max → Min`；time-X mini 不变。

**owner 测试**：custom-X mini 默认显示 `X↑ Δ …`；关掉 Δ 后退回 Avg；
tooltip 仍含全部启用指标。

### C4 设置按钮 hover 残留清理（R11）

**改动**：弹层隐藏回调（`cards.py` 的
`_on_cursor_display_popover_visibility_changed(None)` 分支）里，若鼠标
当前不在按钮矩形内（`QCursor.pos()` 映射判断），清 `WA_UnderMouse` +
unpolish/polish + `update()`。不引入计时器，不改按钮为 checkable。

**owner 测试**：offscreen 模拟开→关弹层（光标不在按钮上），断言
`WA_UnderMouse` 已清；真机顺手在 W1 截图时目验一次（无需单独证据）。

### C6 工具栏横向滑动，废除紧凑重排（R12）

**改动**
- 给 `PgNavigationToolbar` 加横向滑动宿主：工具栏按自然 sizeHint 完整
  排布，外层视口裁剪（建议 QScrollArea 隐藏滚动条，或等价的偏移绘制
  容器）；QToolBar overflow 扩展钮不再出现（所有 action 始终实排）。
- 手势：视口上实现「空白处按下 + 位移超阈值（建议 8 px）→ 拖动滚动，
  未超阈值 → 正常透传点击」；`wheelEvent` 消费水平 delta
  （`pixelDelta().x()` 优先，退回 `angleDelta().x()`，macOS 触摸板
  横滑天然产生）。垂直滚轮不劫持。
- 删除 `cards.py:_prioritize_time_controls` 的 action 重排（错位根因），
  `_sync_responsive_toolbar` 只保留紧凑密度样式（`timeControlDensity`
  属性与按钮宽度收紧可留）。action 顺序自此与常规宽度恒等。
- 有可滑余量时的边缘暗示（左右渐隐或细箭头，QSS/paint 皆可，从简）。
- 兼容 seam：`detach_toolbar`（分屏次卡）、`_find_action`、
  `_insert_right_toolbar_widget`、`toolbar.actions()` 顺序契约、MDI 图标
  与中文标签替换全部保持；新接线不用 lambda（棘轮）。
- 交互新增 → 同步 `ui/hints.py` 与 `ui/quickref.py`（窄窗口滑动查看
  更多工具），实施后跑 `/update-hints` 核对。

**owner 测试**
- followup-1 的 F1 红测
  `test_time_card_settings_button_stays_beside_cursor_segment_and_emits_options`
  归本任务，转绿且**不放宽断言**（followup-1 计划的 T4「修重排」方案
  由本任务取代，见该计划标注）。
- 顺序恒定：500 px 与 1200 px 下 `toolbar.actions()` 顺序一致（错位
  防复发）。
- 可达性：500 px 下设置按钮经程序化滚动进入视口后 `isVisible()` 且
  可点击（`qtbot.mouseClick` 触发 `options_changed`）。
- 手势判定：位移 < 阈值的按压透传为按钮点击；> 阈值为滚动且不触发
  点击；水平 wheel 改变滚动偏移，垂直 wheel 不改。
- 无 overflow：窄宽下 `QToolBar` extension 按钮不可见。
- 回归：`tests/ui/test_chart_stack.py` 工具栏簇、`test_hints.py`、
  `test_quickref.py`。

**护栏**：`test_no_lambda_signal_connections.py`；真机（Cocoa 前台）
窄窗口触摸板横滑目验一次，随 W1 证据一并归档。

### C5 收尾

- 全部 Task 合入后跑一遍护栏组：backref invariants · import boundaries ·
  state ownership · lambda 棘轮 · QSS lint · paint 哨兵。
- `git diff --check`；未决标记扫描。
- 在本文件补「实施结果」：测试计数 + 快照 HEAD + 真机证据路径。
  **不得把 partial 结果记成全绿**（首日教训：验证记录声称全绿但
  HEAD 有红测）。

## 4. 停止条件

- W1 若发现 `project_native_ticks()` 在交互结算点调用后仍不覆盖新视口
  （即枚举器并非按当前范围投影），停：那推翻本诊断，需回到
  `native_axes.py` 层重新定位，先改 2026-08-30 规格再动算法。
- C2 若 Custom-X 支路 Δ 需要在 A、B 落在**不同支路**时跨支路求差，停：
  那是新的产品语义，先补规格。
- 任何 Task 需要放宽既有护栏（值列顺序除外——它由本计划 §2.2 显式修订）
  即停。

## 5. 实施结果

**快照**：`HEAD=a36ef529`（`fix(ui): land cursor-display followup contracts`）。
followup-2 代码在工作区未提交。跑 C5 时相关实现文件未被并行会话改写。

**停止条件**：未触发。W1 投影后 majors 覆盖新 ylim；C2 Δ 仅同支路
`Y(B)−Y(A)`，无跨支路求差；未放宽既有护栏。

**D3**：采纳推荐。原生 View 上 Home 的 Y 回到
`native_tick_policy['y'][axis_id]` 的 lo/hi，不是数据 autorange；Y-Fit
仍全数据。

| Task | 离屏结果 | 真机 |
| --- | --- | --- |
| W1 原生刻度跟随 + D3 Home Y | owner `test_wwt_native_render.py` 簇绿；paint 哨兵 + `TestDiscreteSettle` + backref 绿 | **未跑**。待 Cocoa 开 SFNS_20 → Home → 截图归档 `docs/analyzer/verify/` |
| C1 支路分行 | custom-X dual full `<tr>` = header + 支路数 | n/a |
| C2 差值开关 + 支路 Δ | 64 组合、列序 Min→Max→Avg→Δ、旧 5 字段 JSON 载入 `show_delta_value=True`；`test_signal_no_gui_import.py` 绿 | n/a |
| C3 mini Δ 优先 | 默认 `X↑ Δ`；关 Δ 退 Avg | n/a |
| C4 hover 残留 | offscreen：弹层关且光标不在按钮上时 `WA_UnderMouse` 已清 | **未跑**。计划允许随 W1 截图顺手目验 |
| C6 工具栏横滑 | F1 设置按钮窄宽可点；500/1200 action 顺序恒等；无 overflow 扩展钮；位移阈值 + 水平 wheel 绿；hints/quickref 绿 | **未跑**。待 Cocoa 窄窗口触摸板横滑目验，随 W1 证据归档 |
| C5 收尾 | 见下方计数；`git diff --check` 通过；未决 TODO 扫描无本轮残留 | — |

C1–C3 合跑 251 passed；C4 合跑 152 passed；W1 合跑 71 passed；C6 owner
22 passed。C5 护栏组与 `tests/ui/test_chart_stack.py` + hints/quickref
合跑 **245 passed**（`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.
.venv/bin/python -m pytest`，约 39 s）：

- `tests/ui/test_chart_stack.py`
- `tests/ui/test_pg_canvas_backref_invariants.py`
- `tests/ui/test_import_boundaries.py`
- `tests/ui/test_main_window_state_ownership.py`
- `tests/ui/test_no_lambda_signal_connections.py`
- `tests/ui_kit/test_qss_border_shorthand.py`
- `tests/ui/test_pg_timedomain_canvas.py::TestAaBackstopLatch::test_frame_paint_backstop_is_installed_on_real_canvas`
- `tests/test_signal_no_gui_import.py`
- `tests/ui/test_hints.py`
- `tests/ui/test_quickref.py`

**不得记成全绿**：W1 / C4 / C6 的 Cocoa 前台证据未采集。offscreen 不能
代替真机渲染或触摸板横滑。
