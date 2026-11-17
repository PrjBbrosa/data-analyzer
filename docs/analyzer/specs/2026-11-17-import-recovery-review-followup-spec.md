# 导入恢复提交后鲁棒性补充 Spec

日期：2026-11-17；2026-11-18 更新执行状态。状态：**partial：H01/H02/H04/H05 定向修复已有证据，H03 项目重开和 H06 完整平台验收未闭合。** 本文件补充合同，不接管或重启另一工作流。

配套：[Followup Plan](../plans/2026-11-17-import-recovery-review-followup-plan.md)。来源：[导入恢复执行报告](../reviews/2026-11-17-import-budget-and-dialog-recovery-report.md)、本次提交后源码审查与定向探针。继续遵守[导入恢复 Spec](2026-11-17-import-budget-and-dialog-recovery-spec.md)及[原生采样 Spec](2026-11-17-mf4-native-sampling-spec.md)。用户后续明确授权在独立分支执行；基于 `68013e34` 的实现与未闭合项见[执行记录](../verify/2026-11-18-import-recovery-followup.md)。未改默认入口或版本，未合并/推送/发布。

## 1. 基线与证据边界

审查对象为实现提交 `02d15a61`，已由 `c848fdb1dc36dfc7c8fae2d724faed307264cea0` 合并；相对 `c126fcae` 为 77 个文件、14,264 行新增、413 行删除。它同时包含对话框/资源恢复与 native 数据、分析、项目候选实现，不是单纯 UI 补丁。版本基线仍为 v8.4.8，本文件不变更版本。

前轮审查在该提交、tracked 工作区干净时完成。当前文档起草时 HEAD 仍为 `c848fdb1`，已观察到 `io/native_signal_store.py`、`io/signal_access.py`、`ui/main_window/_fft_time_mixin.py`、`_order_mixin.py` 正在修改；这个列表只是起草快照，不是对其他执行者后续编辑范围的锁定。用户提供的截图说明另一工作流已经开始 B0/B1；截图及进度文字不是修复通过证据。**以下反例归属于已提交审查基线，不能直接宣称并行修改后的当前树仍失败或已修复。**

审查本地记录在 `.state/import-review-20261117/`：`review-notes.md`、`probe.py`、`probe-results.json` 和三份测试日志。该目录不随 Git 分发，因此下文保留可重建输入、预期、owner 和证据等级，不要求后续执行者必须持有本机探针。

- 当时定向测试：284 passed；边界/保真：108 passed、1 skipped、2 xfailed；enum/重名传输修复：2 passed。分属不同命令，不是全仓库验收。
- 数值/生产方法探针与真实 offscreen 画布已执行；MDF2/3/4 对照通过真实 broker 子进程。没有本轮 Cocoa、Windows frozen 或全套通过结论。
- 原始事故样本、固定预算与图2样本的 R01 仍按原生 Spec 管理；新文档不降低其门槛。

## 2. 工作归属与范围

| 工作 | 唯一合同/执行归属 | 本补充的动作 |
| --- | --- | --- |
| N01 采样事实、N09 transport | 原生 Plan B1 | 接收当前实现和证据，不重复修复；H04 作为版本兼容补充交给同一 IO owner |
| N04/N05 范围/邻点、F08/F09 DSP | 原生 Plan B2/B5 | 不重写数值设计；H05 补精度拒绝及用户原因传播 |
| N02 消费者、N03/N06 画布 | 原生 Plan B3/B4 | 依赖验收；不在本计划再分派相同缺陷 |
| N07/N08 资源、项目、导出、Replay | 原生 Plan B5 | H02/H03 补派生通道端到端反例与数据合同，沿其存储/资源/项目 owner 整合 |
| 导入完成后的引用释放 H01 | 本补充，复用导入 coordinator owner | 覆盖默认路径；不等待 native 默认切换才处理 |
| 恢复 UI 的 G02/P02/E02/W01 余项 H06 | 原恢复 Plan T4，本补充登记接收 | 完成缺失验证，不重做 T1–T3 已有组件 |
| native 默认与整树集成放行 | 原生 Plan B6 唯一集成 owner | 接收 H01–H06 及原合同结果；不另开并发全套 |

H 编号是本 followup 的补充验收 ID，不占用原 N/F/R 编号。满足上层宽泛目标不等于这些具体反例已通过；若正在执行的工作已经覆盖某 H 项，只接收相应代码、红绿用例和证据，不做第二份实现。

非目标：第二套 native store/预算/renderer；重新实现 N01–N09；提高预算或放宽数组安全检查；改变 ink/AA 参数；全仓库清理；无依据的性能重构；默认 native 切换与版本发布。普通打开仍走 legacy 不构成共享代码安全证明。

## 3. 补充问题与最小反例

源码位置对应审查基线，以 owner 符号为准，实施时重新定位行号。

| ID / 严重度 | 已提交基线的事实与影响 | 可重建反例 / 证据 |
| --- | --- | --- |
| H01 / P2 | `import_coordinator.py::_start_call` 将 call 留在 `_last_call`，终态不清理；bound transform 可持有宿主，kwargs 可持有大帧数组。影响共享/default 路径 | QWidget 宿主的 bound transform + kwargs 数组；成功 drain、shutdown、close、正常 GC 后两者 weakref 仍存活；仅探针清 `_last_call` 后均释放。已实测，不是 RSS 推测 |
| H02 / P1 | `channel_edit_log.py::_native_series/evaluate_native_entry` 丢失暂存通道时间，将值同时当作时间；连续派生可能静默错值 | 原时间 `arange(8)/4`、原值 `-arange(8)`；暂存 abs 为 `arange(8)`，再 derivative：应全为4，实得全为1。生产 evaluator 实测；编辑器真实点击链待补 |
| H03 / P2 | `_remember_derived/_install_logical_view` 可显示派生通道，`signal_access.py::_read_native` 仅查 immutable store；创建成功不代表可使用 | replay abs 后 `get_signal_channels()` 含新名，`read_signal` 报缺失；再 replay 依赖该名的 derivative 被 skipped。生产取数/配方方法实测 |
| H04 / P2 | `mdf_reader.py::_conversion_plan` 使用 MDF4 常量处理旧格式，其他 dtype/失效位分类也需按版本证明 | 生成 MDF2.14、3.30、4.10，单通道 float64 `t=arange(8)/4, y=arange(8)`；实际保存返回路径交 broker。legacy 均成功，native 2/3 报 conversion size unknown，4.10成功。真实子进程实测 |
| H05 / P2 | `analysis_signal_prepare.py::_passthrough` 无精度拒绝地转 float64，还标记 unchanged_samples | int64 `[2**53+3,2**53+5]`、`t=[0,1]`、Fs=1；两点都变成 `2**53+4`，仍 ready。生产准备层实测；原始 store 并未因此损坏 |
| H06 / 验收缺口 | 原恢复报告 G02、P02、E02 和 Windows 仍有未执行矩阵 | 工作窗、真实重试、父销毁/迟到回调/队列/状态栏分别接收；UNKNOWN 不推定为失败，也不推定通过 |

N09 的基线接收校正：当前已提交 transport 有 `physical_mode="shared"` 和物理记录编码，enum/重名往返两条测试通过；原生 Plan/Spec 中“仍因 identity physical must share raw 失败”的旧快照不能作为重做依据。标记为**已实现修复、完整文件/GUI/平台验收 partial**；不要因此关闭 R01，也不要未经验证更改正在执行的任务状态。

## 4. H01：请求引用和释放合同

活动调用、可重试调用和完成记录的生命周期必须分开。只有运行/等待用户处理/有效重试所需的上下文可以持有完整 call；最终成功、失败、取消、源/目标失效或 session 替换后，在 worker 已回收和必要 continuation 完成时解除所有不再需要的强引用。诊断历史保存有界事实，不保留带大数组、bound method 或 widget 的 call。

不得为释放引用而让活动 QThread 被销毁、提前断开监督、丢失重试参数或复用失效目标。保留应用级 supervisor 所有权与弱宿主引用；正常 close + GC 能释放宿主，不依赖测试主动 `deleteLater` 掩盖保留。通过实际 ImportCall/生产 transform 接线测试，不能只测一个没有执行过导入的空 coordinator。

重试时仍遵守旧 worker 回收、新 request/源快照/target 校验、fresh default_limits 和失败文件单独重试。任务结束后只清理自己的上下文，不取消队列下一项。成功、失败、取消、重试成功/放弃、session 替换和宿主销毁各终态均需验证参数/宿主可释放及单次终态；RSS 高水位不等于活引用泄漏。

## 5. H02/H03：派生通道完整取数合同

沿现有 FileData、signal_access、channel_edit_log 及 B5 的 owner 完善逻辑通道，不另建公共表或第二套存储。冻结的数据单位是“值 + 原时间/轴身份 + 质量/segment + 单位/表示 + 稳定 revision/配方依赖”，不是只有 `(values, unit)`。可复用既有 DTO 或最小扩展；冻结字段与语义后再改消费者，不提前指定新框架。

- 暂存、应用后的派生和项目重放使用同一时间/质量语义。单通道操作继承实际轴；对已派生通道的导数/积分不得以其值作为时间。两级/三级配方保留非等间距时间，用户范围与邻点/halo遵守 B2 已冻结合同。
- 空/单点/短序列按既有算子支持范围返回明确结果或错误；非有限、失效位、复位/segment 不得在暂存过程中丢失，也不得跨 gap 算出无诊断结果。值/时间/质量 shape 不符明确拒绝，禁止 min 截断；原始样本保持不变。
- `get_signal_channels`、`read_signal`、编辑器读取及绘图/分析必须能解析同一逻辑身份。不要以实例级 monkeypatch 形成第二套目录真相；修改所属 owner 的最小分支，保留 legacy 行为。
- 派生名称不能冒充原物理通道身份；同名来源、隐藏/删除、重命名若受支持、依赖失效均显式解析。删除后的新请求不得因原 store 仍保留原始 buffer 而静默重新使用该逻辑通道；已绑定历史结果沿既有意图/生命周期合同处理。
- 派生 revision 含来源 revision 与确定性配方/轴/表示/质量意图。应用更新后旧缓存/Pin 不得误认同一结果；编辑或切 View 不自动启动分析。源关闭、失败与取消的派生暂存量由原 owner 释放并纳入 B5 预算。
- 保存项目只记录可复算配方与身份，不序列化样本/cache。真实保存重开后，派生通道可继续 read/plot/analyze/派生；上游缺失或变更时明确悬挂/未应用，不用同名猜配。
- 原始采样导出与逻辑派生导出保持明确语义；从编辑器触发的选通道导出须尊重选择，不因实现只遍历 store 而漏掉选定派生通道或输出未选通道。此项是端到端验收要求，不把此前 helper 测试当作 UI 已通过。

## 6. H04：MDF2/3 兼容合同

按文件实际版本及固定 asammdf runtime 解释 master、dtype、conversion 和 invalidation 元数据；MDF4 常量不能直接用于 MDF2/3。支持既定正常数值标量、identity/线性转换与时间轴，保留 raw dtype、工程单位和数值转换事实；无失效位字段按该版本合同处理，不伪造数据事实。所有未知/不支持布局继续 fail closed 或明确 unsupported，不只放开一个 NON 常量就宣称兼容。

每个版本至少覆盖整数/浮点、identity/非身份线性转换、空/单点/多点；适用的字节序/位宽分支以独立字节或人工 oracle 验证。转换例 `physical=2*raw+3` 必须同时验证 raw 与 physical，不仅检查加载成功。MDF4 矩形/逆序/3D 数组安全既有门禁保留。

native 必须经正式 broker/transport 成功且维持只读/共享/源 hash，不能自动回退 legacy 来刷绿；旧 loader 的结果和错误分类保持兼容。各版本低预算在分配前拒绝，失败后能读取正常文件，不引入父进程重读。

## 7. H05：分析数值表示合同

对本次新增 native 准备路径，**整数样本不能精确表示为目标计算 dtype 时，第一版明确拒绝，保留通道/表示/范围与精度原因；不静默接受有损转换。** 本补充不新增“允许有损”产品选项，不改变 legacy 历史政策。原始 raw/export 仍须精确保留，不能通过改成浮点源来消除错误。

判断基于实际请求段及必需 halo 的值，而非只按 dtype、全通道最大值或浮点 roundtrip 后的溢出结果。可精确表示的较大偶数不因简单 `>2**53` 一刀切误拒；边界覆盖 `2**53-1`、`2**53`、`2**53+1/+2/+3/+5`、负数、int64/uint64 极值与空输入。浮点来源继续既有非有限/质量合同，本项不承诺消除算法浮点误差。

检查放在现有中立准备 owner，先预算准入再必要物化，复用 B5 缓存/资源政策；不在鼠标/paint 中增加全长 object 拷贝或反复扫描。已精确转换的输入才可使用 unchanged_samples 数值语义，并注明计算 dtype；无法精确表示返回的拒绝不能被上层转换成“通道不存在”或静默跳过。GUI 明确原因且不启动 job/发布结果；Batch 有准确条目失败且 `_RunReporter` 只记录一次。

## 8. H06 与联合验收

H06 复用原恢复 Spec G01/G02/P01/P02/E01/E02/W01，重点补报告未闭合项：Cocoa Batch/UltraView 防退化、进度父销毁/迟到/队列/状态同步、真正完成 fresh-limits 重试；Windows 新鲜 Full/Lite 的真实窗口、取消/资源重试及几何。已通过组件证据按相同源码指纹接收，不为本补充重复改样式或调整尺寸。

验收状态限定为 PASS（源码/输入指纹、命令、平台与结果）、FAIL、partial、UNKNOWN。H01–H05 需要定向红绿及相关 boundary；H02/H03 需要真实编辑器/消费者路由；H06 区分 offscreen/Cocoa/Windows。缺平台或样本列 UNKNOWN，不自行降低原交付范围。

本补充通过仅证明增量缺口关闭；native 放行还依赖原生 B0–B6、N01–N09、F01–F12、资源/性能与 R01。若先交付独立恢复修复，必须列出实际交付文件/行为及受影响共享回归，不能把“native 开关关闭”的整树当作已隔离版本。本文件不授权发布。
