# Grok 分析 View 来源隔离实施与提交审查

- 审查日期：2026-08-10
- 审查基线：`1617b2d0f18205298d3468c2acb291c7938365d8`
- 审查候选：`a08afe3e98f9b04ffdfd4ca0f470d5e9a5096be1`
- 提交范围：`1617b2d0..a08afe3e`，共 6 个提交
- 变更规模：35 个文件，3,194 行新增，211 行删除
- 审查模式：只审查，不修改产品代码
- 结论：**NO-GO / NEEDS REWORK；当前不能宣称 Stage 1 或试运行计划已完成**

## 1. Findings（按严重度排序）

### [P1] 1. 当前分析 View 移出文件后，来源已清空但旧分析曲线仍留在画布上

**代码证据**

- `_detach_files_from_active_analysis_view()` 在确认后修改
  `attached_file_ids` 和 Pane 来源，只重新投影左栏、来源控件和候选；随后直接返回，
  没有调用缓存渲染或清空当前 Pane：
  `mf4_analyzer/ui/main_window/_channel_scope_mixin.py:215-256`。
- 正常的 `_render_analysis_view_from_cache()` 对空 FFT Pane、空时频/阶次 Pane 都会显式
  清图：`mf4_analyzer/ui/main_window/_analysis_mixin.py:641-734`。这证明 detach 路径漏掉
  render/clear 不是等价优化。
- 通道编辑删除来源后也只清 state、刷新候选，最后只重画时域；没有重画当前分析画布：
  `mf4_analyzer/ui/main_window/window.py:3571-3631`。

**确定性复现**

在真实 `MainWindow` 的 offscreen Qt 探针中，先向 FFT canvas 放入一条频谱曲线和一条时域
预览曲线，确认 `canvas.has_result() == True`；随后从当前 FFT View 移出该文件。结果是：

- `state.panes[0].sources == []`；
- `canvas.has_result()` 仍为 `True`；
- 原频谱和原时域预览都仍可见。

**用户影响**

左栏和 Inspector 已表达“当前 View 没有来源”，中央画布却仍展示旧结果。用户可能把历史
曲线误认为当前 View 的有效分析结果，这是比单纯视觉刷新延迟更严重的状态误导。

**要求**

局部 detach 和全局通道删除在 state mutation 完成后，必须按当前 section/View 从缓存重新
投影；当前 Pane 已无来源时清图，但不得做全局 per-fid cache invalidation。新增 FFT、时频、
FRF、阶次的可见 canvas 断言，不能只断言 state 和 cache。

---

### [P1] 2. 进入 FFT 会用当前 live Inspector 反写目标 View，目标参数可能被无声覆盖

**代码证据**

- 模式切换合同要求进入目标 section 时完整 apply 目标 View，且不得读取 outgoing/live
  Inspector 作为目标默认值：
  `docs/analyzer/specs/2026-08-10-analysis-view-source-isolation-pilot-spec.md:231-235`。
- `_on_mode_changed('fft')` 却调用
  `_apply_active_analysis_context(..., render=False, apply_params=False)`：
  `mf4_analyzer/ui/main_window/window.py:1475-1525`。
- 延迟执行的 `_enter_fft_mode()` 随即先调用 `_capture_active_analysis_view('fft')`，把尚未
  apply 的 live 参数写回目标 state：
  `mf4_analyzer/ui/main_window/window.py:1237-1264`。
- 统一 apply pipeline 本来已能在 `apply_params=True` 时恢复 state：
  `mf4_analyzer/ui/main_window/_analysis_mixin.py:194-247,265-275`。

**确定性复现**

探针设置 live FFT `nfft=4096`，目标 FFT View state `nfft=128`。进入 FFT 后：

- live `nfft == 4096`；
- state `nfft` 也从 128 变成 4096。

目标 View 并未恢复，反而被当前控件值覆盖。

**测试为何没有拦住**

`test_mode_switch_applies_target_active_view_before_capture` 明明写入
`state.params={"nfft": 2048}`，却只断言左栏 attachment 和 picker，不断言 live 参数或
序列化 state：`tests/ui/test_analysis_source_scope.py:275-287`。这违背了 Plan Task 0
“测试分别断言 state 和 live projection”的要求。

此外，造成该行为的生产改动放在题为 `test(ui)` 的提交 `9fec2ec2` 中，不利于提交级审查
和回退。

**用户影响**

模式切换、项目恢复或任何 state 与当前控件暂时不同步的路径都可能丢失目标 View 参数。
这种覆盖会进入后续项目保存，属于持久化用户意图丢失。

**要求**

恢复“先完整 apply 目标 state，再建立 render signature/决定是否复用画布”的顺序。性能优化
可以跳过无变化的 render，但不能跳过 state→Inspector apply。测试必须同时断言：目标
attachment、来源、参数、范围、live 控件以及切换前后 state serialization。

---

### [P1] 3. 全局关闭/删通道的依赖索引漏掉 exact-source 自定义 X 轴

**代码证据**

- `collect_source_uses()` 对时域只收集 `attachment` 和 `checked`：
  `mf4_analyzer/ui/main_window/analysis_source_scope.py:53-143`；
  `collect_channel_uses()` 完全依赖该结果：同文件 `:146-167`。
- 自定义 X 轴 exact-source 引用保存在 `ViewState.axis_opts`，文件/通道删除后确实会被清除：
  `mf4_analyzer/ui/main_window/_channel_scope_mixin.py:533-609`。
- 产品允许用户在文件尚未加入/通道尚未勾选时，先从全部已加载通道选择 X 轴：
  `mf4_analyzer/ui/main_window/window.py:2186-2216`。

**确定性复现**

构造一个时域 View：`attached=[]`、`checked=[]`，但 X 轴 exact source 是 `(f1, x)`。
`collect_source_uses('f1')` 和 `collect_channel_uses('f1', ['x'])` 都返回空。全局关闭或通道
删除因此不会弹依赖确认，后续 cleanup 却会清掉 X 轴意图。

**根因属于 Plan + 实现双重缺口**

Plan Task 2 的 `SourceUse.role` 只列了
`attachment | checked | signal | rpm | input | output`：
`docs/analyzer/plans/2026-08-10-analysis-view-source-isolation-pilot-implementation.md:200-247`。
它没有把轴来源、overlay primary 等会被全局删除清理的复合引用纳入“完整依赖”定义。

这同时违反 Spec 的“全局关闭必须先汇总所有依赖”和 NO-GO 条件“无完整依赖摘要时继续”。

**用户影响**

用户没有得到任何警告，View 的自定义横轴配置却被静默删除。后续曲线横坐标语义改变，
且再次保存会固化这一变化。

**要求**

先定义“所有会被全局 cleanup 擦除的 persisted refs”清单，再由依赖索引和 cleanup 共享同一
套遍历合同。至少覆盖 exact X source、checked、attachment、overlay primary、分析 signal、
RPM、FRF input/output，并补文件关闭与通道删除的默认取消测试。

---

### [P1] 4. Plan 的完成条件和试运行 gate 没有执行，当前全量门禁也不是绿色

Plan 明确规定：focused 绿测不能替代 full gate；Stage 1 还需要 50 次状态矩阵、性能
p50/p95、真实 macOS 前台证据和 A1-A18 ledger：

- `docs/analyzer/plans/2026-08-10-analysis-view-source-isolation-pilot-implementation.md:584-603`
- 同文件 `:605-661`
- 同文件 `:691-703`

Grok 留下的 `.state/analysis-source-isolation-pilot/` 证据只覆盖：

- C0：291 passed，1 个旧合同失败；
- T1-T6：45 passed，1 skipped；
- boundary：14 passed，1 skipped；
- final slice：153 passed，1 skipped；
- 中间 focused 仍曾有 388 passed / 3 failed；multiview 曾有 43 failed / 24 passed，后续
  主要通过给测试补 attachment 修复。

没有找到以下证据：

- 3 文件 × 5 模式 × 多 View/Pane 的 50 次 serialization 矩阵；
- candidate/projection 性能基线和 p50/p95；
- 真实 macOS 前台 TraceLab 操作、截图、版本和 commit 记录；
- A1-A18 的正式 PASS/UNVERIFIED ledger；
- Grok 自己执行的两进程 full suite。

本次审查在当前 HEAD 补跑得到：

| Gate | 结果 | 判定 |
| --- | --- | --- |
| approved focused slice | 342 passed | PASS，但不覆盖 Findings 1-3 |
| import/boundary slice | 9 passed，1 skipped | PASS |
| main suite，排除 acquisition | 5904 passed，9 skipped，3 deselected，**3 failed，8 errors** | FAIL |
| `tests/acquisition_ui` 独立进程 | 355 passed | PASS |
| `git diff --check` | 无输出 | PASS |
| lessons status | `lesson_required: False` | PASS |

主套件中的两条 Batch 几何失败和八条 Batch Qt teardown errors 所在产品/测试文件不在本次
变更范围内，因此**不能直接归因给 Grok**，且缺少同命令 baseline 结果，归因状态是
UNKNOWN；但 full gate 客观上仍是 FAIL。另一条
`tests/ui/test_inspector.py:283` 直接属于本次语义更新：产品已把文案改成“来源不可用”
（`mf4_analyzer/ui/inspector_sections/contextual_frf.py:565-576`），测试仍断言旧的“当前时域
View 外”。

因此，“代码已提交”成立，“Plan 完成”不成立；按照 Spec §17.3 应停止扩大试运行。

---

### [P2] 5. 非 FFT 分析的左侧树仍显示“显示”并绘制可点击 checkbox，交互所有者不清楚

**代码证据**

- header 固定为 `Channel / Pts / 显示`：
  `mf4_analyzer/ui/widgets/channel_tree.py:580-592`。
- `set_projection_role('analysis_candidates')` 只改内部布尔值，不改 header：同文件
  `:1176-1193`。
- 文件、raster、channel item 仍带 `Qt.ItemIsUserCheckable`：同文件 `:660-742`。
- 用户点击后才由 `_on_item_changed()` 强制恢复 unchecked：同文件 `:1231-1255`。

Spec A6 和 Plan Task 8 明确要求时频/FRF/阶次左栏不可勾，且分析模式不能继续显示含混的
“显示”列标题。当前实现从 state 角度阻止了写入，但视觉上仍像一个可用选择器，点击时还会
产生瞬时反馈再弹回。

**要求**

analysis-candidates 模式应移除/禁用 checkbox flag，并给第二/第三列明确的分析候选语义，或
隐藏无意义列；FFT 保留“频谱来源”选择语义，Time 保留“绘制/可见”语义。应验证实际 delegate
渲染，而不只测点击后 state 没变化。

---

### [P2] 6. 一个物理文件含多个 logical sources 时，关闭流程不是原子事务

`FileNavigator._request_close_group()` 对同一 physical rows key 的每个 fid 逐个 emit：
`mf4_analyzer/ui/file_navigator.py:500-504`。每个 fid 随后独立进入 `_close()`，并独立执行新加
的 dependency dialog：`mf4_analyzer/ui/main_window/_project_io_mixin.py:1252-1266`。

因此，一个 HDF/MF4 物理文件若展开多个 logical sources，关闭一次可能：

1. 连续弹出多个依赖确认；
2. 用户确认第一个、取消第二个后，只关闭同一物理文件的一部分 logical sources；
3. 左侧物理文件卡仍存在，但内部 source/state 已是部分关闭状态。

逐 fid emit 是 6 月旧代码，不是本次提交新增；但新 preflight 让它成为新的可见产品风险。
Spec 已承认“一个物理文件可展开多个 logical sources”，Plan 却只规定了 single-fid close 和
close-all，没有定义 physical group close 的事务边界。

**要求**

补充产品决策：物理文件卡的关闭应先聚合同组 fids，做一次依赖摘要，再一次性全部取消或
全部关闭；如果刻意允许局部关闭，就必须把 logical source 作为显式可单独关闭的 UI 对象，
不能由一次物理卡关闭隐式产生部分成功。

## 2. 总体判断：与前述产品方向一致，但实施尚未闭环

### 2.1 我认可的部分

这版 Spec/Plan 的核心模型与前述分析一致，而且比“每个 View 复制文件数据”更合理：

> 文件数据在 `MainWindow.files` 全局只存一份；Time/FFT/时频/FRF/阶次下的每个 View
> 独立保存文件关联；每个分析 Pane 独立保存来源角色。新建为空，切换恢复，复制才继承。

因此，用户所说的 `6 文件 × 6 View × 5 模式 = 180` 应理解为最多 180 条文件—上下文
关联，不是 180 份数组或分析结果副本。当前实际 View 上限仍是 Time 12、四类分析各 6，
状态量本身可控。

以下实现方向是正确的：

- `AnalysisViewState` schema 7 把 `attached_file_ids` 追加在 `view_id` 后，保持 positional
  constructor 兼容；显式空列表不会被旧迁移逻辑补满。
- schema ≤6 从 Pane roles 推导 attachment，且 `validate()` 保证来源 fid 属于 View 范围。
- `analysis_source_scope.py` 是 Qt-free 的纯 helper，没有把 widget/cache 写进 state。
- Time 新文件自动加入语义未扩散到分析 View；分析 `+` 默认空；Duplicate 显式复制并生成
  新 `view_id`。
- project restore 用 `(section, view_id)` 管理 deferred work；degraded save 默认取消，
  成功保存和 close-all 后对称清理 health holder。
- 保存 inactive section 时不从当前 live 来源控件覆盖 Pane state，这一点符合 pane-local
  ownership 合同。

### 2.2 Plan 本身值得保留的借鉴

- 用 capture → identity → attachment → candidates → source/params/range → render 的单向
  pipeline 定义切换顺序；这是解决“继承错乱”的正确方法。
- 区分局部 detach 和全局 source-universe change：局部不失效共享 cache，全局才清理所有
  引用和 in-flight job。
- 用 schema 7 的窄字段先试运行，把 unresolved/relink 留到 Stage 2，降低一次变更的风险。
- 明确要求真实前台、性能、full suite 与自动化状态矩阵，不把 focused green 当最终验收。

### 2.3 Plan 需要补强的地方

- “依赖”必须从 cleanup 会删除哪些 persisted refs 反推，不能只枚举主要信号角色；当前漏了
  exact X 轴来源。
- physical file group close 必须有原子性合同。
- “切换 View/模式”测试必须比较 state serialization 和 live projection，不能只看 picker。
- 局部 detach 的验收不仅是“不影响其他 View/cache”，还必须验证当前画布立即与 state 一致。
- checkpoint 应能独立审查/回退；不能在名为 `test(ui)` 的提交中夹入生产切换语义改变。

## 3. 六个提交逐项审查

| Commit | 内容 | 结论 | 说明 |
| --- | --- | --- | --- |
| `74f00a3b` | Spec/Plan、schema 7、pure scope helper、迁移与单测 | PARTIAL PASS | 状态模型和迁移总体正确；dependency role 设计漏 exact X 等 persisted refs，且 C0 red tests 未形成独立 checkpoint |
| `29e5e2fa` | candidate projection、切换、attach/detach、global guards | NEEDS REWORK | 主要 wiring 方向正确，但留下 stale canvas、分析树视觉语义和 channel-delete render 缺口 |
| `cf3aac03` | 清理未使用 import | PASS | 窄且无行为风险 |
| `6f431ed0` | degraded-save guard、复制、hints/quickref | PASS WITH GAPS | holder、默认取消和 reset 边界良好；A16 仍因树 header 和旧 Inspector test 不完整 |
| `9fec2ec2` | 给旧测试补 analysis attachments | NEEDS REWORK | 测试显式 seed attachment 是正确迁移方式，但该“test”提交同时修改生产 FFT mode-entry，直接造成 Finding 2 |
| `a08afe3e` | 适配 FFT smoke tests | NEEDS REWORK | 两处 seed 合理；但 `test_entering_fft_mode...` 改成进入 FFT 后手动 attach/check 并手动调用 `_enter_fft_mode()`，已不再验证自动进入合同 |

## 4. Plan Task 完成度

| Task | 判定 | 审查结论 |
| --- | --- | --- |
| Task 0 现状/RED 冻结 | PARTIAL | 有 baseline 和测试列表，但未形成纯测试 checkpoint；关键 mode-switch test 没断言 params/state |
| Task 1 schema 7/migration | PASS | attachment、显式空、旧 schema 推导、validate、duplicate 基本闭环 |
| Task 2 pure dependency | PARTIAL | 主要分析 roles 正确；Time axis refs 漏索引 |
| Task 3 section-aware candidates | PASS | picker 能按各 section active View attachment 独立过滤 |
| Task 4 transition/projection | FAIL | FFT 跳过参数 apply；candidate 模式仍有可点击外观和含混 header |
| Task 5 active attach/detach | FAIL | state scope 正确，但当前 canvas 不随 detach 清理 |
| Task 6 global close/channel delete | FAIL | 基础默认取消/级联存在；exact X 漏 preflight，物理 group close 非原子，删通道后分析画布可能 stale |
| Task 7 project/degraded guard | PASS | round-trip、missing refs 统计、默认阻止覆盖、health reset 基本正确 |
| Task 8 hints/quickref | PARTIAL | 文案主体更新，但树 header 和一条 FRF Inspector 旧断言未同步 |
| Task 9 automated gates | PARTIAL | focused/boundary 绿；两进程 full gate 当前失败 |
| Task 10 deterministic/foreground pilot | UNVERIFIED | 50 次矩阵、性能和真实 macOS 前台证据均未找到 |

## 5. Spec A1-A18 验收矩阵复核

| ID | 状态 | 依据/缺口 |
| --- | --- | --- |
| A1 | PASS | 新 analysis View attachment 显式空、round-trip 保序有单测 |
| A2 | PASS | schema 6 从 Pane roles 推导；显式空不补全 |
| A3 | PASS | 四个 section picker 按自己的 active View attachment 过滤 |
| A4 | PASS | Time View 切换不改 analysis picker/source 有集成断言 |
| A5 | PASS | FFT navigator 写入不污染 Time checked |
| A6 | PARTIAL | state 写入被拦截，但 checkbox 外观/flags 和“显示”标题未退役 |
| A7 | PARTIAL | 四 section 新 state 来源为空；没有逐 section 证明 live 默认参数与空画布一致 |
| A8 | PASS | Duplicate 深复制 attachment/source/params，`view_id` 新建 |
| A9 | FAIL | FFT mode entry 会覆盖目标 params，见 Finding 2 |
| A10 | FAIL | sibling/cache 边界通过，但当前 View detach 后画布 stale |
| A11 | PARTIAL | 基本依赖默认取消和 cascade 通过；exact X 依赖漏报 |
| A12 | FAIL | exact X channel ref 漏 preflight；分析画布删除后可 stale |
| A13 | PASS | analysis attachment/source 项目 round-trip 有测试 |
| A14 | PASS | missing source 进入 degraded-save guard，默认阻止覆盖 |
| A15 | PASS | deferred restore 继续以 `view_id` + Pane state 为事实源 |
| A16 | PARTIAL | hints/quickref 主体更新；树 header 与 FRF Inspector test 未同步 |
| A17 | UNVERIFIED | 无真实 macOS 前台多文件/多 View/五模式证据 |
| A18 | UNVERIFIED | 无 candidate/projection benchmark 和 p95 证据 |

## 6. 建议修复顺序

1. **先修 Finding 2**：恢复 target state→live 的完整 apply 顺序，并用 serialization + live
   双断言锁住。这是用户意图丢失风险。
2. **再修 Finding 1**：把 state mutation 后的当前 canvas 投影补齐，覆盖 local detach 和
   channel delete；保留共享 cache。
3. **补 dependency 统一合同**：从全局 cleanup 遍历的所有 persisted refs 生成 preflight，
   加 exact X、overlay 等测试。
4. **收口左栏投影语义**：Time / FFT / analysis-candidates 三种 role 在 header、flags、delegate
   和空态上都可见区分。
5. **确定 physical group close 原子性**，增加多 logical-source 文件的一次确认/全有或全无测试。
6. 修复 FRF 旧文案断言；恢复真正的自动 FFT entry 测试，禁止通过手动调用内部方法绕过事件链。
7. 重跑 focused、boundary、两进程 full suite；对本次范围外的 Batch 红项单独建立 baseline/归因，
   不能混写成此次通过或此次回归。
8. 最后执行 Task 10：50 次状态矩阵、性能 p50/p95、真实 macOS 前台；逐项填写 A1-A18，
   再决定 GO。

## 7. 最终结论

Grok 的核心产品模型和大部分状态所有权设计是正确的，值得沿用；schema 7、每 section/View
独立 attachment、Pane-local sources、degraded-save guard 都是有效进展。

但本次提交尚有三个会改变用户判断或用户意图的 P1 代码问题，以及一个明确未完成的试运行
验收门禁：**旧图可能伪装成当前结果、FFT 目标参数会被覆盖、全局删除会漏报并静默清掉
自定义 X 轴、Task 10/foreground/performance/full gate 未完成。**

因此建议把当前 HEAD 保持为可审查 checkpoint，不扩大试运行、不进入 Stage 2，也不要把这
六个提交标记为“Plan 已完成”。修完 P1/P2 后按本文第 6 节顺序重新验收，全部证据闭环后再
由用户确认 GO。
