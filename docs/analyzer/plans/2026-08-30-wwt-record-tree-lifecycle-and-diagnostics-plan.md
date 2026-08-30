# WWT 原始记录归属、文件生命周期与诊断体验优化实施计划

- 日期：2026-08-30
- 状态：待实施
- 实施基线：`main@1ea1a84be3040fae2f434abf45e3404eeea63ca3`
- 对应规格：
  [`2026-08-30-wwt-record-tree-lifecycle-and-diagnostics-spec.md`](../specs/2026-08-30-wwt-record-tree-lifecycle-and-diagnostics-spec.md)
- 前置实现：2026-08-29 WWT fidelity/projection、multi-Board/24 Views、time-domain
  reflow、record-only visibility 与 Analysis viewport 两波更新。
- 交付性质：先红测、后最小 owner 修改；不重写既有 WWT 数据/布局算法。

## 0. 执行结论

本轮分为五个实现波次和一个集成波次：

```text
T0 冻结红测
  ├─→ T1 ChannelTree record presentation
  │      └─→ T2 View 接线 + 移除 Inspector 重复面
  │              └─→ T3 close/detach/project 生命周期闭环
  └─→ T4 WWT 诊断分级与文案（可与 T1–T2 并行）

T1–T4 → T5 文档/帮助 → T6 集成与前台验收
```

T1、T2、T3 共享 ChannelTree/View/MainWindow 调用链，必须串行。T4 可在 T0 后与
T1–T2 并行；若 T3 的 preview invalidation 需要改
`ultraview_workspace_controller.py`，T3 与 T4 必须串行或先重新划清该文件的单一
owner，不能并发编辑。完整 pytest 只由 T6 协调者在稳定快照运行一次，其他任务只跑
owner tests 与必要边界。

建议提交边界：

1. `test(wwt): freeze record tree close lifecycle and diagnostic copy`
2. `feat(ui): project WinWert records under their owner source`
3. `fix(ui): close file-owned WWT projections atomically`
4. `fix(wwt): localize formula failures and silence successful relocations`
5. `docs(wwt): document record tree and lifecycle behavior`

## 1. 问题 → 任务映射

| 级别 | 问题 | 规格 | 任务 |
| --- | --- | --- | --- |
| P1 | 原始记录不在所属文件树，右 Inspector 成第二控制面 | D1–D5 | T0/T1/T2 |
| P1 | close-all 后模型清了但 widget row 残留 | D7–D9 | T0/T3 |
| P1 | 单文件/物理组/detach 依赖后续 render 才可能刷新 UI | D7–D8 | T0/T3 |
| P2 | 文件关闭后可能保留旧画布/UltraView preview | D9 | T3 |
| P2 | 公式失败重复显示名称、完整公式和 `record N` | D10–D11 | T0/T4 |
| P2 | `exact_overlap_relocated` 以 `4 → 3` 形式进入黄条 | D10/D12 | T0/T4 |
| P2 | 两波更新只有 offscreen/聚焦证据，前台/全量仍有缺口 | §9–§10 | T6 |

## 2. Task 0 — 基线、契约冻结与红测

**Owner：测试与本计划状态，不改生产代码。**

### 2.1 开始前检查

1. 记录 `git rev-parse HEAD` 与 `git status --short --branch`；保留现有无关删除与
   untracked 文件，不 stage、不恢复、不清理。
2. `pgrep -fl pytest` 检查本 checkout 是否已有 full gate；T0 不跑改前全套。
3. 只跑现有受影响 owner baseline，记录当前红/绿，不用历史 pass count 代替。
4. 当前已知离屏复现必须保留为红测前提：

```text
files_after=0
bindings=2 -> 0
inspector_rows=1 -> 1
```

### 2.2 合成 fixture

复用 `tests/_helpers/wwt_factory.py`，只增加缺失 profile：

- 一个文件含普通 measurement + record-only tolerance；
- 两个 Time Views 引用同一 record，但具有独立 binding id/隐藏意图；
- 一个物理 WWT 拆成两个 logical fids，record-only Y 只属于其中一个 owner fid；
- 32-record catalog、两个 `Pars` 引用越界 `k51/k52`；
- 三个完全重叠 native rect，产生 `exact_overlap_relocated`；
- project restore 时一个 binding 的 fid/record 无法 remap。

客户 `testdoc/` 继续只作 `skip`-guarded smoke。

### 2.3 红测清单

**ChannelTree presentation** — `tests/ui/test_channel_widget.py`：

- `test_wwt_record_rows_live_under_owner_file_or_raster`
- `test_wwt_record_rows_use_view_binding_identity_not_display_name`
- `test_wwt_record_rows_follow_search_but_not_channel_bulk_checks`
- `test_wwt_record_rows_do_not_enter_axis_group_drag_or_context_menu`
- `test_set_record_rows_preserves_channel_selection_expansion_and_current_item`
- `test_record_eye_emits_view_id_binding_id_and_visibility`

**View wiring** — `tests/ui/test_wwt_import_flow.py`、
`tests/ui/test_view_channel_scope.py`：

- record rows 随 active Time View 替换；同名 binding 不串 View；
- eye 只写目标 View `hidden_curve_binding_ids`，普通 checked/binding 不变；
- 切 Analysis 隐藏 rows，返回 Time 恢复；
- 右 Inspector 不再拥有 record list/signal。

**Lifecycle** — `tests/ui/test_main_window_smoke.py`、
`tests/ui/test_analysis_source_scope.py`、`tests/ui/test_project_session.py`：

- `close_all(force=True)` 后 files、bindings、hidden ids、tree rows、canvas rows、preview
  均没有旧 source；tree rows 必须 `1 → 0`，测试不允许依赖成功 render；
- 单 source close 清所有 Time Views 的该 fid，保留 sibling source 与 View id；
- grouped physical close 原子、取消零 mutation、确认后只刷新/重绘/toast 一次；
- detach 只清 focused View，其他 View 仍能切回并显示记录；
- project replace/restore 不产生 ghost row，missing remap 可观察；
- 空 View/Board preview 不保留关闭前截图。

**Diagnostic copy** — `tests/ui/test_wwt_import_flow.py`、
`tests/ui/test_wwt_board_projection.py`：

- 两个 missing-ref `Pars` 只产生一组中文 summary，显示通道名与 `k51、k52`；
- summary 不含 `record 16`、`record 17`、完整 `abs(...)`、raw code；
- `exact_overlap_relocated` 不进 warning/黄条，`issues` 内部 code 仍可诊断；
- `dropped_curve/window`、cap、unsupported formula 仍按各自语义可见；
- generated/placed/unplaced/unprojected 数量守恒不受 formatter 影响。

### 2.4 T0 接受条件

- 新测试在当前基线因目标语义缺失而红，不因 fixture、Qt owner、event timing 或
  本机样本缺失而红。
- 红测不得断言 QTreeWidget 私有 child index；优先通过 stable item role/API 查询。
- 生命周期测试必须验证模型与 presentation 两层，不允许只断言“无 crash”。
- 不添加固定 sleep；Qt deferred delete 用现有 `qtbot`/event drain 方式。

## 3. Task 1 — ChannelTree record presentation

**Owner 文件：**

- `mf4_analyzer/ui/widgets/channel_tree.py`
- `mf4_analyzer/ui/file_navigator.py`（只做 API/signal facade 转发）
- `tests/ui/test_channel_widget.py`
- `tests/ui/test_file_navigator.py`

**禁止修改：** ViewState、MainWindow、Inspector、WWT parser/formatter。

### 3.1 新 item kinds 与 API

在现有 `file/source/raster/channel` 之外增加 presentation-only：

```text
record_group
record_binding
```

`Qt.UserRole` 建议结构：

```python
("record_group", view_id, owner_fid)
("record_binding", view_id, binding_id, owner_fid, record_index)
```

实现：

```python
set_record_curve_rows(view_id, rows)
clear_record_curve_rows()
record_curve_visibility_toggled(view_id, binding_id, visible)
```

row dict 字段按 spec D6；item data 不保存 ndarray、FileData、binding object 或 callback。
`FileNavigator` 只转发 API/signal，不复制 rows、不另存一份 visibility state。

### 3.2 层级与增量更新

1. flat file：group 加到 file node；nested grouped source：group 加到 owner raster。
2. owner fid 不存在或不 attached 时不创建 row，并返回/记录可测试的 dropped
   presentation fact；不得把 row 挂到第一个同名文件。
3. 以 `(view_id, binding_id, owner_fid, record_index)` 做稳定匹配；名称/颜色变化更新
   presentation，不改变身份。
4. rows 为空时删除所有 record groups；普通 channel items、selection、expanded、
   current item、order、colors、axis groups 保持。
5. `remove_file` / `_remove_file_tree_item` 同步清 `_record_*` presentation caches；
   重复删除幂等。

### 3.3 交互隔离

逐个审计并更新这些 predicate/iterator：

- `_check_hit_rect`：record row 无 membership checkbox；
- `_is_item_attached`：record row 可按 owner 判断可见，但不成为 channel；
- `_fids_for_node`：record group/row 不产生独立 detach 请求；父 file/raster 仍可 detach；
- `_iter_channel_items` / `get_checked_channels`：永远排除 record；
- `_sync_visibility_icon` / `_on_item_clicked`：record 走自己的 eye signal；
- `_on_item_changed` / parent `_count_channels` / `_set_all`：只传播普通 channels；
- channel drag/context/axis-group：排除 record；
- `_apply_filters`：search 命中 record name/unit/source tag；普通“已选”统计不把 record
  当 checked channel。

### 3.4 T1 聚焦验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_channel_widget.py \
  tests/ui/test_file_navigator.py -q
```

**接受条件：** ChannelTree 可独立展示/更新/清空 record subtree；所有普通文件、
grouped raster、channel checkbox、拖放、排序、搜索与 context menu 既有用例不回退。

## 4. Task 2 — View 接线与移除 Inspector 重复面

**Owner 文件：**

- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`（只改 signal wiring）
- `mf4_analyzer/ui/inspector.py`
- `mf4_analyzer/ui/inspector_sections/contextual_time.py`
- 删除无消费者后：`mf4_analyzer/ui/widgets/record_curve_list.py`
- `tests/ui/test_wwt_import_flow.py`
- `tests/ui/test_view_channel_scope.py`

**禁止修改：** file-close 主流程、WWT diagnostic、formula evaluator、UltraView layout。

### 4.1 单一同步入口

把 `_refresh_record_curve_inspector()` 替换为 `_sync_record_curve_tree(state=None)`：

1. 只有 active/focused Time View 且 Time Section 可见时生成 rows；
2. rows 从 `curve_bindings` 中 record-only Y 派生；owner = `y_ref.fid`；
3. `visible = binding_id not in hidden_curve_binding_ids`；
4. 无合法 state/files/owner/bindings 或不在 Time Section 时显式传空 rows；
5. `_project_view_controls()` 与成功 primary render 尾部都调用该入口，重复调用幂等。

不要新增 MainWindow 可变字段；当前投影缓存由 ChannelTree widget 自己拥有。

### 4.2 stale-click guard

将 handler 改为：

```python
_on_record_curve_visibility_toggled(view_id, binding_id, visible)
```

- 当前 focused View id 与 payload 不同：直接拒绝；
- binding 不存在或不再是 record-only：直接拒绝并同步 tree；
- 成功时只更新 hidden ids，按 `preserve_xlim=True` 重绘目标 canvas；
- 重绘后同步一次，不发 Navigator ordinary `channels_changed`。

### 4.3 移除重复控制面

1. 从 `TimeContextual` 删除 `RecordCurveList`、record signal 与 `set_record_curves`；
2. 从 `Inspector` 删除 relay signal；
3. 从 `window.py` 删除 Inspector record signal wiring，改接 Navigator signal；
4. `record_curve_list.py` 无消费者后删除；若存在 QSS/help/test 字面引用一并处理；
5. Time Inspector 的 `绘图` 与其他范围/滤波功能保持现有位置和语义。

### 4.4 T2 聚焦验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_view_channel_scope.py \
  tests/ui/test_view_state.py \
  tests/ui/test_time_curve_bindings.py -q
```

另跑 shrink-only signal gate：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_no_lambda_signal_connections.py -q
```

**接受条件：** 左树是唯一 eye surface；View 切换/隐藏/复制/保存恢复保持；无新的
`.connect(lambda`、无新增 MainWindow state owner。

## 5. Task 3 — detach/close/project 生命周期闭环

**Owner 文件：**

- `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`（仅 `_reset_plot_state`/close aggregation）
- 必要时 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 必要时 `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- 测试：`tests/ui/test_main_window_smoke.py`、
  `tests/ui/test_analysis_source_scope.py`、`tests/ui/test_project_session.py`、
  `tests/ui/test_ultraview_mode_integration.py`

**禁止修改：** ChannelTree item rendering、formula formatter、native layout packing。

### 5.1 明确 sync，不等 render

按 spec D7/D8 在以下成功 mutation 后调用 `_sync_record_curve_tree`：

- `_detach_files_from_focused_view`；
- `_close`；
- `_close_files` 的 batch 尾部；
- `close_all`；
- project teardown/open restore 完成；
- View delete/fallback active View 切换的既有 projection funnel。

close-all 必须显式 `set_record_curve_rows(None, ())`，不能指望 `plot_time()` 进入成功
render。single/group close 在 state filtering 后、用户 feedback 前同步。

### 5.2 聚合与一次性副作用

- single close：一次 sync、一次 replot/reset、一次 toast；
- physical group close：每 fid 只做 owner state/cache 删除，循环结束统一 sync、replot、
  preview invalidation、toast；禁止 N 次全 canvas reset；
- cancel：zero mutation；
- close-all：UltraView `reset_project_state()` 继续一次；record tree/canvas/cursor/preview
  一次清空；
- detach：只重绘 focused Time View，不 invalidate sibling View 的 source cache；
- 过滤 bindings 后总是调用 `prune_hidden_curve_binding_ids`，不留孤儿持久化 id。

若现有 `_close(fid, notify=False)` 仍会做不可聚合的 presentation mutation，应抽一个
窄的 close transaction helper，由 batch caller 控制 final projection；不要复制第二套
删除循环。

### 5.3 UltraView preview

1. 找出关闭 fid 后仍引用受影响 Time View 的 `UltraViewRef`；
2. 保留 ref/Board membership，但使旧 preview 失效；
3. 可见 View 重绘后请求新 capture，空 View 生成明确 empty preview/placeholder；
4. 关闭前启动的 capture 结果到达时必须被既有 generation/invalidation guard 拒绝；
5. close-all 继续清 Board，不额外重建。

不得为此把 fid 写入 `ui/chart_stack/` session state；协调器通过 View/ref 边界完成。

### 5.4 T3 聚焦验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_analysis_source_scope.py \
  tests/ui/test_project_session.py \
  tests/ui/test_ultraview_mode_integration.py \
  -k 'close or restore or wwt or preview' -q
```

再跑状态 owner gate：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_main_window_state_ownership.py -q
```

**接受条件：** 所有 spec D8 路径闭环；probe 变为 `rows 1 -> 0`；View/Board identity
不误删；旧 preview 不复活；不扩大 state-ownership whitelist。

## 6. Task 4 — WWT 诊断分级、公式摘要与布局静默

**Owner 文件：**

- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `mf4_analyzer/io/wwt_document.py`（仅需要中立 record/issue 查询时）
- `mf4_analyzer/io/wwt_formula.py`（只增加纯 refs/diagnostic 辅助，不扩语法）
- `mf4_analyzer/ultraview_core/native_layout.py`（共享非降级 code 定义，如采用）
- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`（消费共享 predicate）
- 测试：`tests/ui/test_wwt_import_flow.py`、`tests/test_wwt_document.py`、
  `tests/ui/test_wwt_board_projection.py`、`tests/ui/test_ultraview_native_layout.py`

### 6.1 冻结内部 code，重做用户 formatter

1. 保持 `WwtIssue.code/detail`、`WwtDocument.diagnostics` 与 evaluator error taxonomy；
2. 增加纯 formatter，例如：

```python
format_wwt_issue_for_user(issue, *, document=None) -> str | None
format_wwt_import_summary(issues, *, document=None, accepted=False) -> str
```

3. 禁止 `issue.detail` 作为未知 code 的用户兜底；未知 code 写日志并给安全通用摘要，
   编程错误仍传播；
4. `WwtImportOutcome.issues` 保留结构化事实，`summary` 才是用户文案；
5. `warnings` 若仍是用户层字段，也必须经过同一 formatter，不能再从 detail 裸拷贝。

### 6.2 公式失败关联与去重

1. 对失败 `Pars` 建立 `record_index → record name/formula/refs/concrete issue` 关联；
2. generic `skipped_channels` formula 项与 concrete evaluator diagnostic 指向同一 record
   时只保留后者；确实没有 concrete code 才归 `unsupported_formula`；
3. missing refs 使用 AST refs 与 catalog 可解析性得到全集，示例应为 `k51、k52`，
   不只展示第一个异常；
4. user summary 显示名称/数量/原因，完整公式与 `record N` 只进 debug/log 详情；
5. 保持中立措辞，不把“当前 catalog 无法解析”写成“文件损坏”。

### 6.3 单点化布局 code 分类

把以下“不是 degraded import”的 native-layout codes 做成中立共享常量或 predicate：

```text
exact_overlap
exact_overlap_relocated
quantized_collision（若已自动解决则 silent；未放置时由结构化结果说明）
duplicate_ref
invalid_rect（仅无用户损失时 silent；造成 unplaced 时用中文结果）
```

实现时必须保持“code + outcome facts”联合判断；不能一刀切隐藏真实 unplaced/cap。
至少消除当前 `_SILENT_CODES` 与 `_NATIVE_LAYOUT_SILENT_CODES` 对
`exact_overlap_relocated` 的漂移。

### 6.4 `kNN` 语义调查闸门

本任务不默认修改 resolver。先做 bounded check：

1. 用当前合成 fixture 与 `U-Can_EO3_000089.wwt` 列出 catalog 长度、Pars refs、
   可解析记录；
2. 检查仓库 WWT writer/reader/tests 是否存在独立 record id 映射；
3. 若没有证据反驳 positional semantics，只改诊断文案；
4. 若发现 `kNN` 是非 positional identity，停止 T4 UI 收口，先写独立 IO spec/red test，
   不在 formatter 中掩盖 resolver bug。

### 6.5 T4 聚焦验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_wwt_document.py \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_wwt_board_projection.py \
  tests/ui/test_ultraview_native_layout.py -q
```

**接受条件：** internal code 稳定、用户文案无 raw detail；公式失败一 record 一事实；
EO3 一条可读 warning；成功 overlap relocation 不黄；真实 unplaced/cap 仍可行动。

## 7. Task 5 — 文档、帮助与删除清理

**Owner 文件：**

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `mf4_analyzer/help/time-domain-guide.html`
- `mf4_analyzer/help/TraceLab-使用说明.html`（若当前 WWT 行存在）
- `docs/analyzer/user-guide/user-guide.html`
- `tests/ui/test_hints.py`、`tests/ui/test_quickref.py`、`tests/test_help_content.py`

步骤：

1. 把“时域 Inspector 列出 WinWert 原始记录”改为“所属文件下的 WinWert 原始记录”；
2. 明确眼睛只影响当前 View，不改普通通道、不改源文件；
3. 说明关闭/从 View 移除后记录同步消失；
4. 说明公式 warning 的“未生成”不等于整个文件导入失败；
5. 删除 `RecordCurveList` 后全仓 `rg` 不得残留 class/signal/旧 Inspector 文案；
6. 不改写历史 release notes、旧 spec 的实施时证据或版本号。

聚焦：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_hints.py tests/ui/test_quickref.py tests/test_help_content.py -q
```

## 8. Task 6 — 稳定集成、回归与前台验收

**Owner：唯一协调者。** T1–T5 全部合入稳定 snapshot 后执行。

### 8.1 changed-scope 与静态检查

1. `git status --short --branch`、`git diff --stat`、逐文件 changed review；
2. `git diff --check`；
3. `rg` stale identifiers：
   - `_refresh_record_curve_inspector`
   - `RecordCurveList`
   - `record_curve_visibility_toggled` 的旧二参数 relay
   - `时域 Inspector 列出 WinWert 原始记录`
   - 两份不一致的 `exact_overlap_relocated` silent lists
4. 确认无用户现有 dirty/untracked 文件进入 patch/commit。

### 8.2 owner 与边界门禁

先连续运行 T1–T5 列出的 owner tests，再运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py -q
```

为保护最近两波更新，再运行以下 focused regression：

- `tests/ui/test_wwt_record_only_plot.py`
- `tests/ui/test_wwt_native_render.py`
- `tests/ui/test_pg_timedomain_canvas.py` 中 View restore settlement/discrete settle
- `tests/ui/test_analysis_multiview_integration.py` 中 viewport restore/cache cases
- `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_pg_heatmap_canvas.py` 的 viewport cases
- `tests/ui/test_view_manager.py` / `test_view_tabbar.py` 的 24 time Views cases

### 8.3 完整测试门禁

本轮横跨 Navigator、View、project close、UltraView preview 与 IO diagnostic，稳定集成
后允许一次 full gate。执行前检查同 checkout 无其他 pytest，并记录前后 HEAD/dirty
scope。两个 fresh process 必须顺序运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

不得并发；异常退出、segfault、timeout、中断或运行中相关文件变化均记
`UNVERIFIED`，不能由先完成的测试推断通过。

### 8.4 macOS Cocoa 前台验收

按一条真实操作链完成，不以 offscreen 代替：

1. 打开 YP：左树文件下出现红色 tolerance record；右 Inspector 无重复列表；eye
   立即隐藏/显示且保持 X 范围；
2. 切换 View/Section 再返回：record rows 与隐藏状态属于正确 View；
3. 从当前 View 移除文件：当前 rows/曲线消失，切到 sibling View 仍保留；
4. 关闭单文件、物理文件组、全部文件：左树、画布、record rows、UltraView preview
   无旧内容；取消关闭保持全部状态；
5. 打开 D6：7 Views/7 cards、紧凑无重叠，黄条无 `4 → 3` 等内容；
6. 打开 EO3：两个公式失败只显示一条可读 warning，其他 7 个非空 View 可用；
7. 保存/重开项目：record rows、eye state、View/Board identity 与当前合同一致。

记录前台截图/步骤证据；不只检查 stylesheet token。

### 8.5 Windows frozen 验收

在 fresh Full/Lite frozen executable 分别验证：WWT 打开、record tree、eye、close-all、
EO3 warning、D6 Board。源码/offscreen/import tests 不替代 frozen 证据；未执行写
`UNVERIFIED`。

## 9. 停止条件

出现任一条件立即停止对应 Task，回到 spec/owner 设计，不扩大范围硬做：

1. 把 record-only row 放入文件树必须给它伪造普通 channel、采样率、时间轴或单位；
2. tree item 必须持有 ndarray/FileData/binding object 才能工作；
3. 实现需要用 display name 作为 identity；
4. 眼睛开关必须改全局 record store 或其他 View 才能生效；
5. 生命周期修复需要扩大 `test_main_window_state_ownership.py` 白名单；
6. close group 只能通过每 fid 完整 reset/toast 实现，无法保持原子与一次性副作用；
7. preview 清理只能通过自动删除 View/Board membership 实现；
8. `kNN` 调查证明当前 evaluator identity 语义可能错误；先独立写 IO spec，不用文案
   掩盖数据正确性问题；
9. 核心测试必须依赖本机 `testdoc/`；
10. owner 文件出现并发重叠编辑，或同 checkout 已有 full pytest 在运行。

## 10. 完成 checklist

- [ ] T0 新合同红测先红后绿，旧 Inspector-only 测试已改写，无两套 UI 断言。
- [ ] record rows 位于 owner file/raster 下，active View/identity/eye/search 合同成立。
- [ ] 右 Inspector 重复列表、signal、widget 文件与旧帮助文案全部移除。
- [ ] detach/single close/group close/close-all/project replace 每条路径模型 + UI + preview
      同步闭环，close-all `rows 1 -> 0`。
- [ ] View/Board identity 不误删，source-owned data/curve/preview 不残留、不复活。
- [ ] EO3 公式 warning 一次、中文、去重；无 raw record/code/formula；其余数据可用。
- [ ] D6 7 generated = 7 placed；成功 relocation 不进 yellow toast。
- [ ] 最近两波 WWT/Analysis focused regression 与适用边界门禁通过。
- [ ] hints、quickref、帮助、用户指南与新位置/生命周期同步。
- [ ] `git diff --check`、stale identifier scan、changed-file review 通过。
- [ ] full suite 两段结果记录；Cocoa 前台与 Windows Full/Lite 各自记录，未跑项明确
      `UNVERIFIED`。
