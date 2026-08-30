# UltraView Smart Layout 固定点与 Fit 隔离专项优化计划

- 日期：2026-08-30
- 状态：IN PROGRESS（Slice A–D 已落地；Integration/Foreground 待跑 artifacts 与实机）
- 类型：问题复盘后的 follow-up 实施
- 当前观察基线：`feat/ultraview-smart-layout-fixed-point` @ `253ba972c207f0c8e70896a9ef0e9c1ab168b9d5`
- 上游规格：
  [`2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md`](../specs/2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md)
- 上游计划：
  [`2026-08-30-ultraview-adaptive-smart-layout-and-fit-plan.md`](2026-08-30-ultraview-adaptive-smart-layout-and-fit-plan.md)
- 适用症状：WWT Board 首次打开为一套卡片几何，再点“适应内容”或“智能排版”后，多张卡同时变窄并留下大横向空洞

## 0. 实施结论

本问题不是继续微调 `6×6`、候选数量或某个空白权重就能稳定解决。当前实现缺少三个系统合同：

1. **动作隔离**：Board Fit 必须是纯相机操作，任何 preview、recapture 或 pending settle 都不能借它的点击时机修改 `GridRect`；
2. **跨入口同源**：WWT 首次布局、后台 settle、手动 Smart Layout 必须冻结同一种语义 facts 和同一份 policy，不能分别用“原始 WWT 拓扑”与“当前绝对网格坐标”描述同一张 Board；
3. **固定点**：布局第一次被接受后，在 facts/policy/viewport/aspect 没变时，再次运行 Smart Layout 必须是严格 no-op；Card Fit 也不得再发现可造成明显跳变的局部收紧空间。

本 follow-up 的产品方向固定为：

```text
WWT/source facts + frozen logical aspects + frozen policy
  → canonical SmartLayoutInputSnapshot
  → span candidates（含 Card Fit hug 候选）
  → topology-preserving compact pack
  → fixed-point validation
  → 一次 geometry transaction
  → 一次 camera fit

后到 preview / recapture
  → 只更新图像与质量状态
  → 不再自动修改 geometry
```

## 1. 已确认事实与证据边界

### 1.1 截图事实

用户提供的打开前后截图显示：

- 缩放标签均约为 `75%`；
- 多张卡片左上起点与所属行基本未变；
- 多张卡片宽度同时缩小，高度变化很小；
- 缩小后原列位置仍被保留，因此出现大段横向空洞。

这不是单纯 camera zoom，也不像单卡 Card Fit；它符合“整组 span 被重算、但绝对列拓扑优先于紧凑回填”的结果。

### 1.2 当前源码事实

1. `NavigationIsland` 的“适应内容”只连接 `zoom_fit_requested`，产品合同是 camera-only。
2. WWT native 入口使用 `native_layout_facts()` 与默认 `balanced/auto` policy。
3. pending group settle 再使用一份 controller 内硬编码的 `balanced/auto` policy，并可能提交整组 `GridRect` 后调用 `zoom_fit()`。
4. 手动 Smart Layout 通过 `plan_smart_layout()` 从当前 placement 重建 facts，把绝对 `rect.row/rect.column` 写回 `source_row/source_column`，并从 QSettings 加载 policy。
5. Smart Layout score 把 Board Fit 后 reading deficit、topology、target-area deviation排在 unused-area/board whitespace 前面；因此“缩窄但保留原列空洞”可能合法获胜。
6. Card Fit 明确是 origin-pinned 的局部 hug，不负责扫描整板或移动邻卡。

### 1.3 当前测试事实

现有测试已经覆盖：

- 同一份 `SmartCardFact` 重复求解具有确定性；
- settle 的 all-ready/quiet/deadline 回调只提交一次；
- Card Fit 与 Smart Layout 是两个入口；
- Board Fit 的纯 viewport 数学；
- Compact Arrange 保持 span。

但没有覆盖：

- WWT 打开完成后点击 Board Fit，placement digest 必须完全不变；
- import facts 与手动 Smart Layout facts 的语义等价；
- `SmartLayout(canonicalize(SmartLayout(x))) == SmartLayout(x)`；
- accepted Smart Layout 对每张卡均为 Card Fit 的“无明显改进”状态；
- preview capture/recapture、窗口 resize、Board Fit 与 pending settle 的事件交错；
- 真实 `U-Can_EO3_000089.wwt` 的“打开 → 等待 → Fit → Smart Layout → 再 Smart Layout”前台序列。

## 2. 本轮范围与非目标

### 2.1 实施范围

- 新增 canonical Smart Layout input snapshot/fact builder；
- 修正 native/import/manual 三个入口的 facts 与 policy 漂移；
- 建立 Smart Layout 固定点和行内无强迫空洞合同；
- 把 Card Fit hug 候选纳入 Smart Layout 候选质量检查；
- 隔离 Board Fit、preview capture、recapture 和 geometry settle；
- 收紧 pending group 的生命周期、事务与可见提交语义；
- 补齐 WWT synthetic owner tests、真实样本 smoke、geometry artifacts 与 Cocoa 验收；
- 同步上游 Spec 中 D7–D9、D14 和 Definition of Done。

### 2.2 明确不做

- 不改变 WWT 解析、WinWert 曲线绑定、坐标轴、颜色或数值；
- 不让 Board Fit、PreviewStore 或 capture coordinator拥有 layout solver；
- 不把 Card Fit 改为循环遍历整张 Board；
- 不通过增加更多 QSettings 权重把算法复杂度暴露给用户；
- 不把本机 `testdoc/` 文件提交为唯一回归 fixture；
- 不升级项目 schema，除非事实证明无法在现有最终 `GridRect` 持久化合同下完成；
- 不扩宽 `MainWindow` state ownership whitelist；
- 不吸收、清理或回滚当前 checkout 中无关的 dirty/untracked 文件。

## 3. 必须先冻结的产品合同

### UFP-01 — 四个动作不再共享“AutoFit”语义

| 动作 | 允许修改 size | 允许修改 position | 允许修改 camera | 允许启动 solver |
| --- | --- | --- | --- | --- |
| 智能排版 | 是 | 是 | 完成后一次 | 是，整板一次 |
| 紧凑排列 | 否 | 是 | 完成后一次 | 否，position-only pack |
| 按原图比例 | 仅目标卡 | 否；冲突则拒绝 | 否 | 否，只调用 Card Fit |
| 适应内容 | 否 | 否 | 是 | 否 |

任何按钮、快捷键、菜单或 callback 不满足该表即为 wiring bug。

### UFP-02 — Board Fit placement digest 不变量

定义：

```text
placement_digest = stable tuple(
    board_id,
    layout_revision,
    (ref.section, ref.view_id, column, row, column_span, row_span)...
)
```

连续执行任意次数 `zoom_fit()`、zoom in/out、overview、minimap navigation 后，`placement_digest`、history depth 和 dirty revision 必须逐字不变。

如果调用前存在 pending layout：

- Board Fit 仍只 fit 当前已提交 geometry；
- 不同步 flush、不间接触发、不等待 solver；
- pending geometry 不得把其提交归因于 Fit 事务；
- 前台事件记录必须能区分 `camera_fit` 与 `layout_commit`。

### UFP-03 — 唯一 `SmartLayoutInputSnapshot`

在 neutral owner 中增加不可变输入快照，至少包含：

```python
@dataclass(frozen=True)
class SmartLayoutInputSnapshot:
    facts: tuple[SmartCardFact, ...]
    policy: SmartLayoutPolicy
    facts_digest: str
    provenance: Literal["wwt-import", "manual-board", "project-current"]
```

约束：

- `smart_layout.py` 不读取 Qt、QSettings、PreviewStore 或 MainWindow；
- orchestrator 在命令开始时一次性冻结 policy/viewport/aspects；
- WWT initial layout、可选 settle、手动 Smart Layout 都消费这个 DTO；
- policy 不得在 native owner、controller 和 UI wrapper 各自创建默认值；
- diagnostics 记录 provenance，不允许它改变 solver score。

### UFP-04 — `source_column` 是语义顺序，不是绝对网格 X

当前 placement 重建 facts 时，不得使用绝对 `rect.column` 充当来源列。统一规则：

- `source_row` 是稳定语义 row id；
- `source_column` 是该语义行内按 reading order 得到的 `0..n-1` ordinal；
- 原始 WWT X/Y 只用于提取 row/order/salience；
- 已排 Board 只从 `(row band, column, stable ref)` 推导 ordinal；
- gap 大小、signed origin 和历史绝对 column 不得变成“必须保留”的拓扑事实。

这样 source topology 只约束顺序，不会把右图中的空洞合法化。

### UFP-05 — Smart Layout 必须成为固定点

对同一 `policy + target_viewport + preview_aspects + locks`：

```text
L1 = solve(snapshot)
S1 = canonicalize(snapshot, placements=L1)
L2 = solve(S1)

要求：L2.placements == L1.placements
     L2.accepted is True
     committed_updates(L2) == ()
```

还必须满足：

- 第二次执行不增加 history、dirty revision 或 camera-fit 次数；
- fallback 输出同样满足固定点；
- fixed-point failure 返回 diagnostic 并拒绝第一次提交，不能把不稳定解先显示给用户；
- 不允许以最多循环 N 次的方式“碰运气收敛”。候选生成和 canonicalization 必须从定义上稳定。

### UFP-06 — Span 决策之后必须 compact normalize

对每个没有 locked obstacle 的语义行：

- 卡片按稳定 reading order 排列；
- 相邻 unlocked 卡之间不得存在一个或多个未被约束强迫的空 Grid column；
- row-break/continuation 可以产生下一行，但同样从可用的最左合法位置开始；
- locked card、signed safety bound 或跨行 continuation 造成的空洞必须进入 structured diagnostic；
- whitespace 不再仅作为 score 第五位的软惩罚，明显内部空洞应在候选 canonicalization 阶段直接消除。

不要简单交换两个 score 权重来修截图；那只会把漂移转移到另一组样本。

### UFP-07 — Smart Layout 对 Card Fit “无明显二次改进”

Smart Layout 的 span candidates 必须包含每张卡的 chrome-aware `preferred_hug_span()` 及相邻量化候选。最终 accepted layout 对每张 unlocked/captured 卡执行只读 Card Fit probe：

- 最佳候选等于当前 rect；或
- 仅有网格量化误差：单轴不超过 1 个 microcell，且 `reading_fill` 改善 `< 0.03`。

若任一卡仍能从例如 `6×6` 明显缩到 `4×6/5×6`，当前整板解不是稳定终态，应把 hug candidate 纳入整组重解，而不是提交后等用户再次点击。

此 probe 只验证/丰富候选，不允许 Smart Layout 逐卡调用并提交 Card Fit，也不允许 Card Fit 移动邻卡。

### UFP-08 — 首次可见以后不再后台改 geometry

本 follow-up 收紧原 Spec D7–D9：

1. WWT 导入在首次可见提交前，使用 source facts 与冻结的 host-estimate/captured/fallback logical aspect 求一次最终 geometry；
2. 已经显示给用户的 Board 不再因为 late preview、resolution recapture、Board Fit、窗口 resize 或 cache replacement 自动重排；
3. capture aspect 晚到只更新 preview/quality，并可记录“重新智能排版可改善”的非侵入诊断；
4. 用户显式点“智能排版”才允许用最新 captured aspects 建立新事务；
5. 若实现者坚持保留 provisional→final 自动 settle，必须先修改 Spec，并证明最终 geometry 在首帧前原子替换；不得继续依赖“用户可能看不见 1200ms 内的跳动”。

推荐删除“首帧以后自动 geometry settle”，保留 capture/recapture 但让其彻底退出 placement mutation 链。

### UFP-09 — Policy 只有一个 owner

- UI/QSettings owner 负责加载用户偏好；
- workspace controller 在 import/manual command 开始时冻结 `SmartLayoutPolicy`；
- `plan_native_layout()`、`solve_smart_layout()` 只消费显式 policy；
- pending group 不再硬编码另一份 `balanced/auto`；
- QSettings 缺失时默认仍是 `balanced/auto/preserve_locked=True`；
- 项目恢复只使用已保存 rect，不依赖当前 QSettings 隐式重排。

## 4. 目标调用链与 ownership

```text
UI intent
  ├─ 适应内容 ───────────────→ UltraViewPage.zoom_fit() ─→ camera only
  ├─ 按原图比例 ─────────────→ CardFitFacts → solve_card_fit() → target card only
  ├─ 紧凑排列 ───────────────→ plan_auto_arrange() → positions only
  └─ 智能排版 / WWT import
       → WorkspaceController freezes viewport + policy + logical aspects
       → canonical fact builder
       → SmartLayoutInputSnapshot
       → solve_smart_layout()
       → fixed-point/material-fit validation
       → one placement transaction
       → one zoom_fit()

Preview capture / recapture
  → PreviewStore image + quality state only
  → never writes GridRect/history/layout revision
```

Ownership 不得变化为：

- widget 读取/写入 workspace state；
- neutral core 读取 QSettings/Qt；
- capture coordinator 调 layout solver；
- `MainWindow` 新增跨文件 mutable fields；
- compatibility facade 成为新实现 owner。

## 5. 实施波次

## W0 — 更新 Spec 并先写红测

**Owner**

- `docs/analyzer/specs/2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md`
- 新增 `tests/ui/test_ultraview_smart_layout_integration.py`
- 扩展 `tests/test_ultraview_smart_layout.py`
- 扩展 `tests/ui/test_wwt_board_projection.py`
- 扩展 `tests/ui/test_ultraview_viewport.py`

**先红合同**

1. `test_wwt_open_then_board_fit_keeps_exact_placement_digest`
2. `test_wwt_open_then_smart_layout_is_already_a_fixed_point`
3. `test_second_manual_smart_layout_is_zero_mutation_zero_history`
4. `test_import_and_manual_paths_build_equivalent_semantic_facts`
5. `test_manual_fact_builder_uses_row_ordinal_not_absolute_column`
6. `test_balanced_layout_has_no_unforced_internal_row_holes`
7. `test_smart_layout_is_material_card_fit_fixed_point`
8. `test_late_capture_and_resolution_recapture_never_change_geometry`
9. `test_window_resize_does_not_relayout_until_explicit_command`
10. `test_fit_during_pending_capture_is_camera_only`

**Fixture**

- 用 `tests/_helpers/wwt_factory.py` 提交一个最小的 U-Can 语义 fixture；
- 结构固定为截图对应的两组 7 卡、混合 preview aspect、至少一个 overlap/continuation；
- 本机 `testdoc/wwt/U-Can_EO3_000089.wwt` 仅作 optional smoke；
- 测试不得读取用户 QSettings，使用隔离 store 或显式 policy。

**W0 exit**

- 红测稳定失败在已确认的跨入口/事务问题上；
- 不使用 `sleep()`、屏幕截图像素猜测或随机时序；
- 原 Spec D7–D9/D14/DoD 已明确采用本 follow-up 的新合同。

## W1 — 建立 canonical facts/policy snapshot

**Owner**

- `mf4_analyzer/ultraview_core/smart_layout.py`
- `mf4_analyzer/ultraview_core/native_layout.py`
- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- `mf4_analyzer/ui/chart_stack/ultraview/smart_layout_settings.py`
- `tests/test_ultraview_smart_layout.py`
- `tests/ui/test_ultraview_native_layout.py`

**实施**

1. 新增不可变 `SmartLayoutInputSnapshot` 与 stable `facts_digest`；
2. 抽出 neutral semantic row/order canonicalizer；
3. native WWT 和 current Board 均输出 row id + ordinal column，不输出绝对 grid X；
4. controller/UI 边界冻结 logical aspects、target viewport、policy；
5. 删除 native 默认 policy 与 pending settle 硬编码 policy 的双重事实源；
6. 保留稳定 `UltraViewRef` tie-break，不用 View 标题。

**W1 exit**

- import/manual 对等样本的 semantic facts digest 相同；
- QSettings 变化只影响下一次显式命令；
- neutral import boundary 继续通过；
- 无 schema、MainWindow state 或 display-key 扩张。

## W2 — 让 solver 从定义上成为固定点

**Owner**

- `mf4_analyzer/ultraview_core/smart_layout.py`
- `mf4_analyzer/ultraview_core/grid_geometry.py`（仅必要的 neutral helper）
- `mf4_analyzer/ui/chart_stack/ultraview/card_fit.py`（优先复用公开纯函数；不复制算法）
- `tests/test_ultraview_smart_layout.py`
- `tests/ui/test_ultraview_card_fit.py`

**实施顺序**

1. 把 `preferred_hug_span()` 所需的纯几何提取到 neutral 可复用 owner；禁止 core 反向 import `ui`；
2. 每卡候选必须覆盖 hug center、相邻量化候选、当前 rect 与密度候选；
3. span 选定后执行 topology-preserving compact normalize；
4. 删除由绝对 source column 产生的非强迫横向洞；
5. 对候选结果执行一次纯 fixed-point probe；
6. 对每卡执行 material Card Fit probe；
7. 不满足 UFP-05/UFP-07 的结果不得进入 commit DTO；
8. equal-grid fallback 同样走 compact normalize 和固定点验证。

**W2 exit**

- 同一输入重复 100 次逐字相同；
- accepted 输出 canonicalize 后再求解完全相同；
- 2/4/7/8/12/24 数量矩阵、宽/方/竖/缺失 aspect 均通过；
- 7 卡 U-Can 不再出现截图右侧那类无锁定大横向洞；
- `search_visits <= 4096`，不得用多轮求解掩盖不收敛。

## W3 — 隔离 WWT 首次提交、capture 与 Board Fit

**Owner**

- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- `mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py`
- 既有 controller-local holder
- `tests/ui/test_wwt_board_projection.py`
- `tests/ui/test_ultraview_placement_history.py`
- `tests/ui/test_ultraview_capture.py`

**实施**

1. import 时一次性冻结 input snapshot 并提交最终 geometry；
2. 移除首帧以后 capture event → `set_free_grid_rects()` 的路径；
3. recapture 只更新 preview 与 `resolution_stale`；
4. `zoom_fit()` 不读取、不 flush pending group；
5. camera event 与 layout event 使用不同 typed diagnostic/event kind；
6. Smart Layout 成功仍保持一个 snapshot、一个 history、一个 dirty、一次 refresh、一次 zoom-fit；
7. Board switch/delete、workspace clear、project restore、window destroy 对称取消所有旧 token/timer；
8. Undo/Redo 只恢复已提交结果，不重新运行 solver。

**W3 exit**

- Fit 前后 placement digest 精确相同；
- late preview、sync source、recapture、DPR 变化均不改 rect；
- import Undo 一次回到导入前；
- 无 stale Board write、timer leak 或额外 MainWindow state。

## W4 — UI 语义与用户反馈闭环

**Owner**

- `mf4_analyzer/ui/chart_stack/ultraview/board_context_controller.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`（仅 wiring）
- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `mf4_analyzer/help/ultraview-guide.html`
- `docs/analyzer/user-guide/user-guide.html`

**实施**

1. UI 不再显示含混的全局 “AutoFit”；
2. “适应内容”tooltip 明确“只缩放画布，不改卡片”；
3. “智能排版”tooltip 明确“重新计算大小与位置”；
4. “按原图比例”明确“只收紧当前卡”；
5. fixed-point 时提示“布局已是最优状态”且不写 history；
6. preview 晚到可能改善布局时只提供非阻塞状态，不自动跳动；
7. hints、quickref、help、user guide 使用同一中文动作名。

**W4 exit**

- shortcut/menu/button/callback 的状态维度与 UFP-01 完全一致；
- 无新增 `.connect(lambda ...)`；
- 不通过 toast 掩盖后台布局变更；
- “布局已是最优状态”只在 solver fixed-point 已验证后出现。

## W5 — 持久化与兼容性

**Owner**

- `mf4_analyzer/ultraview_core/board_ops.py`（仅必要模型操作）
- workspace placement history/project session owners
- `tests/ui/test_ultraview_project_session.py`
- `tests/ui/test_ultraview_placement_history.py`
- `tests/ui/test_ultraview_compatibility.py`

**覆盖**

- 保存/重开逐项恢复最终 `GridRect`，不读取新窗口尺寸重排；
- 老项目没有 semantic source facts 时，从当前 rect 生成 row ordinal 快照；
- 第一次显式 Smart Layout 可改变老布局，第二次必须 no-op；
- lock 造成空洞时保留 lock，并输出 structured diagnostic；
- QSettings 策略不是 project restore 的隐藏输入；
- 不新增 schema 时不得写入临时 facts、preview confidence、diagnostics 或 process-local cache。

**W5 stop rule**

如果必须持久化原始 WWT semantic facts 才能满足产品意图，停止本 wave，单独提出 schema migration、旧项目 fallback 与回退设计；不得把该数据塞进 `opaque_payload` 或 widget property。

## W6 — 验证、artifact 与前台验收

### 6.1 Focused owner gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_ultraview_smart_layout.py \
  tests/ui/test_ultraview_smart_layout_integration.py \
  tests/ui/test_ultraview_native_layout.py \
  tests/ui/test_wwt_board_projection.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_card_fit.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_placement_history.py \
  tests/ui/test_ultraview_project_session.py \
  tests/ui/test_ultraview_viewport.py -q
```

### 6.2 Boundary gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_native_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_quickref.py \
  tests/ui/test_hints.py -q
```

如果移动 Card Fit 纯几何 owner，再运行所有现有 Card Fit lesson 指定测试；如果触及 `_CanvasBackref`，再加 `tests/ui/test_pg_canvas_backref_invariants.py`。

### 6.3 Deterministic geometry artifacts

生成到 `.state/ultraview-smart-layout-fixed-point/`，不默认提交：

- `u-can-open.json`
- `u-can-after-board-fit.json`
- `u-can-after-smart-layout-1.json`
- `u-can-after-smart-layout-2.json`
- `layout-matrix.json`
- `event-timeline.json`

每份至少记录：

- `facts_digest`、policy、viewport、aspect confidence；
- placement digest 与逐卡 rect；
- reading fill、Board union、unforced gap count；
- Card Fit material delta；
- history depth、layout revision、camera fit count；
- solver visits、fallback、diagnostics；
- geometry/camera/capture event 顺序。

自动比较必须满足：

```text
u-can-open.placement_digest
  == u-can-after-board-fit.placement_digest
  == u-can-after-smart-layout-1.placement_digest
  == u-can-after-smart-layout-2.placement_digest
```

如果首次显式 Smart Layout允许把历史/老项目布局升级，则只允许：

```text
open != smart-layout-1
smart-layout-1 == smart-layout-2
```

### 6.4 macOS Cocoa 前台

使用真实 `U-Can_EO3_000089.wwt`：

1. 打开 UltraView，等待预览稳定并记录 placement digest；
2. 连续点击“适应内容”3 次，卡片外框逐像素不变；
3. 点击“智能排版”两次，第二次无跳动、无新增 Undo；
4. 分别对 7 张卡执行“按原图比例”，不得出现多卡一起变形；
5. 执行源同步/preview recapture，卡片 geometry 不变；
6. resize 到窄/宽窗口，未显式排版前 geometry 不变；显式排版后再次执行成为固定点；
7. 验证无横向大洞、无霸屏 hero、View 7 阅读组稳定；
8. 保存重开，geometry 和 camera 恢复合同分别成立。

截图不能单独关闭门禁；必须同时保存 rect/event artifact。Cocoa 未运行时写 `UNVERIFIED`。

### 6.5 Windows Full/Lite frozen

分别验证 WWT 打开、三次 Board Fit、两次 Smart Layout、单卡 Card Fit、Undo/Redo、保存重开及 125%/150% DPI。源码/offscreen 不能替代 frozen 前台，未运行写 `UNVERIFIED`。

### 6.6 Full suite owner

只有稳定 integration milestone 的单一负责人运行一次完整门禁。运行前检查同 checkout 的 pytest 进程，按仓库合同串行执行 main suite 与 `tests/acquisition_ui`；运行前后记录 HEAD 与 dirty fingerprint。相关文件在测试期间变化则结果为 `UNVERIFIED`。

## 6. Definition of Done

只有以下各项同时成立才可关闭：

- [ ] 上游 Spec 已吸收 UFP-01～UFP-09；
- [ ] import/manual 共用 canonical facts/policy snapshot；
- [ ] Smart Layout fixed-point 红测转绿；
- [ ] Board Fit placement digest 严格不变；
- [ ] late preview/recapture/resize 不自动改 geometry；
- [ ] 7 卡 U-Can 无非强迫内部空洞；
- [ ] Smart Layout 结果没有 material Card Fit 二次改进；
- [ ] 第二次 Smart Layout 零 mutation、零 history、零 camera fit；
- [ ] Undo/Redo、锁定、保存重开、生命周期闭环；
- [ ] hints/quickref/help/user guide 文案一致；
- [ ] focused 与 boundary gates 通过；
- [ ] deterministic artifacts 自动对比通过；
- [ ] macOS Cocoa 前台通过或明确 `UNVERIFIED`；
- [ ] Windows Full/Lite 通过或明确 `UNVERIFIED`；
- [ ] `git diff --check` 通过；
- [ ] lessons status 已检查。

## 7. Stop rules

出现任一情况立即停止当前 wave并回报，不写兼容补丁掩盖：

1. Board Fit、preview capture 或 recapture 仍需要调用 layout solver；
2. 固定点只能靠重复运行 solver 若干次才能碰巧得到；
3. 需要把绝对 grid column 继续当作 source topology；
4. 需要复制 Card Fit 数学到 neutral core 而不能迁移为单一 owner；
5. 为消除空洞必须牺牲锁定 rect、stable reading order 或最小 reading box；
6. 测试需要 `sleep()`、随机重试或真实 QSettings 才能通过；
7. 需要扩宽 MainWindow state ownership whitelist；
8. 需要升级 schema 但没有迁移、fallback 和回退计划；
9. 相关 owner 文件出现无法协调的并发修改；
10. 另一个 full pytest 正在同 checkout 运行；
11. offscreen 与 Cocoa 几何/LOD 结论冲突；
12. 无法按用户截图动作序列在真实 U-Can 前台复现或验证。

## 8. 实施切片与交接建议

为避免 shared checkout 中的 solver/controller 冲突，按以下顺序单 owner 交接：

1. **Slice A — Spec + red tests**：只改文档、fixtures 和测试；
2. **Slice B — neutral facts + fixed-point solver**：只拥有 core、free-grid 纯 wrapper 与纯测试；
3. **Slice C — controller transaction isolation**：只拥有 workspace/capture controller 与事务测试；
4. **Slice D — UI/docs/persistence**：只拥有 action wiring、文案、project/history tests；
5. **Integration owner**：解决跨切片接口，生成 artifacts，运行 focused/boundary/full gates；
6. **Foreground owner**：只做 Cocoa/Windows 实机验收，不以手工修源码替代失败回传。

每个 slice 必须先记录当前 HEAD/dirty scope，只 stage 自己的 owner 文件。任何人不得顺手吸收当前 checkout 中的版本、帮助资源、删除文件、`ssh-keygen*` 或其它并行变更。
