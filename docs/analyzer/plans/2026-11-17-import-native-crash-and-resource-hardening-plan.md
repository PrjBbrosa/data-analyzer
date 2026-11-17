# 导入解析崩溃、错误数值与资源失控优化 Plan

日期：2026-11-17

状态：**T1–T4 已实施并完成针对性验证；T5 部分完成，全套与 Windows 发布验收未通过。** 下面的调查数据保留修复前基线；实施记录见第 8 节。

基线：`5bac5a2c9ae40e1ea7a45ac4fbab3d7d6a652867`，工作区已有其他任务的修改。实施时重新记录 HEAD 与相关文件指纹，不覆盖现有改动。

## 1. 结论与范围

这次 MF4 的直接原因是 asammdf 数组元素偏移计算错误，加上 C 读取函数未正确处理记录外偏移，最终破坏堆内存。TraceLab 在同一进程逐通道读取，校验发生在读取之后，因此既不能阻止原生崩溃，也不能发现全部错误数值。同步 GUI 导入又使长耗时读取阻塞事件循环。

**同一个数组算法缺陷属于 MDF4 读取路径；同一类“读前未约束、故障未隔离”风险跨格式存在。** 不能据此宣称 MAT/TDMS/音视频已经发生同一种越界。此次额外确认了 CSV/ASCII 探测整文件读取、ZFD 在判断无可用测量通道前申请超大时间轴两个独立问题。

实施目标按层分开：修正数据解释 → 读取/分配前校验 → 原生解析进程隔离 → 可取消的异步导入与原子注册 → 平台打包验收。仅“不崩溃”或“文件能打开”不构成完成。

包括普通打开、拖入、最近文件、项目恢复、Batch 探测/读取与 MF4 Replay；共享底层 owner，不能只修主窗口按钮。不包含 DSP 算法、绘图质量、采集硬件、通用损坏文件抢救或产品版本发布。本计划不自动授权其他历史计划中的任务，也不包含提交/推送。

## 2. 已验证证据

### 2.1 用户文件与故障链

- 文件：`5.W04_180_10s_rt_11210854.mf4`；实际附件名带 `1-` 前缀，12,353,424 字节，MDF 4.10，84 个组。
- SHA-256：`72d81a087e9816c7dca80633b20f5a899c0a484a6a80465b99a6d2f3c56cf5b3`。客户文件不纳入 Git、不上传到上游；现场文件缺失时此门禁标为 UNKNOWN，用匿名生成文件完成可移植回归。
- 调查基线环境：当时 `.venv` 的 asammdf `8.8.27`、NumPy `2.5.3`。两个独立读取进程均退出 139 / SIGSEGV；没有进入绘图。实施后的环境另见第 8 节。
- 组 39 的原始 `Dem_Cfg_StatusData.EventStatus` 是 `uint8[800,1]`，只有 1 个采样记录；原始组由时间主通道和数组通道组成，802 个解析通道包含库生成的 800 个元素通道，不能称为 802 个原始物理通道。
- 每记录 808 字节，数组基址 8。正确步长为 `[1,1]`；库生成 `[800,1]`，元素偏移变成 `8+800*i`。第 2 个元素已落在边界外，799 个元素越界。
- 本地 `asammdf/blocks/v4_blocks.py:2146` 的 `_factors` 先乘前面的维度，再反转列表；非等长行优先数组需要从最后维度反向累乘。这不是文件名、通道名或文件大小的特例。
- 本地 `asammdf/blocks/cutils.c:1301` 用 `delta=byte_offset+byte_count-record_size` 填零，却只分配 `cycles*byte_count` 字节。以偏移 1608、记录长 808、元素宽 1 为例，试图向 1 字节输出写 801 字节。错误不仅是读到文件外，更会写坏进程内存，崩溃位置可能延迟到无关 Python 语句。
- 产品 [loader.py](../../../mf4_analyzer/io/loader.py) `_read_mdf_signal:208` 先 `mdf.get()`，`_load_mf4_channels:345` 之后才判断形状、数值与时间。`except Exception`、QThread、信号异常钩子都不能隔离这种原生内存破坏。

上游证据：[issue #1318](https://github.com/danielhrisca/asammdf/issues/1318)、[数组步长与 C 边界修复 e79453d](https://github.com/danielhrisca/asammdf/commit/e79453d)、[complete 读取路径修复 1d6e3cb](https://github.com/danielhrisca/asammdf/commit/1d6e3cb)。它们提供修复依据，不代表当前发行包已经包含、也不代表 TraceLab 的数组/身份合同自动通过。

### 2.2 不能只检查“越界”和“能打开”

本轮用匿名生成文件、独立数值 oracle 验证；只读取确定在记录内的元素，避免再次损坏进程。

| 数组形状 | 错偏移元素数 | 越界元素数 | 实际影响 |
| --- | ---: | ---: | --- |
| 800×1 | 799 | 799 | 对应用户触发形状；合成样本使用 float32 |
| 7×6 | 36 | 6 | 同时有错值和越界；`[1,0]` 期望 6，实际 7 |
| 6×7 | 35 | 0 | 不越界但错值；`[1,0]` 期望 7，实际 6 |
| 3×3 | 0 | 0 | 方阵控制组正常，普通样本容易漏检 |
| 2×3×4 | 20 | 0 | 三维数组也会静默错值；`[0,1,0]` 期望 4，实际 2 |

上一轮仅在诊断进程内纠正步长后，用户数组 800 个元素与父数组全部一致，完整 loader 约 0.15 秒返回 `(471652,53)`：52 个数值信号加 Time。关闭数组自动展开也能加载，但会改变数组子通道能力，不能作为无提示的永久修复。单点、非数值、重采样与端点填充仍按现有规则报告，52 个信号不等于所有文件变量均已完整导入。

调查阶段另外通过 `pip --target .state/... --no-deps` 隔离检查官方 `8.8.32` macOS arm64 wheel：矩形与三维数组仍有上述错偏移，方阵控制组仍正常；到达越界门禁后未执行其用户文件全量读取。当时 `.venv` 未升级。**禁止仅写 `asammdf>=8.8.32` 就宣称修复。** 本次检查的是指定 wheel，不推断未来发布物的状态。

### 2.3 本轮跨格式探针

| 项目 | 实测 | 证据边界 |
| --- | --- | --- |
| CSV 头探测 | 1,048,592 字节文件，`_read_sniff_lines` 实际读入 1,048,592 字节，再切 64 KiB | read 调用计数探针，未制造 OOM |
| 固定宽度 ASCII 头探测 | 同一文件实际完整读取，再切 256 KiB | read 调用计数探针 |
| ZFD 隐式时间轴 | 112 字节完整合成容器声明时间 count=2,147,483,647，另有 1 点测量；调用 `np.arange` 申请 17,179,869,176 字节 | 在分配入口抛出诊断异常截住；未实际分配 16 GiB，未声称已复现 OS OOM |

可重跑的本地探针与 JSON：`.state/import-robustness-20261117/probe.py`、`results.json`、`candidate-results.json`。它们是调查证据，不是已提交回归测试或前台/Windows 验收。

## 3. 基线的跨格式影响与优先级

| 路径 | 当前保护与缺口 | 证据 / 优先级 |
| --- | --- | --- |
| MF4 / 内容为 MDF4 的 `.mdf` | `load_mf4` 默认展开数组；读取后才校验。metadata probe 独立 `MDF(path)`，可能列出错误元素；probe 成功不证明 payload 安全 | 崩溃与错值已确认 / P0 |
| MDF2/3 | 共用入口但不是同一个 MDF4 CA 算法；需守住旧格式兼容，不能把扩展名等同内部版本 | 相同入口，未确认同一缺陷 / P1 回归 |
| MAT v4/v5 / v7.3 | `loadmat` 全量读取；`_collect_h5py` 在 dtype/shape 筛选前 `np.asarray(dataset)`。原生库、压缩与大矩阵分配在应用进程中；不同于 HEAD `.hdf` | 源码确认暴露面，原生崩溃 UNKNOWN / P1 |
| 音视频 | `av.open/decode` 在应用进程；全部 frame 累积后 concatenate。无总解码量预算；现有通道数/长度 `min` 路径可能截掉数据，应补不一致输入证明 | 源码风险，原生崩溃 UNKNOWN / P1 |
| TDMS | `TdmsFile.read` 先全量物化，再校验每通道时间。已有局部通道跳过与时间诊断，不解决读入过程的资源消耗 | 源码风险，无同类崩溃证据 / P1 资源 |
| ZFD | 测量负载有 remaining-byte 校验；时间 count 为隐式生成，不受负载字节约束；先建轴再发现所有测量 count 不符 | 安全分配探针确认 / P0 |
| WWT | 样本负载有边界校验；Zeit 无 payload，有 50,000,000 点单轴上限，但整文件、多个轴、换算与副本没有统一总预算 | 源码风险，未复现原生越界 / P1 资源 |
| HEAD HDF | 有有界头部、扫描数×槽位×字宽与文件剩余长度校验，先拒绝截断再建时间轴；正常大数据仍可能产生高峰值 | 已有保护应复用，非 HDF5 / P2 兼容 |
| CSV / ASCII | `read_bytes()[:limit]` 并非有界读取；固定宽度读取还为拿表头执行 `read_text().splitlines()`。无时间/NaN 规则已有合同，不能倒退 | 头探测缺口已确认 / P0 |
| Excel | `pd.read_excel` 全量物化；XLSX ZIP 文件大小不代表展开大小。没有证据说明它有 MDF 数组步长缺陷 | 源码资源风险 / P1 资源 |
| BLF / CANoe ASC | BLF 保留所有帧；ASC 已有有界预检、协作取消和 fallback 诊断，解码后使用 lazy ZOH。底层读取、解压、帧列表仍需预算 | 源码风险 / P1 资源；保护既有 lazy 行为 |

当前 GUI [ProjectIOMixin](../../../mf4_analyzer/ui/main_window/_project_io_mixin.py) `_open_data_paths:538` / `_load_one_impl:1044` 同步读取；大文件确认仅以磁盘字节估时。12 MB MF4 导入后的表格约 200 MB，112 字节 ZFD 甚至能请求 16 GiB：磁盘大小不能作为内存安全判据。

当前代码定位：`io/csv_format.py:53`、`io/ascii_format.py:26` 是全文件探测读取；`io/zfd_format.py:375` 是时间轴分配，`load_zfd_groups` 在筛选 usable 前调用；`io/loader.py:782/1047/1359` 分别是 TDMS/媒体/Excel 读取；`io/mat_format.py:99` 是 HDF5 数据集物化；`io/wwt_document.py:675` 与 `io/head_hdf.py:596` 为另外两个二进制格式入口。以上相对 `mf4_analyzer/`，行号对应本次基线。

## 4. 不可退化的产品合同

沿用 [已有导入容错 Plan](2026-11-02-import-recovery-and-diagnostics-plan.md) 与 [ZFD 合同补充](../specs/2026-11-02-zfd-partial-import-addendum.md)，以当前实现和新回归为准：

1. 源文件只读。复合 source/group/channel 身份、Time 精确列身份、单位、有效值、样本顺序、原始缺口、同名消歧、组顺序及用户采样率意图不变。数组元素身份须可追溯到原父通道与坐标，不能靠短名重新配对。
2. 只有结构/时间/身份可证明的局部问题才跳过，并明确 partial；截断、无法确认边界、运行时崩溃、取消、超预算不能返回“成功的已读前缀”。先前已打开的其他文件保留。
3. 沿用 `source_metadata.import_diagnostics` 的 complete/warning/partial 与缺失诊断 UNKNOWN；失败、取消、超时属于任务终态，不硬塞进只支持成功导入状态的 schema 1。不要为失败注册空来源。
4. 上游为了内存安全而补零，不能被产品当成有效测量。边界/数组语义不可信时读前拒绝该记录或文件，保留具体原因。
5. 不把异常时间轴排序、插值或默认 1 kHz 修成“可打开”；不全局禁用数组后静默丢通道；不通过调整最长参考轴规则让样本通过。本轮不重做多采样率模型。
6. 全局 exception hook 仍负责日志；原生崩溃应由父进程根据子进程退出状态报告。一次文件失败只产生一个终态、一次聚合反馈。

## 5. 技术方案与阶段

按 T0→T1/T2→T3→T4→T5 执行。T1、T2 可独立开展，但本计划不要求启动并行 agent；共享合同与最终集成始终只有一个 owner。

### T0：固定证据与正常行为

Owner：本地 `.state/` 探针与 `tests/_helpers/mf4_factory.py`、`tests/zfd_fixtures.py` 的匿名 fixture。

- 将 §2 的矩阵与独立数值 oracle 变成可移植回归：行优先、逆布局、1D/矩形/3D、整数/浮点、1 点与多点、空组、结构/轴依赖、压缩/多数据块。独立预期不能调用待测 `_factors`。
- 旧版本错误只在受监督的子进程内复现；主 pytest 不直接调用已知危险 C 读取，不以 xfail 吞掉修复回归。无越界但错值的用例必须存在。
- ZFD 巨大 count 用 allocation spy 证明“失败早于分配”；大内存测试用低预算注入和稀疏/小样本，不故意耗尽开发机内存。
- 正常基线只跑相关 owner：`tests/test_mf4_loader.py`、`tests/test_source_adapters.py`、`tests/test_zfd_format.py`、`tests/test_csv_format_sniff.py`、`tests/test_ascii_loader.py`。记录数组、metadata、来源 ID；不跑全套 baseline。
- Gate：真实附件 hash、回归失败原因与正常参考值可复查；先把 8.8.32 不通过的事实保留，不能升级后覆盖旧证据。

### T1 / P0：修复 MF4 数值与原生读取边界

Owner：新增中立 `io/mdf_reader.py` 作为 MDF 打开/元数据/安全读取 owner；`loader.py` 保留公开 API 与 monkeypatch seam；`source_adapters.py::_probe_mdf` 共用此 owner。依赖声明与 Windows 打包使用同一受控版本来源。

- **默认修复路线**：采用包含上述数组步长与各 C 读取路径修复、经测试的固定依赖产物。当前已测官方 8.8.32 不合格：实施时以固定源版本回移上游修复，构建可复现 wheel，保留补丁、源提交、平台/Python ABI、wheel SHA-256 和许可证；不直接修改开发机 site-packages，不跟随 floating development 分支。
- 若届时有正式发布物，通过相同源码核对和数值门禁后可替代维护 wheel；“版本号较新”不构成替代依据。Full/Lite、开发运行与冻结 EXE 必须记录实际加载的 Python 模块及 C 扩展路径/哈希，不能只升级 Python 文件留下旧 `.so/.pyd`。
- 数组创建/读取前验证维度、方向、步长、基址、元素宽度与元素数量；既校验记录外访问，也校验记录内错位。负数、乘积溢出、展开数量超预算在循环/分配前终止。
- 对固定记录验证位宽与可访问区间、实际块覆盖；对 VLSD、虚拟通道、结构、失效位和其他布局走各自已知合同，不能套用一个简单 `offset+bit_count/8` 规则误拒绝合法通道。尚不支持的布局显式 unsupported，不猜布局后调用 C。
- 未验证/存在已知缺陷的运行时不得展开危险数组。必要的兼容模式只能显式报告数组未导入并保留安全标量；它不算“完整数组支持”门禁通过，也不能绕过失败后在主进程重读。
- metadata probe 使用相同数组政策、物理身份和预算，但不为验证而全量读取数据。目录可列举与 payload 完整性分开表示；probe 发现 unsupported 与正式读取保持一致。
- Focused：`tests/test_mf4_loader.py`、`tests/test_source_adapters.py`、`tests/test_acquisition_capture_backends.py`、`tests/test_p0_mf4_probe.py`、`tests/ui/test_mdf_open.py`、`tests/ui/test_mf4_import_flow.py`；新增 `tests/test_mdf_reader_safety.py`（拟）。写入器回读用 `tests/test_acquisition_capture_writer.py`。
- Gate：矩阵全部元素逐点正确，数组名/身份/单位保持；危险偏移从未传入 C；用户样本得到原定 52 个信号和相同时间轴，且原有 skip/alignment 事实仍可查看。此时仅完成已知缺陷修复，不能宣称未知解析崩溃已隔离。

### T2 / P0–P1：读取与分配前的有界检查

Owner：各 `io/` 格式模块；新增小型中立 `io/import_limits.py`（拟）只计算预算与报告资源限制，不承接所有解析逻辑。

- CSV/ASCII：使用有界 `read(65536)` / `read(262144)`；处理 UTF-8/UTF-16 截在字符中间时的合法前缀，保留编码证据。固定宽度表头/单位行按行有界读取，不再整文件读两遍。探测不能迭代到无界长行之后才检查长度。
- ZFD：全文件声明记录结构验证完成后，先筛出满足既有 count/X 合同的可用测量，再分配公共时间轴；没有可用测量直接失败。检查 count、t0、dt、预计末点与总分配量；数学预检不能替代生成后严格递增检查。保留真实截断整文件失败和局部完整通道跳过规则。
- WWT：保留 `_MAX_ZEIT_SAMPLES`；增加累计 Zeit、测量换算、公式输出与分组副本预算。Zeit 无 payload，不能依靠文件大小限制点数。HEAD HDF 复用现有记录/文件边界校验，再估算 float64 转换与时间轴副本。
- MAT：读取可用的 shape/dtype 元数据后先判定支持与预算，再物化；v7.3 非数值/对象引用不先 `np.asarray`。v4/v5 元数据扫描本身也可能进入原生库，仍由 T3 隔离，不能声称预检绝对安全。
- TDMS、Excel、媒体、BLF/ASC：在可用 metadata/块/帧入口估计并累计展开量；读入、解压、float 转换、共享时间轴扩张、DataFrame、concat、父子结果交接同时计入峰值。无法估算记 unknown，在子进程中监督实际消耗，不能按零估算。
- 资源策略由一个 owner 管理：单任务内存预算、应用全部导入任务总预算、临时磁盘预算、通道/元素总量与诊断条目上限。采用 Python 安全整数作乘积，转换到底层有符号尺寸前再校验。初始并发为 1 个解析任务；BudgetExceeded 与损坏/不支持分开报告，不裁剪数据以满足预算。
- 默认预算在 T2 的首个实现提交中冻结为有单位、可测试的配置：依据基线机可用内存及正常大小语料峰值，保留 GUI 与已加载数据余量；同时记录取值理由和最差复制系数。**未给出具体默认值、极值测试和界面错误反馈前，本阶段不得算完成。** 不把固定磁盘大小或 ZIP 压缩比当唯一拒绝条件。
- 媒体解码补通道数/长度不一致的确定性探针；若确认触达现有 `min` 截断路径，改为基于明确解码合同的处理或显式失败，不能靠裁短保持“成功”。正常 mono/stereo/多通道 PCM 数值与长度必须完全一致；不顺带改变单位或声学参考值。
- 原生库内部可能一次分配，RSS 轮询不能提供硬隔离保证。Windows/Linux 如采用 OS 进程资源限制，必须单独实测；macOS 使用的限制若不能证明生效，明确标为估计/监测保护。禁止声称系统级 OOM 已被绝对消除。
- Focused：各自 `test_csv_format_sniff`、`test_ascii_loader`、`test_zfd_format`、`test_wwt_document`、`test_head_hdf_loader`、`test_head_hdf_timebase`、`test_mat_format`、`test_tdms_loader`、`test_excel_loader`、`test_audio_loader`、`test_blf_loader`、`test_asc_can_loader`；新增 `tests/test_import_limits.py`（拟）。按本次改到的 owner 分组执行，不一次运行所有 UI。
- Gate：头探测实际读取量有上界；112 字节 ZFD 在 `np.arange` 前拒绝；合法小时级 ZFD 和普通大文件不因经验点数阈值被错误拒绝；预算边界前后 1 字节/1 点测试确定；资源失败无成功前缀。

### T3 / P1：完整读取在子进程内完成

Owner：中立 `io/import_process.py`、`io/import_worker.py`、`io/import_transport.py`（均拟），入口脚本 hidden mode、adapter 接缝与冻结依赖合同。借鉴现有 A2L/extension probe 的退出回收与 windowed 约束，不把扩展安装/授权状态机搬进导入。

- 先接 MF4/MDF，稳定后接 MAT 与音视频；隔离从 import/open 开始，到实际读取、转换、诊断结果完成。不能先在子进程 smoke 成功，再在 GUI 内重新解析同一文件；QThread 只可监督子进程，不能用来隔离原生解析。
- 父进程负责请求 ID、来源快照、预算、取消、进程回收；子进程负责解析。客户端同步 API 为 Batch/Replay 保留返回形状；GUI 使用异步结果，不在主线程 `wait/communicate/join`。子进程调用内部 in-process 实现，禁止递归启动子进程。
- 隐藏 `--import-worker-request`（拟）加入现有 `allow_abbrev=False` 互斥组，在创建 QApplication/主窗口前路由。冻结构建调用同包 EXE；无 stdout/stderr 时仍通过有界协议/结果文件和退出码工作；复用当前扩展环境快照，使 Full/Lite 的 MAT/媒体依赖可见性不漂移。
- 数据传输采用每任务私有临时目录：小型 versioned JSON manifest + 数值数组文件，`allow_pickle=False`；原子发布完成 manifest。父端检查 request ID、源文件前后快照、shape/dtype/字节数、路径范围与总预算后才接收。禁止传递 Qt 对象、MDF/HDF5 handle、任意 pickle 或完整数组 JSON。
- 大数组通过数值文件交接。原计划采用持久只读 mmap；实施取舍改为总量预算内的独立数组，并强制输出不超过内存预算一半、计入重建副本（原因及代价见第 8 节）。本期不将映射句柄生命周期扩展到全部 FileData/WWT 消费者，不宣称零复制。结果脱离临时目录后立即清理本任务文件，不扫描删除其他会话文件。临时盘满、无写权限、残缺 manifest、worker 正常退出但缺少结果均为失败；Windows 原生删除/占用验收仍独立保留。
- 进程存活心跳与实际解析进度分开。无可测进度时显示阶段和耗时，不编百分比。取消协作宽限目标 2 秒，随后 terminate/kill 并确认回收；取消只终止自己创建的进程树。最大任务时长纳入显式可配置 policy，GUI 长任务可明确延长，Batch 无人值守按请求预算终止；不得无限等候或静默循环重试。
- 故障终态区分 data_error / dependency_error / native_crash / resource_limit / timeout / cancelled / internal_error。记录最后阶段、格式、库版本、退出码、请求 ID、有限堆栈；编程错误保留 traceback，不包装成“损坏文件”。崩溃后不复用受损 worker，不自动在父进程重读或连续重试。
- Focused：新增 `tests/test_import_process.py` / `test_import_transport.py`（拟）：子进程非零退出、模拟 abort、无响应、超时、取消完成竞争、磁盘满、坏结果、迟到结果、资源预算、退出后无遗留进程。异常注入必须只发生在子进程；普通 loader 的错误分类测试保持。
- Boundary：`tests/test_native_import_boundaries.py`、`tests/test_signal_no_gui_import.py`、`tests/test_packaging_imports.py`、`tests/test_importer_runtime_smoke.py`、`tests/test_windows_build_script.py`。扩展 probe/hidden-mode 受影响时补对应既有测试，不用 import 成功代替真实文件解析。
- Gate：任意被监督的 worker 崩溃后父进程仍能读取下一正常文件；捕获一次 probe 崩溃不等于全部导入入口已隔离，须逐入口核对。

### T4 / P1：GUI 生命周期、其他格式与各消费者闭环

Owner：新增 `ui/main_window/import_coordinator.py`（拟），`_project_io_mixin.py` 只作入口/提交协调；`source_adapters.py`、Batch 与 Replay 接缝；既有诊断 UI 与帮助。

- 将 `_open_data_paths`、项目恢复、最近文件、拖入与 Replay GUI 接到同一任务 owner。Batch 通过同一中立 broker 同步等待，其 UI 线程仍不阻塞；进度/条目结果继续归 `_RunReporter`。用户取消整个 Batch 与单个坏源失败必须区别。
- 不能只将 `_load_one_impl` 替换成提交任务：现有 `_load_one` 的 `finally` 会立即调用 `_on_source_load_finished`，`_restore_project_file_refs` 也会立即通过 files 差集做匹配。新增明确异步入口并迁移这些调用者，成功提交后才执行一次 attach/恢复后续步骤；不得用嵌套 Qt event loop 等待，或在旧同步返回合同里偷偷返回 Future。
- MF4/MAT/媒体首先异步提交；随后按格式分批把 CSV/ASCII/Excel/TDMS/WWT/ZFD/HEAD HDF/BLF/ASC 接入相同监督流程。每种格式必须完成数据传输 round-trip gate 后才启用。不能先统一成一个 pandas 大表：BLF/ASC 保留 ChannelFrame 的逐通道/lazy ZOH 结构；WWT 传输记录目录、公式/布局、原 record_index 与共享数组引用；多组源保留 source/group 身份。
- 解析结果先验证全部逻辑组，再在 GUI 线程提交 FileData、navigator 与 View attach；失败不得留下半个新文件或修改其他文件。既有 WWT 布局选择在解析完成后继续，由 `wwt_import_coordinator` 负责，不能为了异步绕过选择/拒绝布局路径。
- `_register_file_data:819` 当前同时修改 files、navigator、缓存、Inspector 和项目 dirty 状态；实施时分离准备与提交，仅为本请求保留可回滚的注册变更。注入第二逻辑组构造失败、navigator 注册失败两种异常，证明第一组也不会残留，且不回滚用户在等待期间对旧文件的编辑。项目恢复失败保持已有缺失来源反馈与身份核验，不把未返回的异步结果误记为永久缺失。
- 启动时捕获目标 `(section, view_id, pane_index)` 和 session generation。期间允许普通浏览；目标 View 删除、项目切换或关闭窗口使相应请求失效。不得把迟到结果附到完成时碰巧激活的 View。项目恢复按既有顺序重建 group、用户采样率、channel edits，完成一次提交后再触发后续恢复。
- 取消/崩溃/超时不新增最近文件，不触发成功 toast，不刷新已有结果；已成功打开的其他文件与用户操作保留。超时/失败可由用户明确重试，新的请求使用新的 worker 与 ID。
- `导入详情` 继续显示成功来源的 warning/partial；失败没有来源卡时保留可查看的本次失败摘要/日志定位。提示用户能采取的行动，不把技术堆栈塞进普通工作流。新增取消/失败入口同步 `ui/hints.py`、`ui/quickref.py` 与用户指南。
- Focused：`tests/ui/test_load_progress_and_heavy_confirm.py`、`tests/ui/test_drop_import.py`、`tests/ui/test_mf4_import_flow.py`、`tests/ui/test_import_diagnostics.py`、`tests/ui/test_project_session.py`、`tests/ui/test_wwt_import_flow.py`；新增 `tests/ui/test_import_coordinator.py`（拟）；Batch 用 `tests/test_batch_loader_dispatch.py`、`tests/test_source_adapters.py`、`tests/test_batch_manifest.py`、`tests/test_batch_run_reporter.py`，Replay 用既有 capture backend 测试及对应 UI 用例。
- Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`；只有引入/改变控件样式时增加 QSS/几何门禁。
- Gate：主线程 100 ms 心跳在慢解析/worker 故障时持续；测试负载下最大间隙目标 <500 ms，最终注册阶段也单独计时。取消后 3 秒内完成退出与请求清理（系统调度异常单独记录）。切 View、删除目标、关窗、换项目、批量好坏混合、恢复期间失败均无误附、双终态、僵尸进程和结果污染。原生前台实测与 offscreen 分开。

### T5 / P1：集成与平台交付

- 数值 gate：完整数组 oracle、用户样本、正常 MDF3、单位转换/别名/Time 同名、重复时间/回退、分组与导入 diagnostics 通过。数组 identity 不能因依赖升级漂移；如发现无法保持，先写明迁移合同，不直接保存新身份覆盖旧项目。
- 全格式合同 gate：每个支持格式至少正常、小型坏文件、超预算、取消/worker 退出、再次打开正常文件五条路径；缺口、未知采样率与部分导入不退化。多格式接入各自完成后才勾选，不用 MF4 成功代表全部完成。
- 真实 Cocoa：原文件打开、绘图、取消慢文件、坏文件后继续打开、项目恢复与关窗；记录耗时/RSS/临时磁盘/心跳和源 hash。0.15 秒为此前纯 loader 诊断值，不能当包含子进程启动、交接和 GUI 注册的 SLA。
- 新鲜 Windows Full 与 Lite **默认 windowed 冻结 EXE**：验证实际库与 C 扩展哈希、含空格/中文/UNC 路径、无控制台、子进程互斥路由、正常/异常 MF4、资源拒绝、取消和后续正常打开。MAT/媒体在相应依赖可用时完成，组件不可用时给出正确状态。源码测试/console build 不能替代。
- 因 T3/T4 跨 IO/UI/Batch/冻结入口，最终稳定集成里程碑允许一次全套：先查运行 pytest 与 cwd；主套 `--ignore=tests/acquisition_ui` 完成后，另启进程跑 `tests/acquisition_ui`，两者不得并发。记录前后 HEAD/相关 dirty 文件指纹；期间源变更、崩溃或中断记 UNVERIFIED。不为 T0/T1 单独重复跑全套。
- 任一平台未测写 UNKNOWN；仅 T1/T2 完成时可称“已知缺陷与分配保护完成”，不能称“跨格式崩溃隔离完成”。

## 6. 验收清单与非目标

| 验收项 | 必须达到 | 负责阶段 |
| --- | --- | --- |
| R1 数值正确 | 矩形/三维/逆布局每个元素与独立 oracle 一致，包含不会崩溃的错值样本 | T1 |
| R2 边界正确 | 危险偏移在 C 调用前拒绝，原生扩展本身也有保护；补零不是成功数据 | T1 |
| R3 分配有界 | ZFD 巨大隐式轴读前拒绝；CSV/ASCII 头探测不读全文件；累计预算可测 | T2 |
| R4 故障隔离 | 解析从 import 到结果全部在受监督 worker；崩溃不带走应用，无父进程重读 | T3/T4 |
| R5 可操作 | 解析期间 GUI 心跳、取消、关窗、View/session 身份与迟到结果合同通过 | T4 |
| R6 数据保真 | 单位/时间/缺口/复合身份/数组元素/多组/WWT 文档/lazy CAN 不退化 | T1–T4 |
| R7 结果原子 | 坏文件、资源拒绝与取消无半注册来源；其他已打开文件保持；Batch 单次终态 | T3/T4 |
| R8 可诊断 | 退出码/阶段/运行时版本/资源事实可定位，用户提示区分损坏、超预算与库崩溃 | T3/T4 |
| R9 可交付 | 固定依赖及 native wheel 可复现；Cocoa、Windows Full/Lite 证据独立齐备 | T5 |

不以这些做法代替完成：增加宽泛异常捕获、只换线程、无限 `processEvents`、忽略所有数组、错误样本补零、删除用户数据、只测方阵、只测 metadata probe、仅升级一个开发机环境，或仅以“不崩溃”验收。

## 7. 本次文档交付与后续记录

首次分析交付时仅新增本计划；诊断脚本、匿名样本与候选包检查留在 `.state/`，当时原产品/测试/依赖声明未修改，因此未执行 runtime suite。分析探针不替代实施红绿测试。该次文档检查包括全文审读、现有/拟新增 owner 区分、相对链接与测试路径、范围和状态一致性、`git diff --check`。用户随后授权的实施另记于第 8 节。

实施证据按 T0–T5 分阶段追加到独立验收记录；本计划中的未来验收不能改成已通过而没有命令/数值/平台证据。已存在的 native-process、分配前边界和 partial-import lessons 继续适用；真正实施新增回归后按项目 lessons 流程归档本次“无越界仍错值”及“隐式轴不受文件体积限制”的经验。

## 8. 授权后的实施记录（2026-11-17）

用户已授权安排 agent 同步执行。四条工作线分别负责 MDF 数值/原生依赖、跨格式资源准入、传输/消费者、GUI 生命周期；协调者负责进程监督、Batch 取消、集成及唯一全套门禁。现有工作区改动先记录指纹，未提交或推送。

- T1：固定 `asammdf==8.8.32+tracelab.1`，源包、补丁和构建依赖有哈希锁；公开 8.8.32 的 C 修复与缺失的 Python 步长修复一起进入产物。共享项目环境已安装这个 wheel。原样本 800 个元素已与独立原始字节 oracle 核对；正式 broker 得到 471652×53，时间轴 SHA256 与 oracle 一致，约 0.86 秒。完整元数据与被跳过通道保留，不能将 52 信号称为全变量无损导入。
- T2：前缀读取、ZFD、MAT、WWT、HEAD 准入已完成 focused 检查；CSV/ASCII 完整解析、TDMS、Excel、媒体及 CAN 的增量预算与实际子进程往返也已纳入。112 字节 ZFD 拒绝前没有调用 `arange`。
- T3：实际解析在一次性子进程中完成；带 request ID 的 JSON + 数值 sidecar 完成后原子发布。崩溃、超时、取消、源文件变化及失败后再次成功读取已有真实子进程测试。数据交接采用**有总量预算的独立数组**，而非持久 mmap：避免将 Windows 映射句柄生命周期扩展到 FileData/WWT 的所有消费者；输出预算最多为本次内存预算的一半，传输统计含 DataFrame 构造副本。不是零拷贝或 OS 硬内存沙箱；持续大文件后可在不变协议上另做 mmap 生命周期优化。
- T4：普通打开、项目恢复和回放改用显式异步 continuation；批处理同步消费者共用 broker，并将本次 run 的取消状态限制在调用上下文。GUI 注册/回滚、目标 View、关闭竞态及 BatchSheet DBC 异步入口的 focused 检查已完成；最终 Cocoa 已实测原样本、取消、崩溃后恢复、超时延长和项目恢复。全套稳定集成仍单独记录。
- 构建：Windows Full/Lite/Modular 已在安装 requirements 前接入固定 wheel 构建，并保留修改后的源归档与 manifest；隐藏 worker 模式在 GUI 初始化前路由。Windows 原生编译与新鲜 windowed EXE 尚未验证。

默认准入取估计可用内存的四分之一，上限 2 GiB；无法估计时为 512 MiB，输出上限为其一半。任务时限默认 1800 秒，协作取消宽限 2 秒。它们是集中于 `ImportLimits` 的资源策略，不是对文件格式或机器承载能力的保证。直接 broker 调用可传入策略；GUI 超时后只有明确选择「延长并重试」才将本次时限加倍、重新创建 worker，取消不重试。该交互有 focused 测试，不将超时错误当作文件损坏。

收尾补齐 QApplication 监督对象的弱宿主引用，以及 BatchSheet DBC 读取中关闭最后窗口时的异步回收等待；不在 GUI 线程阻塞等待。收尾 owner、进程退出、dirty guard、状态归属与两条旧断言的组合检查为 54 passed。

完整主套验证耗时超出合理范围；用户指出反复修改/测试后，协调者在第二轮约 78% 主动终止。该轮运行约 78.5 分钟，源码前后指纹一致，退出码 -15，结果为 UNVERIFIED；随后 acquisition_ui 未启动。仅完成既定收尾补丁的针对性检查及 Cocoa 实测，不再启动第三轮全套。不得以已完成的前缀或 focused 结果替代全套通过。

全格式真实子进程覆盖正常、坏文件、输出超预算和正常重试；取消/崩溃/超时使用共用监督层故障注入证据，没有逐格式重复注入。T5 原列逐格式五路径矩阵并未全部执行，保持部分完成。

阶段结果与剩余门禁记录于 [实施验收记录](../verify/2026-11-17-import-robustness-implementation.md)。Cocoa、offscreen、源级冻结合同及 Windows frozen 结果分别列示；未提交、推送或发布。
