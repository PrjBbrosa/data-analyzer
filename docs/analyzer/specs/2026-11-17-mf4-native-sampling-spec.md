# MF4 原始采样保留与按需分析 Spec

日期：2026-11-17；同日按 `c126fcae`、导入恢复 M6 报告及消费者反例修订。状态：**needs revision / partial：已存在可复现的功能阻断，禁止当前候选切默认或随版本发布。先关闭 §10.1 的问题，再验收产品全链、资源/性能及平台。**

配套 [执行 Plan](../plans/2026-11-17-mf4-native-sampling-plan.md)。本合同与[导入恢复 Spec](2026-11-17-import-budget-and-dialog-recovery-spec.md)共同约束后续实施：本文拥有原生数据、分析与性能合同；恢复 Spec 拥有几何/进度/资源错误与重试，并补充固定预算 R01。初版已提交，恢复任务随后产生候选代码；本次仅修订两份文档，不实施产品变更、启动 agent 或发布。

## 1. 决策与成功定义

采用“通道原生采样存储 + 同时钟数组共享 + 按请求准备分析输入 + 现有显示包络”的方案。MF4 不再在产品导入入口强制展开为公共时间表。

成功必须同时满足：

1. 支持的数值测量逐通道保留原始采样顺序、点数、时间、原始编码与有效性；工程值转换可追溯，不把插值点称为测量点。
2. 时域、游标、统计、分析、导出及项目恢复均从同一通道数据契约取数。不能仅在隐藏缓存保存原始点而前台仍读截断表。
3. 数据量按原始各通道点数增长，不按“最大点数 × 所有通道数”增长。显示抽样不改变分析输入。
4. 同时关闭正确性、内存/耗时、GUI 响应、项目兼容和平台门禁，才能切换产品默认。

当前候选不满足成功定义。§10.1 的 N01–N06 是前轮实际调用/画布探针复现的问题，N09 是新取得的 M6 正式链路失败；N07/N08 分别为源码可见的性能风险和未闭合的兼容范围，不能混称已测故障或已通过。全部纳入放行账本。关闭 native 开关并不能证明版本安全：共享 Order、renderer、准备层等改动仍可能影响 legacy MF4 和其他格式；拟发布快照必须验证实际包含的共享变更。

范围为 MF4 与共用 MDF reader 的 MDF2/3 正常标量兼容、已验证 MDF4 数组元素。其他格式通过统一取数适配保持原语义，不借机全部重写。新增的“无损”承诺限于明确支持的测量类型；未知主轴、结构/VLSD/文本等必须列明能力与原因，不能声称整个 MDF 二进制文件无损重建。

不包含：修改源文件、完整 MDF 编辑器、硬件时钟同步校正、自动修复时钟复位、运行时版本升级、全格式存储引擎迁移。现有 UI/分析结果所有权和绘图 ink 阈值保持合同。

## 2. 实施快照、历史事实与证据等级

修订核对 HEAD 为 `c126fcae24b73961eb798b989df1068a94327197`，产品版本由 `app_meta.py` 读取为 `v8.4.8`；工作区有未提交的原生与导入恢复实现。`161e5387` 已集成隔离/安全导入；`febfc01d`、`c64caaba` 与 `c126fcae` 的 LF 补丁、Lite 导入路径/UNC 修复需保留。`c126fcae` 新增的扭矩 `1e-6 Nm` 默认 dB 参考属于当前分析基线，数值对照须固定单位、reference、weighting 与 scale/offset，不能将参考值变化归因为原生采样误差。

当前源码已存在 `NativeSignalStore`、`read_signal`、`DataLoader.load_mf4_native`、native transport、`analysis_signal_prepare.py` 和 schema 6。普通 adapter、GUI 打开分派及 Replay 仍调用 `load_mf4`；因此“能构造 native FileData”不代表产品默认已迁移。同轴分析已接候选准备接口，异轴抗混叠/FRF 尚未闭环，`tests/test_mf4_native_fidelity.py` 的 F08/F09 仍 strict xfail。

本地执行证据在 `.state/import-budget-recovery-20261117/` 的 `progress.md`、`m0-result.md` 至 `m6-result.md`，M0 oracle 在 `.state/mf4-native-m0-20261117/thresholds.md`。这些是阶段报告，不是本次重跑的当前树验收。新取得的 M6 报告记录：匿名文件显式正式链路通过；事故样本在 transport 读回报 `identity physical must share raw`，GUI 注册为 0，R01 未关闭。进度表“进行中”不覆盖这份实际结果。图2缺样本、Windows 未测，offscreen 不证明 Cocoa 画布；对话框 T4-U 也不能替代。状态与剩余 owner 详见 Plan §0。

以下表格及 buffer 普查保留为**初始调查证据**，不能把旧缺陷描述当作候选代码的当前行为：

初始调查 HEAD：`5bac5a2c9ae40e1ea7a45ac4fbab3d7d6a652867`，当时含导入鲁棒性等未提交修改。接续实施必须重新记录相关文件指纹；HEAD 相同不足以证明源码相同。

| 初始调查事实 | 当时 owner / 证据 | 含义 |
| --- | --- | --- |
| 点数最多轴、线性插值、端点填充、跳过无重叠与单点 | `io/loader.py::_prepare_mdf_time_series`、`_load_mf4_channels` | 原始测试点可能消失，属于导入语义 |
| 文件级时间与 Fs | `io/file_data.py::FileData`；`ui/main_window/analysis_context.py::_file_time_array` | 仅替换 loader 不足以完成迁移 |
| FFT 读取 `fd.time_array/data[ch]/fs` | `ui/main_window/_fft_mixin.py::_fft_fetch_signal` | 会继承导入时的数值改变 |
| 不均匀时间按序号重建，而不重采样值 | `analysis_time_axis.py::prepare_analysis_time_axis`；`batch_compute.py` FRF 准备 | 原生 MF4 必须绕开此旧隐式政策 |
| RPM 仅长度不同才调用对齐；对齐使用端点延长 | `ui/main_window/_order_mixin.py::_order_rpm_for`、`_align_rpm_to_signal_axis` | 等长错位及覆盖不足都需要新边界测试 |
| ChannelFrame 仍要求公共 row_count | `io/channel_frame.py::ChannelFrame` | 不能给多轴数据伪造一个公共长度 |
| CAN 延迟 ZOH 仍返回公共轴列 | `io/blf_format.py::LazyZohFrame._materialize` | 可以借鉴延迟物化，不可等同原生取数 |
| 子进程结果使用受预算限制的独立数组 | `io/import_transport.py`、`io/import_limits.py` | 当前没有持久 mmap；新方案不默认引入 |
| 缓存按未绑定条目数淘汰，已绑定结果保留 | `ui/analysis_cache.py::AnalysisResultCache` | 必须限制新增临时准备缓存，不能破坏 View 已应用结果 |

初始只读探针：`.state/mf4-native-plan-20261117/probe.py`、`results.json`。使用已验证本地 `asammdf 8.8.32+tracelab.1`，通过 `open_mdf` 做读取安全准入；原生计数读取 `raw=True, ignore_invalidation_bits=True`，工程值用库的物理转换，未调用公共轴整理。时间数组按完整内容核对后统计共享体积。探针不是候选产品实现。

| 数据集 | 当前公共表数组字节 | 原生紧凑数组字节 | 解释 |
| --- | ---: | ---: | --- |
| 10 通道同轴、每通道 50,000 点 | 4,400,000 | 4,400,000 | 身份转换、同轴时可以持平 |
| 1 个 100,000 点 + 19 个 1,000 点通道 | 16,800,000 | 1,760,000 | 避免低速通道全量展开，减少约 89.5% |
| 10 个互不重叠的 10,000 点通道 | 160,000 | 1,600,000 | 当前丢掉 9 个通道；保留完整数据合理增加 10 倍 |
| 50,000 点通道 + 200 个单点通道 | 800,000 | 802,000 | 仅数组增加 2,000 字节；目录/对象成本另计 |
| 本地事故样本，源 SHA256 `72d81a087e9816c7dca80633b20f5a899c0a484a6a80465b99a6d2f3c56cf5b3` | 199,980,448 | 25,089,754 | 190.7→23.9 MiB，减少约 87.5% |

本地样本原生计数为 967 个可转换数值标量/元素序列，其中 915 个单点，1,879,975 个样本，8 条按内容区分的时间轴；不能把库展开元素数称为原始物理通道数。22 个非本探针数值向量候选未纳入数组统计，包含结构父项等，须在实施中逐类归因，不能将 967 宣称为所有变量完整导入。计入的体积包括时间 8,482,200、raw 3,717,626、额外 physical 12,889,928 字节；此样本未返回独立失效位数组。源文件 hash 前后相同。

这些数字是**数值 buffer 普查**，不包含目录、Python 对象、解析器/解压、传输副本、分析结果、绘图缓存和 RSS；不证明候选读取速度或前台无卡顿。探针中的一次性秒数不作为性能 SLA。此前临时 MF4 还复现了 `t=[.10,.11,.12], y=[0,100,0]` 被投影到 `.25s` 公共轴后全为零；该反例须固化为回归。

后续 M2 报告对同 hash 事故样本记录 979 个数值通道、927 个单点、84 个轴身份、10 个 unsupported 目录项，数组量 25,090,366 字节。它与上述历史 967/915/8/22、25,089,754 字节不是同一目录/轴计数口径，不能直接替换历史数字或认定差异必然正确。M0/M2 接收必须按 `(group,index,element)` 对账主轴/标量/数组父项/元素，分别报告轴身份数与去重 buffer 数，并以独立 raw/physical/质量 oracle 解释新增及排除项；这些计数均不是通用验收常量。

## 3. 数据量、方案取舍与预算

设 C 为通道数，Nmax 为当前参考轴点数，Nc 为通道真实点数，Ng 为共享时间轴点数，bc 为样本字宽：

```text
旧公共表主体 ≈ 8 × Nmax × (C + 1)
原生主体 B = Σ(Nc × bc_raw) + Σ(Ng × bg_time)
             + 非身份转换的 physical buffer + 必要有效性 buffer
应用峰值 = 已驻留源 + 解析/解压 + 交接副本 + 分析临时输入/结果 + 显示缓存
```

磁盘源 MF4 不变化。临时 sidecar 是解码数据，可能大于压缩 MF4，不能用源文件大小估算它。`.tlproj` 继续引用源与配方，不嵌入样本，所以不会随全部测量点线性膨胀。

| 候选 | 决定 | 原因 |
| --- | --- | --- |
| 改选最长时间轴/最高 Fs | 不采用 | 不能保证包含其他真实采样点与状态事件 |
| 所有时间戳并集再补全表 | 不采用为源模型 | 膨胀、重复时间、缺口与状态语义仍未解决 |
| 按 MDF 组拆为大量用户文件 | 不作为默认 | 对项目身份、文件列表和跨组选择有额外破坏 |
| 原生数组常驻 + 共享轴 + 局部派生 | **第一版默认** | 复用现有隔离/交接，收益已由 buffer 普查支持 |
| 持久 mmap/文件索引懒读 | 本版不要求 | 带来 Windows 文件锁、源变化、取消与句柄所有权；并非免费零内存 |

第一版一次受监督导入保留支持的完整原生数组；不宣称只解码选中通道。只对选择的通道/时间范围创建 float64 分析副本、对齐与显示数据。不以隐藏全表兼容缓存抵消收益。

复用 `io/import_limits.py` 作为资源政策 owner；当前导入 memory 是估计可用内存四分之一、上限 2 GiB，未知时 512 MiB；output 不超过其一半。此方案不简单提高上限或绕过准入，而将 `_reserve_shared_output` 改为原生实际布局与必要副本计费。现有记录边界与 native runtime 检查继续存在。

新增派生准备缓存采用按字节计费的可丢弃 LRU，初始上限 `min(128 MiB, admission_memory / 8)`；同一源 revision 的只读数组不重复计费。应用级源/任务账本位于同一中立资源模块，注入 FileData、导入 broker 与现有分析 job owner；不创建新的 MainWindow 多处状态。一个导入并发保持不变，分析队列保留既有调度，增加内存 reservation。新任务入场前计入已绑定结果和全部存活源、转换/重采样临时量及输出；不得靠淘汰绑定结果或原始样本腾预算。超预算提示缩小请求/关闭不需要的来源；不自动降采样、截断或输出半源。

OS RSS 不等于数组账本，现有监督也不是硬内存沙箱。任务完成/取消、View 删除、源关闭、项目替换必须释放对应 reservation；执行中的 worker 可暂持只读源引用，失效结果不得发布，最终释放由现有 job 生命周期负责。

### 3.1 与导入恢复 R 轨道共享的资源合同

- 固定回归预算为 memory **498,988,944**、output **≤249,494,472** 字节，必须同时注入，不能只改 memory 而留下更高 output 默认值。历史事故样本以 §2 SHA256 锁定；完整 `adapter → broker → typed transport → GUI 注册` 在此预算下保留全部支持样本才满足 R01 的文件链路项。M2 直接/子进程读取报告仅是阶段证据。
- 对该预算分别保留计费分项与父/worker 同时间线 RSS、临时磁盘、GUI 心跳/取消证据；不能将账本数、buffer 数或独立 RSS 峰值相加充当进程实测。Windows Full/Lite 单独验收。
- `ImportBudget.used_bytes` 是单调累计准入估算；现有 `record_lifecycle/release_lifecycle` 是独立生命周期记录，释放记录不降低累计值。候选的局部 `PrepareByteLedger` 和缓存 key 也不证明 §3 的应用级 reservation/byte LRU 已实现。接续时将它们接入同一中立资源 owner，证明存活源、绑定结果、并发任务及临时量一并计费、各终态对称释放；不得简单减小 `copies=3` 或调高预算。
- 复用 T3 的有界资源 envelope，区分 memory estimate、worker memory、output、temp disk 与 count；native 拒绝必须保留类型、单位、需求/上限、phase/basis 与分项，不从中文 message 解析数字。未知值不编造。
- “重新检查并重试”沿 T3：旧 worker 回收、源快照/target 有效后获取新 limits 和 request；超时重试只改时限。native 接线不绕过这些合同，不重复注册已成功文件，broker 1.0 不代表 GUI 事务成功。
- 图2 `2.W04_360_1s_rt_11201724.mf4` 尚无独立样本验收，保持 UNKNOWN，不以事故样本代替。固定预算确实不可达时报告实测瓶颈与 needs revision，不事后抬预算；U 完成不等于 R 完成。

## 4. 原生存储与读取接口

以下 API 已有未提交候选；这是目标合同，是否完全满足仍按各阶段验收，不重新创建同名模块：

- `io/native_signal_store.py::NativeSignalStore`：不可变数值源，轴表、通道表、有效性、原始编码与工程值；无 Qt、无 MDF handle。
- `io/signal_access.py::read_signal(fd, channel_key, span=None, representation='physical') -> SignalSeries`：统一取数，旧表格来源经适配使用原轴；返回 time、values、validity、segment facts、单位、sampling facts 和 stable revision。
- `io/mdf_reader.py::open_native_mdf/load_native_mdf`：现有 MDF reader owner 承担原生读取、安全校验与转换。`DataLoader.load_mf4_native` 为薄入口；旧 `DataLoader.load_mf4` 三元组公共表 API 暂保留兼容，必须标明 legacy shared-axis 语义。
- `SourceAdapter.load_native_payload/load_native_sources` 已提供显式分支；最终产品 UI/Batch/Replay 按 native policy 走此分支，不能悄悄回退。当前默认仍 legacy，仅允许受控候选入口使用 native，最终切换受 §1/§8 门禁约束。

FileData 可持原生 store 或现有表格，新增状态在构造时显式初始化。多轴源没有伪造的 `time_array`/单一 `fs`/公共 `row_count`；未迁移消费者访问这些能力应得到可定位的明确错误，不能选择第一轴作为 fallback。原生 store 不伪装成 ChannelFrame，不把不同长度列塞入 pandas。单轴旧格式 API 不变。

每个通道保存：物理 `(group,index)`、数组父项/坐标（适用时）、既有公开名称映射、原始 dtype、Nc、axis_id、unit、validity、转换来源与支持状态。内部身份是 source + physical occurrence；同名别名不能生成第二份真实通道，显示名不能反向匹配来源。

保持一个 MF4 对外逻辑源的既有 root 身份；时钟组只是其内部结构，避免让文件卡片/项目 fid 分裂。`Time` 同名信号的既有消歧映射保持稳定；真实主时钟与名为 Time 的测量信号分开。

时间轴共享首先使用主通道身份；跨组内容驻留去重只在 dtype/长度/hash/逐点相等且参考原点语义一致时成立。hash 是筛选条件，不是唯一证据；buffer 共享也不能合并不同设备时钟的元数据身份。顺序索引、重复时间和复位 segment 保留。

raw 与 physical 在经证明的身份转换下引用同一 buffer；非身份转换使用库一次物理转换并保留必要的第二份 typed buffer，不自行重写 MDF conversion 引擎。转换事实是受控元数据，不能跨进程传任意对象/pickle。原始 64 位整数不可先转 float64；计算若无法精确表达，必须明确转换限制。枚举文本不冒充连续物理值：可展示 raw code/标签，数值分析需显式选择有意义的数值表示。

数组父项作为结构目录与坐标来源；已验证元素视为数值通道，避免把父数组与所有元素重复驻留。若 reader 已复制元素，按实际 bytes 计费；只有经过 transport stride/布局验证的 view 才可共享，不能通过危险偏移节省空间。

## 5. 时间、缺口与异常合同

| 输入情况 | 原生保留/显示 | 分析入口 |
| --- | --- | --- |
| 空通道 | 目录存在、0 点状态，不生成样本 | 明确空数据 |
| 单点 | 保留真实位置，点标记；Fs unknown | 不做 FFT/滤波/FRF，不外推成常数 |
| 重复时间 | 全部保留，按记录序号区分；游标可返回同时间多个点 | 默认拒绝不满足算法要求的段；显式 keep-last 仅作用于派生输入并记计数 |
| 时间回退/复位 | 保留记录顺序与分段；不跨断点连线 | 请求必须选择明确 segment，不排序拼接 |
| NaN/Inf 时间 | 原记录保留，无法定位点不绘制，诊断计数 | 不得通过删除后重排压缩时间 |
| 信号 NaN/Inf 或 MDF 失效位 | 保留位置与质量，曲线断开 | 默认拒绝跨无效样本计算；可选择完整有效段 |
| 不同通道范围不重叠 | 全部导入，各自绘制 | 跨通道计算无交集时报错 |
| 非时间主轴（角度/距离/索引） | 保留主轴种类，支持展示的路径显式标单位 | 禁止当秒送给频谱；未支持的展示明确报告 |
| 声明/实际形状或长度冲突 | 不以 min 截短；保留可证明边界的诊断 | 不发布错误数值来源 |

正常跨样本间隔与真正缺口分开：显式无效标志/缺测是已知 gap；仅凭时间间隔较大不能自动断言丢采样。分析可依据该通道的采样合同拒绝不均匀段，但不修改原数据。低速事件信号也不能被“补齐”成更高信息带宽。

请求裁切先按原始时间定位；对齐计算允许额外读取左右必要邻点或滤波 halo，但输出范围仍严格遵守请求和真实有效覆盖。不可因先裁掉边界邻点而制造误差。默认无范围外端点填充，无跨缺口插值。

采样率事实与可分析性分别判断。禁止用相邻浮点时间差逐位相等作为唯一均匀条件；也禁止用宽松 `allclose` 掩盖真实抖动。实施 N01 前必须冻结：时间 dtype/量化精度、时间原点量级、ULP/绝对与相对误差界、采样间隔的求法、元数据声明与实际时间冲突的处理，以及 known/estimated/unknown 的来源。用 10/100/1000/1024 Hz、非零原点与真实抖动的独立输入固定边界；容差不足以区分时应明确 unknown，不能捏造 Fs。空/单点、重复、回退、非有限时间的规则不因此放宽，原数组不被“修整”。

选段可以分析不等于整条通道可以分析。FFT/时频/Order/FRF 必须先解析实际 View/pane 的请求与 segment，再验证该段及算法必需邻点/halo；区间外无关失效点不能阻止完整有效段，区间内失效或无法满足的 halo 必须返回真实原因。不能先对整条通道准备失败，再把失败伪装成“源通道缺失”。

## 6. 显示、游标、统计与交互

1. `window.py::_build_time_plot_data` 及 bindings/custom-X 通过 signal_access 给每条曲线自己的 X/Y。既有 canvas 已接收 per-curve t/sig，沿用 renderer/envelope、ink/AA/raster owner，不改阈值来掩盖性能退化。
2. 视口范围为当前 View 所选曲线可定位范围的并集；分析范围来自当前 `(section,view_id,pane_index)` 中实际参与通道，配对任务用有效交集。用户显式范围越界须反馈，不能暗中裁短。
3. 源目录展示“通道数/总原始样本数/采样率多种”，详情展示各通道点数、范围、Fs 来源与有效点数；不展示虚假的共同“行数”。恢复的数百单点通道不自动全勾选，也不逐项弹窗。目录创建和查找需要测量，按需批量构建可见项。
4. 游标默认读取各通道最近的真实采样点，报告实际采样时间、相对查询时间的差值、记录序号和有效性；等距取较早点。同一查询时间各通道独立定位，不能强制吸附到同一采样轴。取样标记落在真实点，不能放在查询时间却显示另一时刻的值。可选插值读数明确标记插值、方法和目标时间；覆盖范围外或明确缺口内显示无数据，不吸附到远端有效点。单点仅在其采样时间可用；重复时间返回多点提示及原记录身份。Pin 保存物理通道/segment/采样身份或既有时间意图，源变化按现有规则悬挂或失效。
5. 峰值从完整有效样本算，不能从屏幕包络算。均值/RMS默认明确为有效样本加权；若提供时间加权，单独命名并定义积分/保持规则。无效数、有效数与时间覆盖可查，不能按稀疏/稠密样本混用统计权重。
6. Custom-X 仅同时间关系确证时直接配对；等长不构成证明。异轴请求使用第 7 节显式对齐，保留多值分支/非单调 X，禁止按 X 排序改变采样序列。
7. 热路径禁止完整 signal hash、全局表物化、MDF 解析和完整转换。单调段定位用索引/searchsorted；重复/复位走预建 segment 索引。stable revision 在载入/派生时形成，不能用 ndarray wrapper id 判定源变更。

有效性约束贯穿首次 attach、pan/zoom、resize、隐藏后重显、View 恢复、raster 与图片导出。显示值可以为断线而派生，raw buffer 始终保留；renderer 后续刷新不得从 raw 重新画出已标无效的值。游标 marker 必须按 composite source/channel、原始/滤波 companion 和所属轴/ViewBox 分配，各子图不能收到其他通道的点；移除、无数据和切 View 必须清除旧点。游标读数、标记、区间统计与导出使用一致的质量事实，但不共用有损显示包络作为数值输入。

显示示例：原始点 `(1.000s,10Nm)` 与 `(1.010s,14Nm)` 可用线连接，但连线不增加测量点。游标在 `1.005s` 时，原始模式显示 `10Nm @ 1.000s，Δt=-5ms`；显式线性插值模式显示 `≈12Nm @ 1.005s，线性插值`。两种读数均查询原生数组，不读取屏幕包络，缩放不能改变相同查询/模式的数值。

## 7. 分析准备合同

已有候选中立 `analysis_signal_prepare.py` 负责单/双通道请求准备，继续补齐其合同，复用已证明等价的 signal 工具；GUI 和 Batch 都使用它。`signal/` 中现有 FFT/时频/FRF/COT 核心数学原则上不变。绘图包络和显示缓存绝不作为输入。

每份 PreparedSignal/Pair 必须带 source/physical identity、source revision、segment、实际输入/输出点数、请求/有效范围、原始/目标 Fs、方法、质量、滤波与边界处理、policy_version。缓存键包含这些确定性输入及原有算法参数，不能只改 Fs 数字而仍复用旧结果。

| 功能 | 第一版要求 |
| --- | --- |
| FFT / FFT-vs-Time | 读取本通道；均匀有效段按该通道 Fs；保留起点。非均匀/复位/缺口默认阻止，详情提供显式“生成均匀分析数据”请求，而非自动按序号改时间 |
| 时间滤波 | 只处理选中通道的有效均匀段；结果作为 companion，不改原数组；不跨 gap 传播滤波状态 |
| Order / Order-vs-Time | 信号与 RPM 各取原轴；即使点数相同也核对 timestamps。RPM 在覆盖范围内按实际时间对齐，信号不为迁就低速 RPM 被导入级降采样；手动 RPM 保持显式常量意图 |
| FRF | 同步均匀有效输入直接进核心；原时间不同/不同 Fs 必须走显式配对准备，默认预检反馈，用户选择“对齐后计算”才产生派生输入；相位与 coherence 独立 oracle 是启用该能力的硬门禁 |
| 通道编辑/公式 | 单通道导数/积分使用原通道真实时间；多输入同轴直接算，异轴明确目标轴/方法，派生通道保存自己的轴与配方；所有原通道不变 |
| Batch | `original` 表示每个选定通道的原生采样；`target_fs/decimate` 是派生请求。保留既有预处理次序：时间范围→质量验证/明确有限值政策→scale/offset→remove mean→抗混叠采样→用户滤波。跨通道对齐属于配对输入准备，须单独记事实，不与此采样步骤重复执行 |

对齐方法冻结如下，禁止靠 dtype 自动决定“连续/状态”：

- 连续量、严格递增且同一时钟参考、无已知缺口：线性插值可用于时间展示/通道运算/RPM，输出只落在有效覆盖；保留插值方法。没有带宽声明时不声称频谱保真。
- 状态/枚举：显式 ZOH，在声明有效范围和断点内保持；不生成分数状态。未知语义必须由用户在计算详情选择，不把任何整数都视作状态。
- 均匀连续信号降采样：先有抗混叠，再降采样；优先复用 `batch_preprocess.py` 已有采样/filter owner，经语义核对后提取到中立 helper。若采用 polyphase，固定滤波设计、padding、延时补偿及有效边缘；不能把库默认零填充当真实测量。
- 目标网格 `origin + k/fs_target`，origin、末点包含规则、比率及边界 halo 写入 provenance；相同输入重复执行应确定性一致。非均匀数据不能直接套用假定输入等间隔的 polyphase；第一版只对明确无 gap 的选段提供显式线性均匀化并报告其限制。
- FRF 双通道对齐仅允许各自均匀、时钟关系明确、无缺口的连续量；共同目标 Fs 默认候选为两者较小值，须在用户应用请求中固化。分别抗混叠、对齐同一物理 origin；非整数时移/滤波边缘必须经过相位 oracle，不能简化成数组对齐或按序号重建。未经验证的比率/时间偏移应显式 unsupported，不得发布近似无诊断结果。
- 恢复旧项目中的“指定 Fs 重解释时间”与重采样是两种意图：前者只能以标明的 legacy 派生策略执行，不覆盖原轴，不默认扩散到其他通道。

本节增加的严格校验可能使过去静默计算的错误请求转为需要处理。UI 应给出通道、范围和可行动原因；不能为了保持历史曲线不变而继续使用错误输入。计算仅在用户点击计算时应用；编辑、显示调整和切 View 的已应用结果合同继续有效。

后续 M4 分为已实现候选的同轴准备与未完成的 F08/F09。独立 oracle 固定：FFT 使用 Fs=N=1024、32 Hz 单位幅值正弦、hanning/remove_mean；频率误差≤1 bin、幅值误差≤1%。同率 FRF 使用 Fs=1000、N=8000、50/80/120/180/250/300 Hz 多正弦、增益2、稳态循环延时4点、hanning/periodic、detrend=none、1s窗、overlap=0；H1/H2 在被激发频点 coherence≥0.99、增益误差≤0.1 dB、相位误差≤1°。此整数延时 oracle 不能证明异轴 fractional-delay 正确。

F08/F09 接续前仍须冻结实际滤波阶数/截止/padding/延时补偿/支持长度，以及支持的比率、origin、fractional delay 和边缘裁切；降采样带外抑制≥60 dB，FRF 安全通带0.05–0.30×较低 Fs。当前两条 strict xfail 只检查缺失设计入口，须扩为带输入输出的频率/幅值/相位/边缘测试，不能靠返回一份设计字典即宣布通过。现有 Batch legacy 采样行为不自动取得 native F08 资格。未通过支持组合仍明确 unsupported，M4 保持 partial；本次文档修订不缩减第一版目标来提前放行。

## 8. 导入隔离、传输和性能边界

保留当前 mdf_reader 安全检查、固定 wheel、一次性解析 worker、request ID、原子注册、取消与诊断。native payload 通过 typed JSON + 数值 sidecar；扩展既有白名单，不传 parser 对象，不在父进程二次解析。

transport 按同一 buffer identity 去重；时钟表共享跨进程后仍共享并设为只读。当前 `.npy` 独立文件数量上限 10,000：在写入前估算 axis/raw/physical/validity 文件数；超限明确资源拒绝，或后续通过有界 packed numeric transport 单独验证后扩容，不能静默丢通道。本版不修改安全上限来掩盖未知量级。

读取优化先避免每通道重复读/解压同一组；以 group/fragment 批量读取或库受支持选择 API 复用记录，保留 invalidation 和轴身份。分块前后逐点/转换/数组元素 oracle 必须一致。不要在 GUI 主线程做 hash/dedup/全量 float 转换；若注册仍包含 O(N) 数据扫描，应移到已受监督结果准备或既有非 GUI 工作阶段。

性能验收是实施门禁，不是本轮实测承诺：

| 项目 | 验收要求 |
| --- | --- |
| 结构成本 | 导入产品链 `np.interp/ZOH/公共表物化` 次数为 0；没有 C×Nmax 常驻或临时分配；共享轴交接后无逐通道复制 |
| buffer 大小 | 对本轮 fixture 达到 §2 紧凑 buffer 模型；额外 raw/physical/validity 有逐项计费，metadata 分开；不拿 RSS 等同 buffer |
| 同轴对照 | 对无新增数据的身份转换控制组，相同源/选择/范围/结果分辨率：导入到可操作耗时和增量同时峰值 RSS 不超过基线 1.20 倍；非身份转换新增 raw 保留成本按 B 单列，不假定旧表已保存 raw；未达标先定位副本/目录 |
| 多率对照 | §2 mixed_rate 身份转换 fixture 的原生源 buffer 不超过等内容旧公共表；其他文件按 raw/physical/validity 的 B 模型验收。恢复丢失数据或新增 raw 副本的场景按真实输入规模对照，不能拿旧截断速度作公平基线 |
| GUI | 新增准备期间 20ms heartbeat 的间隔 p95 ≤50ms，max ≤200ms；取消点击有可见响应≤200ms，沿用 2s 协作宽限及现有强制回收；断开 UNC 阻塞不虚报硬保证 |
| 绘图 | 沿用 `scripts/benchmark_timedomain_interaction.py` 已有 Cocoa gates：首次≤1300ms、pan frame p95≤120ms、pan settle≤150ms、resize frame p95≤300ms、resize settle≤250ms、warm checkbox callback p95≤30ms、paint p95≤220ms；不调整 ink 阈值 |
| 热交互 | 同输入 warm pan/zoom/cursor/switch p95 相对基线≤1.20倍；新增取数/控制层不得每帧完整扫描或重采样，既有 envelope 成本独立测量；记录 callback/lookup/paint/settle 分项 |
| 长期 | 20 次打开/关闭及计算/取消循环无活跃 job/source/cache 强引用残留；GC/稳定后额外 RSS 不呈线性增长，allocator高水位与泄漏分开判定 |

基准机配置、源码指纹、文件 hash、dtype、点数/通道数、DPR/窗口尺寸/AA、冷/热缓存、采样次数与原始序列均记录。导入冷进程至少 5 次、热交互至少 30 次；真实冷磁盘若未控制须写“OS cache 未清空”。应用 RSS 与 worker RSS 在相同时间线上采样，不能相加两个独立峰值。Mac Cocoa 与新鲜 Windows windowed Full/Lite 分别测，不能用 offscreen timing 放行。

若 compact arrays 仍超出目标机器预算，准确拒绝并报告估算；超大文件 mmap/lazy reader 是后续独立方案，须先证明本版瓶颈与 Windows 生命周期门禁。本版不宣称任意大小 MF4 都可打开。

## 9. 导出、项目与其他消费者

- 原始采样导出默认按通道/同轴组输出真实 time/value/validity，或带 channel/record/segment 字段的长表；不为了 Excel 横表静默填满。CSV 用足够的浮点往返精度与整数文本，不能先丢精度再保存；Excel 不能精确表达的大整数/超行数使用文本或明确分片/格式建议，不能截断。
- 统一时间表是显式导出模式，声明 grid、method、范围、无效/缺口策略；范围外为空值，附插值/有效性信息。绘图 PNG/PDF 使用现有 render contract，与数值导出分开验收。
- 项目继续 reference-only。候选 codec 已支持 1–6：普通项目写4，带配方写5，带 native sampling policy、物理身份、对齐意图或悬挂通道写6。继续由现有 project codec 一个 owner 管理，不另分配新 schema 或让旧版本静默误读。schema 6 helper 已有测试不证明恢复入口已遵守 policy；必须补 native/legacy 分派及保存重开真实链路。
- 旧项目默认按 legacy 语义恢复，明确提示存在公共轴对齐；提供显式升级到原生采样，先预览受影响通道/范围/公式，不覆盖原文件或原项目。升级使依赖结果失效/待计算，保留用户范围和视图意图，不能将旧缓存当新结果。不能唯一确认物理身份时悬挂并提示，不按相似名称迁移。
- 最终放行后新开文件默认 native；legacy 仅供明确旧项目/公开兼容 API。当前默认仍 legacy，不能据此认定迁移完成。新 native 产品工作流不得自动回退；旧项目选择不升级不应被标为原生保真验收通过。
- Replay 使用原通道事件顺序/时间，不凭公共 Fs 重放多率数据；相同时间多记录按原序，时间回退需用户选 segment。未知主轴/无效事件明确处理，不能补成采集事实。
- 来源关闭/移除、Pin 挂起、比较 B 面、UltraView 捕获复用 stable revision 与既有 owner，不复制原始数组到每个 View；项目不持久化 cache、进程 token、临时路径或诊断快照作为意图。
- 更新 hints、quickref、主帮助/分析指南中受影响的原始/采样/导出说明；历史发布记录保留，不改写为过去已支持。

## 10. 正确性验收矩阵

| ID | 独立 oracle 与判定 |
| --- | --- |
| F01 | 丢峰反例：原始 `(0.11,100)` 必须在原生取数、游标、峰值统计、数值导出中可达；缩放至原始点可见 |
| F02 | 长短/不重叠/单点：所有支持通道点数与范围保持，单点 Fs unknown，原文件 hash 不变 |
| F03 | 重复/复位/nonfinite/失效位：原始序号、raw bytes、时间和质量对齐；图中断点不跨接，分析明确拒绝或按记录的派生政策处理 |
| F04 | dtype/转换：int64/uint64 超过 2^53、float32/64、线性/表转换、单位、枚举；raw 按位或数值精确，physical 对独立公式，NaN mask 单独比较 |
| F05 | MDF2/3、数组矩形/逆序/3D、虚拟元素和同名/Time：保留安全 reader 数值 oracle 与物理身份；目录父项不算第二套测量 |
| F06 | 等长错位与多率 RPM：按真实 t 核对，不跨有效覆盖端点延长；恒定/斜坡 RPM 的转数、已知阶次结果验证 |
| F07 | FFT/时频：同步均匀通道与迁移前同源数据数值 parity；已知正弦频率/幅值/能量 oracle；恢复峰值的差异是纠错，不要求错误结果一致 |
| F08 | 抗混叠：含带外频率的信号与独立参考过滤/采样结果比较；边界、延时及频带说明一致，不以两条共享实现 parity 代替正确性 |
| F09 | FRF：已知增益/延迟/滤波系统；原轴相位、错位、比率和边缘裁切 oracle，覆盖 H1/H2/coherence；无法达到门限的对齐组合不得启用 |
| F10 | 项目/公式/导出/Replay：保存重开、源变化、旧schema迁移、无缺口错误拼接；原始导出回读逐点一致 |
| F11 | 多 View/比较/UltraView/cache：源 revision、目标 View、请求/已应用结果不混淆；关闭或取消无迟到发布 |
| F12 | 进程/资源：取消、崩溃、盘满、超预算、坏 manifest后正常读取；typed native payload roundtrip保持轴共享和只读 |

浮点一致性：未转换 raw 保留 dtype/bit pattern（含 signed zero、NaN payload 在 reader 可提供时）；未经重采样 physical 使用既有独立公式容差；新增 DSP 容差须在 Plan M0 冻结数值 oracle 与适用频带，禁止事后用宽阈值吞掉失败。没有完成 F01–F12 与性能平台门禁前，状态只能是 partial/UNKNOWN。

### 10.1 当前阻断清单与必须固化的反例

以下为 `c126fcae` 加未提交候选的 2026-11-17 观察，路径均相对 `mf4_analyzer/`。行号会随其他任务变化，按符号定位。N01–N06 的临时探针尚不是持久回归测试；Plan B0 必须将它们固化并确认修复前失败。不能把下列“应满足”写成已通过。

| ID / 当前状态 | 证据、用户影响与回归输入 | 应满足 / 关联合同 |
| --- | --- | --- |
| N01 / P1 已复现 | `io/native_signal_store.py::_sampling` 用 `dt != dt0`。`arange(100)/fs` 在 10/100/1000 Hz 被判 unknown，1024 Hz 对照可准备；100 Hz 真实 MDF 写入/读取也使分析报采样率未知。常见正常数据无法 FFT/滤波等 | 按 §5 冻结的精度合同识别合法均匀段，同时拒绝真实抖动/复位；检查 reader→transport→分析，不只测人工声明 Fs 的 store。F07/F09 |
| N02 / P1 已复现部分入口，其余源码确认 | `ui/main_window/window.py` 的 `_on_inspector_signal_changed`、`_on_fft_time_signal_changed`、`_on_file_activated`、`_build_time_statistics` 仍触发文件级 fs/time/data；`analysis_time_range.py::axis_facts_from_files`、`ultraview_capture_coordinator.py::_channel_signature`、`batch_export_size.py::source_size_facts` 同样不兼容。真实 native FileData 调用这些生产方法抛 `LegacyAxisUnavailable`。`batch.py` 分组/单项/RPM仍有旧表读取，完整 Runner 尚未实测 | 完成 §10.2 的真实事件路由；多率源按通道提供事实，不能用首通道伪造全局 Fs/axis/frame，也不能捕获错误后静默漏项。F06/F07/F10/F11 |
| N03 / P1 已复现 | `ui/pg_canvas/overlay_axes.py` 初画用有效显示值，`renderer.py::_refresh_visible_data` 又从 `channel_data` 取 raw。真实 offscreen canvas，值 `[10,999,30,40,50]` 第二点失效，首次为 NaN，刷新后 999 重新出现 | 每次显示变换均保留失效/复位断线；raw不改，峰值/统计不计无效999。验证首次、刷新、恢复、图像输出以及 Cocoa可见结果。F01/F03 |
| N04 / P2 已复现 | `ui/main_window/_order_mixin.py::_order_rpm_for` 先裁 RPM 再对齐。RPM `t=[0,1,2], y=[100,200,300]`，目标 `t=[.2,1,1.8]`、选区 `[.2,1.8]` 返回 None；保留邻点应得到 `[120,200,280]`。legacy分支也先裁切 | 读取必要邻点后对齐，输出严格落在请求/真实覆盖内；真越界、gap不得端点填充。native与legacy、手动RPM、单位/倍率、Order与Order-vs-Time均覆盖。F06 |
| N05 / P2 已复现 | `ui/main_window/_fft_time_mixin.py::_fft_time_signal_for` 用范围 None 准备整条信号，`_build_fft_time_job` 之后才解析范围。`t=arange(8)/4` 首点失效，选 `[.25,1.5]` 直接准备 ready，实际 getter 返回五个 None | 请求范围先解析；有效段能从实际计算入口执行，段内无效返回原因且不启动job；预览、作业、缓存使用一致范围。二进制精确时间作为控制，独立于N01。F03/F07/F11 |
| N06 / P2 已复现 | `ui/pg_canvas/cursor.py::_sync_native_sample_markers` 把全部 rows 的点赋给每个 marker。两子图在 t=2 的值30与3，两个 marker 都收到两个点 | 按通道/轴映射，双Y轴/子图/overlay/滤波伴随曲线正确，隐藏/重排/移除/重名来源/无数据不残留或串位；读数与实际点位置一致。F01/F11 |
| N07 / 性能风险，SLA UNKNOWN | `analysis_signal_prepare.py::prepare_signal` 每次 hash 两个完整输入，部分预览走此准备；`ui/pg_canvas/cursor.py` 双游标路径有全段统计和额外 mask。源码说明可能产生重复O(N)工作，尚无足够实测证明超时幅度 | 元数据预览不触发完整准备，revision不在交互中重算；必要统计切片/索引或worker执行，缓存按字节计费。记录调用计数、分配与主线程耗时，再按 §3/§8验收，不用小测试耗时作性能证明。F11/F12 |
| N08 / 兼容与端到端 UNKNOWN | 共享 Order/准备/显示层会影响旧MF4和其他格式；helper成功不证明选择、计算、项目重开、Batch/Replay与生命周期正确 | §10.2 全链矩阵、旧结果控制和明确计算行为通过；既有功能不因原生迁移消失，不能通过禁用这些功能交付。F06–F12 |
| N09 / P1 M6报告失败，源码协议冲突确认 | `io/import_transport.py` 写端将 physical/raw 同缓冲区编码为 identity，读端要求 conversion也为identity。事故样本12个enum通道共享raw，读回报 `identity physical must share raw`，GUI注册0；非预算不足 | 冻结“缓冲区共享”与“转换语义”的独立表示；合法enum保留raw/code/标签及共享关系，不谎改conversion、不转object数组、不禁用校验。匿名enum与事故样本真实broker往返均注册，恶意/不一致manifest仍拒绝。F04/F12/R01 |

前轮定向命令覆盖 `tests/test_native_signal_store.py`、`tests/test_signal_access.py`、`tests/test_analysis_signal_prepare.py`、`tests/ui/test_native_signal_consumers.py`、`tests/ui/test_order_multirate_rpm.py`，结果为 **60 passed in 1.63s**；运行前后源码指纹一致（排序后的 `mf4_analyzer/**/*.py` 与上述5个测试文件，依次散列相对路径及文件内容，SHA256 `7ad68e9448e5ef89e9ba5e140da0e36342ee32f709560c15252a499afd8a40fb`）。这些测试未覆盖上述反例，不能用通过数抵消反例。M6报告另记录正式入口7 passed、边界/fidelity 36 passed及2 xfailed；它们不与60条相加，也不证明事故样本成功。本次仅修订文档，未重跑这些命令。

### 10.2 产品兼容与结果变化验收

| 场景 / 必测路由 | 验收内容 |
| --- | --- |
| 导入与选择 | 显式候选入口→真实adapter/broker/transport→MainWindow注册→激活文件/勾选通道/Inspector选择；普通打开、拖入、最近及项目策略分别验证。禁止替换被测consumer/helper以绕开文件级访问异常 |
| FFT、时频、Order、Order-vs-Time、FRF、时间滤波 | 多率/同率、完整/局部段、空/短/非有限、等长错位/不重叠；真正点击计算并等待任务终态，比对独立oracle。合法请求产出；非法请求给准确原因、不发布半结果；GUI/Batch同请求parity加绝对正确性 |
| 游标/统计/显示 | 单/双游标、区间统计、原始/滤波、Custom-X、双Y轴/子图/overlay、Pin；原始点/质量/轴映射在缩放、重排、隐藏、View恢复前后相符。offscreen数值与真实Cocoa几何/像素分开记录 |
| 旧格式与混合来源 | 既有legacy MF4、CSV、HDF、BLF的受影响边界；与native混用、同名通道、不同Fs/时钟。已合法的旧输入保留单位、dB参考、范围与结果；新保留峰值造成的预期变化单独说明，不以错误旧结果作golden |
| 意图、缓存与生命周期 | 编辑范围/参数、预览、选择、切View及项目恢复不隐式计算；应用后结果、比较B面、Pin、UltraView对应正确source revision/view/pane。关闭/取消/替换源时无迟到发布，reservation/引用释放 |
| 项目/通道编辑/导出 | 旧项目legacy复现、新schema6 native恢复、显式迁移预览/取消、单/多输入公式和派生轴；数值导出回读逐点/质量/大整数一致，PNG/PDF保留断线；源变化悬挂不猜配 |
| Batch / Replay | 实际Runner的probe、普通/分组任务、RPM、Custom-X、导出尺寸建议、输出与取消；拆分逻辑来源保留identity。Replay通过实际UI选择/启动/停止，保留原时间/顺序/segment，独立进程测试 |

每项结果只能填 PASS（附证据）、FAIL、UNKNOWN 或明确未完成的 partial；必需项的 xfail/skip不是PASS。N01–N09、F01–F12、R01及资源/性能/平台门禁逐项关闭，才能提出默认切换与发布。缺少Windows、图2样本或数值设计不能自行改成非目标；若确需调整已约定交付范围，先单独提出并取得用户决定。

## 11. 外部依据与文档边界

- [ASAM MDF](https://www.asam.net/standards/detail/mdf/)：可存原始编码与转换规则；多率/非等间隔见 [4.3 规范概述](https://www.asam.net/index.php?eID=dumpFile&f=9630&t=f&token=39c75c0c8841fd89a6caa29376c9483b5ecc40d4)。
- [asammdf API](https://asammdf.readthedocs.io/en/latest/api.html) 与 [读取性能提示](https://asammdf.readthedocs.io/en/master/tips.html)：raw/失效位/record窗口与分组读取是可用机制；最终语义以固定本地 wheel 的 oracle 为准，不能仅凭参数名理解失效位。
- [SciPy resample_poly](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html)：低通与采样组合，以及边界扩展必须显式考虑；此引用不授权新增运行时依赖。
- [Vector CANape 产品说明](https://www.vector.com/dam/jcr%3A67ae5dbf-fe3c-4ea5-8008-d285fa47eeb2/CANape_ProductInformation_EN.2026-06-29-07-00-35.pdf) 说明直接使用 MDF/MF4，不足以证明每项 CANape 操作的内部算法。CANape 同文件对照可作独立参考，不能替代原始字节、人工公式与采样身份 oracle。

本次修订只更新本 Spec/Plan，读取当前候选源码与阶段报告，未重跑实现测试、原生 GUI 性能或 Windows EXE，也未修改产品源代码。检查全文、引用/路径、历史与当前状态、R01/F01–F12 映射及 `git diff --check`；文档交付不运行 runtime/full suite。该 spec 约束最终 native 路径，不改写历史发布记录或其他任务的执行授权。
