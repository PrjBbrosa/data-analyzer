# WWT 可发现性与 Analysis View viewport 状态优化计划

- 日期：2026-08-29
- 状态：已实施（offscreen 门禁通过；macOS Cocoa 前台、全套 pytest、Windows frozen 均为 `UNVERIFIED`）
- 实施基线：`feat/wwt-timedomain-plot-ultraview-reflow@af5174e4`（2026-08-29）
- 历史计划起点：`main@377c20d4`（不要把下面的 dirty 当成本轮产物）
- 对应问题报告：
  [`2026-08-29-wwt-and-analysis-view-state-issue-report.md`](../reviews/2026-08-29-wwt-and-analysis-view-state-issue-report.md)
- 相关既有计划：
  [`2026-08-29-wwt-import-fidelity-and-projection-hardening-plan.md`](2026-08-29-wwt-import-fidelity-and-projection-hardening-plan.md)
  [`2026-08-29-wwt-timedomain-plot-and-ultraview-reflow-plan.md`](2026-08-29-wwt-timedomain-plot-and-ultraview-reflow-plan.md)

> 本计划只处理问题报告确认的两项 P1 与两项 P2。既有 WWT 解析、公式求值、
> record store、native axis/tick、WinWert 颜色、UltraView 原生布局与投影不变量
> 继续作为基线，不重复改造，也不把客户样本变成核心测试依赖。
>
> **P2-A 数量验收已随排版计划覆盖：** 本分支 U-Can 7 窗重叠卡走
> `exact_overlap_relocated`，全部 placed，不再进未放置托盘。守恒式是
> `generated = placed + unplaced + 未投影`；D6/U-Can 合成断言为
> `placed == 7`、`unplaced == ()`，而不是旧稿「7 = 6 + 1」。

### 实施记录（2026-08-29）

- 工作区：`feat/wwt-timedomain-plot-ultraview-reflow`，HEAD `af5174e4`。产品改动未提交。
- 与本计划无关、实施时未回滚的脏树：删除的 branding/icon/WWT 模板、help 面板截图、
  `docs/reports` 图，以及未跟踪的 `code_stats_report.html` / `ssh-keygen*`。
  `tests/test_help_content.py::test_manual_uses_current_real_ui_assets` 因这些截图缺失会红，不算本轮回归。
- Offscreen 已跑：Task 1–4 owner（含 `test_pg_line_canvas.py` / `test_pg_heatmap_canvas.py` /
  `test_project_session.py` / UltraView native+entry+page 托盘用例 / WWT import flow）与
  Task 5 边界门禁；`git diff --check` 通过。
- 收口时修了两处实施缺陷：`channel_tree.grouped_source_raster_tooltip` 对 pandas
  `DataFrame` 做 `or []` 真值判断导致 HDF 加载弹出 `QMessageBox.critical`；
  `board_ops.apply_native_layout` 去掉对 `native_layout` 的 AST 反向导入，打破
  排版分支上已有的 `native_layout ↔ board_ops` 循环。
- 未跑：macOS Cocoa 前台逐项、客户样本 optional smoke、全套 pytest、Windows frozen-app。

## 0. 执行结论与产品决策

### 0.1 优先级与提交边界

按以下顺序实施，每个状态模型单独成可回滚提交：

1. **P1-A：Analysis View + pane 的 X/Y viewport 保持**；
2. **P1-B：WWT record-only 辅助线的单条可见性**；
3. **P2-A：WWT → UltraView 的生成/已放置/未放置数量闭环**；
4. **P2-B：同采样率 WWT 逻辑源的可区分标签与 tooltip**；
5. 文档、前台验收与稳定里程碑门禁。

P1-A 与 P1-B 不共用状态字段、不合并红测；P2 不能阻塞 P1 的交付。

### 0.2 “重新计算”后的 viewport 规则

本计划采用问题报告 §4 的默认建议，使计划可以直接实施：

- 用户明确点击 FFT、FFT-vs-Time 或 Order 的“计算/重新计算”时，只清空本次
  目标 `View + pane` 的旧 X/Y viewport；新结果先按 Inspector 的 X/Y 设置或
  结果有效范围成图，再把最终实际范围写回该 pane。
- View 切换、Section 离开/返回、同一缓存结果重绘、UltraView 捕获均不是重新
  计算，不得清空 viewport。
- 项目打开时的内部恢复计算不是用户“重新计算”。保存的 viewport 在新结果范围
  仍有有效交集时按原值恢复；范围非有限、退化或与新结果完全不相交时，回退到
  Inspector/结果范围并替换掉失效状态，不显示空图。
- 如果产品最终希望“重新计算后有交集就保留旧 viewport”，应在 Task 0 前修改
  本节并补裁剪样例；不得在实现中临时猜测。

### 0.3 viewport 的精确范围

- FFT：只持久化上方主频谱的 X/Y；下方时域预览继续使用现有
  `PaneState.time_range` 语义，不塞入 viewport。
- FFT-vs-Time / Order：持久化主热图的 X/Y；一维 slice 继续从热图 live view
  派生，不独立持久化。
- 热图色标 Z 继续使用现有 `z_auto/z_floor/z_ceiling` 与 split lock 语义，不进入
  X/Y viewport。
- FRF 已有 `PaneState.xlim/ylims` capture/restore，行为只做回归保护，不在本轮
  重写。
- split pane 始终各自存储 viewport。`compare.x_linked=True` 时，用户明确启用的
  X 联动可以同步两个 pane，但必须把两个 pane 的最终 X 范围分别提交；关闭联动
  时不得串写 sibling pane，更不得污染其他 View。

## 1. 状态所有权与接口设计

| 用户意图 | 唯一 owner | 持久化形态 | 明确不做 |
| --- | --- | --- | --- |
| FFT/热图主画幅 | `AnalysisViewState.panes[pane_idx]` | 复用 `PaneState.xlim` / `PaneState.ylim` | 不新增 `MainWindow` 散状态，不把 Z 混入 |
| WWT 原始辅助线隐藏 | 当前 TimeDomain `ViewState` | 新增 `hidden_curve_binding_ids: list[str]` | 不伪造 channel，不写 Navigator 勾选状态 |
| 原始辅助线事实 | `TimeCurveBinding` | 既有稳定 `binding_id`、名称、颜色、record ref | 不删除 record，不修改原 WWT 文件 |
| WWT 投影数量结果 | WWT import outcome + UltraView 投影结果 DTO | 本次 generated/placed/unplaced/board id | 不从 toast 文案反解析计数 |
| WWT 逻辑源标签 | `ChannelTree` presentation | 从 `FileData`/`source_metadata` 派生 | 不用显示名称替代 fid/channel identity |

### 1.1 Analysis canvas viewport seam

在 canvas owner 内提供一致的最小接口，MainWindow 不直接读取 `_plot`、`_plot_amp`
或 ViewBox 私有字段：

- `capture_xy_viewport() -> (xlim, ylim) | None`：只返回 finite、非退化的主图范围；
- `restore_xy_viewport(xlim, ylim) -> bool`：结果已绘制后一次应用 X/Y，失败返回
  `False` 让 orchestration 回退；
- `viewport_intent_committed`：只在用户平移、滚轮/框选缩放以及“查看全部”完成时
  发出；普通 `plot_spectra`、`plot_or_update_heatmap`、cache render 不得冒充用户
  意图。

保留现有 `manual_zoom_changed` 的 UI/质量语义，不复用其 `False` 同时代表 render 与
View-All 的模糊布尔值。新 signal 通过命名 slot 或 `functools.partial` 连接，不能扩大
`.connect(lambda ...)` ratchet。

### 1.2 capture / render / restore 顺序

统一路径为：

```text
用户手势或 View-All
  -> canvas 提交最终 X/Y
  -> 按 stable view_id + pane_idx 写 PaneState

View/Section/cache 恢复
  -> 应用目标 View 的 params/sources
  -> 绘制结果并完成最终 geometry/slice
  -> 恢复该 pane 的 X/Y
  -> 恢复 overlay/cursor，通知 UltraView
```

具体约束：

- `_capture_active_analysis_view()` 对 `fft`、`fft_time`、`order` 捕获所有已成图
  pane 的 viewport；FRF 继续走 `_capture_frf_canvas_ranges()`。
- cache render、同步 cache hit 与异步 worker completion 必须汇入同一个
  `_restore_analysis_pane_viewport(section, state, pane_idx, canvas)` 收口，禁止只修
  tab-switch 路径。
- restore 以 `view_id + pane_idx` 识别 owner；异步结果若已不属于当前 active View，
  只入 cache/pin，不投影到可见 canvas。
- Inspector 明确应用 X/Y 设置时，先清空当前目标 pane 的旧 viewport，再按新参数
  render，并捕获 render 后的实际 X/Y，形成新的权威 viewport。
- “查看全部”保存 canvas 的实际最终范围：FFT 包含现有 visual padding；热图保持
  image extent 的 flush-edge 语义。不能另算一套近似范围。

### 1.3 WWT record-only 可见性

- `hidden_curve_binding_ids` 默认空；旧项目打开即维持当前“全部显示”行为。
- 只允许 `y_ref.kind == "wwt_record"` 的 binding 进入“原始辅助曲线”列表和该隐藏
  集合；channel-backed binding 仍只服从 Navigator。
- `bound_time_plot_rows()` 在 resolve 前按 binding id 跳过被隐藏的 record-only 行；
  不产生 dropped/unknown issue，也不改变 `claimed_channel_keys`。
- binding 因文件/通道删除而被过滤时，同步清理已不存在的 hidden id；复制 View
  深拷贝该用户意图，项目保存/重开保持。
- UI 放在 Time contextual Inspector：无 record-only binding 时整段不出现；有记录
  时显示名称、WinWert 原始色、`WinWert 原始记录`来源标记和眼睛开关。widget 只发
  `binding_id + visible`，由 MainWindow 写当前 ViewState 并按现有保画幅路径重绘。

### 1.4 P2 可发现性

**UltraView 数量闭环**

- 原生投影返回结构化结果：目标 `board_id`、本次 generated ids、placed ids、
  unplaced ids、warnings。兼容入口仍支持现有二值解包
  `(placed_view_ids, warnings)`，避免破坏测试和外部 seam。
- `WwtImportOutcome` 增加 `placed_count`、`unplaced_count` 与 `board_id`；accepted
  导入即使没有 warning，也显示一次完成信息，例如：
  `已生成 7 个 WinWert View：6 个已放置，1 个在未放置区`。
- 所有 View rail 的 UltraView 入口同步显示当前 Board 的未放置 badge；普通点击仍
  打开 Board，点击 badge 直接打开对应 Board 的未放置托盘并聚焦首项。托盘内继续
  复用现有“放入自由网格”动作，不新增第二套 placement 算法。
- 数量验收始终断言 `placed + unplaced == 本次进入该 Board 的 generated Views`；
  View cap 或 Board cap 另列为未投影，不混进 unplaced。

**逻辑源标签**

- 仅对 `source_kind == "wwt"` 的 grouped source，ChannelTree raster 行使用稳定、
  可区分的展示，例如 `1.0 kHz · Zeit 0`；多个 Zeit record 时展示稳定摘要。
- tooltip 至少包含 Zeit record id、样本数、通道数和已注入 Pars 公式通道数。
- 其他格式的 grouped source 保持现有 `_fmt_rate(fd.fs)` 行为。
- 搜索仍直接命中叶子通道名，包括 `Diff.Moment A` 等公式通道；任何 label/tooltip
  都不得参与数据、缓存、轴、保存或颜色 identity。

## 2. 任务拆分

### Task 0 — 基线、决策冻结与红测

**只改测试与计划状态；不跑改前全套。**

1. 记录 `git rev-parse HEAD`、`git status --short`，确认没有覆盖当前 dirty 文件；
   检查是否已有 pytest 在本 checkout 运行。
2. 将 §0.2 的重新计算规则作为实施默认；如产品修改规则，先更新本计划再写红测。
3. 用仓库内合成 fixture 建立红测：
   - record-only 两条线独立开关、普通 channel-backed 行不受影响；
   - FFT/FFT-vs-Time/Order 的 View + pane viewport 切换保持；
   - View-All、Inspector Apply、显式重新计算三条不同语义；
   - split pane（X link off/on）与其他 View 隔离；
   - WWT 投影 generated/placed/unplaced 数量闭环；
   - 同 Fs 逻辑源显示可区分且搜索命中 Pars 通道。
4. 客户样本测试只能是 `skip`-guarded optional smoke；核心红测复用/扩展
   `tests/_helpers/wwt_factory.py`。

**接受条件**：红测因缺少目标语义失败，不因 fixture、Qt owner、信号时序或本地
`testdoc/` 缺失失败；每条报告验收都有唯一测试落点。

### Task 1 — Analysis viewport 模型与 canvas owner API

**文件**：

- `mf4_analyzer/ui/analysis_view_state.py`
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- `tests/ui/test_analysis_view_state.py`
- `tests/ui/test_pg_line_canvas.py`
- `tests/ui/test_pg_heatmap_canvas.py`

**步骤**

1. 将 `PaneState.xlim/ylim` 注释与校验从 FRF-only 拓展为 analysis primary X/Y；
   继续 tolerant-read 旧 schema，无需仅为语义泛化增加 schema 字段。
2. 为 line/heatmap canvas 实现 §1.1 的 capture/restore API；复用项目现有 finite、
   degenerate range 判据，不发明第二个阈值。
3. 手势、框选、modifier wheel 与 context/toolbar View-All 都提交 intent；render、
   empty state、file-close `full_reset()` 不提交。
4. Heatmap restore 后同步 slice；FFT restore 只操作主频谱，不改 time preview。
5. 冻结 View-All 视觉合同：FFT 保存 padded bounds，heatmap 保存原始 image extents。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_analysis_view_state.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py -q
```

**接受条件**：canvas API 不泄漏私有 ViewBox；View-All 后 capture 的值等于实际
`viewRange()`；Z levels 与 slice range 既有测试不回退。

### Task 2 — Analysis View capture、恢复与失效策略

**文件**：

- `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- `mf4_analyzer/ui/main_window/_fft_mixin.py`
- `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- `mf4_analyzer/ui/main_window/_order_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`
- 必要时 `mf4_analyzer/ui/analysis_view_bridge.py`
- `tests/ui/test_analysis_multiview_integration.py`
- `tests/ui/test_project_session.py`
- `tests/ui/test_split_layout_alignment.py`

**步骤**

1. 把新 canvas signal 接到 stable `view_id + pane_idx` slot；active section/View 不匹配
   时拒绝写入。
2. 在离开 View/Section 与项目保存 capture 时，将每个已成图 pane 的主 X/Y 写回
   `PaneState`。
3. 建立一个 restore funnel，覆盖：
   - FFT `_plot_fft_entries` 后；
   - FFT-vs-Time / Order cache render 后；
   - 同步 cache hit 与异步 worker completion 后；
   - project-open 内部恢复计算后。
4. 用户 Compute 入口在 dispatch/cache lookup 前清空目标 pane viewport；内部
   `_recompute_restored_analysis_view` 不调用该失效入口。
5. Inspector X/Y apply 清旧值、render、捕获新值；一般 cache render 不再无条件
   用 Inspector 覆盖已保存 viewport。
6. View duplicate 深拷贝 viewport；new View/new pane 为空；linked X 只提交实际被
   联动的 pane，link off 时严格隔离。
7. 保持 restore projection guard：程序化 apply 不触发用户编辑回调、不提交新 job，
   hidden section 不投影 shared Navigator/Inspector owner。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_project_session.py \
  tests/ui/test_split_layout_alignment.py \
  tests/ui/test_analysis_source_scope.py -q
```

另单独保留门禁：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_analysis_multiview_integration.py::test_order_view_switch_with_cold_cache_does_not_submit_worker \
  tests/ui/test_project_session.py::test_open_project_keeps_analysis_empty_owner_after_time_view_restore -q
```

**接受条件**：三类 Section、两 View、两 pane 的手势/View-All 均可往返；显式重新
计算重置，普通 cache render 不重置；无额外 worker submission；FRF 既有范围保持。

### Task 3 — WWT 原始辅助曲线列表与单条开关

**文件**：

- `mf4_analyzer/ui/view_state.py`
- `mf4_analyzer/ui/time_curve_bindings.py`
- `mf4_analyzer/ui/inspector_sections/contextual_time.py`
- 必要时新增 `mf4_analyzer/ui/widgets/` 下的纯 presentation list widget
- `mf4_analyzer/ui/inspector.py`
- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/project_io.py`

**测试**：

- `tests/ui/test_view_state.py`
- `tests/ui/test_time_curve_bindings.py`
- `tests/ui/test_wwt_view_import.py`
- `tests/ui/test_wwt_import_flow.py`
- `tests/ui/test_main_window_smoke.py`

**步骤**

1. 新增并 round-trip `hidden_curve_binding_ids`；duplicate/remap/filter/close-file 同步
   保持或清理。
2. `bound_time_plot_rows()` 只跳过明确隐藏的 record-only binding；普通 channel
   的 checked/claimed/successful 语义不变。
3. Time contextual panel 从 active `ViewState.curve_bindings` 投影 record-only 行；
   View 切换、项目恢复、文件关闭时刷新，空列表隐藏。
4. 眼睛开关写当前 View 的 hidden ids，立即按现有 `preserve_xlim=True` 路径重绘；
   不触发 Navigator channel check、不修改 binding、不写源文件。
5. 用原始颜色绘制 swatch；名字来自 `display_name`，identity 始终是 `binding_id`。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_view_state.py \
  tests/ui/test_time_curve_bindings.py \
  tests/ui/test_wwt_view_import.py \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_main_window_smoke.py -k 'wwt or binding or auxiliary or view_state' -q
```

**接受条件**：每个 record-only 行独立开/关；只影响当前 View；主曲线、轴、统计、
Navigator 和其他 View 不变；save/reopen 后保持；真实样本缺失不使核心测试失败。

### Task 4 — UltraView 数量闭环与 WWT 逻辑源标签

**文件**：

- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/widgets/ultraview_entry.py`
- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/widgets/channel_tree.py`

**测试**：

- `tests/ui/test_ultraview_native_layout.py`
- `tests/ui/test_ultraview_entry.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_wwt_import_flow.py`
- `tests/ui/test_channel_widget.py`

**步骤**

1. 增加可二值解包的结构化 projection outcome；从真实 Board 最终状态计算本次
   placed/unplaced，不能由 overlap warning 数量推断。
2. WWT accepted outcome 始终生成完成摘要；warning 仍走现有分级，不把 accepted
   overlap 重新伪装成错误。
3. Entry 提供未放置 badge、accessible name、tooltip 与 badge hit target；点击 badge
   通过 coordinator 打开目标 Board 的托盘并聚焦首项。
4. 复用现有 `UnplacedTray` place action；验证插入自由网格后 count/badge/summary
   全部刷新。
5. ChannelTree 仅对 WWT grouped source 生成 Zeit-aware label/tooltip；公式通道搜索
   继续命中叶子。
6. 集成测试至少一条调用真实 WWT → UltraView 投影 seam，不用 lambda 替换 owner
   边界；同时断言失败零 mutation、warning-bearing partial placement 完整 commit。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_native_layout.py \
  tests/ui/test_ultraview_entry.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_channel_widget.py -q
```

**接受条件**：数量守恒 `generated = placed + unplaced + 未投影`。本分支 U-Can /
D6 合成因 overlap relocated 而为 7 generated = 7 placed + 0 unplaced（托盘为空，
badge 为 0）；导入完成信息字面正确。未放置路径仍用合成 overflow 覆盖：badge 可
直达托盘，放入网格后 badge 归零。两个同 Fs source 标签可区分，公式通道搜索可见，
复合 identity 不变。

### Task 5 — 集成、文档与前台验收

1. 更新新增交互对应的 `mf4_analyzer/ui/hints.py` 与
   `mf4_analyzer/ui/quickref.py`；同步时域指南/用户指南中的 WWT 辅助线开关与
   Analysis View viewport 行为。
2. 先跑 Task 1–4 owner tests，再跑边界门禁：

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

3. 本机客户样本仅作 optional smoke：
   - `U-Can_D6-CSER double_00479.wwt`：7 View、6 placed + 1 unplaced、View 2 的
     `Diff.Limit A` 可独立开关；
   - `U-Can_EO3_000089.wwt`：原文件 visible 的 record-only 行逐条出现；
   - 核对公式通道、X binding、颜色和 source cleanup，无普通 Time-Y 意外 fallback。
4. macOS Cocoa 前台逐项验收：
   - FFT/FFT-vs-Time/Order 的拖动、滚轮、框选、View-All，跨 View/Section 返回；
   - split pane link off/on；Inspector Apply；显式重新计算；
   - record-only 眼睛、列表密度、色点与 View 切换；
   - UltraView badge、托盘直达和放入自由网格；
   - 同 Fs WWT source 标签、tooltip、搜索。
5. 稳定集成里程碑若需要全套，只运行一次，并按仓库规则分两个新进程顺序执行：
   main suite `--ignore=tests/acquisition_ui` 完成后再跑 `tests/acquisition_ui`。运行前后
   记录 HEAD/dirty scope；相关文件在运行中变化则结果记 `UNVERIFIED`。
6. `git diff --check`、changed-file review、计划 checklist 收口。未跑的 Cocoa 或
   Windows frozen-app 证据明确写 `UNVERIFIED`，不得用 offscreen 代替。

## 3. 停止条件

出现任一情况应停止对应任务并回到计划/产品决策，不得扩大范围硬做：

1. record-only 开关需要伪造采样率、时间轴、工程单位或 Navigator channel identity。
2. Analysis viewport 需要扩大 `test_main_window_state_ownership.py` 白名单或新增跨
   mixin 可变状态，而不能由 `PaneState` 所有。
3. View restore 只能通过调用普通 `do_*` 用户入口完成，导致程序化恢复提交 worker
   或覆盖 live Inspector。
4. X/Y restore 必须改动 Z level、slice 独立状态、FRF panel ranges 或 TimeDomain
   viewport 才能通过。
5. P2 标签需要把展示文本写入 cache/persistence identity。
6. 核心测试必须依赖本地 `testdoc/` 客户文件才可通过。
7. owner 文件出现新的重叠并发编辑，或全套 pytest 已在同一 checkout 运行。

## 4. 完成定义

- [x] Task 0 红测按四项报告问题逐条建立，客户样本均为 optional smoke。
- [x] FFT、FFT-vs-Time、Order 的 View + pane X/Y viewport 在手势、View-All、
      View/Section/cache 往返后保持。
- [x] Inspector Apply 成为新 viewport；显式重新计算按 §0.2 重置；项目内部恢复不
      冒充用户重算。
- [x] split pane link off 不串写，link on 只提交用户明确联动后的两个 pane；FRF、
      FFT time preview、heatmap Z/slice 无回归。
- [x] WWT record-only 辅助线有名称、颜色、来源与独立眼睛；只影响当前 View，
      save/reopen 保持，不改变 Navigator/源文件。
- [x] WWT 导入完成信息满足 `generated = placed + unplaced + 未投影` 的数量守恒；
      UltraView badge 可直达托盘并复用现有放置动作。
- [x] 同 Fs WWT 逻辑源可稳定区分，tooltip 有来源事实，搜索命中 Pars 公式通道，
      复合 source/channel identity 未变化。
- [x] owner tests、适用边界门禁与 `git diff --check` 通过；前台/全套/Windows 未跑项
      明确标为 `UNVERIFIED`。
