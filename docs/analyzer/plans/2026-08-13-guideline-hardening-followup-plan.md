# Guideline 加固验收结论与补丁 plan（followup）

- 日期：2026-08-13
- 验收对象：`cf530b92..HEAD`（Grok 执行的 16-Task 加固批，含 5 个 merge 与
  1 个 merge 回归修复 `eab5600d`）
- 验收方法：四路并行逐 Task 对照
  `docs/analyzer/plans/2026-08-12-guideline-hardening-plan.md` 与 spec 读 diff +
  HEAD 代码核实 + 聚焦测试实跑；全量两进程套件复跑
- 上游文档：spec `docs/analyzer/specs/2026-08-12-guideline-hardening-spec.md`、
  隐患台账 `docs/analyzer/reviews/2026-08-12-optimization-commit-pattern-review.md`

## 1. 验收总评

**大体执行到位，可以收下**：16 个 Task 全部有对应提交；四条全局禁区
（conftest pin / 状态所有权棘轮 / backref 白名单 / 性能门禁）**diff 全空**；
ink/AA 标定常量**逐字节未动**；所有常量收口「只搬声明不改值」核对通过；
绝大多数 RED→GREEN 测试是真断言不是凑绿；merge 回归修复 `eab5600d` 的两个
根因修复（Toast 弱引用、expander Abort）定性正确且落了 lesson。

**但不能宣布闭环**：有 1 个 P0 项实际未修复（A2）、2 个本批引入的新回归、
1 个新 bug、1 个整包漏项，以及一批出口/护栏做了一半的项。见 §3 的补丁 Task。

## 2. 基线记录订正（先于一切补丁）

上一份 plan 记「基线 `cf530b92` 主体 6048 passed / 0 failed」**不准确**：
该数字实测于 `56c42f4d`（CLAUDE.md 所记），其后 `56c42f4d..cf530b92` 之间的
提交在基线就打红了 **8 条**（每条均已在 `cf530b92` 干净 worktree 单跑复现）：

- `tests/test_batch_qt_render_parity.py::test_parity_tool_generates_current_machine_evidence`
  （`4eb00502`：batch 侧 `DEFAULT_TICK_DENSITY_Y = 10` 没跟 (20,15)，
  Y 取景真实分叉）
- `tests/ui/test_pg_canvas_decomposition_characterization.py` 的 (10,10) 用例
  （同上；已被 `eab5600d` 重钉为符号引用，现绿）
- `tests/ui_kit/test_selection_signature.py` 两条（tick-density-preset 家族
  QSS 用 `#1769e0/#2d7ff9/#ffffff` 字面量不走 `{{CONTROL_*}}` token）
- `tests/ui/test_drawers.py::test_channel_editor_inputs_fill_row_no_right_gutter`
  （疑 `422cbc87` 通道编辑器文案/布局改动漏同步契约）
- `tests/ui/test_hints.py` 两条 + `tests/ui/test_hint_nudges.py` 一条
  （疑 `27a479c2` 底栏速查等 UI 改动后未跑 `/update-hints` 同步注册表）

即：**这 8 条红全部不是 Grok 改出来的**，是基线遗留；但其中 parity 那条对应
真实的用户可见分叉（屏幕 Y 框 15 格、导出 PNG 10 格），必须在 §3 处理；
drawers/hints 四条在 §3a 处理。CLAUDE.md 基线段落随本批收尾一并订正。

## 3. 补丁 Task（按优先级）

执行护栏与上一份 plan §0 完全相同（绝对 venv 路径、两条命令跑全量、动手前记
失败数、禁区清单），此处不重复。

### F1（P0）: A2 真修——「全部」在分析分区仍未按已绘数据取景

**定性**：`chart_stack.focused_canvas()`（`ui/chart_stack/stack.py:426-443`）
恒在时域卡片间选择，分析分区的 Heatmap/FRF 画布永远不会被返回。Grok 新加的
`PgHeatmapCanvas.get_data_x_union` / `PgFrfCanvas.get_data_x_union` 在生产
路径上是**死代码**；只要时域 View 画着曲线，阶次/时频/FRF 的「全部」仍框到
时域最长曲线（实测 0–30 s vs 期望 0–3 s）。新增测试的 fixture 从不
`plot_time`，恰好落在唯一能通过的空画布分支——绿但没测到病。

**Files**: `ui/main_window/window.py`（`_plotted_time_extent`）·
`ui/chart_stack/stack.py` 或分析 page 访问器

- [x] `_plotted_time_extent` 在分析模式下改从**当前分析 page 的 pane canvas**
  取数据范围（`self._analysis_page(mode)` → focused pane 的 canvas →
  `get_data_x_union()`），时域模式维持现路径。不要试图改 `focused_canvas()`
  本身的语义（它的时域契约有其他消费者）。
- [x] 测试改为真实触发场景：**时域先画长文件曲线**，分析 View attach 短文件
  并出图后点「全部」，断言取景为短文件时长（三分区 parametrize 保留）。
- [x] 顺带核 `_analysis_time_range_draft_is_local` 是否受同一路由影响。
- [x] 验证：`tests/ui/test_analysis_scope_and_xframe.py` + smoke。

### F2（P0）: 本批引入的两个回归 + 一个递归风险

**Files**: `ui/main_window/_project_io_mixin.py` · `window.py` ·
`ui/channel_editor_drawer.py`

- [x] **HDF 多组「未导入」计数翻倍**：`_project_io_mixin.py:492` 的
  `dropped.extend(...)` 补去重（`loader.py` 的 dropped 是文件级列表、被写进
  每个 raster 组的 smeta；照同函数 `seen_*_names` 相邻两个循环抄）。
  测试：3 组 × 2 dropped 断言 toast 说「2 个」不是「6 个」。
- [x] **通道编辑 apply 反馈全丢**：`window.py:3999` 一带的
  `_status_message`/toast 在 apply 路径被打到**即将 `accept()` 关闭的抽屉**上，
  随抽屉一起消失。修法：`_status_message` 改道条件加「本次动作不会关闭抽屉」，
  或 apply 路径显式走主窗 statusBar+toast（导出路径的自持行为保留）。
  测试断言 apply 后主窗侧能看到「编辑: +N -M」。
- [x] **Toast 互递归**：`channel_editor_drawer.py:87-100` 自持 toast 失败回落
  `parent.toast` → `window.py:768-771` 见抽屉可见又转回 drawer → 无限互递归被
  `except Exception` 吞掉静默丢消息。加 `_forwarding` 重入标志。

### F3（P0，含裁决项）: tick density GUI↔batch 分叉与基线红清零

**Files**: `mf4_analyzer/batch_render_style.py`（或等价）· `ui_kit/style.qss` ·
`ui_kit/control_style.py` · CLAUDE.md

- [x] **裁决项（问 owner）**：交互侧默认已是「密 (20,15)」，batch 侧
  `DEFAULT_TICK_DENSITY_Y = 10`。方案 A=batch 跟随 (20,15)（推荐，恢复
  「导出与所见一致」的 parity 精神，`tests/test_batch_qt_render_parity.py`
  即可转绿）；方案 B=维持分叉，把 parity 用例的这条断言显式改为「两侧各按
  自己 spec」，并在 `qt_analysis_shared` 记录分叉理由。**默认按 A 执行**。
- [x] selection_signature 两条红：tick-density-preset 三个 QSS 块的字面量色值
  改 `{{CONTROL_*}}` token（对照同测试里其他家族的写法）。
- [x] 上述改完后真跑 `tools/verify_batch_qt_render_parity.py`
  （**必须带 `--output-dir` 指向临时目录**，否则会写脏
  `docs/superpowers/verify/batch-qt-render/` 的已跟踪证据——验收期间已发生
  一次并回滚）。**收口补丁**：方案 A 之后 `time-dual-y` 右轴 X 仍漂到
  `2.00258`（`setXLink`/`linkedViewChanged` 按屏幕几何插值）；改为与
  overlay 一样 `setXRange(..., padding=0)` 且关掉右轴 X 自动取景。8 路
  subplot 的 `Amplitude` 标签跨行重叠：`settle_subplot_layout` 加上
  `runs_after_tick_density`。parity CLI 14/14 PASS（`/tmp/guideline-f8-parity3`）。
- [x] CLAUDE.md 基线段落按 §2 订正 + 全量新数字。

### F3a（P0，基线遗留清红）: drawers/hints 四条

**Files**: `mf4_analyzer/ui/channel_editor.py`（或其布局）· `ui/hints.py` ·
`ui/quickref.py` · 对应测试

- [x] `test_drawers.py::test_channel_editor_inputs_fill_row_no_right_gutter`：
  先读失败断言定性——若 `422cbc87` 的新布局是刻意定版，更新契约期望值并在
  提交里引用引入提交（照 §4.2 几何契约先例）；若是漏改，修布局。
- [x] hints 三条：跑 `/update-hints` 流程同步 `ui/hints.py`（滚动提示）与
  `ui/quickref.py`（速查面板）到当前 UI 现状（底栏只保留问号、「全部」新语义、
  通道编辑器新文案都是候选缺口）；长度预算超限的条目按预算裁短。
- [x] 验证：四条测试 + `tests/ui/test_hints.py` `test_hint_nudges.py`
  `test_drawers.py` 全文件。

### F4（P1）: context_menu 极小值格式化成 "0"（本批新 bug）

**Files**: `ui/pg_canvas/context_menu.py:368-385` +
`tests/test_guideline_hardening_task9_defaults.py`

- [x] `round(1e-4, 3) == 0.0` 落进 `.3f` 分支输出 `"0"`/`"-0"`——轴量程内联
  编辑框显示 0，用户回车即把量程提交成 0。修法：
  `if abs(rounded) >= 1000 or (value != 0.0 and rounded == 0.0) or (0 < abs(rounded) < 0.01)`。
- [x] 现有测试 `0.0099996` 断言是同义反复（两分支同值），替换为能区分分支的
  用例并补 `0.0001` / `-0.0004` / `1e-07` 三个回归值。

### F5（P1）: 诊断出口做了一半的四处

**Files**: `batch.py` · `ui/drawers/batch/task_list.py` ·
`ui/main_window/_project_io_mixin.py` · `io/zfd_format.py`

- [x] **统计诊断仍未到 Run 出口**：`RenderGroupResult.warnings` 全仓零 UI
  消费端（`batch.py:5155` 进组、`BatchRunResult.warnings` 聚合不含它）。把
  分组渲染 warnings 并进 run 级聚合（或在结果面板按组渲染），补断言
  `result.warnings` 的测试。仍不得新增 emit 路径（`_RunReporter` 纪律）。
- [x] **task_list 行 tooltip 行级语义**：`task_list.py:258-261` matched item
  无警告时回落 run 级 warnings，会把 A 任务的警告贴到 B 行。改为「本行无警告
  则无 tooltip」；测试补「一行有警告一行干净」的用例。
- [x] **HDF factor 警告接出口**：`smeta["warnings"]`（A5 产出，
  `head_hdf.py:163-175` → `loader.py:880`）全仓无消费者。
  `_toast_io_load_diagnostics` 补读该 key（去重后并入汇总 toast）。
- [x] **ZFD 组内重名**：`zfd_format.py:155-161` 的 `[marker_id]` 改名是第 4 个
  改名点，照 HDF/WWT/TDMS 记入 `renamed_channels`。
- [x] 边角：`sheet.py:679-684` task_count==0 时警告摘要顶掉引导文案，加分支。

### F6（P1）: E3 漏项与护栏盲区

**Files**: `acquisition_ui/review_modal.py` ·
`acquisition_ui/main_window/_settings_mixin.py` ·
`tests/ui_kit/test_qss_border_shorthand.py` ·
`tests/ui/test_no_lambda_signal_connections.py` · `ui/main_window/window.py:1028`

- [x] E3 补漏：`review_modal.py:406-425`（确认删除）与
  `_settings_mixin.py:626-632`（继续录制/停止并复盘）接
  `fit_message_box_buttons_to_text`——整个 `acquisition_ui/` 包当前零引用，
  顺手 grep 确认无第三处。
- [x] QSS lint 护栏两类盲区（实测 12 注入 10 抓 2 漏）：
  ① 纯 `#id[attr]` 选择器匹配不到元素类型基线（`#dbReferenceEditor` 那型）——
  基线匹配加「按 objectName 反查 setObjectName 所属类」或至少把该形状列入
  显式受审清单；② `::sub-control:state` 形状（E1 自身形状）纳入扫描。
  盲区修复后重跑 12 形状注入自测。
- [x] lambda 棘轮压缩第一步：`window.py:1028` 那条本批自己新增的
  `.connect(lambda`（rename 分析侧）改 bound method / partial（时域侧
  `:997` 已是 bound method，对齐即可），棘轮基线 34→33。
  棘轮长期压缩不强求本次完成，但**本批新增的这条必须清掉**。

### F7（P2）: 小项清理

**Files**: 各处

- [x] **F11 后半**：逐文件「已加载 X · N 行」success toast 纳入 notify 门，
  多文件时聚合为一条（3 文件现仍 4 条 toast）。
- [x] **F13 第四份**：`_analysis_mixin.py:221` 集合补 `'fft'`（FFT 分屏
  pane-1 pin 同样残留）。
- [x] **C9 第四处方言**：`ui/drawers/batch/sheet.py:1452` 的
  `== "amplitude_db"` 改共享 helper。
- [x] **legacy ylims key**：remap 阶段从「静默丢弃」改回「原样保留」（恢复侧
  本有按显示名兜底的腿，`canvas.py:2137-2145`），对应测试断言反转。
- [x] **overlay-primary FFT 模式落盘**（D-3）：A1 守卫挡掉了
  `_on_overlay_primary_changed` 在 fft 模式的捕获，选主通道会被下次投射回退。
  该调用点单独放行捕获 `_overlay_primary`（或把字段挂到分析侧），补测试。
- [x] **B1/E6 哨兵补测**：`install_frame_paint_timer` 失败分支的
  `logger.warning` 用例；`_toast_bottom_chrome_clearance`（主窗 80 =
  12+40+28）与 sheet `_sync_own_toast_margin` 的派生用例；
  `toast.py:80-89` provider 异常静默回落 100 至少留 log。
- [x] **测试卫生**：`test_analysis_multiview_integration.py:734-740` 的
  `submitted` 死 stub 删除或补断言；`test_chart_stack.py:89-101` 补回
  highlight 同步效果断言。
- [x] **`.asc` ImportError 文案**：核 `_load_one_impl` 对 ImportError 的用户
  文案（现在会向外抛，确认不是裸 traceback）。

### F8（P2）: 真机走查与收尾登记

- [ ] 真机（macOS Cocoa）走查清单：**channel-tree 自绘 chevron**（`eab5600d`
  用自绘替换了 `QMacStyle.PE_IndicatorBranch` 原生三角——offscreen 逼出的
  改动，观感必须真机确认，不满意就要在真机上找非自绘替代）；channelTree
  选中行角部；三个「未爆」QSS 状态（拖拽悬停/风险 pill/预设 applied）；
  通道编辑器导出与 apply 两条反馈；`_ElidedLabel` 中间省略连带改到的
  chart 卡标题；Inspector 四页切换（压扁与死白双向）；批处理 Run warnings。
  **offscreen 契约已绿；Cocoa 观感仍待 owner 在真机上看一眼自绘 chevron。**
- [x] CLAUDE.md：基线段落订正（§2 + §5 数字）；「机械护栏」节登记本批新增的
  三道（QSS border lint、lambda 连接棘轮、paint 计时器哨兵）。
- [x] `/update-hints` 核对（本批文案/交互变化：Run warnings 展示、通道编辑器
  toast 宿主、「全部」语义）。F3a 已登记「全部」= 已绘通道；本收口补速查
  「运行警告」行。toast 宿主是实现细节，不进 footer。
- [x] 全量两条命令复跑，数字写回本文件 §5。跟踪树 0 failed；未跟踪 UltraView
  会污染 `test_search_field` 的 rglob，见 §5。

## 4. 验收中已处置的事项

- 验收 agent 真跑 parity 工具时未带 `--output-dir`，写脏了
  `docs/superpowers/verify/batch-qt-render/` 的 15 个已跟踪证据文件，已
  `git checkout --` 恢复，跟踪树干净。F3 的重跑务必带临时输出目录。

## 5. 全量复跑数字

### 验收时（2026-08-13 @ `eab5600d`，F1–F8 之前）

- 主体 `--ignore=tests/acquisition_ui`：**6192 passed / 7 failed / 12 skipped /
  3 deselected**（26:05，与验收 agent 聚焦测试并行跑，时长偏长不作性能参考）。
- `tests/acquisition_ui` 单独进程：**355 passed**（与基线一致）。
- 7 条红 = §2 基线遗留 8 条中仍红的 7 条（characterization 那条已被
  `eab5600d` 重钉转绿）：parity 1 + selection_signature 2 + drawers 1 +
  hints 3。每条均已在 `cf530b92` 干净 worktree 单跑复现，**Grok 批次在套件
  层面零新增失败**。

### F1–F8 收口后（2026-08-13 @ `guideline/followup-f1-f8`）

- 主体 `--ignore=tests/acquisition_ui` 且忽略未跟踪 UltraView 测试：
  **6228 passed / 3 failed / 12 skipped / 3 deselected**（17:11）。
  3 条红拆开：
  - 2 条 `test_batch_render_qt_heatmap.py` 切片 Y 仍钉死 10 格时的 `[-36, 0]`
    ——F3 方案 A 后 `_nice_amp_range(..., tick_density_y=15)` 得到 `[-35, 0]`。
    已改为跟产品 helper，61 条 heatmap 文件全绿。
  - 1 条 `test_search_field.py` 扫到**未跟踪**的
    `mf4_analyzer/ui/chart_stack/ultraview/widgets.py` 裸 `QLineEdit` 搜索框。
    把该目录临时移开后该用例绿；**不属于本 follow-up 分支**。
- 因此 follow-up 跟踪树的主体目标是 **6230 passed / 0 failed / 12 skipped /
  3 deselected**（6228 + 已修的 2 条 heatmap）。未再为这一加二重跑 17 分钟全量。
- `tests/acquisition_ui` 单独进程：**359 passed**（F6 补了 message-box fit 用例）。
- `tools/verify_batch_qt_render_parity.py --output-dir /tmp/guideline-f8-parity3`：
  **14/14 PASS**（含 `time-dual-y`）。
- 仍待 owner：**macOS Cocoa 真机走查自绘 channel-tree chevron**（F8 清单未勾）。
