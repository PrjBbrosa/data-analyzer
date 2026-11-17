# MF4 原始采样、分析正确性与性能迁移 Plan

日期：2026-11-17；同日按 `c126fcae`、导入恢复 M6 报告及消费者反例修订。状态：**needs revision / partial，已复现功能阻断；当前候选禁止切默认或随版本发布。后续执行 B0–B6 修复与验收，不重做已有 M0–M5 成果。**

执行合同：[原始采样 Spec](../specs/2026-11-17-mf4-native-sampling-spec.md)，同时承接[导入恢复 Plan 的 R 轨道](2026-11-17-import-budget-and-dialog-recovery-plan.md)及其[资源/进度 Spec](../specs/2026-11-17-import-budget-and-dialog-recovery-spec.md)。初版文档已随 `b68d2d7a` 提交；后续恢复任务已产生实施记录。本次授权仅更新本 Plan/Spec，不启动 agent、不接管产品编辑、不提交/推送/发版。其他任务的授权和运行状态不由本文变更。

## 0. 当前基线、证据与后续入口

修订核对 HEAD：`c126fcae24b73961eb798b989df1068a94327197`，`APP_VERSION=v8.4.8`。修订前有 56 个 tracked 修改和 18 个 untracked 条目（含目录，不等于文件数）；这是观察快照，不是可复用的源码指纹。原生实现和 T1–T3 交织在同一 dirty tree，未提交不等于未实施，也不等于完成验收。

| 已集成提交 | 后续必须继承的基线 |
| --- | --- |
| `161e5387` | reader 安全检查、固定依赖、broker/typed transport、取消/资源合同已集成；不再按“另一批未提交”等待它 |
| `77ceade6` | 8.4.8 版本与帮助/项目测试基线；本任务不另做版本升级 |
| `febfc01d` / `c64caaba` | Windows patch LF 校验与 Lite 仓库导入路径；不回退构建修复 |
| `c126fcae` | 扭矩 `torque.si` 默认参考 `1e-6 Nm`、Nm/nm 区分及 Lite UNC 路径；同输入 parity 固定当前单位/dB 设置，不能混用旧默认参考 |

以下状态来自本地 `.state/import-budget-recovery-20261117/{progress,m0-result,m1-result,m2-result,m3-result,m4-result,m5-result,m6-result,t4u-result}.md`，并核对了关键 API、默认 loader、schema、xfail 与本轮阻断涉及的源码。报告中的测试结果属于各波次快照，本次文档修订没有重跑，不能累计成当前全树 PASS。`.state` 不随文档分发；后续接收时将必要的命令、源码/输入 hash、未闭合项写入正式验收记录。

| 阶段 | 可接收的现有成果 | 仍需关闭的门禁 |
| --- | --- | --- |
| M0 | fixture、消费清单、账本、manifest；同轴 FFT/FRF oracle 有记录 | F08/F09 滤波/异轴参数尚未冻结；复核消费清单与当前实现 |
| M1 | store、read_signal、FileData native 分支、生命周期记录已有代码及 focused 记录 | N01普通采样率误判；生命周期记录不等于应用级 reservation/LRU 已完成 |
| M2 | native reader、显式 adapter/broker/transport；报告称事故样本固定预算读取成功 | N09事故样本在正式transport读回失败；目录差异、完整注册、峰值与Windows仍未闭环 |
| M3 | per-curve 取数、原始点查询/统计、Custom-X 与单点显示已有候选 | N02入口残留、N03失效点重现、N06标记串子图；Cocoa、性能及Pin/比较/UltraView仍待验 |
| M4 | **partial**：同轴准备及 Order 时间检查已有实现 | N04 RPM邻点丢失、N05整段预检误拒有效选区；F08/F09仍strict xfail；准备缓存/全局预算未闭环 |
| M5 | schema 6、迁移 helper、配方、原生导出与 Replay adapter 已有候选 | 普通项目恢复及 Replay UI 仍走 legacy；helper 测试不能证明产品入口闭环，M5 整体验收仍 partial |
| M6 | 新取得 `m6-result.md`：显式正式路径匿名fixture及7条入口测试有通过记录；事故样本有同时间线RSS与失败记录 | 事故样本 `identity physical must share raw`，GUI注册0，R01未关闭；图2/Windows UNKNOWN，Cocoa/完整性能/全套未放行。复用现有入口测试，不重复搭建 |
| U/T1–T4 | 几何、进度和结构化重试已有实现/局部记录 | T4-U 是组件验收，不能证明 R01；P01 初测失败后有复测记录，接收时核对最终指纹；Windows UNKNOWN |

### 后续工作顺序与共享文件归属

M0–M6 下文仍是完整合同与 owner 测试清单，**不是待从头执行的七个空阶段**。以下为工作流概览，实际派工与退出条件以 §0.1 的 B0–B6 为准：

1. **接收与冻结**（集成负责人）：取得在执行任务的最终交接、当前 HEAD/dirty/hash、阶段命令与未闭合项；核对是否已有 M6 探针或全套。记录普通打开、拖入/最近、项目、Batch probe/load、Replay 的实际分派。共享文件 owner 尚未交接时只读，不重派相同实现。此步不跑通用全套基线。
2. **补 M0/M1/M2 数据与传输基础**（IO/预算 owner）：先解决 N01/N09，再核对 979/927/10 与历史 967/915/22 的目录差异。应用级存活源/绑定结果/任务 reservation 和准备 LRU依 Spec §3 补齐，不能把 `release_lifecycle` 当作降低 `used_bytes`。Focused/Boundary见B1、B5和M1/M2。
3. **补 M4 数值合同**（DSP owner）：先修 N04/N05 的实际范围与邻点，再冻结 F08/F09 的具体设计和支持范围，以真实信号 oracle 实现。保留已通过同轴路径，不能通过新增两个返回参数字典的函数消除 xfail 就宣称实现。Batch native 的 `target_fs/decimate` 必须纳入准备次序和抗混叠证据；现有 legacy 滤波不是其验收。Focused/Boundary 见 B2/B5/M4，并补当前扭矩参考的 `tests/test_db_reference.py`、`tests/test_batch_weighting.py` 及受影响 analysis-context 用例。
4. **补 M3/M5 产品闭环**（集成负责人协调现有 owner）：在受控候选入口贯通普通/拖入/最近、项目 policy 恢复、Batch probe/load、Replay；已有 native helper 复用，不再新建平行路径。schema 6 native 恢复不能读 legacy 后当作成功；旧项目仍明确 legacy。迁移预览/取消、导出和 Replay segment 选择须由真实 UI 触发。Focused 按 M3/M5 各 owner，Replay 独立进程；UI ownership/lambda/import gates 同时适用。
5. **补 M6 / T4-R 并作默认决策**（唯一集成/全套 owner）：先接收已有显式正式链路结果，只补未覆盖的 fixed-budget、Cocoa/Windows、性能/释放和入口矩阵。完成全部必需合同后，才验证拟切默认的稳定候选快照并作放行决定；M4 partial、图2缺失和 Windows UNKNOWN 分列，不用 U 的通过替代 R。全套策略见 M6，不能因文档更新启动一次全套。

共享 `io/import_limits.py`、`import_worker.py`、`import_process.py`、`import_transport.py`、`source_adapters.py` 由一个 IO 集成 owner 接收 T3 后串行整合；`import_coordinator.py`、`_project_io_mixin.py`、`window.py`、`replay_tab.py`、hints/quickref/帮助由一个产品集成 owner 接收 T2/T3 后整合。几何/QSS 留给 U owner；本原生计划不重做 T1–T3。

后续若另获执行授权，只有冻结 store/read_signal/PreparedSignal 合同后，数值 owner 与不重叠的显示/项目 owner 才可并行；共享文件接线和全套始终归同一协调者。各 worker 仅跑所属 focused/boundary，保留其他人的改动。M4 数值与 M5 全链验收存在依赖，已有 M5 helper 不能跳过此依赖。

### 0.1 阻断修复波次：文件归属、红测与退出条件

Spec §10.1 是 N01–N09 的反例与预期，§10.2 是不得遗漏的产品矩阵。下述“测试”是接续实施必须补齐/执行的门禁，不代表本次已新增或通过。现有60条focused通过不能关闭N01–N06，M6匿名入口通过不能关闭N09。每个波次交接记录：N/F/R编号、修复前失败、修复后结果、改动文件、HEAD/dirty/hash、剩余问题；没有实际证据不得标完成。

跨波次共用的 `tests/ui/test_native_signal_consumers.py`、`tests/ui/test_mf4_native_product_path.py` 由集成负责人唯一编辑，各owner交接用例后串行合入；其他测试随其产品owner归属。B2/B4即使并行，也不得同时改共享测试或coordinator文件。已有测试可以共同作为focused门禁，编辑权不能因此重叠。

```mermaid
flowchart LR
  B0["B0 接收/冻结/固化红测"] --> B1["B1 采样事实与传输"]
  B1 --> B2["B2 分析选段/邻点"]
  B1 --> B4["B4 显示质量/游标"]
  B2 --> B3["B3 产品消费者接线"]
  B3 --> B5["B5 DSP/资源/兼容全链"]
  B4 --> B5
  B5 --> B6["B6 稳定快照/平台/放行"]
```

**B0 接收与红测，集成负责人。** 接收M6新增的 `tests/ui/test_mf4_native_product_path.py` 及显式入口，不重复派发；取得重叠owner交接与稳定源码范围。将N01–N06临时probe分别固化到下列owner测试；N09补最小enum共享缓冲区fixture及损坏manifest反例，事故文件保留hash不入仓。N02区分“真实FileData调用生产方法已复现”与“真实界面事件尚待测”，Batch残留仍是源码证据。冻结N01精度政策、请求/halo/有效段API、display质量与marker身份合同；为F08/F09补具体参数设计，未经冻结不开发对应DSP。消费清单逐项标native/legacy-only/无关及证明，不能仅靠grep消除所有 `fd.data`。只跑各反例和受影响focused基线；不跑全套。Exit：反例能稳定失败，失败原因与Spec一致；缺少样本/平台明确UNKNOWN，不能以skip关闭。

**B1 采样事实及transport，IO owner，关闭N01/N09。** 独占 `io/native_signal_store.py`、`io/signal_access.py`、`io/mdf_reader.py`、`io/import_transport.py`，其余导入共享文件仍由同一IO集成owner串行接线。实现Spec §5的精度政策，保持raw/time不变；在manifest中分清缓冲区共享与conversion语义，保留类型/shape/校验/预算及非法输入拒绝，禁止简单删除安全断言。

- Focused：扩充 `tests/test_native_signal_store.py`、`tests/test_signal_access.py`、`tests/test_mdf_native_reader.py`、`tests/test_import_transport.py`；真实broker/GUI复用 `tests/ui/test_mf4_native_product_path.py`。覆盖10/100/1000/1024Hz、非零原点、真实抖动/重复/回退/非有限、单点/空、声明冲突，以及identity/enum/数值转换的共享与非共享buffer。
- Boundary：M1/M2的neutral、native import、transport与packaging门禁；按实际文件选择，不扩到全部UI。
- Exit：普通合法采样率可从reader一直准备到分析，异常轴未被宽容差放行；匿名enum和事故样本均经真实子进程、transport、GUI注册，raw/code/labels/共享关系正确。固定memory/output预算不变，R01此时仅关闭已证实的文件链路项，性能/Windows等仍独立待验。

**B2 分析范围与邻点，DSP owner，关闭N04/N05。** 独占 `analysis_signal_prepare.py`、`ui/main_window/_fft_mixin.py`、`_fft_time_mixin.py`、`_order_mixin.py`、`_frf_mixin.py` 及对应coordinator；接线涉及 `window.py` 由B3 owner处理。请求范围和segment先确定，再读取邻点/halo与质量预检。既有算法核心不无故改写；native与legacy共享的Order路径同步验证。

- Focused：扩充 `tests/test_analysis_signal_prepare.py`、`tests/ui/test_order_multirate_rpm.py`、`tests/ui/test_fft_time_coordinator.py`、`tests/ui/test_native_signal_consumers.py`；用 `tests/ui/test_analysis_time_range_intent.py`、`tests/ui/test_analysis_time_range_confirm.py`、`tests/ui/test_analysis_time_isolation.py` 保护View/pane范围。实际按钮/任务测试在B3接线后闭环。
- 红测：N04应得到 `[120,200,280]`，增加真越界/gap拒绝及手动RPM、单位倍率；N05用二进制精确轴隔离N01，验证段外无效不阻止计算、段内无效不启动job且原因准确。扩至FFT/FRF配对和Order-vs-Time，不只修一个getter。
- Boundary：M4中立依赖与状态ownership；变更Batch编排时补reporter门禁。
- Exit：范围解析、准备、预览、缓存和执行一致；不重复全长转换，不因选区裁掉所需邻点，不静默填端点或跨gap。B2通过不代表F08/F09完成。

**B3 真实消费者接线，产品集成owner，关闭N02并承担N08入口矩阵。** 独占 `ui/main_window/window.py`、`analysis_time_range.py`、`analysis_context.py`、`ultraview_capture_coordinator.py`、导入/项目接线及 `batch.py`、`batch_export_size.py`；遵守现有模块边界，不把新数学放进window/batch编排。B2涉及的coordinator要先交接，禁止双owner同时修改。将N02列出的每个生产入口改为通道级事实，并覆盖Batch分组、单项和RPM，不用全局假的Fs/表兼容。

- Focused：`tests/ui/test_native_signal_consumers.py`、`tests/ui/test_mf4_native_product_path.py`、`tests/ui/test_mf4_import_flow.py`、`tests/ui/test_file_scope_follow.py`、`tests/ui/test_analysis_context.py`、`tests/ui/test_ultraview_capture_facts.py`；Batch用 `tests/test_batch_export_size.py`、`tests/test_batch_loader_dispatch.py`、`tests/test_batch_runner.py`、`tests/test_batch_time_group_acceptance.py`。按实际改动分批，不一次跑所有UI。
- 必补真实路由：注册native源→激活/勾选→Inspector选通道→设范围→点击FFT/时频/Order/FRF→等待任务终态；统计/尺寸建议/UltraView也从真实操作进入。边界可以隔离模态框，但不得mock掉本应被测的取数、范围或consumer。混合不同Fs/同名来源且没有公共axis是必要输入。
- Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`；Batch加 `tests/test_batch_run_reporter.py` 和中立render import门禁。
- Exit：清单中native可达入口无legacy属性异常、无静默漏项；每个请求得到结果或准确的合法拒绝。旧项目legacy-only分支仍可用。完整保存/导出/Replay及缓存生命周期留B5，不靠一条GUI注册测试宣布闭环。

**B4 显示与游标，画布owner，关闭N03/N06。** 独占 `ui/pg_canvas/overlay_axes.py`、`renderer.py`、`cursor.py` 及必要的 `ui/cursor_display_model.py`/bindings；canvas host仅由该owner维护声明过的协作者接口。B1取数/质量合同冻结后可与B2并行，但本轮文档授权不启动agent。复用既有renderer，不改ink、AA、150ms quiet window或View restore结算规则。

- Focused：扩充 `tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_pg_cursor_placement.py`、`tests/ui/test_native_signal_consumers.py`；滤波companion与Custom-X用 `tests/ui/test_time_filter_overlay.py`、`tests/ui/test_time_xaxis.py`。
- 红测：N03首次NaN且刷新后仍NaN，pan/zoom/resize/恢复/隐藏重显不复活999；N06每个子图只收本轴的30或3，扩展双Y轴、overlay、同名来源、隐藏/重排/移除/清空与Pin。断点和marker同时检查真实canvas数据与Cocoa可见几何/像素，图片输出复用现有artifact检查。
- Boundary：`tests/ui/test_pg_canvas_backref_invariants.py` 和既有paint-timer/restore-settlement门禁；真实Cocoa显示由本owner取证，最终平台性能归B6。
- Exit：查询/标记/统计/显示质量一致，raw不变；初画、交互及恢复路径全部成立。只有offscreen证据则视觉项仍UNKNOWN。

**B5 数值余项、资源与兼容，集成负责人协调既有DSP/IO/产品owner，关闭N07/N08并补齐M0–M5 Exit。** 文件仍按前述归属；IO补应用级reservation，DSP补准备cache及F08/F09，产品owner补项目/导出/Replay，不能多方同时修改 `analysis_signal_prepare.py`/`batch.py`。保留其他任务成果，先接收再补缺口。

- F08/F09按Spec §7冻结设计、输入频带/比率/origin/边缘与误差预算，用真实输入输出oracle替换占位xfail，GUI/Batch parity加绝对正确性；不得为通过而放宽门限。Focused用M4及 `tests/test_mf4_native_fidelity.py`，保留当前Nm/nm与dB参考回归。
- N07用调用/分配spy证明预览与鼠标回调不反复完整hash、全通道扫描/转换；必要统计移到局部/索引/worker并正确失效缓存。Focused用 `tests/ui/test_timedomain_hotpath_perf.py`、`tests/ui/test_analysis_cache_pinning.py`、`tests/test_import_limits.py` 及新增owner局部用例；真实耗时按B6测，缓存不能成为未计费副本。
- N08逐行验Spec §10.2。旧格式选 `tests/test_file_data_time_axis.py`、`tests/test_source_adapters.py`、`tests/test_import_format_roundtrips.py`；意图保护用 `tests/ui/test_analysis_explicit_refresh_contract.py`、`tests/ui/test_analysis_explicit_family.py`、`tests/ui/test_analysis_project_explicit_compute.py`；项目/公式/导出/Replay用M5，补 `tests/ui/test_ultraview_project_session.py`、`tests/test_mf4_native_export.py`。Replay在独立新进程运行。
- 资源按Spec §3/§8验证源、绑定结果、任务临时量并存的准入，以及成功/失败/取消/关闭/替换项目各终态释放；目录计数按物理身份对账，不以数量接近通过。
- Exit：N01–N09的功能/结构要求及F01–F12有owner证据，完整矩阵无遗漏；原生保真导致的合理结果变化与新回归分开列。未完成F08/F09、项目入口或共享legacy兼容时禁止进入“默认切换验收”。性能/平台尚未测的项目保持UNKNOWN交B6。

**B6 稳定候选与发布决定，唯一集成/全套owner。** 执行M6的真实Cocoa、Windows Full/Lite、固定预算、性能/生命周期及唯一稳定里程碑全套，记录前后HEAD/dirty指纹；主套与acquisition_ui顺序独立进程。先核对其他任务已有同快照结果，不重复或并发全套。默认启用点必须纳入拟交付快照及入口测试，不能用关闭开关的快照替代新默认验收。

Exit：提供逐项放行表，包含N01–N09、F01–F12、R01、资源/性能、Cocoa与Windows、共享legacy回归、完整产品路由；全部必需项PASS且无未解决的P1/P2，才能提出切默认/发布。xfail、skip、图2缺样本、Windows未测均不能冒充PASS，不能自行删减原约定范围。若仅交付与native分离的恢复修复，须另行确定隔离后的文件/行为范围并验证，不能只关闭native开关就将当前整树发版。本计划本身不授权版本升级、提交或发布。

## 1. 结论与方案

首选原生 typed 数组存储、共享时间轴、按需准备选定分析区间，复用现有进程隔离与画布包络。第一版不引入持久 mmap、不做“全文件统一到最快 Fs”、不为性能丢点。当前已有 import-hardening 变更是前置基础，不能覆盖或恢复成旧同步导入。

数据量并非一定增加：初始探针的本地样本公共表数值数组 199,980,448 字节；按原生样本保留 raw、必要 physical 与共享 time 统计为 25,089,754 字节。另一方面，10 个不重叠通道由旧公共轴只保留 1 个改为完整保留，会合理增加 10 倍数组量。需要按等内容比较性能，不能以历史丢数据的速度作放行依据。

性能主要风险是解析器重复读取同一组、交接和 float64 副本、恢复后增多的通道目录、逐 View 缓存、分析任务临时数组以及 GUI 内全量扫描。时域画布已经接受每条曲线独立 t/sig；这里优先接通取数合同，避免新建一套 renderer。

初始探针位置：`.state/mf4-native-plan-20261117/probe.py`、`results.json`。数字是 buffer 普查，不是产品峰值 RSS、冷盘吞吐或 native GUI 验收。未宣称新方案已经不卡顿。详细数据与局限见 Spec §2–3。

## 2. 前置条件、范围与变更控制

- 初始调查 HEAD 为 `5bac5a2c9ae40e1ea7a45ac4fbab3d7d6a652867`；当前基线见 §0。接续实施前重新记录 HEAD、`git status` 和所有受影响源 hash；等待重叠 owner 交接，不擅自 stash/reset。
- import-hardening 已由 `161e5387` 集成；参考 `docs/analyzer/plans/2026-11-17-import-native-crash-and-resource-hardening-plan.md` 与 `docs/analyzer/verify/2026-11-17-import-robustness-implementation.md`。其历史验收不是新原生采样或 Windows 验收。T3 资源错误字段/重试已有候选，接续使用其同一协议与 owner。
- 路由范围包含普通打开、拖入/最近文件、项目恢复、Batch probe/load、Replay、时域/Custom-X/游标/统计、FFT/时频/Order/FRF、通道编辑、导出、Pin/比较/UltraView。仅保留原始点而这些消费者继续取旧表，不能交付。
- 最终放行后保留旧 `load_mf4` 公开兼容入口，产品新开来源不再调用；当前默认仍 legacy。旧项目 legacy 恢复是显式兼容能力，不与 native 结果混用。
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

此图表示合同依赖，不表示当前施工起点。M3/M4 依赖同一冻结接口；并行条件见 §0。M6 前只在隔离开发开关/测试入口启用 native 产品路径；不能让半迁移版本成为默认。开关不是用户长期保真选项，完成后新开默认 native，legacy 只保留明确用途。

### M0：固化证据、消费者清单与数值门槛

接续重点：接收已生成 fixture/manifest/账本，补冻结 F08/F09，更新消费者清单和事故样本目录对账。保留初始红测记录，不重造一套 fixture。

Owner：测试 fixture、独立 probe、计划验收记录，不先改产品。

1. 将本轮丢峰、长范围、不重叠、单点、等长错位、重复/复位/失效位、大整数转换变成匿名 fixture，保留人工预期与文件 hash。失效位测试同时验证原始 API 的 flags 语义；不能依赖参数名猜测。
2. 给每个源建立预期通道目录：物理通道/别名/数组父项/元素/主轴/unsupported 分开。初始探针 967 个计数、22 个排除项和 915 个单点不是目标上限；与 M2 的 979/10/927 按物理身份逐项对账。所有受支持单点均应恢复而不伪造采样率。
3. 精确搜索生产入口的 `load_mf4`、`fd.time_array`、`fd.fs`、`fd.data`、`len(fd.data)`、`.shape` 和所有 frame helper。逐项标记 native 要迁移、legacy-only 或非受影响，记录 owner 与验证项，不用机械全局替换。
4. 建立可复现性能 manifest：同轴控制组、多率组、长覆盖恢复组、单点密集组、同钟错位组；补压缩/转换多/多文件/6×1,188,000 点标准绘图负载。小 fixture 测正确性，大 fixture 按预算生成；不故意耗尽开发机资源。
5. 冻结数字门槛与原始序列：无重采样的同源 uniform 输入以现有核心为回归 parity，同时用人工频率/增益/延迟 oracle 判绝对正确；新增对齐先用 noise-free 多正弦、已知延迟 LTI 和恒定/斜坡 RPM。测试频带、窗、分辨率、边缘忽略范围必须提前固定。F08/F09 未固定具体滤波参数和数值误差预算，不准进入 M4 的异轴 DSP 实现。
6. 首版数字门槛（同轴具体刺激已固化于 Spec §7）：稳态整周期 FFT 正弦频率误差≤1 bin，幅值相对误差≤1%；FRF 安全通带 0.05–0.30×较低输入 Fs，noise-free coherence≥0.99，增益误差≤0.1 dB、延迟对应相位误差≤1°；降采样带外混叠抑制≥60 dB。滤波边缘按设计支持长度剔除，不挑选结果有利区间。若已有 filter 不满足，保留现有用户 filter 行为，为新采样准备另定通过 oracle 的滤波设计；不得事后放宽门限。
7. 纳入恢复 R 轨道：memory=498,988,944、output≤249,494,472 同时注入；匿名与原样本分别记录。旧公共轴累计拒绝 638,740,162 是对照，不是 native 目标。M2 报告中的样本读取成功必须追溯源 hash/计费项，不把它升级为 R01 或同时峰值验收。图2样本缺失单列 UNKNOWN。

Focused（既有）：`tests/test_mf4_loader.py`、`tests/test_mdf_reader_safety.py`、`tests/test_analysis_time_axis.py`、`tests/ui/test_order_multirate_rpm.py`。候选已新增：`tests/test_mf4_native_fidelity.py`。补充合同先有红测并写明失败原因，不运行全套基线。

Exit：原始独立数据 oracle、消费清单和基准 manifest 可复查；控制组与错误结果区分明确。不得把现有“验证截断”的通过测试当作无损证明。

### M1：原生源与统一取数，保持其他格式兼容

Owner：候选已有 `mf4_analyzer/io/native_signal_store.py`、`io/signal_access.py`；现有 `io/file_data.py` 与 `source_adapters.py` 的明确分支。接续补资源生命周期/缓存合同，不重建存储层，不改 loader 默认。

- 实现不可变 axis/channel 表、raw/physical/validity、物理 identity、segment、Fs known/estimated/unknown 和 stable revision；轴共享不能消灭时钟来源。
- `read_signal` 支持真实范围、segment 与表示；连续区间尽量只读 slice，不先生成全长布尔 mask 或 float64 拷贝。非单调/重复保持样本序号；为空、单点、类型错误提供确定返回/错误合同。
- 既有表格来源适配遵守原格式时轴/单位规则。多轴 FileData 不提供假的公共 axis/fs/rows；所有 legacy-only 访问失败须可定位，测试证明未偷偷生成 shared table。
- 生命周期只由 FileData/store 与现有 job owner 持有，View/预览引用同一只读 buffer；派生渠道独立，不能原地改 native。资源 reservation 与释放接口放在中立预算 owner，先用 spy 验证。
- 固定 MF4 source root ID 和既有公开名；新增 physical key 用于内部、缓存与持久化，旧显示名只作为已知映射，不能自动模糊匹配。

Focused（既有）：`tests/test_source_adapters.py`、`tests/test_channel_frame.py`；候选已新增：`tests/test_native_signal_store.py`、`tests/test_signal_access.py`。预算接续同时用 `tests/test_import_limits.py`。Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_native_import_boundaries.py`。

Exit：不同长度、同名/Time、raw大整数、readonly、共享轴、source close/worker引用与旧格式适配全部通过；尚不声称 native 文件导入完成。

### M2：MDF 原生读取、准入与进程传输

接续重点：接收显式 native broker 实现及固定预算记录，补目录差异/生命周期/同时峰值证据，复用 T3 结构化错误。产品默认尚未切换；本阶段结果不证明 GUI 注册或 Windows。

Owner：`io/mdf_reader.py`、`io/loader.py` 薄入口、`io/source_adapters.py`、`io/import_transport.py`、`io/import_worker.py`、`io/import_limits.py`；broker 生命周期在原 owner 内改。

- 新增 native payload/入口，复用当前固定 runtime 与 MDF 数组/记录边界 admission。probe 与 load 使用相同目录、physical identities、主轴种类和 unsupported 事实。
- 每通道保留 raw、原 timestamps 和失效位置，按需保留已转换 physical，不做 shared interpolation、去重时间、回退排序、范围截断。非时间轴不伪装成秒；结构父项和元素的支持状态诚实呈现。
- 按 group/fragment复用读取，避免每个元素反复解压同一记录块；任何分块/元素view优化先做独立 oracle。未知依赖/布局仍 fail closed，不能为恢复单点禁用安全检查。
- 替换公共表字节估算为累积 raw/time/physical/validity/目录/读写临时量。包括转换输出类型膨胀、DataFrame兼容路径副本、父子交接峰值，unknown 不按零。低预算 tests 在分配前失败。
- typed transport 增加显式 native kind，验证 shape/dtype/数量、质量长度、physical-key引用、axis ID、只读与共享关系。请求、源变更、原子 manifest、临时目录清理合同不变；10,000 文件上限需写前估算。
- 新产品 load/probe 从 adapter 返回一个 native source，保持旧 API 可调用但不作为自动 fallback。含空格/中文路径、坏文件后正常导入、资源拒绝都走真实 broker。

Focused（既有）：`tests/test_mdf_reader_safety.py`、`tests/test_import_process.py`、`tests/test_import_transport.py`、`tests/test_import_resource_preflight.py`、`tests/test_source_adapters.py`；候选已新增：`tests/test_mdf_native_reader.py`、`tests/test_mf4_native_fidelity.py`。Boundary：`tests/test_native_import_boundaries.py`、`tests/test_import_packaging.py`、`tests/test_packaging_imports.py`。

Exit：真实子进程往返与独立 loader raw oracle逐点一致，源hash不变，资源/取消失败无部分注册；同轴共享在父进程仍成立；数组字节符合 Spec §3。不能只测直接函数绕过 transport。

### M3：时域、查询与显示成本

接续重点：保留 native FileData 消费者改造，完成真实 Cocoa 断线/单点/游标与交互验证；补齐真实入口、Pin/比较/UltraView 未覆盖项，不凭 offscreen 测试宣布本阶段全部完成。

Owner：`ui/main_window/window.py` 已有绘图/导出入口的薄接线；`ui/time_xaxis.py`、`ui/time_curve_bindings.py`；`analysis_context.py`/`analysis_time_range.py`；对应 canvas/query/Pin owner。不把新取数逻辑堆进 window.py。

- 接通 per-curve X/Y、当前选择范围并集、通道级滤波 Fs、单点 marker、失效/复位断线。源目录统计改为真实含义，恢复的单点不自动勾选；不再为提示行数遍历所有通道。
- 游标查询与统计从 native 完整数据获取；按 Spec §6 验证默认最近原始点、等距取较早、实际时间/差值、标记位置、重复点序号、覆盖外/缺口无数据与显式插值标签。相同查询/模式在缩放前后数值一致，不能读取显示包络。峰值与有效样本统计不依赖当前包络。Custom-X 同长度错位必须走显式关系检查。
- 局部范围查找、segments/metadata在导入时预计算；必要的大型查询交给已有 worker，不在鼠标/paint/attach回调中读盘或扫描全部样本。保持图层 ink、AA、150ms quiet window 与一次 settle合同。
- stable revision 贯穿 Pin、比较pane、UltraView；已绑定 View 不复制全数据或触发分析重算。视图删除/源关闭不产生迟到写入。
- 新增用户文案同步 hints/quickref；普通界面显示采用值与明确状态，复杂对齐/质量细节放详情。

Focused（既有）：`tests/ui/test_mf4_import_flow.py`、`tests/ui/test_time_xaxis.py`、`tests/ui/test_time_curve_bindings.py`、`tests/ui/test_time_range_consumers.py`、`tests/ui/test_time_filter_overlay.py`、`tests/ui/test_pg_cursor_placement.py`、`tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_ultraview_capture.py`；候选已新增：`tests/ui/test_native_signal_consumers.py`。按 owner 分批运行，不一次跑所有 UI。

Boundary：`tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`；若实际变更 QSS，再加 `tests/ui_kit/test_qss_border_shorthand.py`，本计划不要求改 QSS。

Exit：丢峰反例可见且游标/统计与原生取数逐点一致，native Cocoa检查实际 widget路径、断线与点标记；时域性能按 Spec测量。完整产品导出验收归 M5，尚不能因此宣称频谱保真。

### M4：统一分析输入，保护算法与相位

Owner：候选已有中立 `mf4_analyzer/analysis_signal_prepare.py`；现有 FFT/时频/Order/FRF mixin与coordinator、`batch_preprocess.py`、`batch_compute.py`、`batch_frf.py`、`batch.py`薄编排；`signal/`算法仅在明确数值需要时改。同轴准备已有局部测试记录，接续重点是 F08/F09、统一资源 owner 与 Batch 原生预处理，整体仍 partial。

- 统一返回 PreparedSignal/Pair，明确同轴直通、局部float转换、质量拒绝和显式对齐；配对两端分别传原轴，不接受仅“长度相同”的同步证明。
- native调用不进入 `prepare_analysis_time_axis` 的自动按序号重建；旧来源/旧项目的原政策保持隔离。显式均匀化必须计算新值与新时间并记录来源，不能仅换标签。
- Order修复等长错位检查及范围外端点延长；RPM/目标信号单位、倍率、有效覆盖先验证。针对同一源/跨源、相同点数不同timestamp测试，不因identity改造隐式改变RPM选择。
- FRF默认直通须符合原核心时间同步规则；异轴需用户应用“对齐后计算”。实现前提交M0已冻结的抗混叠、origin、比率、fractional delay与边缘合同，用独立相位/增益 oracle启用；不通过的组合明确unsupported。不能以GUI/Batch共享同一错误结果作为正确性。
- 分离 Fs重解释与重采样、状态ZOH与连续量线性、原始范围与计算有效范围。过滤halo按源读入并按设计处理边缘；已知gap不跨接。处理前后原始数组hash保持。
- 更新缓存key与effective facts，保留“编辑不计算、计算才应用、显示只重绘、切View恢复已应用结果”。准备缓存按字节计费，已绑定结果继续由原cache owner保留；大任务入场先预检。
- Batch与GUI使用同一准备合同；保留时间范围→质量验证/有限值政策→scale/offset→remove mean→抗混叠采样→用户滤波的既有次序。配对输入对齐单独计事实，不重复采样；单一reporter、取消、slice导出与单位/dB含义不改变。

Focused（既有）：`tests/test_analysis_time_axis.py`、`tests/test_batch_preprocess.py`、`tests/test_frf.py`、`tests/test_frf_scipy_parity.py`、`tests/test_batch_frf_pairing.py`、`tests/test_batch_frf_export.py`、`tests/signal/test_order_cot.py`、`tests/synthetic/test_cot_known_order.py`、`tests/ui/test_order_multirate_rpm.py`、`tests/ui/test_frf_main_window.py`、`tests/ui/test_fft_time_coordinator.py`、`tests/ui/test_analysis_cache_pinning.py`、`tests/ui/test_analysis_project_explicit_compute.py`；候选已新增：`tests/test_analysis_signal_prepare.py`。F08/F09 扩充 `tests/test_mf4_native_fidelity.py` 的真实 DSP oracle；当前参考值回归见 §0。

Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py`、`tests/test_batch_run_reporter.py`、`tests/ui/test_main_window_state_ownership.py`。所有数字修改红绿测试，unchanged核心不因本任务重写。

Exit：F06–F09与GUI/Batch同请求parity通过、内存准备有界、同轴回归结果不变；错误旧输入造成的差异有逐项解释。未验证的相位对齐不启用，若目标支持范围因此未满足，本阶段为partial而非完成。

### M5：项目、编辑、导出与 Replay 闭环

接续重点：复用现有 schema/配方/导出/Replay helper，补真实产品入口与 native policy 恢复。已有阶段报告“完成”仅按其实际 helper/owner 覆盖接收，不能作为本节完整 Exit 通过。

Owner：`ui/project_io.py`、`ui/project_source_match.py`、`ui/main_window/_project_io_mixin.py`、`io/channel_edit_log.py`、`signal/channel_recipe.py`、channel editor、`batch_output.py`、现有导出入口、`acquisition_capture/backends.py`/`acquisition_ui/replay_tab.py`、帮助/hints/quickref。

- 候选 codec 已支持1–6，native policy/物理key/对齐意图或悬挂通道写6；普通项目写4、带配方写5。接续沿用该 owner，不重新占用或改号。保持reference-only、不存样本/cache；补 policy 到 loader/注册/配方重放的实际分派。
- 旧项目自动按legacy恢复且标明，升级需明确用户选择与影响预览；新开文件native默认仅在M6后开启。迁移不覆盖源/原项目，不按显示名猜匹配。旧Fs override与公式在原政策下恢复，升级时转为明确派生意图或未应用状态。
- 单通道配方继承轴，多输入配方存axis/method/segment及raw/physical表示，重开可复算。派生/删除只改逻辑源目录，不改不可变raw。跨时钟缺口/源变化须报可行动原因。
- 原始数值导出支持同轴分组或长表，点数/时间/质量/整数精度回读一致；统一时间横表需显式request。Excel精度与行数限制显式处理，不截尾；PNG/PDF维持原render contract。
- Replay改为原事件时间/顺序，保留同timestamp记录；多率/单点/复位/失效位语义明确。其返回结构不能通过重新公共表化来兼容。
- 检查普通打开、拖入/最近、项目恢复、Batch probe/full load、Replay全链，不遗漏worker/打包hidden-import。更新受影响帮助与用户guide，不更改历史发布条目。

Focused（既有）：`tests/test_channel_edit_log.py`、`tests/ui/test_channel_editor_recipes.py`、`tests/ui/test_channel_editor_export.py`、`tests/ui/test_project_session.py`、`tests/ui/test_ultraview_project_session.py`、`tests/test_acquisition_capture_backends.py`、`tests/acquisition_ui/test_replay_tab.py`、`tests/test_help_content.py`；候选已新增：`tests/test_mf4_native_export.py`、`tests/ui/test_mf4_native_project_migration.py`。入口接线补 `tests/ui/test_import_coordinator.py`、`tests/ui/test_import_diagnostics.py`、`tests/ui/test_mf4_import_flow.py` 与实际受影响的 Batch probe/load owner。Replay目录在独立新进程运行。

Exit：F10–F12通过，迁移可预览/取消，保存重开保真；所有产品native读取不经旧shared-axisAPI。不能通过暂时禁用导出/编辑/Replay宣布完整迁移。

### M6：性能、跨平台与默认切换

Owner：单一集成负责人；不与其他全套重叠。

接收已有 `m6-result.md` 与 `tests/ui/test_mf4_native_product_path.py`；匿名路径结果可复用，事故样本N09失败必须修复后复验，不能重复报告为读取成功。显式正式链路验证允许在默认关闭时进行；它只能关闭对应矩阵项，不能越过 N01–N09、M4 partial、应用级资源合同、产品入口或平台门禁。R01 必须含 Spec §3.1 的固定预算、原样本 hash、完整 GUI 注册和独立逐点 oracle；事故样本与图2分列。

1. 根据 Spec §8 跑 cold/warm、单/多文件、1/6/20条曲线、少量/全部选择、缩放/拖动/游标/切View/取消/关闭/恢复。导入、交接、目录注册、查询、准备、DSP、paint/settle分阶段计时；CPU/RSS/临时磁盘同时间线采样。记录恢复的额外数据量，公平比较等内容工作负载。
2. 先复用 `scripts/benchmark_timedomain_interaction.py` 标准synthetic控制组，再新增MF4 native fixture入口（现有脚本仅synthetic/HDF，不能伪称已有MF4模式）。真实样本与合成payload同时跑，原始数值与像素/几何验收分开。
3. 用 `scripts/probe_view_switch_quality.py` 做视图恢复/AA结算回归；不调整质量阈值。新增大通道目录、缓存byte budget、20次循环leak测试。若吞吐失败，先依据profile优化group解码、复制或树构建，禁止损失样本换速度。
4. 默认放行前取得所有owner focused/boundary gate。先完成必需实现与候选分派，再对拟交付的稳定源码快照执行唯一集成全套；不在 M4 partial 时为攒通过数提前消耗全套。检查pytest进程及cwd，复用同 HEAD/dirty 指纹的权威结果；主套 `--ignore=tests/acquisition_ui` 完成后，另启进程跑 `tests/acquisition_ui`。不得并发；源变更/崩溃/中断记UNVERIFIED，不重启刷通过数。最终启用点若改变受测快照，原结果不冒充新快照验收，须明确新增变更及适用补验范围。
5. macOS Cocoa：真实打开、原始峰值/单点、计算/项目/取消闭环及性能。Windows新鲜Full/Lite windowed EXE：验证固定native库、子进程/typed传输、中文空格/正常UNC路径、峰值/内存/关闭；Modular受影响时加其打包入口。Windows未测即UNKNOWN，不能以源码打包tests代替。
6. CANape对照为可选独立参考：同文件同通道/单位/范围/真实时间点，对比点数、峰值、首末时间；仅使用其实际原始导出/采样读数，不能拿插值游标当原始点。没有CANape不阻止人工/字节oracle，但不能声称已与CANape实测一致。
7. 只有N01–N09、原生支持范围、所有消费路径、旧格式兼容、项目迁移、性能和平台门禁都闭环才切默认；某平台未闭环保持UNKNOWN，不由执行者自行缩小交付范围来放行。不会自动提交/推送或做版本发布；届时另按发布合同同步版本面。

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

最终交付包含已存在候选及接续补齐：native store与读取、typed传输、取数接口、全消费者接入、对齐与有效性facts、项目迁移/导出/Replay、帮助更新、focused测试、独立数值oracle、Cocoa/Windows性能记录。每阶段记录文件scope、实际命令、源码/输入hash和未闭合项；不能只写“完成M4”。统一列出 U 的 G/P/E/W 与 N01–N09、R01、F01–F12、资源/性能/平台结果，不累计历史通过数、不把缺失项改成非目标。

开发回退：未完成时保持新产品路径关闭；切换前保留旧公开loader与旧项目legacy恢复。若candidate验收失败，撤销本任务启用点并保留修复源与证据，不回滚其他工作、不改写用户文件。关闭启用点是开发隔离，不是共享代码回归已消除的证明；发布回退还须验证实际交付的共享变更。正式native项目不能在旧版静默降级；版本不支持时明确拒绝。

本次文档修订检查：全文读回Spec/Plan、相对链接/测试路径/owner符号核对、候选与已验收区分、阶段依赖/固定预算/数值与资源恢复合同一致性、两份文档的 `git diff --check`。本次只编辑这两份已有文档，保留所有既有产品及其他文档变更。未改可执行行为，不运行runtime/full suite；读取的阶段报告不代替当前源码验收。既有lessons已覆盖原生安全、缺口与证据区分，本次无需新增lesson。
