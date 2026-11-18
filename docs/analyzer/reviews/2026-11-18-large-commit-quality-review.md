# 11 月 17–18 日大规模提交质量审查

日期：2026-11-18。结论：**needs revision / partial**。确认 7 项需要处理的问题，其中时域坐标、滤波质量和资源准入优先处理。已有导入隔离、原生存储、数值修复有明确价值，但 helper 测试通过尚未形成完整产品闭环。

配套：[优化 Spec](../specs/2026-11-18-large-commit-quality-spec.md) · [优化 Plan](../plans/2026-11-18-large-commit-quality-plan.md)。本次只审查和写文档，不修改产品代码或持久测试，不提交、推送或发布。

## 1. 按严重度排序的发现

### R01 · P1：原生 Custom-X 被画布换回采集时间，造成空图或错误横坐标

- 位置：`mf4_analyzer/ui/pg_canvas/overlay_axes.py:332–335`，`ui/pg_canvas/renderer.py:547–555`；接线 `ui/main_window/window.py:5213–5215`。
- 首次 attach 和后续 refresh 看到 `native_query` 就无条件使用 `query.display_time/display_values`。这些是完整采集时间/源值，无法表示用户应用的 Custom-X，也没有承接绘图选区。上层已经解析好的 X/Y 被覆盖。
- **真实 Cocoa MainWindow、正式 native broker 路径复现**：1000 点，`t=arange(1000)/1000`，`sig=sin(2π·3t)`，同轴 `angle=10+10t`。勾选 sig、通过 `apply_time_xaxis_spec` 应用 angle 后，payload X 为 `[10,19.99]`，视口也是 `[10,19.99]`，但实际 PlotDataItem X 是 `[0,.999]`；截图中曲线消失。不是只有内部数组或 stylesheet 推断。
- 影响：新“多采样率”入口下正常的同轴指定横坐标已不可用；X 范围碰巧重叠时可能显示错误位置而非空图。
- 修复要求：显示坐标与采集时间查询分别承担各自职责，首次/刷新/恢复消费同一份正确的显示绑定；同时保留 invalid/segment 断线。不能简单删除 `native_query`，否则会回退原生游标与有效性修复。

### R02 · P1：失效样本进入时域滤波，制造原始有效数据不存在的峰

- 位置：`mf4_analyzer/ui/main_window/window.py:5148–5166`；数据入口 `ui/time_curve_bindings.py::load_native_checked_curve`。
- native 分支只取 `series.values` 和 Fs，滤波前未检查 validity/segment；原始曲线的断线在画布阶段才应用，无法阻止坏值先进入滤波。companion 没有相应质量绑定。
- **真实 Cocoa MainWindow 复现**：Fs=1000，N=1000，全为零，仅 index 500 的值为 1000 且 MDF invalidation=True。6 阶 50Hz 低通后，index 500 得 `115.0271935876`，有效邻点 499 得 `112.0204952992`；所有原始有效样本仍为零。画面出现虚假的滤波峰，原始失效点虽不画出，却已污染整个滤波结果。
- 修复要求：在滤波前按本次选区检查时间、质量和精度；跨失效/复位的请求明确拒绝 companion 并给可行动原因，用户选取完整有效段后可算。禁止把坏值改零或删点拼接再滤波。

### R03 · P1：准备预算仍不是请求总预算，生产 FRF 还绕开 pair 准入

- 位置：`mf4_analyzer/analysis_signal_prepare.py:174–175,198–199,330–338,1171,1208`；生产调用 `batch_compute.py:363–375`、`ui/main_window/_frf_mixin.py:474–481`。
- 同轴 pair 将完整 `byte_limit` 分别给两侧，未核对合计；单路只按输入点数预估，然后可生成远大于输入的目标网格；完整 hash 在预算拒绝之前生成。跨率 helper 的新预算检查确实存在，但 GUI/Batch 调用 `prepare_pair` 未传 byte_limit，不能把 helper 的低预算测试当产品级保护。
- **小型确定性探针**：两侧各 100 点、100Hz、limit=1600，返回 ready 且 `bytes_charged=3200`。单路 `[1,2] @ [0,1]`，显式连续均匀化至 1000Hz，limit=32，返回 ready、1001 点、16016 bytes。100 点、limit=1 的拒绝仍先 hash 两个数组共1600 bytes。
- 边界：第二个反例是中立准备 API，未声称 GUI 已提供升采样按钮；没有用大内存输入制造崩溃。生产 pair 无预算接线与总量错误足以说明大数据保护未闭环。应用级 reservation、LRU、RSS 是旧计划未完成项，本次没有证明发生 OOM。
- 修复要求：总请求计费、生成网格前预检、hash/滤波前准入，生产调用接同一中立预算 owner；保留既有导入上限。

### R04 · P2：FRF 把选区首样本当时钟原点，误拒同原点整数比数据

- 位置：`mf4_analyzer/batch_compute.py:358–360`、`ui/main_window/_frf_mixin.py:468–471` → `analysis_signal_prepare.py:966–973`。
- 两侧独立按请求裁切后，用各自第一个剩余采样点判断原点是否相同。正常 2:1 同步网格，任意范围起点不一定落在共同采样点上，不能由此判为分数延时。
- **生产 Batch FRF 准备方法复现**：输入 8000 点@2000Hz，输出4000点@1000Hz，均从0开始，80Hz正弦、输出增益2，显式对齐、窗长.25s。范围 `[0,3.5]` ready；`[.1001,3.5]` 报“两端原点不一致”；`[.1006,3.5]` 又 ready。第二种裁切后首点分别为 .1005 和 .101，并非原始时钟不同。
- 修复要求：保留原始时钟原点/相位证明，选共同目标网格并读取必要 halo；只裁切最终有效输出。继续明确拒绝真正的未验证分数偏移，不放宽到任意异轴插值。

### R05 · P2：Replay 提示选择 segment，但没有操作入口，Play 空跑

- 位置：`mf4_analyzer/acquisition_capture/backends.py:461–479`、`acquisition_ui/replay_tab.py:290–291,307–325`。
- backend 对复位时间返回 `segment_required` 和空 `source_samples`；ReplayTab 照常启用 Play，也没有 segment 控件或选择回调。
- **真实 Cocoa ReplayTab、正式 broker 复现**：MF4 `t=[0,.1,.2,0,.1,.2]`、y=`[0,1,2,3,4,5]`。加载后6个 events、0个可播放 samples，提示“时间回退，请选择要回放的段”，Play enabled=True；点击后 playing，第一次 drain 即 stopped，没有任何数据。截图确认没有选择段的控件。
- 影响：Replay UI 已默认 native，用户无需打开新的分析器开关也会遇到，不能归类为尚未启用的实验 helper。
- 修复要求：明确等待选段状态、可用段信息与选择入口；未选不能开始；使用保留的 native 数据/事件生成选择结果，不回退公共轴或全局排序拼接复位。

### R06 · P2：FRF 轻量查询仍完整 hash 和复制输入

- 位置：`mf4_analyzer/ui/main_window/_frf_mixin.py:470–480,1039–1041`；`analysis_signal_prepare.py:330–338`。
- `materialize=False` 只传到 pair。此前的两次 `load_native_channel` 已 hash、验证和复制全量所选数据；同轴 pair 又进入两次 `prepare_signal`，忽略 materialize。最新提交避免了跨率 pair 内部抗混叠/hash，但没有关闭真实 caller 的成本。
- **生产 GUI 准备方法 + hash spy**：2000/1000Hz、4s跨率请求，`materialize=False` 仍4次hash、192000 bytes；两路各4000点同轴请求为8次hash、256000 bytes。最后返回值为None不代表此前没物化。此方法用于 cache lookup，不仅用于用户点击计算。
- 修复要求：元数据描述与实际准备分开，使用 stable revision/索引/采样事实；同轴与跨率都禁止预览完整hash、滤波和全量值副本。实际作业保留质量验证。调用计数已证实，百万点卡顿时间和RSS尚未实测。

### R07 · P2：用户帮助及提示合同留下当前红测，发布证据不完整

- 位置：`mf4_analyzer/ui/hints.py:283–286,322–323,340–341,367–368`；`mf4_analyzer/help/frf-guide.html:99`、`tests/test_help_content.py:443–449`。
- 本轮真实执行出现3项失败：`test_every_registry_hint_stays_within_length_budget`、`test_wwt_export_storage_is_a_shipped_discovery_hint`、`test_frf_guide_is_mapped_and_covers_frozen_frf_contract`。
- 四条近期引入/修改的提示宽度为26/38/32/35，超过既有18字宽预算；WWT提示被替换为原生长表说明，却继续使用旧 id/retire_on，原WWT发现入口丢失。FRF指南已改语义，旧测试仍要求“严格同时间轴”。最后一项是测试/文档未同步，**不是建议把合法多率能力撤回**。
- `e9d61cd5` 执行记录承认其中若干是相对其父提交的既有红；它们仍位于本次两天提交范围。不能继续以“既有红”当作本次候选已通过。
- 修复要求：保留短提示与详细帮助的分工，WWT与native导出分开说明；更新语义合同测试，不能删除测试或放宽长度阈值消红。

## 2. 审查范围、基线与边界

`git pull --ff-only` 返回 `Already up to date.`。分支 `main`，HEAD `b802b382e38cedc896af4f34f51637aecd819238`，版本 `v8.4.8`。相对上个基线 `5bac5a2c9ae40e1ea7a45ac4fbab3d7d6a652867`，合计 **238 files changed, 27602 insertions(+), 1539 deletions(-)**，14个非merge提交。11月17–18日按主线集成范围审查，因此包含作者时间较早、在此期间合入的 UltraView `240ab4b0`，不只按 author date 过滤。

开始及所有运行检查结束时 tracked 树干净，原有未跟踪 `CSER TTR/` 保留。本轮新增3份文档；临时输入、探针、截图和日志仅在忽略的 `.state/review-20261118/`。当前源码未变，所以各 focused 结果可归于该HEAD，但不是整仓库验收。

| 提交组 | 本轮查看/验证重点 | 结论边界 |
| --- | --- | --- |
| `161e5387`、`02d15a61`、`2c08c890` | broker/worker隔离、typed transport、MDF安全、预算/重试、source注册/释放、短框和进度 | owner检查及有限Cocoa恢复通过；新平台/大数据仍未签收 |
| `63619b1c`、`0bde6286`、`e9d61cd5` | store/read_signal、分析准备、GUI/Batch消费者、导出、Replay、保存policy | 接收已修复项；本报告R01–R06仍需处理 |
| `b802b382` | 多率开关默认关闭、设置持久化、请求内冻结、只路由新开.mf4、项目保存policy优先 | 当前定向测试通过；开关增加了上述缺口的实际可达性 |
| `febfc01d`、`c64caaba`、`c126fcae`、`77ceade6` | LF补丁校验、Lite构建路径/UNC、Nm/nm与dB参考、版本和帮助 | 源码及相关测试；不是Windows EXE验收，帮助门禁有R07 |
| `240ab4b0` / PR #41 | QRect矩形命中、负/零跨度、组合移动测试 | focused未发现新缺陷；未做完整UltraView视觉验收 |

审查是按实际变更与高风险消费链展开，不宣称逐行证明238个文件无缺陷。未做全套pytest、Windows Full/Lite、完整派生项目“编辑→保存重开→再派生”、Pin/比较B面全矩阵、20轮RSS/交互基准、事故样本R01及图2验收。

## 3. 接收已有成果，避免重复派工

与[上轮收尾记录](../verify/2026-11-18-mf4-native-completion.md)对照后，不能再沿用旧L编号中的失败结果：RPM解包方向、失效RPM拒绝、FRF prepared目标Fs、跨率1字节预算helper拒绝、Chebyshev II指定频带oracle、GUI Excel大整数文本均已有实现和本轮相关绿测；不重写它们。MDF2/3标量、native transport、逻辑派生基础取数、schema6 policy恢复也应接收现有成果。

当前源码已有GUI“对齐后计算”控件（`ui/inspector_sections/contextual_frf.py:227–233`）及Batch对应选项（`ui/drawers/batch/method_buttons.py:989–996`），参数进入准备调用。因此旧L11“未找到控件”的记录不再是当前缺陷；余下问题是R04/R06的选区与准备成本，而非重新添加这个入口。

当前入口政策：未勾选时普通打开/拖入/最近仍legacy；勾选文件区“多采样率（仅MF4）”后新开`.mf4`走native，其他后缀不随开关改变；保存为native的项目按其policy恢复；Replay UI是native，直接 `source_from_mf4` 和路径Batch仍legacy。不能继续说“只有隐藏API可以打开native”。本报告不更改这些政策。

补充接口探针 **S01，非已确认用户路径故障**：`batch.py:6706–6708` 的rpm_channel分支没带neighbor_halo，rpm_signal分支有。信号t=`[0,.25,.5,.75,1]`、RPM t=`[0,1,2]`/v=`[100,200,300]`，直接给 `_rpm_values(time_range=(.25,.75))`，前者拒绝、后者`[125,150,175]`。但 `batch_recipe.py:455–456` 当前会移除 `order_time` 的time_range，因此不把它夸大成已复现的Runner选区错误。未来接入范围或修改此owner时补一致性测试；本轮不改变该既有产品政策。

## 4. 本轮实际验证

环境：macOS 27.3 arm64、项目Python 3.12.16、NumPy 2.5.3、asammdf `8.8.32+tracelab.1`、Qt5.15.14。所有运行均用项目venv与 `TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=.`。UI测试隔离QSettings；自建Cocoa探针也将设置factory指向`.state`，不改真实偏好。

| 检查 | 实际结果 | 日志/证据 |
| --- | --- | --- |
| native准备、Batch来源集成、保真/导出、preprocess、GUI消费者/入口/Order | **196 passed, 6 warnings** | `native-focused.log` |
| 导入limits/process/transport、MDF安全/native、packaging/Windows脚本、coordinator、dialog/progress | **362 passed, 13 skipped, 9 warnings** | `import-focused.log`；skip不算通过 |
| neutral/UI/renderer/state/lambda/reporter边界，db/help，UltraView命中/多选，派生及迁移 | **3 failed, 256 passed, 1 skipped** | `boundary-product.log`；失败全列R07，整体为FAIL |
| Cocoa生产短提示、Batch/UltraView工作窗、真实资源重查/新worker/回收 | **2 passed** | `cocoa-recovery.log`；不是完整生命周期矩阵 |
| Replay现有owner，独立新pytest进程 | **9 passed** | `replay-focused.log`；既有用例没覆盖R05 |
| 新反例脚本 | R01–R06相关确定性值如§1；S01单列 | `probe.py`/`probe-results.json`、`ui_probe.py`及3份Cocoa JSON/PNG |

不把以上数字相加成全套结果。Cocoa几何：短提示380×115，Batch1080×760，UltraView1280×800，资源框498×166，等待进度420×152，DPR均为2。R01/R02使用1400×900真实MainWindow，R05使用1200×720真实ReplayTab；已查看渲染截图。截图及日志不提交，§1保留足以重建的输入、操作与实际结果。

可复验的pytest文件集合（均追加 `-q --tb=short`）：

```text
native-focused:
tests/test_analysis_signal_prepare.py tests/test_batch_source_integration.py
tests/test_mf4_native_fidelity.py tests/test_mf4_native_export.py tests/test_batch_preprocess.py
tests/ui/test_native_signal_consumers.py tests/ui/test_mf4_native_product_path.py
tests/ui/test_order_multirate_rpm.py

import-focused:
tests/test_import_limits.py tests/test_import_process.py tests/test_import_transport.py
tests/test_mdf_reader_safety.py tests/test_mdf_native_reader.py tests/test_import_packaging.py
tests/test_windows_build_script.py tests/ui/test_import_coordinator.py
tests/ui_kit/test_dialog_geometry.py tests/ui_kit/test_import_progress_dialog.py
tests/ui_kit/test_message_dialog.py

boundary-product:
tests/test_native_import_boundaries.py tests/test_signal_no_gui_import.py
tests/test_batch_render_import_boundary.py tests/test_packaging_imports.py
tests/test_batch_run_reporter.py tests/test_db_reference.py tests/test_help_content.py
tests/ui/test_main_window_state_ownership.py tests/ui/test_import_boundaries.py
tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_no_lambda_signal_connections.py
tests/ui/test_hints.py tests/ui/test_ultraview_author_geometry.py
tests/ui/test_ultraview_author_multiselect.py tests/ui/test_native_derived_followup.py
tests/ui/test_mf4_native_project_migration.py

Cocoa（独立进程，QT_QPA_PLATFORM=cocoa）:
tests/ui/test_import_recovery_followup.py

Replay（独立进程，QT_QPA_PLATFORM=offscreen）:
tests/acquisition_ui/test_replay_tab.py
```

不因写文档再次运行这些集合；后续按Plan的受影响owner执行。采用既有 partial-import质量、native准入、真实caller及plan/spec证据教训，本次没有新建同义lesson。
