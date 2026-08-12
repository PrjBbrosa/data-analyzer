# 分析 View 文件/通道来源隔离 · 可撤回试运行实施计划

- 日期：2026-08-10
- 状态：可执行；Stage 1 完成并通过试运行 gate 后再决定 Stage 2
- 基线：`main` @ `1617b2d0f18205298d3468c2acb291c7938365d8`
- 设计依据：
  [`2026-08-10-analysis-view-source-isolation-pilot-spec.md`](../specs/2026-08-10-analysis-view-source-isolation-pilot-spec.md)
- 审查依据：
  [`2026-08-10-analysis-view-channel-inspector-inheritance-review.html`](../reviews/2026-08-10-analysis-view-channel-inspector-inheritance-review.html)

## 1. 交付结果

Stage 1 结束时必须得到以下可运行行为：

1. 时域、FFT、时频、FRF、阶次的每个 View 都拥有独立文件范围。
2. 每个分析 Pane 的来源只属于该 section / View / Pane。
3. 新 View 的文件、来源为空，Inspector 恢复确定性默认值。
4. 切换模式/View/Pane 完整恢复目标状态，不借用 outgoing live 控件。
5. 左侧通道树按当前模式成为时域选择器、FFT 来源选择器或只读候选树。
6. 局部移出只影响当前 View；全局关闭有依赖摘要并默认取消。
7. 老项目可迁移，项目 round-trip 保存分析 attachment；缺失文件进入 degraded-save
   guard，不静默固化丢失。
8. 不改变算法、不自动计算、不修改 Batch。
9. 以 checkpoint commits 在真实 TraceLab 中试运行；任一 NO-GO 可直接回退。

## 2. 当前基线与必须保留的事实

### 2.1 工作区

开始实施前重新确认：

```bash
git rev-parse HEAD
git status --short
git diff --check
```

本计划编写时已有两个不属于产品实现的 untracked review artifact：

- `docs/analyzer/reviews/2026-08-10-analysis-view-channel-inspector-inheritance-review.html`
- `docs/analyzer/reviews/2026-08-10-view-channel-inspector-inheritance-report.md`

实施、暂存和提交不得误收、覆盖或删除它们，除非用户另行要求。

### 2.2 已确认代码事实

- Time attachments：`ui/view_state.py:ViewState.attached_file_ids`。
- Analysis sources：`ui/analysis_view_state.py:PaneState`。
- Analysis managers：`ui/chart_stack/stack.py:128-133`，每 section 一份。
- Analysis switch pipeline：`ui/main_window/_analysis_mixin.py:175-233`。
- Shared candidate scope：`ui/main_window/window.py:2465-2499`。
- Mode switch gap：`ui/main_window/window.py:1468-1495`。
- Time attach/detach：`ui/main_window/_channel_scope_mixin.py:48-128`。
- Global destructive cleanup：`_channel_scope_mixin.py:345-403`、
  `_project_io_mixin.py:1215-1242, 1492-1522`。
- Project remap drops missing analysis refs：`ui/project_io.py:268-298`。
- Empty params apply no-op：`ui/analysis_view_bridge.py:10-16`。
- Stable logical source helper exists：`io/source_adapters.py:116-134`。

### 2.3 基线测试不是假定全绿

审查时目标集合已有一条旧合同冲突：
`test_channel_eye_column_is_only_available_in_time_mode` 仍要求分析模式隐藏整列，而生产
代码保留该列给文件移出动作。Task 0 必须重跑并记录当前结果；不得把旧红算作本次新
回归，也不得为“全绿”而保留已经被新 spec 淘汰的列语义。

## 3. 实施红线

1. 先写失败测试，再改 owner。
2. `MainWindow.files` 仍是唯一数据仓库；不得为每 View 复制 `FileData`。
3. 新持久状态只放 `ViewState` / `AnalysisViewState` / `PaneState`；投影 controller 不拥有
   第二份可变真相。
4. inactive section / inactive Pane 不从 live navigator/Inspector capture。
5. 不用 display name、短文件名或 tooltip 做身份。
6. 局部 detach 不调用 per-fid global cache invalidation。
7. 切换不自动计算。
8. Stage 1 不实现 unresolved `SourceRef`，不得半做一套并把临时运行对象写进项目。
9. 不扩大 `tests/ui/test_main_window_state_ownership.py` 白名单；若新增状态，放入明确 holder。
10. 不修改数值算法、Batch、兼容 facade 或 `CLAUDE.md`。

## 4. Checkpoint 与回滚策略

| Checkpoint | 内容 | 可单独回退 |
| --- | --- | --- |
| C0 | red tests + 现状基线记录 | 是 |
| C1 | schema 7 attachment + migration + pure dependency helpers | 是；旧程序忽略新增嵌套字段 |
| C2 | section-aware candidate / navigator projection + transition apply | 是；不含关闭语义 |
| C3 | active-context attach/detach + global dependency guard | 是 |
| C4 | project degraded-save guard + docs/hints | 是 |
| C5 | foreground pilot evidence与必要窄修复 | 是 |

建议在 `codex/analysis-view-source-isolation-pilot` 分支执行。Stage 1 不提升项目顶层
schema，所以回退到基线版本仍能读取原有 analysis sources；新增 `attached_file_ids` 会被
旧 `AnalysisViewState.from_dict()` 忽略。

## 5. Task 0 — 冻结现状与失败用例

### 5.1 目标

先把本次真正要改变的旧合同变成显式 RED，防止实现过程中把“当前偶然行为”当成目标。

### 5.2 只新增/修改测试

- Create: `tests/ui/test_analysis_source_scope.py`
- Modify: `tests/ui/test_analysis_view_state.py`
- Modify: `tests/test_project_io_analysis_views.py`
- Modify: `tests/ui/test_analysis_scope_and_xframe.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/ui/test_view_channel_scope.py`
- Modify: `tests/ui/test_project_session.py`
- Modify: `tests/ui/test_frf_main_window.py`
- Modify only if the action-column contract changes:
  `tests/ui/test_main_window_smoke.py`

### 5.3 RED 合同

至少先写以下失败用例：

1. `test_analysis_view_default_attachment_is_explicitly_empty`
2. `test_schema6_analysis_view_derives_attachment_from_all_pane_roles`
3. `test_each_section_picker_uses_its_own_active_view_attachment`
4. `test_time_view_switch_does_not_change_any_analysis_picker_or_source`
5. `test_fft_projection_never_writes_time_view_checked`
6. `test_new_view_is_empty_in_fft_fft_time_frf_and_order`
7. `test_mode_switch_applies_target_active_view_before_capture`
8. `test_local_analysis_detach_does_not_touch_sibling_or_other_section`
9. `test_local_detach_does_not_invalidate_shared_fid_cache`
10. `test_global_close_with_dependencies_defaults_to_cancel`
11. `test_explicit_global_cascade_cleans_every_reference_and_cache`
12. `test_project_missing_source_blocks_overwrite_save_by_default`

测试必须分别断言 state 和 live projection，不能只看控件文字。

### 5.4 基线命令

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_analysis_view_state.py \
  tests/test_project_io_analysis_views.py \
  tests/ui/test_analysis_scope_and_xframe.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_view_channel_scope.py \
  tests/ui/test_project_session.py \
  tests/ui/test_frf_main_window.py \
  tests/ui/test_main_window_smoke.py -q
```

记录每条既有失败的完整 node id；新增测试应按预期 RED，而不是 import error、崩溃或
fixture 泄漏。

### 5.5 完成条件

- spec A1-A15 均有至少一条自动化映射。
- 现状红/绿分类写入实施记录。
- 无产品文件改动。

## 6. Task 1 — Analysis attachment 状态与 schema 7 迁移

### 6.1 文件

- Modify: `mf4_analyzer/ui/analysis_view_state.py`
- Modify: `mf4_analyzer/ui/project_io.py`
- Modify: `tests/ui/test_analysis_view_state.py`
- Modify: `tests/test_project_io_analysis_views.py`

### 6.2 实现

1. `AnalysisViewState` 增加 ordered `attached_file_ids: list[str]`；为保留现有 positional
   constructor 兼容性，字段必须追加在全部既有字段（包括 `view_id`）之后，不能插入
   `panes`/`params` 前。
2. `_SCHEMA = 7`；`to_dict()` 显式写字段。
3. `from_dict()`：
   - 字段存在：去重、保序、按字符串规范化；显式 `[]` 保持空；
   - 字段缺失：调用唯一的 pure helper，从 payload 内 `sources/rpm/input/output` 的 fid
     首次出现顺序推导；不得补全部项目文件。
4. 增加 pure helper，例如：
   - `analysis_view_source_fids(state_or_payload)`；
   - `normalize_analysis_attachments(values)`；
   - `filter_analysis_view_for_removed_fids(state, removed)`，只操作一个 View并返回 impact。
5. `remap_analysis_view_fids()`：
   - remap schema 7 attachments；
   - schema ≤6 且字段缺失时，先 remap role，再复用同一 helper 从 remapped
     `sources/rpm/input/output` 首次出现 union 推导；
   - 不补全部项目文件。
6. `AnalysisViewState.validate()` 增加 source fid ⊆ attached 的错误；迁移后必须通过。

### 6.3 边界测试

- 两 Pane、重复 fid、四类角色、FRF 两端、显式空、缺失 fid、部分 remap。
- Duplicate 深拷贝 attachment，且 `view_id` 不同。
- 不把 source label 当 fid。

### 6.4 完成条件

- A1、A2、A8 的 state 部分通过。
- 旧项目 fixture 无字段仍能读取。
- `project_io.py` 保持 Qt/MainWindow-free。

## 7. Task 2 — 纯依赖索引与局部 mutation 合同

### 7.1 文件

- Create: `mf4_analyzer/ui/main_window/analysis_source_scope.py`
- Modify: `mf4_analyzer/ui/main_window/__init__.py` only if an existing
  monkeypatch/export seam requires it
- Create/Modify: `tests/ui/test_analysis_source_scope.py`
- Run: `tests/ui/test_main_window_state_ownership.py`

### 7.2 类型

建议定义不可变 DTO：

```python
SourceUse(
    domain,       # time | fft | fft_time | frf | order
    view_id,
    view_name,
    pane_idx,
    role,         # attachment | checked | signal | rpm | input | output
    fid,
    channel,
)
```

以及无 UI 副作用 helper：

- `collect_source_uses(fid, time_views, analysis_managers)`；
- `collect_channel_uses(fid, channels, ...)`；
- `detach_analysis_files(state, removed_fids) -> DetachImpact`；
- `analysis_scope_fids(state, files)`。

helper 读取 managers/state，但不保存 widget、cache、QMessageBox 或 MainWindow。

### 7.3 精确 mutation

- FFT：过滤所有 Pane overlay 中 matching fid。
- 时频：清 matching signal。
- Order：signal/RPM 分别清理。
- FRF：任一端匹配时清完整 pair。
- 删除 attachment 后运行 `validate()`；若不满足则测试失败，不能静默留下悬空 role。

### 7.4 完成条件

- dependency count 可稳定按 domain/view_id/pane/role 输出。
- pure tests 不构造 MainWindow。
- 不增加多文件 MainWindow state writes。

## 8. Task 3 — Section-aware candidate 刷新

### 8.1 文件

- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/analysis_context.py` only if the existing
  collaborator is the correct owner for pure lookup
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_view_mixin.py`
- Modify: `tests/ui/test_analysis_scope_and_xframe.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/ui/test_frf_main_window.py`

### 8.2 替换共享 `_update_combos()` 合同

把当前无参、单 scope 的更新改成 section-aware 单入口：

```text
_refresh_analysis_candidates(section=None)
  section given → 只刷该 section
  section None  → 文件/通道 universe 变化时逐 section 刷新
```

每个 section 从自己的 manager.active → `AnalysisViewState.attached_file_ids` 构造候选。

兼容策略：若测试或窄调用仍使用 `_update_combos()`，暂留一行兼容 wrapper 委托新入口并
标注退休；不得在 wrapper 中恢复时域 scope 旧语义。

### 8.3 刷新规则

- Analysis View switch/attach/detach：只刷新该 section。
- Time View switch/attach/detach：不刷新分析候选。
- File load/global close/channel edit：刷新所有 section。
- 对每个 combo block signals；刷新完成不得触发 `signal_changed/pair_changed` capture。
- FRF 保留 same-logical-source validation；正常 attached 状态不再使用“当前时域 View 外”
  文案。防御性 missing state 改为“来源不可用”。

### 8.4 性能

为 6 个 attached logical sources × 大通道集合增加确定性 candidate-build benchmark。
只重建受影响 section；不得在切时域 View 时四组全量重建。

### 8.5 完成条件

- A3、A4 通过。
- 旧的 `test_signal_pickers_only_offer_files_attached_to_focused_view` 等测试改为按 section
  active View 断言，不能删除覆盖后不补新合同。
- FRF、Order 各角色候选仍完整。

## 9. Task 4 — Navigator projection owner 与模式/View/Pane 切换

### 9.1 文件

- Modify: `mf4_analyzer/ui/widgets/channel_tree.py`
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_view_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/analysis_view_bridge.py`
- Modify: four contextual sections only for a public reset-to-default API
- Modify: focused widget/integration tests

### 9.2 Presentation API

用一个明确 role API 替代多个布尔残留，例如：

```text
navigator.set_projection_role("time" | "fft_sources" | "analysis_candidates")
```

角色只控制展示/交互：

- `time`：checkbox、eye、file detach 可用；
- `fft_sources`：checkbox 表示 focused FFT Pane sources，eye 不可用，file detach 可用；
- `analysis_candidates`：channel checkbox 不可编辑，eye 不可用，file detach 可用。

配置保存/应用行是 Time View 功能；分析角色下隐藏或禁用并解释，不得把通道配置应用到
分析 View。

### 9.3 统一 apply 顺序

新增单一 target-context apply funnel（符号名实施时按现有 owner 选择）：

```text
capture outgoing owner
→ set mode / active identity
→ project target attachments
→ refresh target candidates
→ apply target sources/params/range/cursor
→ render cache/empty state
```

所有入口复用：

- `_on_mode_changed`；
- `_on_analysis_view_switched`；
- `_on_analysis_focus_changed`；
- `_apply_active_view` / Time return；
- project restore final apply。

### 9.4 Channels changed 路由

- Time role：只写 focused Time View 并重绘 Time。
- FFT role：只写 active FFT View focused Pane；更新 preview/cache signature，不写 Time。
- candidate role：checkbox 不可操作；防御性 signal 直接忽略并记录诊断，不写任何 state。

不得继续让 `_ch_changed()` 无条件捕获 Time View。

### 9.5 新 View 默认

- `apply_params_from_state()` 遇到空 params 调 contextual 的 public
  `reset_to_defaults()`，而不是 no-op。
- `_apply_analysis_sources()` 对空 Pane 必须显式清空所有角色：FFT、时频、FRF、阶次
  行为一致。
- shared range 的 enabled + start/end 一起从目标 Pane apply；空范围关闭并恢复安全显示
  值，不能把上一模式数值写回新 View。

### 9.6 完成条件

- A5-A9 通过。
- 50 次无操作切换 probe 的 state serialization 前后 byte-equivalent（允许 active index
  按用户切换变化，不允许其他字段变化）。
- 切换不提交 job；缓存 miss 只显示提示。

## 10. Task 5 — Active-context attach/detach

### 10.1 文件

- Modify: `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py` wiring only if needed
- Modify: `mf4_analyzer/ui/widgets/channel_tree.py`
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `tests/ui/test_view_channel_scope.py`
- Modify/Create: `tests/ui/test_analysis_source_scope.py`

### 10.2 Attach 路由

保留 `_attach_files_to_focused_view()` 作为 Time-specific compatibility seam；新增 active
context route 给 drag/drop：

- mode=time → focused Time View；
- mode=analysis → 해당 section active `AnalysisViewState`；
- append 去重保序；
- project restore 不触发 auto attach；
- `_on_source_load_finished()` 仍只调用 Time-specific auto attach。

toast 必须包含 section + View 名，不能只说“当前 View”。

### 10.3 Detach 路由

`files_detach_requested` 改接 active-context handler：

- Time：复用现有 `_detach_files_from_focused_view()`；
- Analysis：调用 pure dependency/`detach_analysis_files()`；有来源依赖时确认默认取消；
- 只重新投影当前 section/View；
- 不刷新其他 section，不清 global cache。

### 10.4 空态

- 新分析 View：`当前“频谱 · View 2”尚未加入文件`；
- 次级提示：`从上方拖入文件；要沿用当前配置请复制 View`；
- 无占位 file/channel 节点。

### 10.5 完成条件

- A10 通过。
- Time View 1 detach B 后，Time View 2 与四种 analysis manager 的所有 state byte-equivalent。
- Analysis View 1 detach B 后，同 section View 2 和其他 section state byte-equivalent。

## 11. Task 6 — 全局 close / close-all / 通道删除依赖保护

### 11.1 文件

- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: channel editor apply flow in `window.py`
- Modify: `tests/ui/test_view_channel_scope.py`
- Modify: `tests/ui/test_frf_main_window.py`
- Modify: `tests/ui/test_task4_cache_invalidation.py`
- Modify/Create: global dependency modal tests

### 11.2 单文件 close preflight

在任何 cache/state/file mutation 前：

1. collect dependencies；
2. 无依赖 → 继续；
3. 有依赖 → 显示 Time View 数、analysis View 数、role 数和可展开摘要；
4. 默认 `取消`；
5. 只有 `关闭并从所有 View 移除` 才进入现有全局清理链。

把真实清理收敛为一个 `force`/confirmed internal path，避免 UI handler、close-all 和项目
恢复各写一套删除顺序。

### 11.3 close-all

- Navigator 原确认与 dependency preflight 合并为一次产品确认；不得连弹两次。
- 汇总所有文件依赖；默认取消。
- 确认后先 invalidate/cancel jobs，再清 state、files 和 navigator。

### 11.4 通道删除

`_apply_channel_edits()` 在修改 DataFrame 前做 channel dependency preflight。取消后：

- 不增删列；
- 不修改 Time/Analysis state；
- 不 invalidate cache；
- 不 refresh navigator。

确认后保留现有全局 per-fid cache invalidation，并清全部 matching composite keys。

### 11.5 完成条件

- A11、A12 通过。
- FRF 旧测试 `test_frf_file_invalidation_clears_pair_and_coordinator` 拆成：local detach 不
  全局失效；confirmed global close 才清 pair/coordinator。
- 任何 modal 默认按钮都是取消。

## 12. Task 7 — 项目迁移、degraded restore 与保存保护

### 12.1 文件

- Modify: `mf4_analyzer/ui/project_io.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_state_holders.py`
- Modify: `tests/test_project_io_analysis_views.py`
- Modify: `tests/ui/test_project_session.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`

### 12.2 Restore result

不要新增散落的 `MainWindow` bool。用明确 holder/dataclass 保存：

```text
ProjectRestoreHealth
  missing_paths
  missing_old_fids
  dropped_time_refs
  dropped_analysis_refs (section/view_id/pane/role)
  degraded
```

`_restore_project_file_refs()` 返回结构化结果，而不是继续扩大无名 tuple。

### 12.3 Save guard

打开项目缺失来源后：

- warning 显示跳过的分析 View/Pane 来源数量；
- `_project_restore_health.degraded = True`；
- 覆盖保存原项目或 Save As 都先确认；默认取消；
- 文案说明 Stage 1 尚未保存 unresolved refs，继续会固化当前缺失状态；
- 用户明确确认后允许保存，并清/更新 health 状态。

新建会话、完整项目恢复、close-all teardown 对 holder 对称 reset。

### 12.4 Deferred restore

保持：

- pending key 为 `(section, view_id)`；
- candidate 来自 saved PaneState；
- reorder 不改变目标；
- inactive/split Pane 不读 live controls。

### 12.5 完成条件

- A13-A15 通过。
- `tests/ui/test_main_window_state_ownership.py` 白名单不扩大。
- 项目顶层 schema 仍为 2，analysis state schema 为 7。

## 13. Task 8 — 文案、帮助和交互提示

### 13.1 文件

- Modify: `mf4_analyzer/ui/hints.py`
- Modify: `mf4_analyzer/ui/quickref.py`
- Modify: relevant empty-state strings in `ui/widgets/channel_tree.py`
- Modify: user-facing help only where current guidance still says analysis follows Time View
- Modify: focused hints/quickref tests

### 13.2 必改旧文案

退休：

- `分析只列当前 View`（未说明哪类 View）；
- `FFT / FFT-时间 / 阶次的信号框只列当前 View 已加入的文件`（当前含义是时域 View）；
- “打开只是载入；要画图/分析得先加入 View”中未说明加入哪个 active View 的部分；
- 分析模式下含混的“显示”列标题。

替换成：

- 上方文件 = 全局已打开；下方 = 当前 section / View 已加入；
- 新 View 为空；复制 View 才继承；
- 局部移出不影响其他 View；
- FFT 左侧勾选，时频/FRF/阶次右侧选角色；
- 全局关闭会检查所有 View 依赖。

### 13.3 完成条件

- A16 通过。
- `hints.py` 与 `quickref.py` 同步，没有一处继续声明分析候选来自当前时域 View。

## 14. Task 9 — 自动化集成 gate

### 14.1 Focused state/UI gate

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_analysis_source_scope.py \
  tests/ui/test_analysis_view_state.py \
  tests/test_project_io_analysis_views.py \
  tests/ui/test_analysis_scope_and_xframe.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_view_channel_scope.py \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_project_session.py \
  tests/ui/test_frf_main_window.py \
  tests/ui/test_task4_cache_invalidation.py \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_main_window_state_ownership.py -q
```

### 14.2 Boundary gate

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_packaging_imports.py -q
```

### 14.3 Full-suite gate

按仓库合同使用两个新进程，异常退出/超时一律记为 UNVERIFIED：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

最后运行：

```bash
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

不得用 focused 绿测替代 full gate，也不得把已知旧红改名为“通过”。

## 15. Task 10 — 确定性试运行与真实前台验收

### 15.1 自动化状态矩阵

准备 3 个文件 A/B/C，其中一个产生至少两个 logical sources。构造：

| Context | View 1 | View 2 |
| --- | --- | --- |
| Time | A+B+C，勾 A/B | A+C，勾 C |
| FFT | A+B，Pane0=A/B，Pane1=B | C，Pane0=C |
| FFT-time | A，Pane0=A | B，Pane0=B |
| FRF | A，A.in→A.out | C，C.in→C.out |
| Order | A+B，signal=A/rpm=B | C，signal/rpm=C |

脚本执行并比较每一步 serialization：

1. 五模式 × 两 View × 两 Pane 循环切换 50 次；
2. Time View 1 detach B；
3. FFT View 1 detach B 后取消，再确认；
4. 尝试全局 close C 后取消；
5. 保存项目、关闭、重开；
6. reorder 一个 inactive analysis View，再触发 deferred restore；
7. 比较预期 state、live source、cache/job 计数。

产生的探针和 JSON 证据放 `.state/analysis-source-isolation-pilot/`，不提交 Git。

### 15.2 性能

- 在改动前记录等量 attached sources 下 candidate build 与 projection p50/p95。
- 改动后使用相同数据、相同 QSettings 隔离环境重复。
- GO：p95 ≤ `max(基线 × 1.25, 基线 + 50 ms)`，且主线程无肉眼冻结。
- 超标先分析是否四 section 无差别重建；不得直接放宽门槛。

### 15.3 macOS 前台

真实 TraceLab 依次检查：

1. 新建五种空 View 的空态和默认 Inspector；
2. 从上方文件区拖入当前 View；
3. FFT 左侧多选、其他分析右侧选角色；
4. 模式/View/Pane 来回切换；
5. 局部 detach 确认文案和非级联行为；
6. 全局 close 依赖摘要、默认取消与明确级联；
7. 项目保存/重开；
8. 窄左栏下 section/View 所有者文案不截断或误导。

offscreen Qt 不能替代本项。记录截图、版本、commit 和操作序列。

### 15.4 GO/NO-GO 复核

逐项填写 spec §17；任一 NO-GO：

1. 停止扩大试运行；
2. 保存失败 state diff、日志和截图；
3. 回退到最近 checkpoint；
4. 只修 owner/root cause，不加“自动帮用户恢复”的隐式分支；
5. 重跑对应 checkpoint gate 后再继续。

## 16. Stage 2 — 仅在 Stage 1 GO 后另立执行 gate

Stage 2 目标是 persisted unresolved source + relink，不属于本 plan 的当前执行授权。
进入前必须补充/复核单独 spec，至少解决：

1. GUI loader 接入 neutral `LoadedSource.source_id` / `stable_source_id()`；
2. `SourceRef` 如何表达 physical path、group identity、channel 和当前 runtime fid；
3. 同路径重复加载、文件移动、group 顺序变化、通道重命名的歧义；
4. schema 7 → 下一 schema 的双向兼容；
5. unavailable state 的 Inspector/画布/项目保存合同；
6. 自动 relink 只在唯一精确匹配时发生；
7. 重新加载后旧 cache 永不复活，必须重算。

Stage 1 不预埋半成品 `SourceRef` 字段。

## 17. Spec 验收映射

| Spec | 负责 Task |
| --- | --- |
| A1-A2 | Task 1 |
| A3-A4 | Task 3 |
| A5-A9 | Task 4 |
| A10 | Task 2 + Task 5 |
| A11-A12 | Task 2 + Task 6 |
| A13-A15 | Task 1 + Task 7 |
| A16 | Task 8 |
| A17-A18 | Task 10 |

## 18. Definition of Done

Stage 1 只有同时满足以下条件才算完成：

- C0-C5 每个 checkpoint 都有独立、可审查的 diff 和对应测试证据；
- spec A1-A18 全部有 PASS/UNVERIFIED，不得留空；
- 所有切换/刷新路径无隐式 state mutation；
- 局部 detach 与全局 close 的 cache/state 边界被自动化锁定；
- 老项目迁移、显式空 View、degraded-save guard 都通过；
- `hints.py` / `quickref.py` 同步；
- focused、boundary、两进程 full suite 完成并如实记录；
- 真实 macOS 前台试运行完成；
- 用户确认 GO 后，才讨论 Stage 2 unresolved/relink 或把试运行行为变成默认正式行为。
