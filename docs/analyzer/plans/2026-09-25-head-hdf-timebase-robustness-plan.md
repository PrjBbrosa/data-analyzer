# HEAD HDF 多采样率与时间轴鲁棒性优化方案

日期：2026-09-25。状态：规则与结构校验已落地；官方绝对时间对照和真实 FLOAT32 48 kHz 混合文件仍待核验，不能当作发布验收。

## 1. 目标与取舍

同时支持已确认的同采样率文件和多采样率文件，允许麦克风、传感器、已解码 CAN 信号混合。采样率由文件语义决定，不按通道类型预设 24 kHz、48 kHz、1 kHz，不根据常见频率取整猜测，不通过频谱形状选择时间公式。

推荐：在现有 HEAD HDF 解析器中增加有明确适用条件的时间规则、严格的布局检查与采样事实传递，使用官方软件建立独立基准。保留现有分组导入接口，不引入通用格式框架，也不把官方授权库作为默认运行依赖。

| 路线 | 优点 | 不足 | 决策 |
| --- | --- | --- | --- |
| 只按 scan mode 加一个分支 | 很快修复本例 | 单点数据、异常头部、下游 fs 与工程恢复仍可能出错 | 不作为完整方案 |
| 本地严格解析 + 官方基准 | 保持跨平台，行为可测，未知组合可明确拒绝 | 支持范围需要逐步验证 | 推荐 |
| 直接依赖 ASX 01 | 时间语义由官方库处理 | Windows/.NET 和开发、运行许可证要求；分发方式需确认 | 作为验证工具或后续可选导入后端 |

## 2. 已有证据与尚未确认的边界

本次会话直接读取两个真实文件并调用 `DataLoader.load_hdf`：

| 项目 | 20260924_LS6_直驱#1 gear_running_outdoor.hdf | 260417-ripple-PK2C-电机加热-1.hdf |
| --- | --- | --- |
| version / release | 4 / 6 | 4 / 6 |
| scan mode | simultaneous | synchronised multiple |
| 通道 | 12 个 FLOAT32，加速度 | 28 个，含 UINT32 原始 CAN |
| factor / 总槽数 | 全部 1 / 12 | 24、1、48 / 259 |
| delta | 4.16666666666667e-5 s | 3.86100386100386e-6 s |
| scan 数 | 1,732,800 | 49,500 |
| 现行导入结果 | 2 kHz，覆盖时长 866.4 s | FLOAT32 组 24 kHz、1 kHz，覆盖时长 49.5 s |
| 待官方对照的目标 | 24 kHz，覆盖时长 72.2 s | 原组采样率与时长保持 |

新文件有效数据区 83,174,400 字节，等于 scan 数 × 12 × 4；样本数量与布局自洽。该等式不证明绝对时间尺度。旧文件 factor=48 对应被跳过的 UINT32 通道，不能把它当作已验证的 48 kHz FLOAT32 麦克风样本；仍需补充真实 48 kHz 传感器与 CAN 混合文件。

已运行现有 `tests/test_head_hdf.py` 与 `tests/test_head_hdf_loader.py`：41 passed。它们不能证明 simultaneous 正确，因为既有时间公式测试主要覆盖 synchronised multiple。

当前代码依据：

- `mf4_analyzer/io/head_hdf.py:176` 只对版本、kind、字节序做部分变体检查；`:188` 按每槽 4 字节解复用；`:214` 保存 scan mode。
- `mf4_analyzer/io/loader.py:1339` 无条件按 `delta * sum(factor) / factor` 生成时间轴。
- `mf4_analyzer/io/file_data.py:255` 默认 fs=1000；正常路径从时间差恢复 fs，单点不能靠差分恢复；传入 `fs=` 的另一分支会重建零起点时间轴。
- `mf4_analyzer/io/source_adapters.py:329` 的 HDF group identity 包含 factor、样本数、dt、t0，时间修复会改变相应身份值。

## 3. 时间规则：先识别组合，再计算

规则输入保留：version/release、kind、scan mode、data org、idx order、横轴数量与定义、横轴物理量/单位、absc sort、distribution func、first value、delta、scan 数、ch order、通道存储类型。

第一阶段只支持有证据的 v4/release 6、Intel、Time data、单一线性计算时间轴（秒）、现有交织布局。标准化大小写和空白可接受，缺失值不得被标准化为猜测值。若要兼容其他 release，先证明字段语义等价并增加夹具，不悄悄通配所有版本。

| 规则 | 条件 | 时间计算 | 限制 |
| --- | --- | --- | --- |
| simultaneous | 所有声明 factor=1，布局及横轴符合支持范围 | dt_i=delta；fs_i=1/delta；N_i=n_scans | channel 数不参与 dt；其他 factor 组合在有官方依据前不支持 |
| synchronised multiple | 正整数 factor，当前已验证交织布局及 32 位存储槽 | S=sum(f_i)，T_scan=delta*S，dt_i=T_scan/f_i，N_i=n_scans*f_i | 包含跳过通道的槽；作为现有兼容规则，绝对语义需官方对照后限定适用范围 |
| 其他/字段冲突 | 未验证模式、显式或非均匀轴、未知布局等 | 不生成采样率 | 返回具体不支持原因；后续按独立规则扩展 |

公式生成 `t_i[k] = t0 + k*dt_i`。明确区分最后采样时刻 `t0+(N_i-1)*dt_i` 与覆盖时长 `N_i*dt_i`；不同采样率组最后一个样本时间略有差别是正常的。

示例（用于解释规则，不是官方证据）：在混合模式中若 f=[48,24,1]、S=73、header delta=0.001/73，则 scan 周期 1 ms，产生 48 kHz、24 kHz、1 kHz。通道增删导致 S 改变时，合法文件写入的 delta 也必须按该格式保持目标 scan 周期；不得在测试中固定 delta 改 S，又要求采样率不变。

不要求 factor 集合含 1，不把最慢组强制设成 1 kHz，不把最大 factor 当实际 Hz。44.1 kHz、12.8 kHz、500 Hz 或其他值只要由已支持的文件语义得到，均按原值保留。采样率标签可以格式化，计算与身份键不得吸附到整数/常用率。

## 4. 数据布局和异常处理

先读有界文件头，验证数据偏移、计数、乘法尺寸和文件可用字节，再读取/分配大数组。第一阶段无需顺带重写为流式或 mmap。

- delta 必须有限且大于 0；t0 必须有限；scan 数为非负整数；factor 为正整数；通道引用在声明范围内。
- 当前支持范围要求每个数据通道有唯一、完整的 ch order 映射。缺失 factor 不再自动估为 1；重复引用暂明确不支持，不宣称它必然违反所有 HEAD 格式版本。
- FLOAT32 正常解码；已确认宽度和布局的 UINT32 槽保持对齐并记录跳过原因。不能仅因通道不支持就假设它也占 4 字节；未知宽度拒绝整个布局。
- 数据区字节数按布局核对。已声明的数据块必须完整；允许已识别的尾部元数据，不要求整个文件长度必须恰好等于 header+samples。无法解释的额外数据段标为不支持，不无条件忽略。
- 非有限信号值按已有策略处理：全 NaN 通道可跳过并记录，部分 NaN/Inf 保留事实并给出可观察诊断，不伪造/补齐样本，不用最短长度裁剪来掩盖组内长度冲突。
- 0 scan：解析可表达空记录，导入不生成可分析源，给出明确无数据反馈。1 scan/单点：保留头部推导的 fs，禁止落到默认 1000 Hz。
- 构建时间轴后检查有限、严格递增以及与声明 dt 的数值一致性；若巨大 t0 与极小 dt 导致 float64 无法分辨相邻点，明确报精度问题，不能通过 median(diff) 掩盖。
- 未知格式用明确 unsupported 错误，损坏或矛盾字段用数据错误，程序错误继续暴露。GUI 与 Batch 复用现有错误通道，不添加大范围静默异常兜底。

## 5. 原始采样事实只计算一次

`head_hdf.py` 拥有布局和时间语义，返回已验证的每组 dt、t0、样本数及规则依据；`loader.py` 只负责按原始采样组建表、单位及元数据，不维护第二套公式。解析/时间校验必须在生成时间数组前完成。

source/channel metadata 至少保留原始 mode、delta、factor、槽数、dt、fs、t0、N、解析规则版本。开发验证记录另外保存官方软件版本、证据文件及文件 SHA-256；不把开发诊断或运行缓存当作用户意图写进工程。

`FileData` 对 HDF 使用经校验的 dt 设置 fs，同时保留 loader 已构建的 Time 列和非零 t0。可参照现有 `apply_verified_zfd_sampling` 的所有权方式实现小范围 HDF 接入，不把 HDF 冒充音频走 `FileData(fs=...)`，不顺带修改其他格式的默认行为。

显示可继续使用原有分组方式；“官方对照通过”是带证据的开发验收结论，不能因为结构检查通过就自动打该标签。未知时间规则不得以警告后继续生成可分析数据的方式放行。

## 6. 多采样率、CAN 与派生通道

保留每个原始采样组，例如 48 kHz、24 kHz、1 kHz 各自的 N、dt、t0。GUI、Batch、导出共用这一份源事实。相同 fs 但时间起点或时间轴不同的组不能仅按显示频率合并；现阶段不扩展异步多轴文件支持。

已解码 CAN 信号在 HDF 中的网格频率不等于原始报文发送频率，也不等于总线 bitrate。只能从该 HDF 的时间定义读取，不能按名字、quantity 或“CAN 通常 1 kHz”推断。原始 UINT32 CAN 数据的解码不在本次范围。

导入不将所有原始通道升采样到最高频率。真正需要对齐时，由分析功能生成明确标识的派生数据；升采样不会增加原有带宽，状态量/连续量的插值策略需另有语义依据。

当前 loader 已有 `SP (rpm-injected)` 的历史派生列。第一阶段保留既有行为并验证其使用同一时间规则，不借时间修复重做 RPM 选源、单位或插值策略；该列不得冒充原始高采样率 CAN 通道。未来改变对齐策略须独立设计与验收。

## 7. 旧工程与身份兼容

修复 simultaneous 的 dt 会改变现有 group identity；实施前追踪 project restore、Batch 持久源引用和用户手动重建时间轴的恢复路径，不能假设重导入自动解决所有引用。

- 不改变旧多采样率文件的既有身份和排序，不改全项目统一 source-id 算法。
- 对受此次错误影响的 simultaneous 文件，建立有范围限制的旧身份兼容匹配：同一物理源、相同 scan 数、factor、t0 和通道身份事实，且旧 dt 明确等于已知错误公式的结果，才能匹配旧引用。文件指纹可用时必须核验；无足够事实或匹配不唯一则明确反馈，不能靠通道显示名猜测。
- 回归验证旧项目恢复不重复加载、不串通道，Batch 通道集合保持逻辑源边界。
- 从错误时间轴派生的缓存失效并重算。原始导入时间、用户显式采样率覆盖、用户选区/游标是不同来源，禁止统一除以 12。
- 对无法证明意图的历史时间范围/标注，不自动缩放；使用现有恢复反馈明确指出时间基准变化与需重新确认的状态，保留工程原文件。实施时确认当前恢复机制能承载此反馈，若需要新交互则单独界定最小 UI 范围，并同步 hints/quickref。

## 8. 独立证据与测试矩阵

官方参考：

- [HEAD Companion](https://www.head-acoustics.com/products/analysis-software/head-companion/)：免费、免许可证；通道属性、按采样率排序、WAV/ATFX 导出。
- [ASX 官方资料，Rev.07，08/26](https://cdn.head-acoustics.com/fileadmin/data/en/Data-Sheets/AS/HEAD-acoustics-Data-Sheet-ArtemiS-SUITE-Extensions-ASX-HEAD-System-Integration-and-Extension-Overview-5090ff-EN.pdf)：ASX 00 免许可证开发文档；ASX 01 HDF Library；Windows/.NET 与开发运行许可证要求。

公开资料尚未给出本方案两种 scan mode 的逐字段公式定义。优先读取 ASX 00 编程文档或向 HEAD 支持确认：各 mode 下 delta 单位与语义、factor 含义、各存储类型宽度、abscissa/scan/data-block 的关系、版本兼容范围。不得把 SENX 的格式规范误当 HDF 规范。

官方基准至少包括：本次 12 通道 simultaneous、旧多采样率文件、新增真实 FLOAT32 48/24 kHz + CAN 混合文件。记录逐通道 fs、N、起止时间、导出是否重采样/截取、软件版本与 SHA-256。WAV/ATFX 只有在确认未重采样和未裁剪后才能作为原始时间轴对照。只看波形相似或 FFT 峰位置不足以验证绝对时间。

| 类别 | 必测组合与断言 |
| --- | --- |
| 同采样率 | 1/2/12 通道，24k/48k/非标准率；保持 delta 增减通道后 fs 与时长不变 |
| 多采样率 | 48k+24k+1k、24k+1k、48k+500、所有 factor>1；逐组 fs/N/dt 正确且覆盖时长一致 |
| 槽位与选择 | 通道重排、丢全 NaN、跳过已知 UINT32 不改变剩余组时间；未知宽度明确失败 |
| 时间边界 | 非零/负 t0、0/1 scan、无效 delta、极大 t0 精度丢失；不触发隐式 1 kHz 或零起点重建 |
| 结构边界 | 缺失/重复/越界 ch order、截断、未知 mode/release/layout、非时间/非线性轴明确反馈 |
| 输出正确性 | 官方基准与样本切片、独立定义时间的已知频率合成信号；不仅验证解析器和自身公式相等 |
| 集成 | GUI/Batch 使用相同事实；工程恢复、手动时间覆盖、旧身份匹配和多组不重复加载 |

合成夹具覆盖计算与组合，官方样本覆盖绝对语义，两者不可互相代替。真实客户样本通过现有 corpus/env 机制供给，默认测试不能依赖本机 testdoc；公开仓库不加入原始测量数据。缺少必需官方样本时标记该发布验收未完成，不能用 skip 当通过。

## 9. 实施顺序与门槛

1. **限定规则和建立基准**：保存两文件头部事实、官方核验结果、现有导入期望；补 simultaneous 失败用例和混合采样组用例。官方确认前可完成结构校验和可审查实现，发布验收仍待确认。此阶段不要求全量测试基线。
2. **解析与采样事实**：在 `head_hdf.py` 和 `loader.py` 收敛规则、验证布局，按需小范围接入 `file_data.py`。先跑 `tests/test_head_hdf.py`、`tests/test_head_hdf_loader.py`、`tests/test_file_data_time_axis.py` 中受影响 owner 用例。
3. **集成与恢复**：验证 `source_adapters.py` 的身份变化，实施有证据的兼容恢复；跑 `tests/test_source_adapters.py`、`tests/test_batch_source_integration.py` 和 `tests/ui/test_project_session.py` 的相关 HDF/时间覆盖用例。若涉及 Batch runner 本身，再加 `tests/test_batch_run_reporter.py`；不能为方便直接重构编排层。
4. **边界及真实文件**：按改动运行 `tests/ui/test_import_boundaries.py`、`tests/test_signal_no_gui_import.py`；若新增模块/改变打包导入，追加 packaging gate。运行扩展后的 `tests/integration/test_head_hdf_realfile.py`，显式要求 corpus；以官方结果核对三类真实文件。
5. **产品验收**：前台核对分组 fs、Time、FFT 频率轴、Batch 导出、工程重开。源码、macOS 前台、Windows 冻结程序为独立证据；Windows 发版前需 frozen 导入烟测。修改现行误泛化注释和相关 lesson 的适用条件，不回写历史计划。

执行完成标准：已支持组合准确保留原始采样事实；未知组合不会悄悄生成时间轴；旧多采样率数据和工程不回归；simultaneous 新例与官方时间轴相符；新增真正的 48 kHz 混合源有独立基准。不得宣称已覆盖全部 HEAD HDF 变体。

本次只新增方案文档，检查引用、范围和 `git diff --check` 即可，无需重跑运行时测试。
