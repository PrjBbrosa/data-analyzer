# WWT 时域绘图与 UltraView 自动排版优化计划

- 日期：2026-08-29
- 状态：已合入父分支（聚焦门禁已过；全量 pytest 与 macOS 前台仍 UNVERIFIED）
- 当前基线：`feat/wwt-timedomain-plot-ultraview-reflow` @ `7e16e6b9`（T1–T4 已合入）
- 分支：`feat/wwt-timedomain-plot-ultraview-reflow`
- 并行任务分支由隔离 worktree 落地后合并回本分支
- 对应产品结论：本计划处理当前确认的 4 项时域/排版问题。
  另一份未跟踪计划
  [`2026-08-29-wwt-and-analysis-view-state-optimization-plan.md`](2026-08-29-wwt-and-analysis-view-state-optimization-plan.md)
  覆盖 Analysis viewport 与辅助线可见性，**不是本轮范围**。
  其中 UltraView「重叠进未放置」的旧验收被本计划显式覆盖：U‑Can 7 窗应全部 placed。

> 不改 ViewState 持久化 schema，不改复合 source/channel identity。
> 不覆盖当前工作区内无关 dirty/untracked 文件。
> 核心测试只用已提交的 synthetic WWT fixture；真实 `testdoc/` 只作存在时运行的 optional smoke。

## 0. 结论摘要

当前 4 个问题已定位到不同层级：

- **UltraView 排版**：当前先按 WWT 绝对坐标映射，再逐卡缩放但固定原点；卡片缩小后不会整体回流，所以保留大量空洞。U‑Can 的 View 6/7 原始矩形完全重叠，现逻辑还会把 View 7 放进未放置区。
- **多坐标轴堆叠**：没有绕过之前的共轴渲染路径；问题发生在上游轴分组。NLTNP 中 `deg/s` 与 `°/s` 被当作不同单位，最终生成 3 个轴槽而不是 2 个。
- **U‑Can View 6/7 空图**：两窗均为有效的 record-only XY 数据，长度和有限值正常；但两者 `checked=[]`，`_plot_time_on_canvas()` 在解析 `curve_bindings` 前就按“Navigator 无勾选”提前清空画布。
- **YP 初始坐标错误**：测量线与红色公差线共用一个轴。恢复时先应用测量线的 `0..0.2`，随后又把缺少独立保存范围的公差线单独 fit 到约 `0.0944..0.1064`，覆盖整个共享轴；右键 Fit 走的是“按轴内全部曲线求并集”，所以能恢复。

现有相关测试为 `75 passed`，但没有覆盖以上端到端组合。

## 1. 实施改动

### 1. 修复 record-only View 的绘图入口

- 在普通 Navigator“无勾选”判断前解析当前 View 的 `curve_bindings`。
- “无可绘制内容”的条件改为：既没有可见 Navigator 通道，也没有成功解析的 record-only 曲线。
- channel-backed binding 继续服从 Navigator 勾选；不能因本次调整重新显示用户已取消勾选的普通通道。
- record-only 解析失败继续进入现有结构化诊断，不允许静默回退成普通 Time-Y。
- U‑Can View 6/7 即使 `checked=[]`，也必须创建有效 PlotDataItem 并完成 X/Y 恢复。

**Owner 文件**

- `mf4_analyzer/ui/main_window/window.py`（仅 `_plot_time_on_canvas` 早退条件）
- `tests/ui/test_time_curve_bindings.py` 或新增 `tests/ui/test_wwt_record_only_plot.py`
- 必要时 `tests/ui/test_wwt_native_render.py` 的绘图入口用例（不要改 Y 恢复断言）

### 2. 将 Y 恢复从“逐通道”改为“逐轴槽”

保留 `restore_visible_ylims(ylims)` 兼容调用，并增加可选参数：

```python
restore_visible_ylims(ylims, *, native_axis_ranges=None)
```

每个共享 handle 只设置一次 Y 范围，优先级固定为：

1. 该 handle 任一成员已有持久化范围；多个旧范围不一致时取有限并集；
2. WWT `native_ticks["y"][axis_id].lo/hi`；
3. 当前可见 X 内，该 handle 所有可见曲线的原始数据并集；
4. 当前 X 无样本时才退回该 handle 的全量有限数据。

同时：

- 不再对共享 handle 中“缺少独立 ylim 的成员”逐条 fit，避免后一个成员覆盖前一个成员。
- 没有 `ylims` 的 record-only 轴也必须完成一次数据 fit，不能停留在 `0..1` placeholder。
- 保持恢复顺序为 X → 按轴恢复 Y → native ticks → `settle_view_restore()`，仍只 settle 一次。
- YP 首次打开应保持 WWT 的 `0..0.2` 轴范围并同时显示蓝色测量线和红色公差线；右键 Fit 仍可进一步缩到实际数据范围。

独立 handle 上“新勾选且无保存 ylim”的现有行为必须保留
（`test_restore_visible_ylims_fits_new_overlay_channel_to_visible_x`）。

**Owner 文件**

- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/main_window/_view_mixin.py`（`restore_visible_ylims` 调用处传入 `native_axis_ranges`）
- `tests/ui/test_pg_timedomain_canvas.py`
- 必要时 `tests/ui/test_wwt_native_render.py` 的共享轴范围用例
- fixture：`tests/_helpers/wwt_factory.py` 的 `shared_axis_evaluation_before_owner`

### 3. 修复 WWT 共轴识别

- 在 WWT 轴兼容判断中增加小范围、显式的单位规范化：`°` 与 `deg` 等价，因而 `°/s` 与 `deg/s` 等价；保留原始单位文本用于显示。
- 只有规范化单位、量程、主刻度和网格刻度均兼容时才共轴；不同物理单位或不同量程仍保持独立轴。
- NLTNP 的 `y_speed [deg/s]` 与 `Steering speed [°/s]` 应归入同一个轴槽；最终只显示扭矩轴和转速轴。
- 不修改通用 pyqtgraph 共轴算法；本问题是 WWT `axis_id` 规划错误，不是旧优化路径被绕过。
- 不要把全局 `db_reference.normalize_unit` 扩成任意同义词匹配。

**Owner 文件**

- `mf4_analyzer/ui/wwt_view_import.py`（`_norm_unit` / `_compatible_axis`）
- `tests/ui/test_wwt_view_import.py`
- 必要时新增 synthetic fixture 到 `tests/_helpers/wwt_factory.py`

### 4. UltraView 改为“保留拓扑、紧凑回流”

- WWT 原始矩形只用于确定行列关系、顺序和宽窄等级，不再保留原始空白距离。
- 同一行相邻卡片统一为一个网格 gutter；行间同样压缩为一个标准间距。
- 宽窗/窄窗比例继续保留，例如 U‑Can 前两张宽窗与其余窄窗保持约 `2:1`，但不保留截图中的大面积空洞。
- preview 到达后不再逐卡固定原点缩放；对本次导入的整组卡片重新计算 span 并整体回流。尚无 preview 的卡片用 WWT 矩形宽高比作为临时值。
- 完全重叠的 View 不再直接进入未放置区：按源顺序将后一个 View 移到最近合法位置，并保留 `exact_overlap_relocated` 诊断。
- U‑Can 的 7 个 View 默认全部放入专属 Board；只有矩形无效、Board/卡片容量耗尽或确实无合法位置时才进入未放置区。
- 整次导入、preview fit 和最终回流仍合并为一个 Undo 操作；用户在自动回流前手动移动卡片时，取消该组后续自动调整。

当前 `_register_pending_native_card_fits` / `_apply_one_pending_auto_aspect` 仍是逐卡固定原点缩放，需要改成整组回流。

**Owner 文件**

- `mf4_analyzer/ultraview_core/native_layout.py`
- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- 必要时 `mf4_analyzer/ultraview_core/board_ops.py`、`mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/ui/test_ultraview_native_layout.py`
- `tests/ui/test_wwt_board_projection.py`

现有断言 `plan.unplaced == (refs[6],)` 与
`test_exact_overlap_still_unplaced_on_dedicated_board` 必须改成新语义，
不得为迁就旧测试保留“重叠进托盘”。

## 2. 测试与验收

### 自动化红测

- synthetic record-only-only View：Navigator 无勾选仍绘制；channel-backed 未勾选仍隐藏。
- U‑Can View 6/7：binding 无 issue，切换后 PlotDataItem 非空，Y 不停留在 placeholder。
- YP 共享轴：恢复后两条曲线均有数据，共享 handle 为 `0..0.2`；缺 ylim 的公差线不得覆盖该范围。
- 空 `ylims` 多轴 View：每个 handle 按各自数据并集 fit。
- NLTNP 单位别名：`deg/s` 与 `°/s` 共轴，最终轴槽数为 2。
- U‑Can 原生矩形：7 张全部 placed、无碰撞、间距紧凑、重叠 View 被迁移、一次 Undo 清空整组。
- 核心测试使用已提交的 synthetic WWT fixture；真实 `testdoc/` 只作为存在时运行的客户样本 smoke。

### 聚焦门禁

运行 WWT proposal/binding、TimeDomain canvas、MainWindow import、UltraView native layout/Board projection，以及：

- `tests/ui/test_pg_canvas_backref_invariants.py`
- `tests/ui/test_main_window_state_ownership.py`
- `tests/ui/test_no_lambda_signal_connections.py`

稳定集成后由一个协调者运行一次完整测试套件，避免并行 full pytest。

### 前台验收

- U‑Can：7 个时域 View；View 6/7 首次切入即有曲线；UltraView 7 张卡均可见、无大空洞、无重叠。
- YP：首次打开即同时显示蓝色测量线和红色公差线；切换 View 后范围不漂移；无需先右键 Fit。
- NLTNP：速度辅助线与速度测量线共轴，不再出现重复速度轴堆叠。
- 多 WWT 仍各自进入独立且正确命名的 Board；WinWert 曲线颜色与 View tab 颜色保持现有语义。

## 3. 实施假设

- 自动排版采用“保留 WWT 行列拓扑和宽窄关系、压缩空白”的策略，不追求毫米级绝对位置复刻。
- WWT 原生有效 Y 范围优先于首次数据 auto-fit；用户之后的手动缩放/Fit 和持久化范围优先级更高。
- 不改 ViewState 持久化 schema，不改复合 source/channel identity，不覆盖当前工作区内无关的 dirty/untracked 文件。

## 4. 并行落地

| Task | 隔离分支意图 | 允许改的主文件 |
| --- | --- | --- |
| T1 绘图入口 | `feat/wwt-reflow-t1-plot-entry` | `window.py` 早退 + record-only 绘图测试 |
| T2 逐轴 Y 恢复 | `feat/wwt-reflow-t2-axis-ylim` | `canvas.py`、`_view_mixin.py`、Y 恢复测试 |
| T3 共轴单位 | `feat/wwt-reflow-t3-unit-alias` | `wwt_view_import.py`、proposal 测试 |
| T4 紧凑回流 | `feat/wwt-reflow-t4-ultraview` | `native_layout.py`、workspace controller、layout 测试 |

合并顺序：T3 → T1 → T2 → T4，最后在父分支跑聚焦门禁。全量 suite 只由协调者在稳定快照上跑一次。

## 5. 停止条件

1. record-only 绘图需要伪造采样率、时间轴、工程单位或 Navigator identity。
2. Y 恢复必须扩大 `test_main_window_state_ownership.py` 白名单。
3. 共轴修复需要改通用 pyqtgraph 共轴算法，而不是 WWT `axis_id` 规划。
4. UltraView 必须改 ViewState schema 或破坏 dedicated Board 命名。
5. 核心测试必须依赖本机 `testdoc/` 才可通过。
6. 同一 checkout 已有全量 pytest 在跑。
