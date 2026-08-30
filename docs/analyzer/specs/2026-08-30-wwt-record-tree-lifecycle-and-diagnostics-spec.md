# WWT 原始记录归属、文件生命周期与诊断体验优化 Spec

- 日期：2026-08-30
- 状态：待实施
- 当前基线：`main@1ea1a84be3040fae2f434abf45e3404eeea63ca3`
- 配套计划：
  [`2026-08-30-wwt-record-tree-lifecycle-and-diagnostics-plan.md`](../plans/2026-08-30-wwt-record-tree-lifecycle-and-diagnostics-plan.md)
- 增量前置规格：
  [`2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md`](2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md) ·
  [`2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md`](2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md)
- 相关已实施计划：
  [`2026-08-29-wwt-timedomain-plot-and-ultraview-reflow-plan.md`](../plans/2026-08-29-wwt-timedomain-plot-and-ultraview-reflow-plan.md) ·
  [`2026-08-29-wwt-and-analysis-view-state-optimization-plan.md`](../plans/2026-08-29-wwt-and-analysis-view-state-optimization-plan.md)

## 0. 结论

最近两波 WWT 更新已经修复了 record store、record-only 绘图、WinWert 颜色、
native tick、UltraView 投影事务、专属 Board、紧凑回流、24 个时域 View，以及
record-only 单条隐藏状态；这些合同继续有效。

当前结果仍是 **PARTIAL / NEEDS REVISION**，剩余问题集中在三个产品边界：

1. `WinWert 原始记录` 被做成右侧 Time Inspector 的独立列表，没有归到拥有它的
   文件/逻辑源下，造成左侧文件树与图上曲线事实不一致；
2. 文件关闭只清理了 View 模型中的 binding，没有同步清理该列表的 widget 投影，
   因而出现“文件为 0，右侧原始记录仍在”的确定性残留；
3. WWT 降级提示把公式名称、完整公式、内部 record 编号和成功的布局迁移 code
   拼成一条黄条，用户无法判断哪些数据丢失、哪些动作已成功完成。

本规格将左侧文件/通道树设为 record-only 曲线的唯一控制面，保持
`ViewState.hidden_curve_binding_ids` 为唯一用户意图 owner，并把单文件关闭、物理
文件组关闭、从 View 移除、关闭全部和项目恢复统一成显式的投影同步事务。内部诊断
继续使用稳定 code，用户层只显示去重、分级、可行动的中文结果。

## 1. 已验证证据

### 1.1 用户界面证据

- 普通通道位于左侧所属文件下；record-only 曲线位于右侧 Inspector，两个同属一个
  WWT 文件的数据面被拆开。
- 左侧文件区与通道树已经为空时，右侧仍可见 `WinWert 原始记录` 行。
- 黄色提示实例同时包含：
  - 两个未生成的公式通道；
  - `record 16: k51`、`record 17: k51`；
  - `4 → 3`、`5 → 3`、`7 → 2`。

### 1.2 当前实现证据

| 事实 | 当前 owner / 路径 | 缺口 |
| --- | --- | --- |
| record-only 显示意图 | `ViewState.hidden_curve_binding_ids` | owner 正确，继续保留 |
| record-only 右侧列表 | `RecordCurveList` + `TimeContextual` | 与文件树分裂，成为第二控制面 |
| 列表行来源 | `_refresh_record_curve_inspector()` 从 focused View bindings 临时投影 | 只在成功主画布 render 尾部刷新 |
| 文件关闭模型清理 | `_remove_file_from_all_time_views()` → `filter_curve_bindings()` + `prune_hidden_curve_binding_ids()` | 模型已清，presentation 未保证同步 |
| close-all | 过滤 View → 删除 files/tree → `_reset_plot_state()` | 没有显式清空/重投影 record list |
| record 数据 owner | `FileData.source_metadata["wwt_record_store"]` | 关闭后必须不可再被 UI/缓存引用 |
| 布局迁移 code | `exact_overlap_relocated` | workspace controller 静默，WWT coordinator 漏配 |

离屏合成复现的字面结果：

```text
files_after=0
bindings=2 -> 0
inspector_rows=1 -> 1
```

这证明残留不是“文件仍在后台打开”，而是模型清理后旧 widget 行未被清空。

### 1.3 公式提示样本

`testdoc/wwt/U-Can_EO3_000089.wwt` 当前解析得到 32 条 record。公式 record 16、17
均引用 `k51` 与 `k52`，当前 catalog 无法解析这些引用，因此两个 `Pars` 未物化：

```text
missing_formula_ref: record 16: k51
missing_formula_ref: record 17: k51
```

已验证事实仅为“当前 TraceLab catalog 无法解析引用”。在 WinWert `kNN` 是全局 id、
物理序号还是当前文件位置没有额外证据前，用户文案不得断言“源文件损坏”或“公式写错”。

### 1.4 两波更新的继承边界

本规格不重新实现以下已落地合同：

- record-only Y/X 使用真实 WWT record store，不伪造采样率、时间轴或 Navigator
  channel identity；
- channel-backed 与 record-only binding 都保留 WinWert 初始色、轴 owner、X/Y
  关系和线型；
- record-only-only View 在 Navigator 无勾选时仍能绘图；
- D6 完全重叠 View 迁移到最近合法位置，7 个 View 全部 placed；
- 多窗口 WWT 使用专属/可复用空 Board，单窗口不自动建 Board；
- 时域 View 上限 24，分析 View 上限 12；
- Analysis viewport 按 `view_id + pane_idx` 保持。

旧计划或旧测试计数不构成本规格的当前验收证据。

## 2. 术语与身份

| 术语 | 定义 | 身份键 |
| --- | --- | --- |
| 物理文件 | 用户打开的一份 `.wwt` 路径 | canonical physical path |
| 逻辑源 | 一份 WWT 按 Zeit/cohort 拆出的 `LoadedSource` | `fid` |
| 普通通道 | 已进入 `FileData.data` 的信号/成功物化公式 | `(fid, channel)` |
| WWT record catalog | 文件级只读 `WwtRecord` 元组 | `(physical file, record_index)` |
| record-only binding | View 中引用 catalog X/Y、但不进入普通通道树语义的曲线 | active `view_id + binding_id` |
| 记录树行 | record-only binding 的左树 presentation | `view_id + binding_id + owner_fid + record_index` |
| 公式失败项 | 未物化、无可绘制数据的 `Pars` | `record_index + issue.code` |

显示名称、截断文字、单位文本、颜色和 tooltip 均不得成为数据、缓存、持久化或
清理身份。

## 3. 范围

### 3.1 要做

1. 把当前 active Time View 的 record-only Y binding 投影到其拥有者文件/逻辑源下。
2. 删除右侧 Inspector 中重复的 `WinWert 原始记录` 列表；右侧保留现有绘图动作。
3. 复用现有 per-View `hidden_curve_binding_ids` 实现树行眼睛开关。
4. 为 View 切换、Section 切换、文件 detach/close/group-close/close-all、项目恢复、
   View duplicate/delete 建立单一 record-tree 同步入口。
5. 文件关闭时清理 source-owned binding、hidden id、缓存、画布与 UltraView 预览；
   不让旧 ndarray、旧曲线或旧截图继续可见。
6. 把公式失败、真实曲线/窗口丢弃、容量失败与成功布局调整分级；用户文案不泄漏
   原始 code、record 序号对或完整公式表达式。
7. 补合成红测、当前客户样本 optional smoke、帮助与交互说明。

### 3.2 明确不做

- 不把所有 `wwt_auxiliary_records` 都伪装成可绘制通道；只展示 active View 已有、
  plot-capable 的 record-only Y binding。
- 不把公式失败项做成可勾选树行；它没有有效数据。
- 不把 record-only 行加入普通 `checked`、`hidden_channels`、`colors`、axis group、
  channel config 或 Batch 通道选择。
- 不因为关闭一个文件自动删除 Time View 或 Board membership；View 可能仍含其他
  文件。只清除被关闭 source 的内容并刷新为空/剩余内容。
- 不扩展公式 AST 白名单，不在缺证据时改变 `kNN` 引用语义。
- 不改 Analysis viewport、ink/AA/raster 阈值、150 ms quiet timer、项目 schema、
  24/12 View 上限和 UltraView Board schema。
- 不把本机 `testdoc/` 客户文件提交为核心 fixture。

## 4. 产品体验合同

### D1 — 左侧文件树是唯一控制面

active Time View 含 record-only binding 时，树结构为：

```text
物理文件.wwt
└── 逻辑源 / Zeit 分组（仅多源模式存在）
    ├── 普通通道 A
    ├── 普通通道 B
    └── WinWert 原始记录 (N)
        ├── ● Tol_oben [mm]                         👁
        └── ● Md Sensor Tol. unten [Nm]             👁
```

平面文件模式下，`WinWert 原始记录 (N)` 直接位于文件节点下。多逻辑源模式下，分组
位于 `y_ref.fid` 所属 raster 节点下；不得复制到每个 sibling raster。

右侧 Time Inspector 不再显示同名列表，避免两个眼睛开关互相漂移。

### D2 — 只展示 active View 的可绘制记录

- 行集合来自 active `ViewState.curve_bindings` 中
  `binding.y_ref.kind == "wwt_record"` 的项。
- 辅助 X record、Zeit record、未被 WinWert 窗口标记为 visible 的 Y、没有 binding
  的 catalog record、失败公式均不显示。
- 切换 Time View 时整组替换；切到 Analysis Section 时隐藏 record 分组；返回 Time
  时按 focused View 重建。
- 同一 record 在不同 View 里的颜色、轴、显示意图可能不同，必须按 `view_id +
  binding_id` 区分，不能合并成全局开关。

### D3 — 眼睛语义复用现有 ViewState

- 树行眼睛只写 active View 的 `hidden_curve_binding_ids`。
- 隐藏后不删除 binding、不改变 `checked`、Navigator 普通通道、record store 或源文件。
- 立即按现有保 X 画幅路径重绘；其他 View 不受影响。
- duplicate View 深拷贝隐藏意图；save/reopen 保持；旧工程默认全部显示。
- signal 必须携带触发时的 `view_id + binding_id + visible`；若触发时 active View 已
  切换，拒绝写入，防止迟到 click 改错 View。

### D4 — record 行不参与普通通道操作

- `全选`、`全不选`、`已选`统计和父节点 checkbox 只统计普通 channel leaves。
- record group 与 record leaves 不显示 membership checkbox；只在显示列有眼睛。
- record 行不可拖入自定义 X、Analysis source、Batch、轴合并/拆分或通道排序。
- 右键普通通道菜单不对 record 行开放。
- 搜索可按记录名称、单位和 `WinWert 原始记录` 命中；清空搜索恢复原层级。
- 文件/逻辑源关闭或从 View 移除的操作仍作用于整个 source，record 子树随 owner
  一起消失。

### D5 — 密度、文本和无障碍

- 行高与普通通道一致；使用 WinWert 初始色 swatch、完整名称 tooltip 和可读单位。
- 名称省略只影响显示；tooltip 含完整名称、`WinWert record N`、所属 View 和
  “仅控制当前 View”。
- 眼睛 accessible name 使用“显示/隐藏 WinWert 原始记录：{完整名称}”。
- record group 显示当前 active View 的数量 `N`；`N == 0` 时整组不存在。

## 5. 状态所有权与接口

### D6 — 不新增 MainWindow 散状态

| 状态/事实 | 唯一 owner | 生命周期 |
| --- | --- | --- |
| record 数组 | `FileData.source_metadata["wwt_record_store"]` | file load → close |
| binding 事实 | `ViewState.curve_bindings` | View create/restore → filter/delete |
| 隐藏意图 | `ViewState.hidden_curve_binding_ids` | View create/restore → prune/delete |
| 树 item/widgets | `MultiFileChannelWidget` | active projection，可随时重建 |
| 当前画布曲线 | Time canvas | render/reset |
| UltraView 图片 | UltraView capture/preview store | View render/invalidate/reset |
| import issues | `WwtImportOutcome.issues` / load diagnostics | 本次导入与日志，不进 preset |

建议的 presentation seam：

```python
MultiFileChannelWidget.set_record_curve_rows(
    view_id: str | None,
    rows: Sequence[Mapping[str, object]],
) -> None

MultiFileChannelWidget.record_curve_visibility_toggled
# Signal payload is ``(view_id: str, binding_id: str, visible: bool)``.
```

`FileNavigator` 负责把该 signal 与 `set_record_curve_rows` 作为 facade 转发给
MainWindow；MainWindow 不直接操作 QTreeWidgetItem。

每个 row 至少包含 `binding_id`、`owner_fid`、`record_index`、`name`、`unit`、
`color`、`visible`。不得复制 record ndarray 到 widget/item data。

MainWindow 只保留一个 orchestration 入口，例如：

```python
_sync_record_curve_tree(state: ViewState | None = None) -> None
```

该入口从 active View 生成 presentation rows；没有文件、不是 Time Section、无有效
active View 或无 record-only binding 时，必须调用 `set_record_curve_rows(None, ())`。

## 6. 生命周期合同

### D7 — source 关闭是一个可观察事务

单个 fid 的顺序固定为：

```text
确认依赖
→ invalidate file-owned time/analysis caches and in-flight results
→ 从所有 Time Views 过滤 attached/checked/colors/ylims/bindings/hidden ids
→ 从所有 Analysis Views 移除 source
→ 删除 FileData 与 Navigator 文件节点
→ 同步 focused View 控件和 record tree（即使 canvas 不 render）
→ 重绘剩余数据或明确清空 canvas
→ invalidate/recapture 受影响 UltraView preview
→ 一次状态栏/toast
```

不允许依赖“下次成功绘图时顺便清理 record rows”。

### D8 — 生命周期矩阵

| 操作 | View 模型 | record tree | canvas / preview | 其他 View |
| --- | --- | --- | --- | --- |
| 从当前 View 移除 source | 只过滤当前 View | 立即重建 | 当前 View 重绘/重捕获 | 不变 |
| 关闭单 logical source | 所有 View 过滤该 fid | 立即重建 | 所有受影响可见/缓存 preview 失效 | 其他 source 保留 |
| 关闭物理文件组 | 整组 fid 原子过滤 | 循环后同步一次 | 循环后重绘/捕获一次 | 无半关闭 |
| 关闭全部 | 所有 file-owned state 清空 | 强制空 rows | canvas、cursor、preview/Board 按现有 reset 清空 | 无残留 |
| 打开/替换项目 | 先 teardown 旧投影，再 restore/remap | restore 完成后重建 | 只显示新项目 | 旧 id 不可复活 |
| 切 Time View | 不改模型 | 按目标 View 替换 | 按目标 View render | sibling 不变 |
| 切到 Analysis | 不改模型 | 隐藏/空投影 | Analysis 自己投影 | Time state 保留 |
| 删除 View | 删除其 state | 若为 active，投影 fallback View | 删除对应 capture/ref 按既有合同 | sibling 不变 |

close/group-close/close-all 的 presentation 同步必须是幂等的；重复清空不报错、不
创建新 item、不发 visibility signal。

### D9 — View/Board 身份与陈旧预览

- 关闭某个 source 后，Time View id 不自动删除；其余 source/bindings 继续存在。
- View 已为空时，时域画布进入真实 empty state，不显示关闭前最后一帧。
- 若 Board 仍引用该 View，preview 必须失效并更新为空态/剩余曲线；不得保留关闭
  文件的旧截图。
- close-all 继续沿用 `reset_project_state()` 清 Board 的现有产品语义。
- 异步 capture/job 回调必须用 source/view generation 或既有 coordinator invalidation
  拒绝旧结果，不能在关闭后复活记录曲线。

## 7. 诊断与文案合同

### D10 — 内部 code 与用户文案分层

`WwtIssue.code` 继续作为测试、日志和分支判断的稳定身份。用户 summary 通过一个纯
formatter 生成，不直接使用 `issue.detail` 兜底。

| code / 类别 | 严重度 | 用户层行为 |
| --- | --- | --- |
| `missing_formula_ref` | warning | 指明公式通道数、名称和不可解析引用 |
| `unsupported_formula` | warning | 指明当前版本不支持该公式语法 |
| `formula_axis_mismatch` | warning | 指明引用数据轴不一致，未生成 |
| `formula_shape_mismatch` | warning | 指明样本长度/形状不一致，未生成 |
| `formula_no_finite_values` | warning | 指明无有效数值，未生成 |
| `formula_nonfinite_values` | warning | 已生成但含非有限点，说明数量 |
| `dropped_curve/window` | warning | 中文说明实际跳过数量 |
| View/Board cap | warning | 使用既有可行动中文文案 |
| `exact_overlap_relocated` | success diagnostic | 不进黄色降级 toast，不显示箭头对 |
| `auto_range` / `hidden_axis` 等 | internal/silent | 不进用户 toast |

`_SILENT_CODES` 与 `_NATIVE_LAYOUT_SILENT_CODES` 对共有 code 必须有单一共享定义或
共享 predicate，禁止两份列表再次漂移。

### D11 — 公式失败去重与可读内容

- 同一个失败 `Pars` 只形成一个用户项，不能同时出现“未导入公式文本”与
  `record N: kM` 两份重复事实。
- formatter 可用 `document.records[record_index]` 把内部 record 号解析为通道名；
  内部 record 号只进入 debug/log 详情。
- 缺失引用集合从公式 AST refs 与当前 catalog 可解析性计算，不能只显示第一个抛错
  的 `k51`；示例中应汇总 `k51、k52`。
- 黄色 summary 不展开完整公式，避免横向撑满窗口；公式表达式可留在日志/复制详情。
- 用户文案不归责源文件，使用“当前文件解析结果中无法解析”或“当前版本暂不支持”。

推荐文案：

```text
2 个 WinWert 公式通道未生成（Abtrieb – mech. Krafteinleitung、
Theor. F_Spust. min）：当前文件解析结果中无法解析引用 k51、k52。
其余可读取数据已导入。
```

多原因时按原因分组，不超过两行；完整名称可在详情/tooltip 中查看。不得出现：

```text
record 16: k51
4 → 3
exact_overlap_relocated
abs(k51-(...))
```

### D12 — 成功布局不伪装成错误

`4 → 3`、`5 → 3`、`7 → 2` 表示重叠 View 已迁移到合法位置，是成功布局事实：

- 不进入 yellow warning；
- 不计入 `unplaced` 或“未导入”；
- generated/placed/unplaced 守恒仍由结构化 outcome 给出；
- 如产品需要说明，只能作为普通完成信息“3 个重叠 View 已自动调整位置”，不能
  暴露内部源序号对。

## 8. 持久化、兼容与性能

### D13 — 不升级 schema

- 继续复用 `curve_bindings` 和 `hidden_curve_binding_ids`；旧项目默认 rows 可见。
- tree rows、展开状态和 import toast 不进入项目 schema。
- project restore 先 remap/filter binding，再投影 rows；无法恢复的 fid/record 必须
  产生既有 degraded health/issue，而不是 ghost row。
- 普通 CSV/MDF/HDF/TDMS 工程序列化结果不得变化。

### D14 — 不复制数据，不扩大热路径

- 树投影复杂度只与 active View 的 binding 数量有关，不遍历/复制 record ndarray。
- `set_record_curve_rows` 应按 stable row key 做最小更新或一次小规模 subtree 重建；
  不重建整个文件树，不改变普通通道 selection/expanded/current item。
- 搜索和 role 切换不得触发 WWT 重新解析或公式重算。

## 9. 验收矩阵

### 9.1 合成核心合同

| 场景 | 必须断言 |
| --- | --- |
| 普通通道 + record-only tolerance | record group 位于 owner 文件/raster 下；普通通道与记录同时可见 |
| record-only-only View | Navigator 无普通勾选仍显示 record rows 并可绘图 |
| 两个 Time Views | rows 随 active `view_id` 替换；隐藏不串 View |
| eye toggle | 只改目标 View hidden id；不改 checked/binding/source |
| 搜索/全选/轴组/拖放 | 搜索命中；其他普通通道操作忽略 record rows |
| detach current View | 当前 View rows/曲线消失；其他 View 保留 |
| close single source | 所有 View binding 被过滤；focused rows 同步清除 |
| close physical group | 原子关闭；只同步/重绘一次；无 half-state |
| close all | `files == 0`、bindings/hidden ids/rows/canvas/preview 均无旧内容 |
| project round-trip | rows 与 per-View visibility 恢复；缺 source 不生成 ghost row |
| missing formula refs | 一条中文分组 summary；包含名称/refs；无 raw record/code/formula |
| exact overlap relocation | 7 generated = 7 placed；黄色 toast 无箭头/raw code |

### 9.2 真实样本 optional smoke

- `YP_SS_000089.wwt`：1 View、红色 `Tol_oben` 与深蓝测量线；原始记录位于所属
  文件树；关闭文件后行与曲线均消失。
- `NLTNP_000089.wwt`：1 View、4 曲线、2 个速度/扭矩轴槽合同保持；record-only 行
  不在右 Inspector 重复出现。
- `U-Can_D6-CSER double_00479.wwt`：7 View、7 placed、无布局 raw code toast；
  View 6/7 record-only XY 可绘图。
- `U-Can_EO3_000089.wwt`：7 个非空 View；两个失败公式形成一条可读 warning；
  toast 不含 `record 16`、`record 17` 或箭头对。

### 9.3 边界门禁

- ChannelTree owner/interaction：`tests/ui/test_channel_widget.py`、
  `tests/ui/test_view_channel_scope.py`。
- WWT flow/binding/render：`tests/ui/test_wwt_import_flow.py`、
  `tests/ui/test_time_curve_bindings.py`、`tests/ui/test_wwt_record_only_plot.py`、
  `tests/ui/test_wwt_native_render.py`。
- lifecycle/project：`tests/ui/test_main_window_smoke.py`、
  `tests/ui/test_analysis_source_scope.py`、`tests/ui/test_project_session.py`。
- UltraView：`tests/ui/test_wwt_board_projection.py`、
  `tests/ui/test_ultraview_native_layout.py`。
- 适用结构门禁：state ownership、no-lambda、backref invariants、import boundaries、
  native import boundaries、QSS border shorthand。

## 10. 完成定义

1. 左树是 record-only 的唯一控制面；右 Inspector 无重复列表。
2. 所有 lifecycle 矩阵路径都有自动化测试；close-all 红测从
   `rows 1 -> 1` 变为 `rows 1 -> 0`，且不依赖成功 render。
3. source-owned binding、hidden id、data ref、canvas row 和 preview 不在关闭后存活；
   View/Board 身份遵循 D9，不被误删。
4. 公式 warning 去重、中文化、按原因分组；成功 relocation 不进黄条；原始 code、
   record 对、完整公式不外泄。
5. 两波既有 WWT/Analysis 合同的聚焦回归全绿；无扩大 MainWindow state ownership
   白名单、无 display-name identity、无 record ndarray copy。
6. hints、quickref、时域帮助和用户指南同步新的左树位置与关闭语义。
7. `git diff --check` 与适用 docs/link/identifier 检查通过。
8. macOS Cocoa 前台、完整两段 pytest、Windows frozen-app 各自执行并记录；未执行
   必须明确为 `UNVERIFIED`，不得由 offscreen 结果替代。
