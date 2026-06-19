# HEAD acoustics `.hdf`（HEAD datafile format v4）导入 — 设计文档

- 日期：2026-06-19
- 状态：待用户复核
- 范围：**v1 仅数据导入**（把 HEAD 时域数据忠实读进 app，复用现有 FFT / 阶次 / 时频 / Campbell）

## 1. 背景与动机

为 MF4 Data Analyzer 增加对 HEAD acoustics ArtemiS 导出的 `.hdf` 文件的读取支持。

经实读样本文件 `260417-ripple-PK2C-电机加热-1.hdf`（51 MB）确认：该 `.hdf` **不是** HEAD 私有二进制、也**不是** HDF5，而是 **HEAD acoustics datafile format version 4 / release 6**——一个自描述的"ASCII 头 + 二进制数据"混合格式。因此**无需** HEAD 的 .NET Data Access SDK、无需 Windows、无需授权，纯 Python + numpy 即可解析，跨平台。

## 2. 样本文件实测事实（解析依据）

文件级头（ASCII，位于前 `start of data = 65536` 字节内，`key: value` + `;` 注释）：

| 字段 | 值 |
|---|---|
| version / release | 4 / 6 |
| byte order | Intel（小端） |
| kind | Time data |
| start of data | 65536（二进制数据起始字节偏移） |
| nbr of abscissa | 1 |
| nbr of channel | 28（数据通道；另有 1 条 Time 横轴定义） |
| scan mode | synchronised multiple（同步多采样率） |
| abscissa | Time / t，单位 s，first value 0，delta value 3.86100386100386e-006，nbr of scans 49500，linear |
| date of recording | 17.04.2026 09:49:33.400（原始戳 `31247884-1884802385`） |
| timezone / code page | China Standard Time / 936（GBK） |

多采样率（已用 Read 工具完整解出头部确认）：

完整 `ch order: 24*1,2, 24*3,24*4,24*5,24*6,24*7,24*8,24*9, 10, 11, …, 27, 48*28`，`data org: a1b1 a2b2`，`absc sort: calc`（abscissa 不存储）。

按 `ch order` 因子分为 **3 个速率档**（不是最初估计的 2 个）：

| 速率档（factor） | 通道数 | 通道 | 每通道样本数 |
|---|---|---|---|
| **1×** | 19 | `SP`（转速 °/s）+ ch10–27（全部 `Com_*` 控制量：转速/扭矩/温度…） | 49,500 |
| **24×** | 8 | `L`/`R`（声压 Pa，cal≈104）+ `MOTOR X/Y/Z` 与 3 个 GBK 命名通道（加速度 m/s²，cal≈93.8） | 1,188,000 |
| **48×** | 1 | ch28 `CAN 1@SQuadriga`（**可疑**：CAN 不应是最高采样率，疑为同步/触发线，待确认） | 2,376,000 |

**交织布局已由算术钉死，无需读二进制**：Σ 因子 = 24 + 1 + 24×7 + 18 + 48 = **259**；259 × 49,500 = 12,820,500 floats = 51,282,000 B，正好等于文件内 `data1 51282000` 声明的数据块大小。每个 base scan 按通道序依次写「factor 个 float」，重复 49,500 次；abscissa（Time）为 calc 计算、不存储。

**绝对采样率仍有歧义（§7 头号确认项）**：`delta value = 3.861e-6` + `nbr of scans = 49500` 有两种读法：
- (a) delta = base scan 周期 → 录制 ≈ 0.191 s，1× 通道 259 kHz、24× 6.2 MHz、48× 12.4 MHz（费解、不合物理）。
- (b) delta = 最细栅格周期（对应最大 factor 48）→ 录制 ≈ **9.17 s**，1× ≈ 5.4 kHz、24× ≈ 129.5 kHz、48× ≈ 259 kHz（合物理，符合"电机加热"多秒测试）。

**强烈倾向 (b)，但须用 HEAD Companion 打开真实文件读一眼实际 fs/时长定死**。各组时间轴按确认后的公式 `period = delta × (max_factor / factor)` 生成。

每通道头字段（已确认存在）：`name str`、`physical quantity`、`physical unit`、`calibration`、`;#dB reference`、`;#moniker`、`physical channel nbr`、`implementation type`（FLOAT32）、`;#equalization`、`emphasis`。注意 `moniker`/`dB reference`/`equalization`/`quantity domain` 是 `;#` 注释行，与普通 `key: value` 行交错出现在每个 `channel definition` 块内——解析器须把它们归到所属通道。

### 2.1 二进制实读确认（已用 venv python 解 `/tmp` 副本）

- **交织/分组 100% 确认**：259 floats/scan × 49,500 scans = 数据块精确吻合；factor 直方图 `{24:8, 1:19, 48:1}`。`raw[start : start+49500*259*4]` 按 (nscan, 259) reshape、按 `ch order` 列偏移切片即得各通道。
- **GBK 解码确认**：ch7–9 解出 `输出轴 z/y/x`（输出轴三轴加速度）。
- **数据语义对上**：L/R ≈ ±0.4（声压音频），MOTOR X/Y/Z 与输出轴 ≈ ±3~13（加速度），SP/`Com_RPS_Speed` 为速度量级。
- **空通道**：12 个 `Com_*`（ch10–16/20–23/26–27）全 0（本次未采）——**保留**（合法空通道，与 MF4 行为一致）。
- **ch28（48× "CAN 1@SQuadriga"）的 `implementation type` 是 UINT32**（非 FLOAT32；早期按 `<f4` 探查时误读成"全 NaN"——其实是 UINT32 字节按 f4 解出的 NaN 位型）。该通道**按"非 FLOAT32 → 丢弃并记录"**处理（见 §3.6）。丢弃后 48× 组消失 → **本文件实际 2 组（24×/1×）**。（Task 8 真实文件集成测试发现：原"任何非 FLOAT32 整文件报错"的守卫会使真实文件打不开。）
- **footer**：数据块后 137 字节 `; xmlAppendix_utf16 …`（UTF-16，`<HdfAppendix version="1"><UserDoc /></HdfAppendix>`），无采样率信息。
- **采样率仍需 HEAD Companion 定死**：读法 (a) 0.191s 使音频达 6.2 MHz（物理不可能）→ **排除**。剩两候选：① delta=24×周期 → 音频 259 kHz、控制 10.8 kHz、时长 4.59 s；② delta=48×周期 → 音频 129.5 kHz、控制 5.4 kHz、时长 9.17 s。loader 用 `period = delta × (max_factor_in_ch_order / factor)` 计算（max_factor 取 `ch order` 原始最大值，本文件含 ch28 即 48 → 候选②）；最终以 HEAD Companion 显示的 fs/时长为准。

## 3. 设计

采用「**独立解析模块 + 薄适配层**」路线（解析逻辑可独立 TDD，契合现有 `io/loader.py` 分发 / `io/file_data.py` 模型分层）。

### 3.1 解析器 `mf4_analyzer/io/head_hdf.py`（纯函数、无 pandas/Qt 依赖）

`parse_head_hdf(path) -> HeadHdfFile`：

1. **签名嗅探**：读文件头，要求出现 `HEAD acoustics datafile format` 签名；否则抛出清晰错误（疑似 HDF5/其他格式）。
2. **头解析**：解析 `start of data` 之前的 ASCII 区（`key: value` + `channel definition` 块）；字符串按 **cp936(GBK)** 解码（修中文通道名乱码）。
3. **二进制解复用**：从偏移 `start of data` 起，按 `data org` + `ch order` 把交织的小端 FLOAT32 拆成各通道**原生速率**数组（快轨 1.188M 点 / 慢轨 49500 点）。
4. 输出：文件级头字典 + 每通道 `{name, samples(原生), raster_factor, physical_quantity, physical_unit, calibration, db_reference, moniker, physical_channel_nbr, implementation_type, equalization, emphasis}`。

### 3.2 适配层 `DataLoader.load_hdf`（`mf4_analyzer/io/loader.py`）

- **施加标定**：每通道 `samples × calibration` → 物理值（默认恒开，保证与 HEAD 数值一致）。
- **丢弃全 NaN 通道**（如 ch28），保留全 0 通道；与现有 loader `dropna(axis=1, how='all')` 一致。
- **按 factor 分组（通用，不硬编码组数）**：`ch order` 里出现的每个不同 factor 一组（丢弃全 NaN 后本文件 = 2 组：24×/1×）。同 factor 的通道样本数相同、共享时间轴。
- **注入 RPM**：把转速通道（`SP` / 相应 `Com_RPS_*`）重采样到含加速度的 24× 组时间轴后并入该组，使组内可直接做"振动 vs 转速"阶次分析。
- 每组按确认后的采样率公式生成统一时间轴（见 §2 / §7）。
- 返回**分组列表**：`[(df, chs, units, channel_meta, file_meta, group_label), …]`，每元素对应一个待建 FileData。

### 3.3 多采样率 → 每个 factor 一个 FileData（不改 FileData 模型）

`_load_one(fp)`（`mf4_analyzer/ui/main_window/_project_io_mixin.py:101-113`）：`.hdf` 分支调用 `load_hdf`，**遍历分组创建 N 个 FileData**（本文件 N=3），条目名加后缀区分（如 `260417-ripple… [24x ≈129k]` / `[1x ≈5.4k]` / `[48x ≈259k]`，具体率值待 §7 确认）。每个 FileData 仍为单一 `fs` 的常规对象，下游分析/UI 零改动。

> 待确认（§7）：ch28（48× 单通道、名为 CAN）是否单独成组、并入、或丢弃——默认按 factor 通用分组使其单独成第 3 条目。

### 3.4 元数据保留（为后续声学分析留门，本身零额外解析成本）

`FileData` 新增两个**格式无关**的字典：

- `source_metadata`（文件级，每个 FileData 都带）：录制日期时间 + 原始戳、时区、`version/release`、`code page`、`kind`、`scan mode`、原始采样率/`delta`、`nbr of scans`、源文件名、`group_label`。
- `channel_metadata`（每通道）：`physical_quantity`、`physical_unit`、`calibration`、`db_reference`、`moniker`、`physical_channel_nbr`、`raster_factor`、`implementation_type`、`equalization`、`emphasis`。

**不保存**（显示用/可推导）：`graph style`、`distribution func`、`quantisation func`、`composition`。

> 理由：A 计权 / SPL / 滤波等后续声学功能需要每通道 `db_reference`、`physical_quantity`、`calibration` 与原生采样率。这些 v1 解析时本就读到，保留几乎零成本；丢弃则"后续添加"需回头重做 FileData plumbing 甚至重读文件。

### 3.5 接入点（最小改动）

- 文件对话框过滤器（`_project_io_mixin.py:31-34, 81`）加 `*.hdf`。
- `.hdf` 经 §3.1 签名嗅探确认，再走 HEAD 路径；不符则报错，不与 HDF5 撞扩展名误解。
- 项目 `.tlproj` I/O 无需特殊处理：重开时按扩展名经同一 `_load_one` 分发（一个 `.hdf` 仍恢复为 2 个条目）。

### 3.6 错误处理（变体守卫）

**文件级守卫（硬失败）**：`version != 4`、`kind != Time data`、`byte order != Intel` → 抛 `NotImplementedError`（含实际值），整文件不解析。

**单通道 `implementation type` 非 FLOAT32（如 UINT32/INT16/DOUBLE）→ 丢弃该通道并记录，不连累整文件**：解析器对这类通道跳过 demux（`samples` 留 None，因 demux 只按 `<f4` 读，其它 dtype 不能正确解释），`load_hdf` 把它与全 NaN 通道一并丢弃，并把丢弃的通道名+原因记入 `source_metadata["dropped_channels"]`（不静默）。只要还有 ≥1 个 FLOAT32 数据通道存活就正常加载；若无则 `load_hdf` 抛 `ValueError`。

> 真实文件依据：ch28 `CAN 1@SQuadriga` 为 UINT32，须被丢弃而非使整文件失败（Task 8 集成测试发现）。

## 4. 测试策略（TDD-first；数值改动必须先测）

- **单元测试用合成 HEAD 文件**：自写一个小生成器，产出含快/慢两轨、若干通道（含 GBK 名、含一个转速通道）的最小合法文件，避免把 51 MB 真文件入库、测试更快。覆盖：
  - 头解析：version、通道数、快/慢 fs、通道名（GBK 解码正确）、单位、calibration、db_reference。
  - 解复用：各通道样本数（快 1.188M / 慢 49500 规模）、首/尾样本值。
  - 标定：施加后数值正确。
  - 分组 + RPM 注入：快轨 8 通道 + 注入转速；慢轨 20 通道。
  - 元数据：`source_metadata` / `channel_metadata` 字段齐全。
  - 守卫：签名嗅探、变体守卫在构造的坏头上正确抛错。
- **对标验收（手动门槛）**：用免费 **HEAD Companion**（或 ArtemiS）打开真实文件，比对 ≥2 个通道的样本值 / RMS / min-max / 采样点数 / 采样率，确认 loader 在浮点精度内一致。**重点核对标定是否乘对**（最常见翻车点）。

## 5. 性能与内存

- 24× 组 ≈ 9 通道（8 + 注入转速）× 1.188M × float64 ≈ 85 MB
- 1× 组 ≈ 19 通道 × 49,500 ≈ 8 MB
- 48× 组 ≈ 1 通道 × 2.376M ≈ 19 MB
- 合计 ≈ 112 MB/文件（远低于"全部升采样到最快率"方案）。

`signal/envelope.py` 抽稀不做抗混叠，最高速率波形（≈129–259 kHz）显示时需留意视觉混叠（v1 不处理，记录备查）。

## 6. v1 范围之外（后续独立项）

明确**不在 v1**：A/B/C/Z 计权、IIR/FIR 滤波、1/1 & 1/3 倍频程(CPB)、总声级/Leq/时间计权(Fast/Slow/Impulse)/统计声级、心理声学（响度/尖锐度/粗糙度）、音频回放/WAV 导出、批量抽屉对 HEAD 的探测。这些为加法式扩展，且 v1 的拆组 + 元数据保留已为其备好正确输入。如需"对标 HEAD"地实现，须另备 ArtemiS 参考导出 + 按标准（IEC 61672 / 61260、ISO 532 等）验证，作为独立 spec。

## 7. 开放项 / 需确认的假设

1. **绝对采样率（唯一硬确认项）**：读法 (a) 0.191s 已排除（音频 6.2 MHz 不可能）。剩候选 ① 音频 259kHz/4.59s 与 ② 音频 129.5kHz/9.17s（见 §2.1）。**用 HEAD Companion 打开真实文件，读 channel `L` 的采样率或录制时长，二选一即定死**。loader 公式 `period = delta × (max_factor_in_ch_order / factor)` 默认给候选②；若 Companion 显示候选①，则改为 max_factor 取"丢弃 NaN 后存活通道的最大 factor"。
2. ~~ch28 处理~~ **已解决**：ch28（48×）全 NaN，按全 NaN 丢弃；本文件实际 2 组（24×/1×）。
3. 转速注入选哪个通道作 RPM 源（`SP` °/s vs `Com_RPS_Speed`）、单位换算（°/s → RPM = ×60/360）。默认用有数据的 `Com_RPS_Speed`（ch17）或 `SP`（ch2），实现时取非全 0 者。
4. 交织布局**已实读确认**（259×49500 精确吻合、abscissa 不存储、各通道值域语义正确）；验收再加一次 HEAD Companion 数值交叉比对（标定后的 L/SP 值、采样点数）。

## 8. 环境前置（实现前必须解决的硬阻塞）

项目位于 `~/Downloads`，受 macOS TCC 保护。当前 **Bash 子进程对项目目录全部 EPERM**（`ls` 项目根目录即"Operation not permitted"），因此 **pytest / python 解析脚本无法运行**——这阻断整条 TDD 实现链（执行方 Sonnet 同样以子进程跑测试）。harness 的 Read 工具不受影响（本设计的头部事实即由它读出）。

实现开始前必须二选一永久解决：
- **将项目移出 `~/Downloads`**（如 `~/dev/`、`~/projects/`）——推荐，彻底。
- 给运行 Claude Code 的终端 App 授予系统「**完全磁盘访问权限**」（可能需重启会话生效）。

参见记忆 `env-tcc-downloads-blocks-access`。
