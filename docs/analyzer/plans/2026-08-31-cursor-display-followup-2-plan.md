# 游标显示 Follow-up 2 + WWT 原生刻度视口跟随实施计划

- 日期：2026-08-31（晚）
- 状态：实施中
- 基线：`main@a9667968` + 工作区中**未提交**的 followup-1 实现
  （`cursor_display_model.py` 中立 DTO、fid 泄漏修复、mini/full 密度、
  弹层 paintEvent、单管线、custom-X 缓存、关闭全清复位；聚焦测试本机
  170 passed）。**本计划开工前先把 followup-1 审查合入**，不要在双份
  未提交改动上叠加。
- 上游文档：[`2026-08-31-cursor-display-followup-spec.md`](../specs/2026-08-31-cursor-display-followup-spec.md) ·
  [`2026-08-31-cursor-display-settings-spec.md`](../specs/2026-08-31-cursor-display-settings-spec.md) ·
  [`2026-08-31-wwt-single-owner-axis-finalization-plan.md`](2026-08-31-wwt-single-owner-axis-finalization-plan.md)
- 验证范围声明：各 Task 只跑自己的 owner 聚焦用例 + 所列护栏，不安排
  全量。真机（Cocoa 前台）证据仅 W1（WWT 截图）与 C4（hover 状态）需要。

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
