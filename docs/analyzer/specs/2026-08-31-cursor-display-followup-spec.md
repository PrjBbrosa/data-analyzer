# 游标显示修复与关闭全清会话重置规格

- 日期：2026-08-31
- 状态：已实施（offscreen 契约绿；T3/T6 Cocoa 真机未验）
- 基线：`main@a9667968`（今日 `codex/cursor-display-settings` 分支合入后）
- 上游规格：[`2026-08-31-cursor-display-settings-spec.md`](2026-08-31-cursor-display-settings-spec.md)
- 实施计划：[`../plans/2026-08-31-cursor-display-followup-plan.md`](../plans/2026-08-31-cursor-display-followup-plan.md)

## 1. 背景：合入后 review 结论

今日合入的游标显示设置功能（13 个提交，约 +4600 行）经实机使用与代码
review，确认了六个用户可见缺陷与若干结构/性能问题。本规格约束修复方案；
问题编号在实施计划中一一对应。

### 1.1 用户报告的缺陷（均已定位根因）

| # | 现象 | 根因（文件与机制） |
|---|---|---|
| R1 | 结果面板每个通道名前多了 `f0 /` 前缀 | `pg_canvas/cursor.py` 与 `chart_stack/stack.py` 各有一份 `_cursor_identity_labels`，把 composite key 解析出的 **内部 fid**（`_project_io_mixin.py:437` 的 `f"f{self._fc}"`）直接当 `source_label` 显示。identity 键泄漏为显示标签，方向性违反「Display labels are never identity keys」契约 |
| R2 | 单游标按 `−` 无反应 | `cursor_display._time_rows` / `_custom_rows` 在 `cursor_mode == "single"` 时 mini 与 full 投影**逐字节相同**（含通道 header）。按钮字形翻转但内容不变。旧行为：mini 折叠为「彩点 + 数值」单行 |
| R3 | 双游标 mini（`−` 收起后）每通道占两行 | `_block_html` 把限定名 header 独占一行，Δ 值另起一行。旧 mini 是「● 名称 △值」单行 |
| R4 | 结果面板信息密度回退、观感变化大 | 单游标 full 由旧的「名称=值」单行变为「header 行 + `Value` 行」两行；叠加 R1 的 `f0 /` 前缀 |
| R5 | 游标设置弹层透明度过高、看穿到网格线 | `CursorDisplayPopover` 设了 `WA_TranslucentBackground` 却没有 `paintEvent` 兜底，QSS `#cursorDisplayPopover { background:#fff }` 被 Qt 跳过 → 底板全透明。CLAUDE.md Gotchas 明确记录过该坑（`CursorPill` 自己就是用 `paintEvent` 兜底的正例） |
| R6 | （遗留）关闭全部文件后 View 不清、横坐标不回自动，下次打开新文件默认不是时间轴 | `_validate_custom_xaxis_source` 对 `PER_SOURCE_NAME` 解析器无条件保活（设计意图是跨文件加载存续）；`_remove_file_from_all_time_views` 只过滤通道引用不收敛空 View；不存在「最后一个来源关闭 → 会话复位」的事务 |

### 1.2 系统性 review 的补充发现

| # | 问题 | 证据 |
|---|---|---|
| F1 | **HEAD 上有红测**：`tests/ui/test_cursor_display_settings.py::test_time_card_settings_button_stays_beside_cursor_segment_and_emits_options` 在 500 px 紧凑工具栏下 `button.isVisible()` 为 False（本机 offscreen 复现）。合入前验证记录（实施计划「实施结果」节）声称该组全绿 | 本机 `a9667968` 复跑：1 failed, 106 passed |
| F2 | **单/双游标双管线双写**：每次鼠标移动，legacy 路径（`cursor_info`→格式化→`set_single_detail_html`→adjustSize）与投影路径（`single_cursor_rows`→`build_cursor_presentation`→`reflow_to_parent`，constrained 时最坏 O(N 通道) 次 setText+layout activate）**各跑一遍**；双游标同理（`dual_cursor_info` html + `dual_cursor_rows` 投影） | `stack.py` `_on_cursor_info` / `_on_dual_cursor_info` 与 `_refresh_cursor_projection` 并存 |
| F3 | **Custom-X 单游标热路径 O(n) 纯 Python**：`sample_custom_x_cursor` 每次移动、每条通道都全量重跑 `analyze_custom_x_paths`（`_raw_legs` 逐样本 Python 循环）+ `_sample_path_contribution` 逐段 Python 线性插值。500k 点级通道会把光标拖动拖垮 | `signal/custom_x_paths.py:163-199, 343-366` |
| F4 | **ui 内部分层反向**：`pg_canvas/cursor.py` 函数体内 import `chart_stack.cursor_display` 的 DTO（`CursorDisplayOptions/Branch/Channel`）。lazy import 不触发 import 门禁，但画布协作者依赖图表卡片包是方向反了 | `cursor.py` `set_cursor_display_options` / `_emit_single_cursor_html` |
| F5 | 杂项：`_cursor_identity_labels` 在两个文件重复实现；`cursor_display._tooltip` 用 `label.startswith("X")` 识别分支（漏 `全程`）；popover `_deferred_refit` 强制 `min height 248` 在 note 隐藏时留白；`ChartStack.closeEvent` 是子 widget 上的死代码；custom-X 单游标 X 值固定 `:.1f` 精度；`_emit_single_cursor_html` 的 plain-dict fallback 路径 hidden 集合键域混用 | 各处见实施计划 T8 |

今日合入中**确认良性**、本规格不动的部分：`signal/custom_x_paths.py` 的
数值契约与测试矩阵、双游标极值 marker 的形状/复合键过滤/开关即时性、
WWT 轴 `defer_axis_finalize` 单次结算链（view-restore 事务尾部
`set_tick_density` + `settle_view_restore` 补齐，闭环成立）、
`_hidden_channel_names` 改用复合键、`_run_marker_cleanup` 收窄异常。

## 2. 目标与非目标

**目标**：修复 R1–R6 全部用户可见缺陷；消除 F1 红测；把游标热路径收敛到
单管线（F2）并给 Custom-X 单游标建立缓存（F3）；DTO 归位（F4）；清理 F5。

**非目标**：不改五个偏好开关的语义、存储键与全局同步机制；不改双游标
区间统计口径与 Custom-X 升/回程分类算法；不改 FFT/FRF/预览/批处理游标；
不引入新的 MainWindow 状态；不动项目文件 schema（R6 的会话复位是**运行时
行为**，不涉及持久化格式）。

## 3. 设计契约

### 3.1 来源标签契约（R1）

- 任何用户可见文本（结果面板、tooltip、诊断）**不得出现内部 fid**
  （`f0`/`f1`…）。fid 只作 identity 键。
- `source_label` 解析顺序为单点函数（放 `chart_stack` 一处，画布与
  stack 共用，消除现有两份重复）：
  1. 显示名自带 `[short_name]` 前缀 → 用该前缀内容（与图例/通道树一致）；
  2. 否则经调用方注入的 `fid → short_name` 解析器查 `files[fid].short_name`；
  3. 都拿不到 → 空字符串（只显示通道名）。
- **单来源工作区不显示来源前缀**：当前画布参与游标结果的来源数 ≤ 1 时，
  visible face 只出通道名；tooltip 仍带完整限定名（重名可分辨性契约不变，
  它只在 ≥2 来源时才有意义）。
- 解析器不得反向把显示名当键查数据（保持复合键语义，`_ChannelKeyDict`
  契约不变）。

### 3.2 投影密度契约（R2/R3/R4）

对齐旧版信息密度，mini 必须是 full 的**真收缩**：

| 场景 | full（自然布局） | mini |
|---|---|---|
| 单游标 · 时间轴 | 每通道一行：`名称 值`（名称承载通道色；不再有独立 `Value` 标签行） | 每通道一行：`● 值` |
| 单游标 · Custom-X | 每通道一行：`名称 X↑ 值 X↓ 值`（单支路径只出已知方向） | 每通道一行：`● X↑ 值 X↓ 值` |
| 双游标 · 时间轴 | header 行 + 一行启用的 `Min/Max/Avg` + `Δ`（现状保留） | 每通道一行：`● 名称 △值` |
| 双游标 · Custom-X | header 行 + 每支路一行（现状保留） | 每通道一行：`● 名称` + 每支路 `方向 优先级指标值` 内联；放不下才允许支路换行 |

- mini 与 full 的投影在每个 `(cursor_mode, x_mode)` 组合下**必须可区分**
  （新增契约测试：对同一输入，mini 与 full 的 HTML 不得相同，除非
  blocks 为空）。这是 R2 的机械护栏。
- constrained 降级布局与 `+N channels` 截断规则不变（上游规格 §6）。
- mini 丢掉的名称/指标继续全量进 tooltip（上游规格 §5.4 不变）。

### 3.3 弹层渲染契约（R5）

- `CursorDisplayPopover` 保留 `WA_TranslucentBackground`（Popup 顶层圆角
  需要），但必须补 `paintEvent` 画不透明底板 + 边框（对齐 `CursorPill`
  的 `_CURSOR_PILL_BG` 手法；底板 alpha ≥ 245，不追随 pill 的 235）。
- QSS 中 `#cursorDisplayPopover` 的背景声明保留作为非透明平台的兜底，
  但**验收不得只看 QSS token**：必须有真机（macOS Cocoa 前台）截图证据，
  offscreen 只能当排版草稿——这是仓库 Gotchas 的既有要求。

### 3.4 紧凑工具栏契约（F1）

- 游标设置按钮在紧凑（<840 px）与常规两种密度下都必须可见、可点击，
  不允许掉进 QToolBar overflow 扩展钮。
- 现有红测 `test_time_card_settings_button_stays_beside_cursor_segment_and_emits_options`
  是该契约的 owner 测试：**修代码使其变绿，不得放宽断言**。
- `_prioritize_time_controls` 的 action 重排必须是幂等的（反复跨越 840 px
  阈值不累积顺序漂移），补一条来回 resize 的幂等测试。

### 3.5 单管线渲染契约（F2）

- live 画布的单/双游标结果**只经结构化投影管线渲染一次**：
  `single_cursor_rows` / `dual_cursor_rows` → `build_cursor_presentation`
  → `set_display_projection`。
- legacy `cursor_info` / `dual_cursor_info` 字符串信号**保留发射**（兼容
  seam、测试与外部消费者不动），但 `ChartStack` 对 live 画布来源不再用
  它们驱动 detail 渲染；单游标的 primary 行（`t=…` / `A/B/ΔT`）继续取自
  `cursor_info` 首段。无 rows 信号的兼容调用方路径保留现有 fallback。
- 该契约的量化收益：单游标拖动每 move 的 pill 布局遍数从 2+ 收敛到 1；
  以 owner 测试锁定「一次 move 只触发一次 `set_display_projection` 且不
  触发 `set_single_detail_html`」。

### 3.6 Custom-X 单游标性能契约（F3）

- 路径分析结果按 `(data_id, channel)` + 数据版本缓存于画布游标协作者
  （不进 `signal/`；`signal/` 保持无状态纯函数）。缓存失效随既有
  envelope/monotonicity 缓存失效点走（数据重载、range filter 变化、
  文件关闭）。
- `_sample_path_contribution` 改为在**单调 leg 内**用 `np.searchsorted`
  插值（leg 方向已知，降序先翻转），移除逐段 Python 循环；语义与现实现
  逐点等价（既有数值测试全保留，作为等价性护栏）。
- `analyze_custom_x_paths` 的 `_raw_legs` 逐样本循环本轮**不改写**（它在
  dual 路径也在用且有完整测试矩阵；缓存已把它移出每 move 热路径）。若
  后续真机测量仍超预算，另立性能 spec。
- 门槛：500k 点 × 4 通道 Custom-X 单游标拖动，缓存命中路径每 move 的
  取值成本 ≤ 5 ms（真机标定，offscreen 只做数量级冒烟）。

### 3.7 DTO 归位契约（F4，随 T5 顺带）

- `CursorDisplayOptions` / `CursorDisplayBranch` / `CursorDisplayChannel`
  等**无 Qt 依赖的数据类**迁至中立模块（建议
  `mf4_analyzer/ui/cursor_display_model.py`），`chart_stack/cursor_display.py`
  保留 re-export（兼容既有 import 与测试 monkeypatch 缝）。
- `pg_canvas/` 只 import 中立模块，消除画布→图表卡片包的反向依赖；
  popover/渲染函数留在 `chart_stack`。

### 3.8 关闭全清会话复位契约（R6）

- **触发条件**：交互式关闭使最后一个逻辑来源被 purge（`self.files` 变空）。
  项目加载/恢复过程中的中间清空**不触发**（以 `_applying_view` /项目恢复
  in-progress 标志防重入，实施时确认现有守卫字段）。
- **复位事务**（单点实现，建议挂在 `_present_after_sources_closed` 的
  files-empty 分支，保持「批量关闭一次收尾」的既有结构）：
  1. 时域与四个分析分区的 View manager 重置为各自的单个默认空 View
     （View 绑定的是 `(fid, channel)`，来源全关后所有 View 均已无意义）；
  2. `self._custom_xaxis.clear()` + Inspector 横坐标回 `time`（自动）模式、
     标签清空——`PER_SOURCE_NAME` 的跨文件保活设计**仅在仍有文件时**成立，
     工作区清空即失效；
  3. 时间范围（使用选定时间范围勾选与起止值）与滤波开关回默认；
  4. 游标 pill/弹层清理走现有 `clear_cursor_pill` 路径（全局五开关偏好
     **不**复位，上游规格 §3 的应用级偏好语义不变）。
- 复位后打开新文件的首个绘图必须是时间轴自动排序（用户报告的验收场景）。
- 显式排除：不清 QSettings、不清最近文件、不清配置预设。

## 4. 错误处理与守卫

- 全部修复不得引入宽泛 `except Exception`；popover paintEvent 无兜底
  异常（编程错误直接传播）。
- 复位事务中任一步失败按既有错误分类走：基础设施失败留 log，用户可见
  状态不得半清（事务内先算后设，避免中途异常留下混合状态）。
- 既有护栏全部维持：backref `_owned_names/_delegate_names` 声明、状态
  所有权棘轮（复位事务不得新增跨文件 `MainWindow` 裸写；新增状态进
  `_state_holders` 具名 holder）、`.connect(lambda` 棘轮只降不升、QSS
  border 简写 lint。

## 5. 验收标准

1. R1–R5：offscreen 契约测试全绿 + macOS 前台截图证据（单游标 full/mini、
   双游标 full/mini、弹层展开）确认无 `f0` 前缀、mini/full 可区分、单行
   密度恢复、弹层不透明。
2. R6：聚焦测试覆盖「开两文件→设 Custom-X→全关→查 View 数/横坐标模式
   →再开文件→默认时间轴」全链；项目恢复路径回归不触发复位。
3. F1：现有红测变绿 + 紧凑/常规往返幂等测试。
4. F2：单 move 单投影的计数断言测试。
5. F3：缓存命中/失效单元测试 + 数值等价性测试全绿；真机拖动标定记录
   进 `docs/analyzer/verify/`。
6. 边界门禁：`test_import_boundaries` · `test_signal_no_gui_import` ·
   `test_pg_canvas_backref_invariants` · `test_main_window_state_ownership` ·
   `test_no_lambda_signal_connections` · `test_qss_border_shorthand` ·
   paint 计时器哨兵，全绿。
7. `git diff --check` 干净；`ui/hints.py` 与 `ui/quickref.py` 若交互文案
   受 T2 影响需同步（预期只有 mini 行为描述微调）。

## 6. 决策点（实施前需用户确认或实施者按推荐执行）

- **D1 单来源省略前缀**（§3.1）：推荐省略；若用户希望始终显示文件名，
  改为始终用 `short_name` 前缀，其余契约不变。
- **D2 复位范围**（§3.8）：推荐时域+分析分区 View 全复位；若用户希望
  保留分析分区参数骨架，缩小到时域 View + 横坐标 + 时间范围。
