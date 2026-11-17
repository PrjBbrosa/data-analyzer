# 导入恢复提交后鲁棒性补充 Plan

日期：2026-11-17；2026-11-18 更新执行状态。状态：**partial：独立分支已实现补充修复；项目重开、Cocoa 完整生命周期及 Windows/联合门禁未闭合。** 执行合同：[Followup Spec](../specs/2026-11-17-import-recovery-review-followup-spec.md)。实际结果见[执行记录](../verify/2026-11-18-import-recovery-followup.md)。

## 1. 目标、基线和并行工作约束

目标是关闭 `02d15a61` / merge `c848fdb1` 提交后审查的增量缺口 H01–H06，并把成果纳入已经执行的[原生采样 Plan B0–B6](2026-11-17-mf4-native-sampling-plan.md)及[导入恢复 Plan T4](2026-11-17-import-budget-and-dialog-recovery-plan.md)。不从头执行 M0–M6，不重写既有 store/prepare/renderer，不重做已提交的 enum/重名传输修复。

审查证据和确定性输入完整列于 Spec §1/§3。文档起草时 HEAD 为 `c848fdb1dc36dfc7c8fae2d724faed307264cea0`；已观察到 native_signal_store、signal_access、FFT-time/Order mixin 四个文件存在进行中的修改，`CSER TTR/` 为既有未跟踪目录。实施时重新获取实际状态；不能用该快照覆盖新增改动，也不能把旧红测结果声称为当前树结果。

**执行关系是增量交接，不是另起一组人员同时改同一文件。** 下表的 owner 是职责归属，不是新 agent 派发。默认复用在执行工作流的 owner；若新增执行者，必须先取得具体文件/符号的交接。用户对另一工作流的执行授权不由本文件更改。2026-11-18 用户另行明确要求开分支执行：本任务使用独立 worktree `codex/import-recovery-followup`，基于已合并原生修复的 `68013e34`，不编辑 Grok 的 checkout、不替其更新状态。以下共享文件规则适用于最终接收/合并；本分支不合并、不推送、不发布。

| 补充任务 | 上游既有 owner / 冲突面 | 执行规则 |
| --- | --- | --- |
| S1 / H01 引用释放 | 导入产品 owner；`import_coordinator.py` 与 `_project_io_mixin.py` 可与 B3/B5 冲突 | 先核对文件归属；无活动冲突时可先做，不等全部 native 完成 |
| S2 / H02 暂存配方时间 | B5 编辑/配方 owner；`channel_edit_log.py`、channel editor | 同一 owner 接收反例并串行实现 |
| S3 / H03 逻辑派生取数 | B1/B3/B5 接缝；`signal_access.py`、`file_data.py`、编辑/项目/消费者 | 等正在修改的取数/halo 合同交接；由一个数据 owner 维护 resolver，产品 owner 只接线 |
| S4 / H04 MDF2/3 | B1 IO owner；`mdf_reader.py`、native reader tests | 接入 B1 版本分支与证据，不由第二人并行编辑 reader |
| S5 / H05 整数精度 | B2/B5 DSP owner；`analysis_signal_prepare.py`、分析接线 | 与范围/halo/预算合同整合，禁止独立另写转换流程 |
| S6 / H06 恢复 UI 验收 | 原恢复 T4 / 产品 owner | 补验未闭合项；发现代码缺陷交回 owner，几何/QSS不由其他阶段顺手修改 |
| S7 联合接收 | 原生 B6 唯一集成/全套 owner | 接收增量与上游结果，复用同快照证据；不启动第二套全量验收 |

共享 `tests/ui/test_native_signal_consumers.py`、`tests/ui/test_mf4_native_product_path.py` 和项目/配方测试同样执行单 owner 编辑；多个任务需要用例时先汇总给所属 owner。独立实现期间只跑所属 focused/boundary。

## 2. 执行图和完成定义

```text
S0 接收当前源码、owner、红测归属
 ├─ S1 导入生命周期 ───────────────────────→ S6 恢复 UI 补验
 ├─ S4 MDF2/3 ───────────→ 接入原生 B1
 ├─ S2 暂存配方合同 → S3 逻辑派生取数 ─────→ 接入原生 B5
 └─ S5 整数精度 ─────────→ 接入原生 B2/B5
以上增量 + 原生 B1/B2/B3/B4/B5 的相关成果 → S7 接收账本 → B6 唯一联合门禁
```

该图表示依赖，不是并发授权。S2/S3 可由同一 owner 在一个波次内完成；必须先冻结暂存/应用后通道的取数合同，避免先修一半又返工。S4/S5 若另一工作流已经实现，只补缺失的反例或接收证据。N01–N08 在本文件中始终是上游依赖，不再创建第二套修复任务。

完成标准：每个 H 项有当前快照的修复前反例或可追溯的已有红测、实现范围、通过的 owner/boundary、真实路由证据及剩余平台状态。源码消除了旧模式或已有大批测试通过，都不能单独关闭 H 项。H01 可独立接收；H02/H03 产品链尚缺 B3/B5 时保持 partial。

## 3. S0：接收与固化反例

Owner：原生集成负责人协调各现有 owner；只维护接收账本和未被占用的测试。

1. 记录 HEAD、tracked/untracked 范围、受影响文件内容 hash、正在修改的 owner、已运行测试和当前 API。初始账本可放 `.state/import-recovery-followup/`；最终必要证据写入 `docs/analyzer/verify/`，不让交付依赖临时目录。
2. 按 Spec H01–H06逐项标记未覆盖/进行中/待接收/通过/失败/UNKNOWN，并记录所属 B 阶段。用户截图只作为工作已启动的背景，不能替代命令与源码证据。
3. 将新增反例归入 S1–S5 的 owner 测试；已修复时保留回归断言并追溯旧实现的失败证据，不在活动工作区反向恢复代码制造红测。不得因“现在不是红的”重复修一个已完成问题。
4. N09 以已提交的 shared enum/物理记录实现和两条往返测试为起点，分别登记“合成协议已过”与“事故样本 GUI/oracle/平台待验”。原生计划历史状态的更新由其文档 owner 接收，不在本工作流抢改。
5. 冻结 S2/S3 的 time/axis/validity/segment/revision 字段与 S5 的精度政策，复用 B1/B2 当前邻点接口。若接口仍在编辑，先完成无依赖的 H01 或准备测试输入，等交接再接线。

Focused：只跑尚未有当前证据的对应反例与 owner 基线，不跑通用全套。Exit：每个 H 项有唯一 owner、依赖、可重建预期、测试落点；没有重复派工或未经验证的“完成”。

## 4. S1：完成调用的引用释放（H01）

Owner：`mf4_analyzer/ui/main_window/import_coordinator.py`；只有确需调整实际 transform/回调持有方式时才修改 `_project_io_mixin.py`、Replay/Batch 接线，由原产品 owner 整合。

- 先补真实执行过 ImportCall 的生命周期红测：bound transform 持有宿主，kwargs 持有可 weakref 的数组/帧对象；终态后关闭+GC可释放。保留真实 Qt 事件处理与 worker drain，不用显式删除宿主来替代验证。
- 追踪成功、错误、取消、重试/放弃、session变化与宿主销毁的引用链。仅清理已终结调用；必须保留活动 worker 和尚有效重试所需数据。不要只为测试把 `_last_call` 在任意时间设空，不排查其他实际引用。
- 用生产导入的 bound transform 和 CAN 帧 kwargs 补接线测试。之后排队一个正常请求，证明清理不反向取消、不发布迟到结果、不重注册。
- 诊断历史仍有有界 request/path/stage 信息，失败恢复和 fresh-limits 重试语义不变。无需更改源文件或默认预算。

Focused：`tests/ui/test_import_coordinator.py`、`tests/ui/test_batch_dbc_parent_close_subprocess.py`；涉及 Replay 后在独立新进程跑 `tests/acquisition_ui/test_replay_tab.py`。Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`。

Exit：活动 QThread 安全回收、各终态一次、宿主与大型参数 weakref 释放，下一请求正常；真实最后窗口退出探针不留所属子进程。现有弱宿主 lesson 已覆盖原则，不创建重复教训。Cocoa 交 S6 单独取证。

## 5. S2/S3：派生数据在暂存和应用后保持同一合同（H02/H03）

Owner：B5 编辑/配方 owner 负责 `io/channel_edit_log.py`、`ui/dialogs/channel_editor.py`；数据 owner 串行整合 `io/file_data.py`、`io/signal_access.py`，必须先接收 B1/B2 正在修改的接口。项目、绘图、导出接线仍分别归原 owner，不把新实现塞进 MainWindow。

1. 固化两个独立失败：暂存 abs→derivative 应为4而非1；已应用 abs 被 `read_signal` 读取并继续派生必须成功。单独检查首次与保存重开，不能只断言 `logical_channels` 中存在数组。
2. 冻结并实现完整暂存表示，继承真实 time/axis/quality/segment/revision；用非等间距时间和两/三级配方验证导数、积分，原始 raw/time 不变。空、单点、shape冲突、非有限/失效、segment按 Spec §5 验证。
3. 统一 logical channel 的目录与读取解析，沿 B1 的 span/neighbor halo API。原始 physical key 与派生身份分开；隐藏/删除与依赖缺失不自动回退原始同名对象。已有同名来源用复合 identity 验证。
4. 接真实编辑器：新建→继续派生→应用→勾选/绘制→分析→保存重开。可隔离文件选择/确认对话框，不 mock 取数、计算准备或注册。编辑/切 View 不隐式计算，应用后的 revision/cache 按现有 owner 失效。
5. 从真实编辑器导出选定派生通道并回读；原始导出模式、逻辑选择、质量与大整数分别验证。项目仍 reference-only，关闭/取消/失败释放临时量并接入 B5 预算，不另做独立 byte ledger。

Focused：`tests/test_channel_edit_log.py`、`tests/test_signal_access.py`、`tests/test_mf4_native_export.py`；UI 分批跑 `tests/ui/test_channel_editor_recipes.py`、`tests/ui/test_channel_editor_expression.py`、`tests/ui/test_channel_editor_export.py`、`tests/ui/test_native_signal_consumers.py`、`tests/ui/test_mf4_native_project_migration.py`，补受影响的 `tests/ui/test_project_session.py` 用例。若沿用现有测试文件不足，可新增明确 owner 测试文件，须在账本写明，不能把临时 probe 当永久回归。

Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_native_import_boundaries.py`；接线涉及 UI 后加 ownership/import/lambda gates，实际改 canvas 才加 `tests/ui/test_pg_canvas_backref_invariants.py`。不为了“派生”二字重跑全部 signal/UI。

Exit：H02/H03 两条反例及实际使用链通过、原数据不变、质量/范围/identity不丢失、取消/重开不残留。若 B3 的入口或 B5 项目分派未交接，已完成 helper 单列通过，产品链保持 partial，不绕过消费者完成验收。

## 6. S4：版本专属 MDF 数值读取（H04）

Owner：B1 IO owner，`io/mdf_reader.py` 与 `tests/test_mdf_native_reader.py`；loader/adapter/transport 若需接线，由同一 IO owner 顺序处理。

先用固定 runtime 生成 Spec §3 的三版本最小文件，使用 `MDF.save` 的实际返回路径避免扩展名重命名导致假失败；legacy/native分别经真实 broker。再增加带人工转换 `2*raw+3` 的整数/浮点与空/单点/多点矩阵。

按各版本真实类型/转换/质量字段修 classifier 和读前预算；不将所有旧版转换判为 identity、不用 legacy fallback、不删除未知布局和数组安全检查。验证 master 时间、raw dtype、physical、单位、源 hash及跨进程只读/共享；低预算先拒绝，之后正常文件可打开。

Focused：`tests/test_mdf_native_reader.py`、`tests/test_mdf_reader_safety.py`、`tests/test_mf4_loader.py`、受影响的 `tests/test_source_adapters.py` 和 `tests/test_import_transport.py`；产品链复用 `tests/ui/test_mf4_native_product_path.py`，由集成 owner 合入新增用例。Boundary：`tests/test_native_import_boundaries.py`、`tests/test_import_packaging.py`、`tests/test_packaging_imports.py`。

Exit：MDF2/3/4 各适用正常标量与转换 oracle通过，无源改写/自动回退/计费绕过，旧 loader 控制通过。Windows frozen 与事故样本 R01 仍交 B6，不用这些小文件代替。

## 7. S5：精度拒绝与原因传播（H05）

Owner：B2/B5 DSP owner，`analysis_signal_prepare.py`；具体 FFT/时频/Order/FRF、Batch 调用者由原产品 owner 接线，和范围/halo变更串行整合。

- 先冻结 Spec §7 的精确可表示政策，加入两点合并反例与边界 oracle。安全整数转换应 ready 且数值精确；不可精确表示的整数在创建有损分析数组前拒绝。不得通过改断言、宽容差或转换原始 store 消除红测。
- 实际请求/halo先确定；段外不相关大整数不得阻断合法选区。覆盖 int64/uint64、正负/极值、精确的大偶数、空/短/shape/质量和显式 representation。原始读取和数值导出保持精确。
- 将精度原因传至 GUI 和 Batch 的真实请求结果，不能变成“源缺失”、忽略该通道或成功空结果；不启动拒绝请求的 job、不污染旧已应用结果，Batch reporter单次终态。
- 预检与 B5 的预算/准备缓存相接，allocation/call spy 检查不新增 hot-path 全量扫描或 object数组，保持 UI 编辑不计算。此项不实现 F08/F09、不调整时间轴精度容差。

Focused：`tests/test_analysis_signal_prepare.py`、`tests/test_mf4_native_fidelity.py`、`tests/test_mf4_native_export.py`；生产入口用 `tests/ui/test_native_signal_consumers.py` 及实际受影响的单个分析 owner 测试，Batch 用 `tests/test_batch_runner.py` 对应请求用例。Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py`，实际 Batch 编排变更补 `tests/test_batch_run_reporter.py`，UI state 写入变更补 ownership gate。

Exit：不再静默合并两点、ready 输入保证该转换数值精确、原始数组不变、用户得到准确拒绝理由；GUI/Batch parity同时配绝对整数 oracle。未接通的入口保持 partial。

## 8. S6：恢复界面与生命周期缺失验收（H06）

Owner：恢复 T4/产品 owner；几何/进度组件 owner 仅处理实际新复现的缺陷。前置 S1 及当前共享接线稳定，接收原有 G01/P01/E01 的有效证据，只补受变更影响或尚未验证的项。

- Cocoa：真实短提示与 Batch/UltraView 工作窗、进度父销毁/重复取消/迟到回调/连续两个任务、状态栏同步；实际资源拒绝→旧 worker回收→重新检查→新请求成功或再次明确拒绝。记录 UI 几何/截图和进程/请求事实，不能只点到重试按钮。
- Windows：新鲜 Full/Lite windowed EXE，包 hash/运行时/DPR，100%及125%或150%，按恢复 Spec 的普通/紧凑工作区核对短框内容高度、轨道/按钮右边缘、取消和重试。缺环境标 UNKNOWN；不以 offscreen/Cocoa冒充，也不启动无关全窗口验收。
- 多文件失败只重试失败项；源/目标/项目改变后旧重试无效，程序关闭不取消下一项。与 S1 同矩阵取证可以复用，不另起重复生命周期实现。

Focused：按实际修改或尚缺证据选择 `tests/ui_kit/test_dialog_geometry.py`、`tests/ui_kit/test_message_dialog.py`、`tests/ui_kit/test_import_progress_dialog.py`、`tests/ui/test_tool_window_screen_fit.py`、`tests/ui/test_project_dirty_guard.py`、`tests/ui/test_import_coordinator.py`、`tests/ui/test_compute_progress_integration.py`；Replay仍独立进程。QSS实际修改才补 `tests/ui_kit/test_qss_border_shorthand.py`。

Exit：G02/P02/E02逐场景/平台有结果，W01独立标记。只有组件结果则仍partial；不把U通过写成低预算R01关闭。

## 9. S7：联合接收、验证成本和交付边界

唯一集成 owner 汇总 H01–H06、原生 N01–N09/F01–F12/R01 和恢复 G/P/E/W 状态，列明已完成/失败/未测及具体证据。消除旧状态与新代码不一致，记录每次修复实际所属提交或 dirty hash，不累计不同源码快照的通过数当作当前验收。

本补充没有独立的全套 baseline 或第二套全量 gate。各阶段先跑 owner，再跑实际相关 boundary；通过即停止，只有新改动、失败或明确未覆盖风险才扩大。S7 接入原生 B6 的一次稳定集成里程碑：检查运行中的 pytest及cwd，复用同HEAD/源码指纹的权威结果；唯一协调者先主套 `--ignore=tests/acquisition_ui`，结束后新进程跑 `tests/acquisition_ui`。不得与另一工作流同时启动全套，活动源码修改期间的全套不构成验收。

如果用户另行要求先发布独立 U 修复，由发布负责人明确挑选后的文件/行为范围、共享 legacy 回归和平台门禁；不能只用 native 开关隔离整个提交，也不因新文档自动启动发布或重复全套。native默认和整树放行仍由原生 B6决定，本补充不降低目标或取消旧版/样本/Windows要求。

回退只针对本次新增修复的明确单元，保留其他工作流成果、导入隔离和原安全检查；不 reset 活动工作区、不改源数据、不整批回滚 `c848fdb1`。修复失败先保留可重建反例与实际状态，不用 fallback、删测试或新增 xfail 隐藏回归。

最终交付：修复代码/持久回归测试、H逐项验收记录、上游B阶段接收位置、实际命令/输入与源码指纹、未测平台及明确剩余项。只更新确有用户操作变化的 hints/quickref及相关帮助，不做版本升级或无关文档重写。

## 10. 起草阶段文档检查（历史记录）

起草阶段仅创建本 Plan 与配套 Spec。全文读回、检查相对链接与实际源码/测试路径、H问题→合同→任务→门禁映射、共享文件归属和上游依赖、`git diff --no-index --check /dev/null <新文档>`。不改原生/恢复旧计划，以免与在执行工作流竞争；新文档的关系表与反例可直接供其接收。

文档不改变可执行行为，不运行 runtime/full suite。前轮测试和探针是固定审查基线的证据，不是起草期间并行源码的新验收。继续使用既有 weak-host、native numeric oracle 与 partial-import lessons；本次未发现需新增的独立规则，不重复创建 lesson。


## 11. 独立分支执行与接收状态（2026-11-18）

| 阶段 | 当前接收结果 | 尚缺条件 |
| --- | --- | --- |
| S0 | PASS：基线 `68013e34`、独立分支/worktree，红测和变更归属已登记 | 合并时重新核对 Grok 后续改动，不覆盖其工作区 |
| S1 / H01 | 定向 PASS：成功/失败/取消/session 失效后释放 call/回调；下一请求继续 | Cocoa 完整父销毁/最后窗口退出矩阵归 S6 |
| S2 / H02 | 定向 PASS：真实编辑器连续派生保留时间；shape 冲突明确拒绝 | 不替代 N07 全局资源/缓存验收 |
| S3 / H03 | partial：暂存/应用/绘图/准备/选择导出/保存已过 | B5 native 项目重开与完整复算链仍缺 |
| S4 / H04 | 定向 PASS：MDF2.14/3.30/4.10 标量版本矩阵及 IO 回归 | R01/Windows 不由合成小文件关闭 |
| S5 / H05 | 定向 PASS：精度 oracle、FFT 拒绝不计算、Order 不建 job、真实 Batch 失败原因及安全范围 | 全入口/平台由 B5/B6 联合接收 |
| S6 / H06 | partial：Cocoa 短框/工作窗与真实资源重试通过 | 混合 Cocoa 生命周期命令停滞为 UNVERIFIED；Windows UNKNOWN |
| S7 | partial：接收账本已交付；未启动第二套全量 gate | 原生 B6 唯一稳定快照集成/平台门禁 |

本轮新增 owner 测试：`tests/ui/test_native_derived_followup.py`、`tests/test_native_precision_routes.py`、`tests/ui/test_import_recovery_followup.py`。未接收项已有 B5/B6/T4 归属，不另起重复实施计划；具体验收输入和退出条件见执行记录“剩余接收项”。
