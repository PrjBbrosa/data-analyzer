# MF4 原始采样、分析正确性与性能迁移 Plan

日期：2026-11-17。状态：**规划完成，等待实施指令；下列阶段均未执行。**

执行合同：[原始采样 Spec](../specs/2026-11-17-mf4-native-sampling-spec.md)。本轮仅交付两份文档与 `.state/` 只读探针，不改产品、依赖、AGENTS/CLAUDE。用户随后授权提交并推送这两份文档；本地探针不纳入提交，产品实施仍未授权。不会因为本计划列出工作包而自动启动 agent。

## 1. 结论与方案

首选原生 typed 数组存储、共享时间轴、按需准备选定分析区间，复用现有进程隔离与画布包络。第一版不引入持久 mmap、不做“全文件统一到最快 Fs”、不为性能丢点。当前已有 import-hardening 变更是前置基础，不能覆盖或恢复成旧同步导入。

数据量并非一定增加：本轮本地样本公共表数值数组 199,980,448 字节；按原生样本保留 raw、必要 physical 与共享 time 统计为 25,089,754 字节。另一方面，10 个不重叠通道由当前只保留 1 个改为完整保留，会合理增加 10 倍数组量。需要按等内容比较性能，不能以历史丢数据的速度作放行依据。

性能主要风险是解析器重复读取同一组、交接和 float64 副本、恢复后增多的通道目录、逐 View 缓存、分析任务临时数组以及 GUI 内全量扫描。时域画布已经接受每条曲线独立 t/sig；这里优先接通取数合同，避免新建一套 renderer。

本轮证据位置：`.state/mf4-native-plan-20261117/probe.py`、`results.json`。数字是 buffer 普查，不是产品峰值 RSS、冷盘吞吐或 native GUI 验收。未宣称新方案已经不卡顿。详细数据与局限见 Spec §2–3。

## 2. 前置条件、范围与变更控制

- 调查 HEAD 为 `5bac5a2c9ae40e1ea7a45ac4fbab3d7d6a652867`；当前 dirty tree 包含其他任务。开始实施前重新记录 HEAD、`git status` 和所有受影响源的 hash；等待相关 owner 的重叠编辑稳定后再改，不擅自 stash/reset。
- 复用导入鲁棒性工作的实际 reader/broker/transport/资源合同。调查时参考了工作区中的 `docs/analyzer/plans/2026-11-17-import-native-crash-and-resource-hardening-plan.md` 与 `docs/analyzer/verify/2026-11-17-import-robustness-implementation.md`；这些材料及其实现属于另一批未提交变更，不随本次文档提交，远端 checkout 可能尚不存在。实施前必须确认该前置工作已集成；其历史验收也不能当作新原生采样或 Windows 验收。
- 路由范围包含普通打开、拖入/最近文件、项目恢复、Batch probe/load、Replay、时域/Custom-X/游标/统计、FFT/时频/Order/FRF、通道编辑、导出、Pin/比较/UltraView。仅保留原始点而这些消费者继续取旧表，不能交付。
- 旧 `load_mf4` 公开兼容入口保留但产品新开来源不再调用；旧项目 legacy 恢复是显式兼容能力，不与 native 结果混用。
- 非 MF4 原生化、完整 MDF 写回、任意大文件支持和持久 mmap 不在本版；旧格式适配只改受影响边界，不能借此重构全项目。
- 数值修改先有独立 oracle/红测；文件、时间、算法、View ownership 各由现有 owner 承担。是否并行需后续明确授权；即使并行，也只有一个集成与全套门禁 owner。

## 3. 阶段与依赖

```mermaid
flowchart LR
  M0["M0 合同与数值基线"] --> M1["M1 原生源与取数"]
  M1 --> M2["M2 安全读取与交接"]
  M2 --> M3["M3 时域/查询/显示"]
  M2 --> M4["M4 分析输入"]
  M3 --> M5["M5 项目/编辑/导出/Replay"]
  M4 --> M5
  M5 --> M6["M6 性能/平台/集成放行"]
```

M3/M4 依赖同一冻结接口，允许独立实现，不意味着授权并行。M6 前只在隔离开发开关/测试入口启用 native 产品路径；不能让半迁移版本成为默认。开关不是用户长期保真选项，完成后新开默认 native，legacy 只保留明确用途。

### M0：固化证据、消费者清单与数值门槛

Owner：测试 fixture、独立 probe、计划验收记录，不先改产品。

1. 将本轮丢峰、长范围、不重叠、单点、等长错位、重复/复位/失效位、大整数转换变成匿名 fixture，保留人工预期与文件 hash。失效位测试同时验证原始 API 的 flags 语义；不能依赖参数名猜测。
2. 给每个源建立预期通道目录：物理通道/别名/数组父项/元素/主轴/unsupported 分开。现地样本 967 个计数不是通用常量；其 22 个排除项逐类归因。受支持的 915 个单点元素/标量应恢复而不伪造采样率。
3. 精确搜索生产入口的 `load_mf4`、`fd.time_array`、`fd.fs`、`fd.data`、`len(fd.data)`、`.shape` 和所有 frame helper。逐项标记 native 要迁移、legacy-only 或非受影响，记录 owner 与验证项，不用机械全局替换。
4. 建立可复现性能 manifest：同轴控制组、多率组、长覆盖恢复组、单点密集组、同钟错位组；补压缩/转换多/多文件/6×1,188,000 点标准绘图负载。小 fixture 测正确性，大 fixture 按预算生成；不故意耗尽开发机资源。
5. 冻结数字门槛与原始序列：无重采样的同源 uniform 输入以现有核心为回归 parity，同时用人工频率/增益/延迟 oracle 判绝对正确；新增对齐先用 noise-free 多正弦、已知延迟 LTI 和恒定/斜坡 RPM。测试频带、窗、分辨率、边缘忽略范围必须提前固定。F08/F09 未固定具体滤波参数和数值误差预算，不准进入 M4 的异轴 DSP 实现。
6. 首版建议的可验证信号集：稳态整周期 FFT 正弦频率误差≤1 bin，幅值相对误差≤1%；FRF 安全通带 0.05–0.30×较低输入 Fs，noise-free coherence≥0.99，增益误差≤0.1 dB、延迟对应相位误差≤1°；降采样带外混叠抑制≥60 dB。滤波边缘按设计支持长度剔除，不挑选结果有利区间。若已有 filter 不满足，保留现有用户 filter 行为，为新采样准备另定通过 oracle 的滤波设计；不得事后放宽门限。

Focused（既有）：`tests/test_mf4_loader.py`、`tests/test_mdf_reader_safety.py`、`tests/test_analysis_time_axis.py`、`tests/ui/test_order_multirate_rpm.py`。新增（拟）：`tests/test_mf4_native_fidelity.py` 与 fixture 扩展。预期新合同红测须写明失败原因，不运行全套基线。

Exit：原始独立数据 oracle、消费清单和基准 manifest 可复查；控制组与错误结果区分明确。不得把现有“验证截断”的通过测试当作无损证明。

### M1：原生源与统一取数，保持其他格式兼容

Owner：拟新增 `mf4_analyzer/io/native_signal_store.py`、`io/signal_access.py`；现有 `io/file_data.py` 与 `source_adapters.py` 的明确分支。此阶段不改 loader 默认。

- 实现不可变 axis/channel 表、raw/physical/validity、物理 identity、segment、Fs known/estimated/unknown 和 stable revision；轴共享不能消灭时钟来源。
- `read_signal` 支持真实范围、segment 与表示；连续区间尽量只读 slice，不先生成全长布尔 mask 或 float64 拷贝。非单调/重复保持样本序号；为空、单点、类型错误提供确定返回/错误合同。
- 既有表格来源适配遵守原格式时轴/单位规则。多轴 FileData 不提供假的公共 axis/fs/rows；所有 legacy-only 访问失败须可定位，测试证明未偷偷生成 shared table。
- 生命周期只由 FileData/store 与现有 job owner 持有，View/预览引用同一只读 buffer；派生渠道独立，不能原地改 native。资源 reservation 与释放接口放在中立预算 owner，先用 spy 验证。
- 固定 MF4 source root ID 和既有公开名；新增 physical key 用于内部、缓存与持久化，旧显示名只作为已知映射，不能自动模糊匹配。

Focused（既有）：`tests/test_source_adapters.py`、`tests/test_channel_frame.py`；新增（拟）：`tests/test_native_signal_store.py`、`tests/test_signal_access.py`。Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_native_import_boundaries.py`。

Exit：不同长度、同名/Time、raw大整数、readonly、共享轴、source close/worker引用与旧格式适配全部通过；尚不声称 native 文件导入完成。

### M2：MDF 原生读取、准入与进程传输

Owner：`io/mdf_reader.py`、`io/loader.py` 薄入口、`io/source_adapters.py`、`io/import_transport.py`、`io/import_worker.py`、`io/import_limits.py`；broker 生命周期在原 owner 内改。

- 新增 native payload/入口，复用当前固定 runtime 与 MDF 数组/记录边界 admission。probe 与 load 使用相同目录、physical identities、主轴种类和 unsupported 事实。
- 每通道保留 raw、原 timestamps 和失效位置，按需保留已转换 physical，不做 shared interpolation、去重时间、回退排序、范围截断。非时间轴不伪装成秒；结构父项和元素的支持状态诚实呈现。
- 按 group/fragment复用读取，避免每个元素反复解压同一记录块；任何分块/元素view优化先做独立 oracle。未知依赖/布局仍 fail closed，不能为恢复单点禁用安全检查。
- 替换公共表字节估算为累积 raw/time/physical/validity/目录/读写临时量。包括转换输出类型膨胀、DataFrame兼容路径副本、父子交接峰值，unknown 不按零。低预算 tests 在分配前失败。
- typed transport 增加显式 native kind，验证 shape/dtype/数量、质量长度、physical-key引用、axis ID、只读与共享关系。请求、源变更、原子 manifest、临时目录清理合同不变；10,000 文件上限需写前估算。
- 新产品 load/probe 从 adapter 返回一个 native source，保持旧 API 可调用但不作为自动 fallback。含空格/中文路径、坏文件后正常导入、资源拒绝都走真实 broker。

Focused（既有）：`tests/test_mdf_reader_safety.py`、`tests/test_import_process.py`、`tests/test_import_transport.py`、`tests/test_import_resource_preflight.py`、`tests/test_source_adapters.py`；新增（拟）：`tests/test_mdf_native_reader.py`、`tests/test_mf4_native_fidelity.py`。Boundary：`tests/test_native_import_boundaries.py`、`tests/test_import_packaging.py`、`tests/test_packaging_imports.py`。

Exit：真实子进程往返与独立 loader raw oracle逐点一致，源hash不变，资源/取消失败无部分注册；同轴共享在父进程仍成立；数组字节符合 Spec §3。不能只测直接函数绕过 transport。

### M3：时域、查询与显示成本

Owner：`ui/main_window/window.py` 已有绘图/导出入口的薄接线；`ui/time_xaxis.py`、`ui/time_curve_bindings.py`；`analysis_context.py`/`analysis_time_range.py`；对应 canvas/query/Pin owner。不把新取数逻辑堆进 window.py。

- 接通 per-curve X/Y、当前选择范围并集、通道级滤波 Fs、单点 marker、失效/复位断线。源目录统计改为真实含义，恢复的单点不自动勾选；不再为提示行数遍历所有通道。
- 游标查询与统计从 native 完整数据获取；按 Spec §6 验证默认最近原始点、等距取较早、实际时间/差值、标记位置、重复点序号、覆盖外/缺口无数据与显式插值标签。相同查询/模式在缩放前后数值一致，不能读取显示包络。峰值与有效样本统计不依赖当前包络。Custom-X 同长度错位必须走显式关系检查。
- 局部范围查找、segments/metadata在导入时预计算；必要的大型查询交给已有 worker，不在鼠标/paint/attach回调中读盘或扫描全部样本。保持图层 ink、AA、150ms quiet window 与一次 settle合同。
- stable revision 贯穿 Pin、比较pane、UltraView；已绑定 View 不复制全数据或触发分析重算。视图删除/源关闭不产生迟到写入。
- 新增用户文案同步 hints/quickref；普通界面显示采用值与明确状态，复杂对齐/质量细节放详情。

Focused（既有）：`tests/ui/test_mf4_import_flow.py`、`tests/ui/test_time_xaxis.py`、`tests/ui/test_time_curve_bindings.py`、`tests/ui/test_time_range_consumers.py`、`tests/ui/test_time_filter_overlay.py`、`tests/ui/test_pg_cursor_placement.py`、`tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_ultraview_capture.py`；新增（拟）：`tests/ui/test_native_signal_consumers.py`。按 owner 分批运行，不一次跑所有 UI。

Boundary：`tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`；若实际变更 QSS，再加 `tests/ui_kit/test_qss_border_shorthand.py`，本计划不要求改 QSS。

Exit：丢峰反例可见且游标/统计与原生取数逐点一致，native Cocoa检查实际 widget路径、断线与点标记；时域性能按 Spec测量。完整产品导出验收归 M5，尚不能因此宣称频谱保真。

### M4：统一分析输入，保护算法与相位

Owner：拟新增中立 `mf4_analyzer/analysis_signal_prepare.py`；现有 FFT/时频/Order/FRF mixin与coordinator、`batch_preprocess.py`、`batch_compute.py`、`batch_frf.py`、`batch.py`薄编排；`signal/`算法仅在明确数值需要时改。

- 统一返回 PreparedSignal/Pair，明确同轴直通、局部float转换、质量拒绝和显式对齐；配对两端分别传原轴，不接受仅“长度相同”的同步证明。
- native调用不进入 `prepare_analysis_time_axis` 的自动按序号重建；旧来源/旧项目的原政策保持隔离。显式均匀化必须计算新值与新时间并记录来源，不能仅换标签。
- Order修复等长错位检查及范围外端点延长；RPM/目标信号单位、倍率、有效覆盖先验证。针对同一源/跨源、相同点数不同timestamp测试，不因identity改造隐式改变RPM选择。
- FRF默认直通须符合原核心时间同步规则；异轴需用户应用“对齐后计算”。实现前提交M0已冻结的抗混叠、origin、比率、fractional delay与边缘合同，用独立相位/增益 oracle启用；不通过的组合明确unsupported。不能以GUI/Batch共享同一错误结果作为正确性。
- 分离 Fs重解释与重采样、状态ZOH与连续量线性、原始范围与计算有效范围。过滤halo按源读入并按设计处理边缘；已知gap不跨接。处理前后原始数组hash保持。
- 更新缓存key与effective facts，保留“编辑不计算、计算才应用、显示只重绘、切View恢复已应用结果”。准备缓存按字节计费，已绑定结果继续由原cache owner保留；大任务入场先预检。
- Batch与GUI使用同一准备合同；保留时间范围→质量验证/有限值政策→scale/offset→remove mean→抗混叠采样→用户滤波的既有次序。配对输入对齐单独计事实，不重复采样；单一reporter、取消、slice导出与单位/dB含义不改变。

Focused（既有）：`tests/test_analysis_time_axis.py`、`tests/test_batch_preprocess.py`、`tests/test_frf.py`、`tests/test_frf_scipy_parity.py`、`tests/test_batch_frf_pairing.py`、`tests/test_batch_frf_export.py`、`tests/signal/test_order_cot.py`、`tests/synthetic/test_cot_known_order.py`、`tests/ui/test_order_multirate_rpm.py`、`tests/ui/test_frf_main_window.py`、`tests/ui/test_fft_time_coordinator.py`、`tests/ui/test_analysis_cache_pinning.py`、`tests/ui/test_analysis_project_explicit_compute.py`；新增（拟）：`tests/test_analysis_signal_prepare.py`。

Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py`、`tests/test_batch_run_reporter.py`、`tests/ui/test_main_window_state_ownership.py`。所有数字修改红绿测试，unchanged核心不因本任务重写。

Exit：F06–F09与GUI/Batch同请求parity通过、内存准备有界、同轴回归结果不变；错误旧输入造成的差异有逐项解释。未验证的相位对齐不启用，若目标支持范围因此未满足，本阶段为partial而非完成。

### M5：项目、编辑、导出与 Replay 闭环

Owner：`ui/project_io.py`、`ui/project_source_match.py`、`ui/main_window/_project_io_mixin.py`、`io/channel_edit_log.py`、`signal/channel_recipe.py`、channel editor、`batch_output.py`、现有导出入口、`acquisition_capture/backends.py`/`acquisition_ui/replay_tab.py`、帮助/hints/quickref。

- 项目原生policy/物理key/对齐意图需要schema演进，当前1–5，6为本计划候选；先核对并行改动。保持reference-only、不存样本/cache；普通不涉及新政策的项目可保持旧写入兼容。
- 旧项目自动按legacy恢复且标明，升级需明确用户选择与影响预览；新开文件native默认仅在M6后开启。迁移不覆盖源/原项目，不按显示名猜匹配。旧Fs override与公式在原政策下恢复，升级时转为明确派生意图或未应用状态。
- 单通道配方继承轴，多输入配方存axis/method/segment及raw/physical表示，重开可复算。派生/删除只改逻辑源目录，不改不可变raw。跨时钟缺口/源变化须报可行动原因。
- 原始数值导出支持同轴分组或长表，点数/时间/质量/整数精度回读一致；统一时间横表需显式request。Excel精度与行数限制显式处理，不截尾；PNG/PDF维持原render contract。
- Replay改为原事件时间/顺序，保留同timestamp记录；多率/单点/复位/失效位语义明确。其返回结构不能通过重新公共表化来兼容。
- 检查普通打开、拖入/最近、项目恢复、Batch probe/full load、Replay全链，不遗漏worker/打包hidden-import。更新受影响帮助与用户guide，不更改历史发布条目。

Focused（既有）：`tests/test_channel_edit_log.py`、`tests/ui/test_channel_editor_recipes.py`、`tests/ui/test_channel_editor_export.py`、`tests/ui/test_project_session.py`、`tests/ui/test_ultraview_project_session.py`、`tests/test_acquisition_capture_backends.py`、`tests/acquisition_ui/test_replay_tab.py`、`tests/test_help_content.py`；新增（拟）：`tests/test_mf4_native_export.py`、`tests/ui/test_mf4_native_project_migration.py`。Replay目录在独立新进程运行。

Exit：F10–F12通过，迁移可预览/取消，保存重开保真；所有产品native读取不经旧shared-axisAPI。不能通过暂时禁用导出/编辑/Replay宣布完整迁移。

### M6：性能、跨平台与默认切换

Owner：单一集成负责人；不与其他全套重叠。

1. 根据 Spec §8 跑 cold/warm、单/多文件、1/6/20条曲线、少量/全部选择、缩放/拖动/游标/切View/取消/关闭/恢复。导入、交接、目录注册、查询、准备、DSP、paint/settle分阶段计时；CPU/RSS/临时磁盘同时间线采样。记录恢复的额外数据量，公平比较等内容工作负载。
2. 先复用 `scripts/benchmark_timedomain_interaction.py` 标准synthetic控制组，再新增MF4 native fixture入口（现有脚本仅synthetic/HDF，不能伪称已有MF4模式）。真实样本与合成payload同时跑，原始数值与像素/几何验收分开。
3. 用 `scripts/probe_view_switch_quality.py` 做视图恢复/AA结算回归；不调整质量阈值。新增大通道目录、缓存byte budget、20次循环leak测试。若吞吐失败，先依据profile优化group解码、复制或树构建，禁止损失样本换速度。
4. 默认开启前运行所有owner focused/boundary gate。因本次跨IO/存储/分析/项目，是一个合理的稳定集成全套里程碑：检查pytest进程及cwd，记录前后HEAD/源码指纹；主套 `--ignore=tests/acquisition_ui` 完成后，另启进程跑 `tests/acquisition_ui`。仅一次；源变更/崩溃/中断记UNVERIFIED，不重启刷通过数。
5. macOS Cocoa：真实打开、原始峰值/单点、计算/项目/取消闭环及性能。Windows新鲜Full/Lite windowed EXE：验证固定native库、子进程/typed传输、中文空格/正常UNC路径、峰值/内存/关闭；Modular受影响时加其打包入口。Windows未测即UNKNOWN，不能以源码打包tests代替。
6. CANape对照为可选独立参考：同文件同通道/单位/范围/真实时间点，对比点数、峰值、首末时间；仅使用其实际原始导出/采样读数，不能拿插值游标当原始点。没有CANape不阻止人工/字节oracle，但不能声称已与CANape实测一致。
7. 只有原生支持范围、所有消费路径、项目迁移、性能和平台门禁都闭环才切默认；若某平台未闭环明确限定交付范围。不会自动提交/推送或做版本发布；届时另按发布合同同步版本面。

Focused与边界补充（既有）：`tests/ui/test_interaction_smoothness_baseline.py`、`tests/ui/test_timedomain_hotpath_perf.py`、`tests/ui/test_view_switch_integration.py`、`tests/ui/test_import_coordinator.py`、`tests/test_import_packaging.py`、`tests/test_windows_build_script.py`、`tests/test_windows_runtime_dependencies.py`、`tests/test_conftest_autouse_scope.py`、`tests/ui/test_qsettings_isolation.py`。

Exit：数值/时域/分析/迁移/资源/Cocoa/Windows分别有PASS证据；未测项不能勾选。达到门禁后停止扩展测试；只有新增修改、失败或明确未闭合风险才扩大验证。

## 4. 对用户可见的影响

| 项目 | 预期变化 | 必须避免 |
| --- | --- | --- |
| 内存 | 多率数据通常减少；恢复丢弃内容会增加，按实际原生量与副本准入 | 承诺所有文件都更小或绝不会OOM |
| 通道数量 | 单点/独立时段元素恢复后可能明显变多 | 自动全选全部新增元素导致首屏卡顿 |
| 时域 | 看得到曾丢失的峰值/尾段/独立事件；缺口不被伪造填平 | 用原始全点每帧重画、破坏既有ink策略 |
| 分析 | 单通道回归原轴/Fs；不合法请求需要显式处理 | 为保持旧错误结果而继续自动重排时间 |
| 导出 | 原生采样导出可能多表/长表；公共横表是明确派生 | 把导出补点误称原始测量 |
| 旧项目 | 默认保持legacy复现，可预览升级；native项目有新schema | 静默改变旧分析或让旧版本误读 |

## 5. 交付清单、回退与本轮检查

未来实施交付：native store与读取、typed传输、取数接口、全消费者接入、对齐与有效性facts、项目迁移/导出/Replay、帮助更新、focused测试、独立数值oracle、Cocoa/Windows性能记录。每阶段记录文件scope、实际命令、输入hash和未闭合项；不能只写“完成M4”。

开发回退：未完成时保持新产品路径关闭；切换前保留旧公开loader与旧项目legacy恢复。若candidate验收失败，撤销本任务启用点并保留修复源与证据，不回滚其他工作、不改写用户文件。正式native项目不能在旧版静默降级；版本不支持时明确拒绝。

本轮文档交付检查：全文读回Spec/Plan、相对链接/测试路径/owner符号核对、拟新增与既有区分、阶段依赖/策略/数值一致性、`git diff --check`，以及仅新增两份文档和本任务`.state`证据。因未改产品可执行行为，不运行runtime/full suite；buffer探针是分析证据，不代替实施回归。既有lessons已覆盖原生安全、缺口与性能证据区分，本轮不为尚未实施的方案新增lesson。
