# WWT 原生坐标范围与刻度生命周期单 Owner 优化计划

- 日期：2026-08-30
- 状态：**IMPLEMENTED (offscreen)**；Cocoa 前台验收仍 **UNVERIFIED**
- 当前基线：`main@db92d41c`（`main...origin/main [ahead 1]`）
- 实施记录：2026-08-30 按 T0→T1–T3 落地；Task 0 红测在修复前真实失败，修复后 focused+boundary 通过
- 建议实施分支：`codex/wwt-native-axis-lifecycle`
- 主样本：`testdoc/wwt/NLTNP_000089.wwt`（只作 optional smoke）
- 核心测试：必须使用 `tests/_helpers/wwt_factory.py` 中已提交或新增的 synthetic fixture
- 历史合同：
  - `docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md` §8
  - `docs/analyzer/plans/2026-08-29-wwt-timedomain-plot-and-ultraview-reflow-plan.md` §1.2
- **现行性说明（2026-09-01）**：本文的 WWT native display policy 生命周期已由
  [`2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md`](2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md)
  取代；本文保留为历史实施证据，不回溯改写其结论。

### 实施后实测（offscreen）

Task 0 红测在改产品代码前的 actual：

| 用例 | 修复前 actual | 期望 |
| --- | --- | --- |
| dual-axis default density | torque `-10.5..12`，speed `0..600` | `-10..10` / `0..460` |
| persisted speed `40..520` | ylim `40..640`，majors 停在 `460` | `40..520`，cadence 20 含 520 |
| X after resize settle | majors 步长 100 | native 120/60 |
| adaptive overflow | `_tickLevels` 仍为种下的 0..460 | `setTicks(None)` |
| passive capture | `axis_opts` 无 `native_ticks` | 深度保留 |

修复后：`tests/ui/test_wwt_native_render.py` + `test_view_bridge.py` + `test_overlay_grid_ticks.py` + `test_wwt_import_flow.py` + backref/state-ownership/lambda/qsettings = **217 passed**；`TestViewRestoreSettlement` + `TestRepinTicks` + `TestFitYToVisibleOverlay` **15 passed**。

未跑 full gate：工作区仍有无关 dirty（署名/帮助、删除的 assets），同一 snapshot 不能当作发版验收。Cocoa §5 **UNVERIFIED**。

Lesson：`docs/lessons-learned/view-restore-range-and-ticks-need-full-transaction.md`。

> 本计划不改 WWT 文件解析结果、不改复合 source/channel identity、不新增
> `MainWindow` 散状态、不扩大 `ViewState` schema。目标是让 native range、native
> tick cadence、通用 overlay density 与 View restore 只通过一个明确的 canvas tick
> owner 协作，不再依靠调用先后互相覆盖。

## 0. 结论与问题边界

### 0.1 当前可稳定复现的事实

`NLTNP_000089.wwt` 的 WWT proposal 正确保存：

| 轴 | native range | major | grid |
| --- | ---: | ---: | ---: |
| 左轴 Steering torque | `-10..10 Nm` | `1` | `0.5` |
| 右轴 Steering speed | `0..460 °/s` | `20` | `10` |

但完整 View 恢复事务实际执行：

```text
plot/build axes
→ generic set_tick_density() 第一次框定
→ restore X
→ restore persisted/native Y
→ generic set_tick_density() 第二次框定
→ apply native explicit ticks
→ settle
```

默认 `Y density = 15` 时，第二次 generic density 会通过
`_repin_overlay_channel_ticks()` 调用 `handle.set_ylim()`：

| 轴 | restore 后 | density 后最终范围 | native labels | 覆盖率 |
| --- | ---: | ---: | ---: | ---: |
| 左轴 | `-10..10` | `-10.5..12` | `-10..10` | 88.9% span |
| 右轴 | `0..460` | `0..600` | `0..460` | 76.7% span |

因此右轴上方约 23.3% 没有标签，正是用户截图中的红框区域。它不是 WWT
解析错误，也不是 AxisItem 物理裁剪，而是 final ViewBox range 与 explicit tick
枚举范围来自两个 owner。

### 0.2 之前优化过什么、没有覆盖什么

- `92b3a913`：把 native Y tick 从位置 `zip` 改为按 `axis_id` 配对；解决“刻度贴错轴”。
- `320a8c33`：把 Y restore 从逐通道改为逐 shared handle；解决 record-only sibling
  再次 fit 覆盖 owner range。
- 仍未覆盖：恢复完成前的 generic density 会再次改写 range；native helper 只写 ticks，
  不拥有 final viewport。
- 现有共享轴测试在 `restore_visible_ylims()` 后直接断言，没有执行生产中的第二次
  `set_tick_density()` 与 native tick 重放，因此局部测试全绿。

### 0.3 同源生命周期缺口

这次不能只修右轴一处；同一个 native policy 还有三个已确认缺口：

1. `capture_controls_into()` 用普通控件快照整体替换 `state.axis_opts`，被动 View
   capture 会丢掉 `native_ticks`。原 spec 明确规定只有用户主动修改刻度密度才退出
   native mode。
2. native X ticks 在 View restore 中写入后，settle/resize 又会运行 generic target-X
   tick 投影，native cadence 没有稳定 owner。
3. 用户 Home/Fit/缩放得到新的有效 viewport 后，native major/grid 仍按最初 lo/hi
   枚举，可能再次产生“当前范围大于标签范围”的局部空白。

## 1. 必须冻结的产品合同

### C1 — 初次打开的 native viewport

- 有效 WWT native X/Y range 是首次绘制的 viewport，不得被默认 tick density、
  auto-range 或 record-only sibling fit 覆盖。
- range 优先级继续保持：
  1. 当前 View 已持久化的有效范围；
  2. WWT native initial range；
  3. 当前可见 X 内该 handle 的可见原始数据并集；
  4. 全量有限数据 fallback。
- 不能通过把标签补到 `600` 来掩盖首次打开本应为 `0..460` 的事实。

### C2 — native range 与 native cadence 分工

- `native_ticks[*].lo/hi` 是初始 viewport 事实，不是永久限制用户 viewport 的裁剪框。
- `major/grid` 是 native mode 下的刻度 cadence。
- overlay 背景 graticule 只是共享展示层，不是第三个 viewport owner：它可以继续按主轴/
  density 合同绘制；不同 Y 轴的 native major/grid 由各自 AxisItem 表达。任何 graticule
  更新都不得反向改写某个 handle 的 effective range。
- 初始绘制、View 切换、split 投影和项目恢复：effective range 应等于已持久化范围，
  若尚无用户范围则等于 native initial range。
- 用户 Home/Fit/缩放后，仍使用 native cadence 在**当前 effective range** 内重新枚举
  ticks；首末可见区最多允许小于一个 major interval 的自然边缘空隙，禁止出现连续
  多个主刻度间隔没有标签。

### C3 — 退出 native mode 的唯一用户动作

- 被动 capture、View 切换、split、resize、项目保存不得清除 `native_ticks`。
- 切到普通 View 时只清当前 canvas 的 active policy，不删除其他 WWT ViewState 中保存的
  `native_ticks`；切回该 WWT View 时必须从它自己的 state 重新安装。
- 用户在 Inspector/ChartCard **主动修改刻度密度**时：
  1. 先清除 ViewState 的 `native_ticks`；
  2. 同步清除 canvas 的 native tick policy；
  3. 再执行现有 generic density/reframe；
  4. 保存后重开继续使用 generic policy。
- Home、Y Fit、pan/zoom 只改变 viewport，不自动等价为“用户修改刻度密度”。

### C4 — 普通 overlay 行为不得回归

- 非 WWT View 的 `set_tick_density()` 仍允许把 arbitrary range 对齐到 nice grid。
- Shift-wheel、Home、Y Fit、原始/滤波可见性变化继续使用现有 nice-step、anchor、
  visibility-aware 数据并集合同。
- 新勾选且无 saved ylim 的独立轴继续按 restored visible X 内原始数据 fit。
- 不得为了 WWT 直接全局禁用 `_repin_overlay_channel_ticks()`。

### C5 — 单 owner 与同步不变量

每次稳定 frame 必须同时满足：

```text
ViewState/effective range
    == PgAxisHandle.get_*lim()
    == linked AxisItem.range
```

native mode 还必须满足：

```text
explicit tick values = native cadence projected over effective range
```

invalid/overflow/adaptive fallback 必须显式 `setTicks(None)` 或等价清理，不能保留上一个
WWT View 的 stale explicit ticks。

## 2. Owner 与允许修改范围

| Owner | 责任 | 允许修改 |
| --- | --- | --- |
| `ui/pg_canvas/native_axes.py` | 纯 native spec 校验；按 effective range 生成/应用 X/Y levels；adaptive 时清 stale ticks | 是 |
| `ui/pg_canvas/tick_density.py` | canvas 的 active native tick policy；generic/native X tick 路由；restore-safe density 入口 | 是 |
| `ui/pg_canvas/overlay_axes.py` | 区分“重框 range”和“只投影 ticks”；Y range 变化后按 active policy 重投影 | 是，保持 `_CanvasBackref` 声明准确 |
| `ui/pg_canvas/canvas.py` | host 委托、rebuild/reset 对称清理、restore transaction 调用面 | 仅薄接线 |
| `ui/main_window/_view_mixin.py` | 从 ViewState 安装/清除 policy，并按最终几何顺序恢复 | 是，不新增散状态 |
| `ui/view_bridge.py` | 被动 capture 保留 native semantic facts | 是 |
| `ui/main_window/window.py` | 显式 density 用户动作先退出 native mode | 仅 `_update_all_tick_density_pair()` |
| `ui/view_state.py` | 继续使用现有 `axis_opts`/`xlim`/`ylims` | **不改 schema** |
| `ui/wwt_view_import.py` | proposal 已正确，本轮不改翻译/axis_id | **不改** |

禁止把新实现放进兼容 facade `ui/pg_canvases.py`。如果 TickDensityController 增加 mutable
policy，必须更新 `_owned_names`，在 canvas rebuild、empty plot、View 切换与 teardown 中
对称清理，并通过 `_CanvasBackref` invariant。

## 3. 实施任务

### Task 0 — 先冻结完整事务红测

**Owner tests**

- `tests/_helpers/wwt_factory.py`
- `tests/ui/test_wwt_native_render.py`
- `tests/ui/test_view_bridge.py`
- `tests/ui/test_pg_timedomain_canvas.py`
- 集成回归面：`tests/ui/test_wwt_import_flow.py`

**新增 synthetic fixture**

建立一个 NLTNP-like 双轴窗口：

- X `-660..540`，major `120`，grid `60`；
- torque axis `-10..10`，major `1`，grid `0.5`；
- speed axis `0..460`，major `20`，grid `10`；
- 每轴同时有 selected channel-backed owner 与 record-only companion；
- `plot_mode="overlay"`，不依赖 `testdoc/`。

**必须先红的用例**

1. `test_native_dual_axis_restore_keeps_ranges_after_default_density`
   - 执行生产顺序，而不是直接调用单个 helper；
   - 默认 `(20, 15)` 后左轴仍为 `-10..10`、右轴仍为 `0..460`；
   - 每个 `AxisItem.range` 与对应 handle 完全一致；
   - major labels 覆盖完整 effective range。
2. `test_native_ticks_project_over_persisted_user_viewport`
   - 给 speed 轴保存 `40..520`；
   - restore 后范围保持 `40..520`；
   - 以 `20` cadence 生成 `40..520`，不再截止于原始 `460`。
3. `test_passive_capture_preserves_native_ticks`
   - capture controls/ranges 后 `native_ticks` 深度值等价保留；
   - 其他 `range_filter/x_axis/tick_density` 仍刷新。
4. `test_explicit_density_change_exits_native_mode_before_reframe`
   - 只有 `_update_all_tick_density_pair()` 清除 state/canvas policy；
   - 当次 frame 立即使用 generic ticks，保存/恢复后不复活 native mode。
5. `test_native_x_ticks_survive_settle_and_resize`
   - restore、`settle_view_restore()`、有效 resize settle 后仍使用 `120/60` cadence；
   - `AxisItem.range == ViewBox x range`。
6. `test_plain_view_after_wwt_has_no_stale_native_policy`
   - WWT View → 普通 overlay View；
   - 普通 View 使用自己的 generic range/ticks，不能继承 WWT `axis_id` 或 cadence。
7. adaptive/overflow fallback：切换到无效或超 cap spec 后，旧 `_tickLevels` 被清空。

**红测纪律**

- 在当前基线确认新用例因上述真实失配失败；不得写一个绕过
  `set_tick_density()`/settle/resize 的 helper 让它假绿。
- 记录每个红测当前 actual 值；NLTNP-like 主用例应至少看到右轴 `0..600` vs
  `0..460` 的差异。
- 先提交 tests/fixture，再开始实现。

### Task 1 — 建立 canvas-owned native tick policy

**Owner files**

- `mf4_analyzer/ui/pg_canvas/native_axes.py`
- `mf4_analyzer/ui/pg_canvas/tick_density.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`（仅 host 委托/reset）

**接口合同**

1. TickDensityController 持有 active native specs 的不可变/深拷贝快照，不持有
   ViewState、widget 或 MainWindow 引用。
2. 提供明确的安装/清除入口，例如：

   ```python
   canvas.set_native_tick_policy(native_ticks_or_none)
   ```

   具体命名可按现有风格调整，但不得用静默 `getattr(..., False)` 代替初始化。
3. `native_tick_levels()` 保持纯函数；新增或改造 apply helper 时，tick 枚举的 lo/hi
   必须取当前有效 handle/ViewBox range，spec lo/hi 只用于首次 range fallback。
4. X generic target-tick 路由在 active native policy 下必须调用 native projector，
   因此 settle/resize 不再覆盖 native X。
5. axis_id 未匹配、step 无效或 cap overflow：该轴回 adaptive，并清掉旧 explicit
   ticks；unexpected error 不得静默降级。

**不变量测试**

- 安装 policy → rebuild/empty plot/clear → policy 为空；
- WWT A → WWT B：按 B 的 axis_id/spec，不混入 A；
- WWT → ordinary：所有 axes adaptive/generic；
- explicit label 数值满足 tick-truthfulness lesson 的误差合同。

### Task 2 — 将 density 的“密度更新”和“Y 重框”拆开

**Owner files**

- `mf4_analyzer/ui/pg_canvas/tick_density.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`（薄委托）

**最小兼容接口**

保留所有现有两参数调用的默认行为，并增加 kw-only restore 控制，例如：

```python
set_tick_density(x, y, *, reframe_overlay_y=True)
```

- 普通调用默认 `True`，现有 density-change/nice-grid 语义不变。
- native View restore 使用 `False`：更新 density 数值、共享 graticule 与布局，但不得
  再调用会改变已提交 Y range 的 generic reframe。
- 不能用“保存 ranges → generic reframe → 再写回 ranges”的临时补丁隐藏重复工作；
  owner API 必须明确本次是否允许 range mutation。

**拆分内部职责**

- 把 `_repin_overlay_channel_ticks()` 中以下行为明确分离：
  1. 可选的 nice-range framing；
  2. 基于 active policy 的 tick projection。
- Home/Y Fit/Shift-wheel/visibility change 继续先按各自合同决定 range，再统一调用 tick
  projector；不得各自重新实现 native tick 枚举。
- native mode 下 projector 使用 current effective range + native cadence；generic mode
  保持 divisions 对齐与 `_fmt_tick` 语义。

**必须保持绿色的旧合同**

- `test_density_change_reframes_when_new_step_is_not_nice`
- `test_repin_still_frames_arbitrary_external_range`
- overlay Shift-wheel anchor/round-trip/3..20 density sweep
- visibility-aware companion reframe
- new-channel Y-fit-after-restore

### Task 3 — 修正 View restore 与 native mode 持久化生命周期

**Owner files**

- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/view_bridge.py`
- `mf4_analyzer/ui/main_window/window.py`（仅显式 density handler）
- 对应 `test_view_bridge.py`、`test_main_window_smoke.py`、`test_wwt_native_render.py`

**恢复事务**

目标顺序应显式表达为：

```text
clear canvas policy from prior View
→ build target axes/rows
→ install target native policy (or keep cleared for ordinary View)
→ restore final X
→ restore final Y by persisted/native/data priority
→ apply density without Y reframe when native policy is active
→ project native/generic ticks from FINAL ranges
→ settle once; settle/resize继续走同一 policy router
```

- `_plot_time_on_canvas()` 现有第一次 density 应记录为“建轴阶段 temporary framing”；
  final restore 必须覆盖它。
- `_render_view_to_canvas()` 的第二次 density 不得再修改 native final Y。
- split secondary canvas 与 primary canvas 各自安装目标 View 的 policy；禁止共享一个
  MainWindow-level native state。

**capture/clear 规则**

- `capture_controls_into()` 合并普通控件字段时显式保留已有 `native_ticks`；不要笼统
  保留所有未知 axis_opts，避免保住过期 transient 字段。
- `_update_all_tick_density_pair()` 必须先从 ViewState 和 canvas 清 native policy，再调用
  generic `set_tick_density()`；当前已有的 `axis_opts.pop('native_ticks', None)` 是唯一
  产品级退出点，应保留并补 canvas 对称清理。
- 用户仅切 View、保存、关闭项目、resize、Home/Fit、pan/zoom，不得无意清 native mode。
- 不新增 `viewport_intent_committed` 或另一个 MainWindow 状态；现有 `xlim/ylims` 已足以
  表达用户 viewport。

### Task 4 — 集成回归、文档诚实度与 lesson closeout

**范围**

- 更新本计划状态与实测结果；不回写历史 spec 的版本/状态来伪装当时已覆盖。
- 若实现确认形成可复用规则，新增一条短 lesson：
  “View restore 的最终 range、AxisItem.range 与 explicit ticks 必须由同一 policy 在完整
  事务后断言；局部 range/tick 测试不能替代组合测试”。
- 不需要改 `ui/hints.py` / `ui/quickref.py`：没有新增、删除或重命名用户交互。

## 4. 验证门禁

### 4.1 Task 0 红测命令

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_wwt_native_render.py \
  tests/ui/test_view_bridge.py \
  tests/ui/test_pg_timedomain_canvas.py \
  -k 'native or passive_capture or explicit_density or stale_native' -q
```

要求：新增用例在基线按预期失败；既有用例不能被改成宽松断言。

### 4.2 每个实现任务的 focused gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_wwt_native_render.py \
  tests/ui/test_view_bridge.py \
  tests/ui/test_overlay_grid_ticks.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_wwt_import_flow.py -q
```

如整文件运行时间过长，可在任务内先跑精确 node id；任务完成前必须补跑上述 owner
集合。测试报告要记录实际命令与 pass/skip，禁止硬编码历史数量。

### 4.3 边界门禁

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py -q
```

并运行：

```bash
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

### 4.4 Full gate owner

- 仅父任务/协调者在所有相关文件稳定后运行一次 full gate。
- 开始前记录 `HEAD`、`git status --short`、相关 dirty fingerprint，并检查没有另一个
  pytest 在同一 checkout 运行。
- 按仓库合同使用两个新鲜、串行进程：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

- 运行期间相关文件变化、异常退出、崩溃、超时或中断一律记 `UNVERIFIED`。

### 4.5 本轮计划文档自身的验证

本轮不修改产品代码或测试，因此不运行 runtime pytest 来伪装实现已验证。交付前只执行：

```bash
git diff --check
git status --short --branch
/usr/bin/python3 scripts/lessons/check.py --status
```

并逐项核对计划中列出的 owner 文件、测试文件和现有关键符号确实存在；实现后的 runtime
门禁以 §4.1–§4.4 为准。

## 5. Cocoa 前台验收

自动化通过后，必须在真实 macOS Cocoa 的 TraceLab 前台完成；offscreen 不替代：

### A. NLTNP 初次打开

1. 打开 `testdoc/wwt/NLTNP_000089.wwt`。
2. 不点 Fit、不改 density。
3. 记录 canvas/AxisItem 数值探针与截图：
   - 左轴 ViewBox/AxisItem：`-10..10`；标签覆盖 `-10..10`；
   - 右轴 ViewBox/AxisItem：`0..460`；标签覆盖 `0..460`；
   - 右轴顶部不得再出现连续 `480..600` 对应的无标签空带；
   - 曲线、红/蓝辅助线、颜色、轴槽数保持当前正确结果。

### B. 生命周期

- 在 NLTNP 与普通 TimeDomain View 间来回切换 5 次；范围/ticks 不漂移，普通 View
  无 stale native cadence。
- 开/关 split，并分别聚焦左右 pane；两个 canvas 按各自 View policy 渲染。
- resize 到窄/宽窗口，再回原尺寸；native X/Y cadence 与范围不被 generic tick 覆盖。
- 保存项目、关闭、重开；结果与保存前一致。

### C. 用户 viewport

- 执行 Home、Y Fit、Shift-wheel/pan 后切 View 再回来：保存的 effective range 恢复，
  native ticks 在当前范围内继续完整投影。
- 主动修改 tick density：当帧立即完整切换为 generic ticks/range；切 View及项目重开后
  仍为 generic，不复活 native mode。

### D. 邻近真实样本

- `YP_SS_000089.wwt`：首次仍为 owner `0..0.2`，红色公差线不得覆盖/缩窄共享轴。
- `U-Can_D6-CSER double_00479.wwt`：record-only Views、共轴与 UltraView 排版不回归。

验收记录必须把 source facts、offscreen probe、Cocoa screenshot 和用户可见结论分开。

## 6. 实施顺序与协作

本缺陷是单一恢复事务，默认建议一个实现 agent 顺序完成，避免多个 agent 同时修改
`tick_density.py` / `overlay_axes.py` / `_view_mixin.py`：

```text
T0 red tests
→ T1 native policy owner
→ T2 density/reframe separation
→ T3 View lifecycle wiring
→ focused + boundary gates
→ single coordinator full gate
→ Cocoa foreground acceptance
```

如果必须并行，只允许：

- Agent A：T0 fixture + `test_wwt_native_render.py`；
- Agent B：只做 `view_bridge.py` 被动 capture 红测；
- 主 agent：等待 T0 后实现 T1–T3，并负责所有共享文件和最终 full gate。

所有 agent 必须知道工作区并非独占，不得回退他人或用户的 dirty/untracked 文件。

## 7. 停止规则

出现任一条件立即停止实现并回报，不得用兼容补丁掩盖：

1. 修复需要伪造 WWT range、major、grid、采样率、时间轴或单位。
2. 需要新增/扩大 `MainWindow` 多文件 mutable state，或扩大
   `test_main_window_state_ownership.py` 白名单。
3. 只能通过全局禁用 overlay nice-grid reframe 才能让 WWT 通过。
4. `set_tick_density()` 的普通 overlay 既有 reframe/Shift-wheel 合同发生变化但没有明确
   产品决策。
5. native policy 在 WWT → ordinary、empty plot、canvas rebuild 或 teardown 后仍残留。
6. 被动 capture 无法保留 native facts，除非笼统保留所有未知/transient axis_opts。
7. 核心 owner tests 必须依赖 gitignored `testdoc/` 才能运行。
8. 需要修改 WWT proposal/axis_id 才能修复本问题；这说明根因判断发生变化。
9. 同一 checkout 已有 full pytest，或 source snapshot 在 full gate 中变化。

## 8. 完成定义

只有同时满足以下条件才能标记完成：

- T0 新增用例在修复前真实失败、修复后通过；
- NLTNP-like synthetic 完整事务最终 range、AxisItem.range、tick extent 一致；
- native mode 只在显式 density 用户动作后退出；
- settle、resize、View switch、split、project reopen 不覆盖 native policy；
- 普通 overlay density/Home/Fit/Shift-wheel/new-channel Y-fit 全部保持既有合同；
- focused、boundary、stable full gate 状态诚实记录；
- 真实 Cocoa NLTNP/YP/U-Can 验收完成，截图中的右轴空带消失；
- `git diff --check` 通过，lesson 状态已清；
- 提交范围只包含本计划 owner 文件、测试与必要 lesson，不带入用户无关 dirty 文件。
