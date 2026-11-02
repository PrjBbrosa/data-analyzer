# 文件导入容错与异常提示优化 Plan

日期：2026-11-02

状态：**本轮功能实施及定向/Cocoa 验收完成；整仓回归未通过，不作为发布绿灯**。用户已于本会话明确授权安排 agent 执行。最终范围与限制见第 8 节及[验收记录](../verify/2026-11-03-import-recovery-verification.md)。

执行方式：主 agent 负责共享诊断合同、计算输入保护、Batch 与最终集成；三个 agent 分别负责 WWT/ZFD、表格/TDMS、GUI/恢复/帮助。文件所有权分离；只有主 agent 执行全套门禁。本文不包含提交、推送或发布。

## 1. 目标与完成边界

目标：当文件中存在可隔离的异常时，打开可验证的有效数据，并明确告知异常和影响；不能为了“能打开”制造时间轴、错配通道、补齐损坏数据，或让部分导入看起来是完整导入。

首先解决 `NLTNP_72deg.wwt` 的空时间轴阻断问题，再统一诊断传递，处理 CSV/Excel、TDMS 和窄范围 ZFD 部分导入。MF4、MAT、HEAD HDF、CANoe ASC 作为兼容性检查对象，不在本轮重写它们的读取策略。

不包含：通用损坏文件抢救器、未知二进制格式扫描器、ZFD 新记录类型/多时间轴支持、BLF/音视频截断恢复、DSP 算法重设计、导出格式改造、全应用异常捕获重构、版本发布。读取原文件始终只读。

“打开数据”与“所选数据可以计算”是两个独立结论：含缺口的通道可以查看，但计算窗口不满足有限值、长度或时间要求时，应由计算入口明确拒绝该任务，不能拒绝整份文件，也不能偷偷补值继续算。

## 2. 实施前证据与基线

代码基线：`b1fc5753b3806ca80e23aeca9f2d2ce02d990971`，另有与本任务无关的未提交修改；HEAD 不能代替工作区指纹。以下为实施前的读取、探针和测试记录，不代表修复后状态；最终结果见第 8 节。

| 项目 | 已确认事实 | 证据类别 |
| --- | --- | --- |
| 用户 WWT | 584,595 字节，11 条记录；第 6 条、偏移 `0x3109d` 是 `Zeit / Time / n=0`；其后立即出现有效 Zeit | 原文件字节与顺序解析 |
| 原文件复现 | 实施前读取器在 `parse_wwt_document` 的 `0 < n` 检查处失败，与截图相同 | 当前代码实际调用 |
| 内存诊断 | 仅在独立内存函数中允许零点 Zeit 后，可解析 11 条记录、1 个显示窗口、5 个测量通道；每通道 24,941 点，0～24.94 s | 诊断探针；不是已修复产品或前台验收 |
| TDMS | 一个正常定时通道与一个缺失时间元数据的通道共存时，整个文件失败 | 合成文件实际调用 |
| ZFD | 8 点时间轴、8 点正常通道、5 点短通道共存时，整个文件失败 | 合成文件实际调用；符合现有严格合同 |
| CSV | 信号或 Time 列中的 `broken` 被转为空值并插值，未生成诊断元数据 | 合成文件实际调用 |
| Excel | `to_numeric` 后统一 `interpolate/ffill/bfill`，未返回相应诊断 | 源码检查，尚无本次真实 Excel 探针 |
| 定向测试 | 上述相关既有用例 `8 passed in 0.78s` | 上一轮分析结果，不替代新增红测 |

原文件：`/Users/donghang/Desktop/666#/NLTNP_72deg.wwt`。SHA-256：`fb99e8fd8b23348ca7c3a04327bc569b3045b10f15d2d618a1e91fbcac052a2d`。不把客户二进制纳入 Git；路径不存在时现场验收记 `UNKNOWN`，可移植核心测试仍必须通过。

关键 owner：

- `mf4_analyzer/io/wwt_document.py::parse_wwt_document/load_wwt_document` 与 `wwt_format.py::_looks_like_record_header`：顺序读取与重同步共同影响记录编号、空 Zeit 和后续引用。
- `mf4_analyzer/io/loader.py::DataLoader.load_tdms/load_csv/_load_csv_with_layout/load_excel/load_ascii`：时间信息、表格清洗与返回元数据。
- `mf4_analyzer/io/zfd_format.py::load_zfd_groups/_read_record`：结构与时间引用校验。
- `mf4_analyzer/io/file_data.py::FileData`：时间列绑定及既有默认采样率路径；不能让异常 Time 列被清洗掉后进入默认 1 kHz 路径。
- `mf4_analyzer/ui/main_window/_project_io_mixin.py::_load_one_impl/_toast_io_load_diagnostics/_consume_wwt_import_outcome`：注册及加载反馈。
- `mf4_analyzer/io/source_adapters.py`、`mf4_analyzer/batch.py::_loader_source_diagnostic/_merge_source_diagnostic`：GUI 外调用及 Batch 结果传递。目前通用 Batch 收集主要消费 `warnings/mf4_alignment`，WWT 文档级诊断不能假定已传播。

## 3. 行为与验收合同

本节是本轮实施与验收的目标合同，实际完成证据及剩余限制见第 8 节。

### 3.1 四种导入结果

| 状态 | 条件 | 用户行为与数据约束 |
| --- | --- | --- |
| `complete` | 支持范围内的数据完整可解释，无异常 | 正常加载 |
| `warning` | 有非关键异常，测量通道和测量点未因此丢失 | 加载并提示，例如空占位记录或显示布局降级 |
| `partial` | 至少一个可靠通道保留，但存在通道遗漏或样本缺口 | 加载并明确“部分导入”，列出遗漏/缺口及原因 |
| `failed` | 无可用通道，或结构/时间解释不可信 | 不注册该文件的新来源；保留已打开的其他来源；显示具体错误 |

有意排除的非数值说明变量不一概算测量数据丢失；保留现有兼容提示。状态按实际影响归类，不能仅按是否出现 warning 字符串决定。复合异常取最高影响等级，`failed` 不得返回“成功的空组”。

必须保留的硬失败：无法识别文件头；记录头/负载截断；未知记录无法确认下一边界；关键时间轴无效或单位无法解释；内存/依赖/IO 失败导致结果不完整。编程错误不能被当成可跳过的数据异常；不增加宽泛 `except Exception: continue`。

### 3.2 WWT 空记录与身份

1. 顺序解析到完整、已知结构的 `Zeit(n=0)` 时，保留一条零长度记录，记录 `empty_time_record` 诊断；不生成测量来源、不补造采样点。
2. 空 Zeit 必须形成明确的所属关系边界；后续数据不能继续沿用前一个有效 Zeit。后面遇到新的有效 Zeit 后恢复正常归属。若空 Zeit 下出现非空数据且没有可信轴，只将该部分标为不可导入，不能借用别组时间轴。
3. 记录目录中的物理序号保持不变，公式 `kN` 和显示 X/Y 引用不得整体前移。引用空记录的曲线/公式局部降级并说明原因，不影响其他曲线。
4. 不把 `_looks_like_record_header` 的点数下限无条件放宽为零。重同步中的零 Zeit 候选必须有完整字段和后继边界证据；对含伪 `Zeit` 字节的负载做负例。无法确认时保留明确失败，不能伪造“已完整导入”。
5. 超大 Zeit 分配上限、负载越界、真实截断仍拒绝；不得借本次修复放开内存保护。
6. 用户样本目标：5 个测量通道、各 24,941 点、0～24.94 s；空记录编号不变；普通初始 View 的有效 X/Y 绑定不变。

### 3.3 CSV / Excel / 表格 ASCII

1. 清洗前区分时间列与信号列，保留精确列身份；有效数值输入的值、顺序、单位、时间起点不变。
2. 禁止自动插值、前后填充时间列；不能丢弃无效时间列后回落为默认 1 kHz。多点时间轴必须有限且严格递增；重复/回退时间不能靠排序或去重消除，明确报错。无法建立可信时间轴时明确失败。本轮不增加坏时间轴修复向导或手工猜采样率功能。
3. 信号列中的局部空值、不可解析值按缺口保留为 NaN，保留全部行与可信时间坐标，并报告列、数量和有限数量的原始行号；不自动插值、补零、ffill/bfill，也不因另一列缺值删除整行。
4. 整列无有效数值的信号跳过并提示；全部信号不可用则失败。Inf 不替换成有效测量值；明确记为非有限样本并走同一显示/计算验证。
5. 对没有时间列且未提供可信采样元数据的表格，不能静默生成秒数。实施前核实既有显式设置采样率入口；有明确用户设置时沿用该意图，否则报“无法确定时间轴”。这是有意收紧隐式时间生成，不改其他格式的全局默认行为。
6. 行列结构损坏（例如无法可靠识别分隔符、引号/列数异常）本轮明确失败，不使用 `on_bad_lines='skip'` 隐式丢行。正常标题行、单位行、BOM、编码、小数逗号兼容保持。
7. 改变信号清洗策略之前，验证现有时域绘图与各分析入口如何处理 NaN/Inf。必要修补限定为调用既有验证或增加窄输入拒绝，不重新设计 FFT/Order/FRF 数学；不能将“出现全 NaN 结果”视为成功。

### 3.4 TDMS

- 先依据原物理 group/channel 身份收集数值通道，再校验各自 waveform 元数据。缺失/无效 `wf_increment`、非法起点或时间数组溢出的通道局部跳过，记录原因；至少一个可靠通道存在才继续。
- 时间校验还需覆盖有限值、正间隔、生成后严格递增、样本长度匹配。共享参考轴只从可用通道中选择；保留现有同名消歧规则，诊断用物理身份而非短名去重。
- 全部无时间信息仍失败；不借另一个通道的采样率补齐。底层 TDMS 容器读取失败仍失败，本轮不恢复截断容器。
- 对本次保留通道的既有线性对齐算法不改公式；记录重采样与端点填充事实。无时间重叠通道跳过，避免整个通道成为端点常值；单点映射到多点轴不进行常值扩展。

### 3.5 ZFD：有限扩展，保留完整性底线

既有 [ZFD Spec](../specs/2026-09-09-zfd-long-record-robustness-spec.md) §4/§5/§8 要求整文件严格失败。执行本阶段前，新增当日合同补充文档，明确替代其中“边界完整但通道不兼容”的条款；旧文档的历史事实和原验收结果不重写。

拟允许的唯一局部恢复范围：所有声明记录的类型和字节边界均已确认完整，首条且唯一的 type 0 时间轴有效；部分 type 4 通道为零点、count 与时间轴不符或 X 引用不受支持时，跳过该通道，并保留其他 `X=0`、同 count 的完整通道。

- type 4 零点只在完整元数据及后继边界可确认时作为空通道处理；type 0 零点/非法 dt 仍失败。
- 负 count、负载截断、未知/type 1–3、多个时间轴、缺失时间轴仍失败。先完成全文件结构验证再返回部分结果，不提交任意已读前缀。
- 不裁剪长通道、不补齐短通道、不用另一条记录猜 X。无剩余有效测量通道仍失败。
- 保留完整通道的 32 位 count、非零 t0、真实末点、Fs 和记录身份。分别报告声明/解析/导入/跳过通道数。
- 部分导入时不能继续把 `measurement_records_complete=true` 当作全部测量已导入的证明。新增明确的结构完整性与数据覆盖字段；审查该旧字段的全部消费者后定义兼容语义，并在合同补充中写清。

## 4. 诊断与用户界面合同

### 4.1 数据所有权与兼容

沿用原 loader 返回形状与 `source_metadata`，不另建一套导入框架。可在中立 IO 层新增小型 `import_diagnostics.py`，仅负责校验、聚合与格式化跨格式诊断，不负责文件读取或 UI。

拟增加 `source_metadata['import_diagnostics']`，包含结构版本、导入状态、来源/组身份、准确计数和 issues。每条 issue 至少包含稳定 code、影响等级、实际处理动作、物理记录/列身份、原因；offset、原始行号、缺失点数等按格式选填。详细行号限量并保留总数，不能为百万行异常生成百万条 UI 文本。

- 旧 `warnings/skipped_channels/skipped_vars/renamed_channels` 保留兼容，通过同一归一化入口去重；真实记录身份不能被显示名合并。
- WWT 的文档级 diagnostics 在 load owner 映射到各组的来源元数据，保留文档本身；GUI、adapter、Batch 获得同一事实，文件级异常不要在每个组重复弹出。
- 无诊断字段的旧数据表示“未记录/UNKNOWN”，不能伪装成“已校验无异常”。字段不能带 QWidget、数组副本、计时器或进程缓存。
- 运行诊断属于本次读取事实，不写入 preset 或作为项目恢复的旧结论。恢复时重新读取生成诊断，保留原有用户设置；批处理结果可以归档本次诊断到 effective facts。

### 4.2 展示与生命周期

- 成功但有异常时，显示一次非阻断摘要，例如“已打开，5 个测量通道；发现 1 条空时间轴记录，测量数据未丢失”。部分导入必须使用“部分导入”措辞，不能同时显示无条件的绿色“全部成功”。
- 在文件卡提供“导入详情”入口，查看当前文件/逻辑来源的状态、异常列表、计数和影响；同物理文件的多组聚合展示，同时保留组身份。避免只依赖短暂 toast 或状态栏。
- 展示控件归 `ui/widgets/`，文件卡动作归 `file_navigator.py`；MainWindow 只做必要信号接线和数据传递，不增加跨 mixin 可变状态簇。窗口持有明确 Qt parent，文件关闭后不残留旧对象；不缓存已销毁 wrapper。
- 项目重新打开时重新生成详情；恢复过程可以合并摘要以避免弹窗风暴，但不能因 `_restoring_project` 而丢掉可查看的异常事实。
- 对无有效数据的文件保留错误反馈；列表中的其他已加载文件不受影响。批量打开时按文件聚合，个别失败不阻断其他文件。
- 同步 `ui/hints.py`、`ui/quickref.py` 及当前用户指南中的新入口、部分导入与缺口说明。

### 4.3 Batch

- 扩展现有 `_loader_source_diagnostic/_merge_source_diagnostic`，把归一化诊断纳入结果详情和 manifest effective facts；不写入 requested params 或复用缓存的身份键。
- 目标通道仍存在且数据满足分析条件时运行，结果保留导入 warning/partial 信息；目标通道被跳过、或所选区间不可计算时，返回现有明确的条目失败状态，不能换用同名其他来源。
- 分组、顺序执行、恢复执行共用 `_RunReporter`；不新增第二条进度或结果记录路径。相同 source 的重复引用不重复追加警告，FRF 两个输入均保留各自诊断。
- preview/probe 尚未真正读取时显示诊断未知，不能提前宣称文件完整。resume 不能凭旧“成功”覆盖本次已变化来源的异常。

## 5. 执行顺序、owner 与门禁

统一测试前缀：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`。新测试先红后绿；测试构造器使用匿名合成数据，不依赖客户文件可用性。

每阶段先跑本阶段 focused，再按 T6 的触及条件运行适用 boundary gate，不把边界验证全部拖到最后。相同源码指纹的通过结果可在 T6 复用；仅相关代码又变化、出现新失败或新增边界时重跑。

### T0：冻结输入、确认边界（只读）

- 记录 HEAD、工作区 owner 差异、pytest 进程及 cwd；不要覆盖当前版本/帮助/其他功能修改。证据放 `.state/import-recovery/`。
- 核实本文 owner 和测试路径；重现 WWT、TDMS、ZFD、CSV 探针，补真实 `.xlsx` 合成文件探针。
- 跟踪 CSV/Excel→FileData→时域/FFT/FFT-Time/Order/FRF 与 Batch 的时间身份和非有限值处理，列出 T3 需要的具体入口测试。若发现修复需要 DSP 算法变更，先修订本计划范围，不顺手扩大。
- 仅运行受影响 owner baseline：WWT document/format、TDMS、CSV header、Excel、ZFD 对应定向用例；不跑全套 baseline。
- Gate：每项可恢复异常都有边界证据与独立预期；未验证的 UI/平台状态写 UNKNOWN。

### T1：WWT 空 Zeit 修复与最小可见提示

Owner：`io/wwt_document.py`、`io/wwt_format.py`、必要的 `io/wwt_formula.py`、`ui/main_window/wwt_import_coordinator.py` 及其测试。保持 facade/import 兼容。

- 先补首部/中间/连续/尾部空 Zeit、空轴下数据、公式/显示引用空轴、全空文件与重同步伪候选红测，再按 §3.2 实施。
- 此阶段就必须使普通打开路径展示非阻断摘要，不能只放宽检查而无提示。读取数据而不导入布局时也必须提示。
- Focused：`tests/test_wwt_document.py`、`tests/test_wwt_format.py`；UI 选 `tests/ui/test_wwt_import_flow.py` 与 `tests/ui/test_wwt_initial_view_contract.py` 的相关用例，新增真实 loader→注册→诊断测试，不 mock 掉关键 seam。
- Gate：正常通道逐点一致、原记录编号及 X/Y 引用一致、空轴数据不挂错组；截断/超大声明仍失败。完成用户样本只读加载探针。

### T2：统一诊断、详情入口和各消费者

Owner：中立 IO 诊断 helper（如需新增）、`io/wwt_document.py`、`io/source_adapters.py`、`batch.py` 的诊断接缝、`ui/file_navigator.py`、`ui/widgets/` 新详情控件、`ui/main_window/_project_io_mixin.py` 与必要接线；帮助文件只改相关片段。

- 按 §4 接通完整路径，复用原 warning/skip 字段，支持旧来源无诊断字段。CSV/Excel 的三元组接口保持，诊断可经 DataFrame attrs 传递，但 GUI 必须像 MF4 一样实际提取，不能只改 adapter。
- 新增中立诊断 owner 测试和独立详情控件测试（拟 `tests/test_import_diagnostics.py`、`tests/ui/test_import_diagnostics.py`）。
- Focused：`tests/test_io_load_notices.py`、`tests/test_source_adapters.py`；`tests/ui/test_file_navigator.py`、`tests/ui/test_project_session.py` 的导入/恢复用例；`tests/test_batch_runner.py` 的 source-diagnostics 用例及新增 partial 用例、`tests/test_batch_manifest.py`、`tests/test_batch_run_reporter.py`。
- Gate：单文件/多组/多文件、只读数据、不接受布局、恢复、Batch、resume 均不漏报或重复报；未知诊断与空诊断可区分；旧项目能打开。

### T3：表格缺口与时间轴保护

Owner：`io/loader.py` 的 CSV/Excel/ASCII 入口，`io/csv_format.py` 仅在检测确有必要时修改；`FileData` 只允许针对这些已明确元数据的来源作窄适配。计算入口只补 T0 证明缺失的验证。

- 红测覆盖信号坏值、原有空值、Inf、全坏列、混合好坏列、坏 Time、时间回退/重复、无 Time、整行空白、短文件、原始行号和编码/单位行；先固定正常输入输出，再移除自动补值。
- 可信的非均匀时间保留原值并交给既有非均匀分析入口，不能在加载时平滑时间。一步丢行/补时间都不允许作为通过测试的手段。
- Focused：`tests/test_csv_header_loading.py`、`tests/test_csv_format_sniff.py`、`tests/test_excel_loader.py`、`tests/test_ascii_loader.py`、`tests/test_file_data_time_axis.py`、`tests/test_io_load_notices.py`。
- 数值消费者 Gate：`tests/test_analysis_time_axis.py`、`tests/test_nonuniform_fft_preflight.py`、`tests/test_batch_compute_time_axis.py`；在 T0 定位的 GUI/Batch 各分析 owner 中新增缺口输入用例，证明所选有限区间可计算，包含非法样本的区间明确失败、无静默全 NaN 结果。若新增计算验证修改 FRF，增加对应 FRF focused tests。
- Gate：有限原值逐点保持；长度/时间对齐不变；信号缺口显示为缺口；时间坏值从不变成插值秒数；正常表格兼容通过。只补提示而仍静默补时间不算完成。

### T4：TDMS 局部不可用通道隔离

Owner：`io/loader.py::load_tdms`、`tests/test_tdms_loader.py`；中立诊断 helper 仅扩充必要 code。

- 以“好 + 无时间”“好 + 非法 dt”“好 + 无重叠”“好 + 单点”“全部无时间”、重复名称/分组的合成文件固定行为。
- 先筛选可信通道，再选参考轴，记录既有对齐造成的重采样/端点填充；不猜时基、不让被跳过项污染 reference。
- Focused：`tests/test_tdms_loader.py`、source adapter 的 TDMS 用例、IO notices 与 GUI/Batch partial 集成用例；复用 `tests/test_mf4_loader.py` 相关时间对齐测试作差异检查，不直接复制 MF4 算法。
- Gate：有效通道存在即带诊断导入；全不可用明确失败；完整正常 TDMS 的输出保持；每个被跳过项可定位原 group/channel。

### T5：ZFD 窄范围部分导入

Owner：新增 ZFD 合同补充文档、`io/zfd_format.py`、`tests/test_zfd_format.py`、`tests/zfd_fixtures.py`；消费者按必要范围衔接。

- 先落实 §3.5 合同并将旧测试拆分为“完整结构下局部不兼容”和“结构/时间不可信”。不能直接删除原拒绝用例以获得绿测。
- 在完整解析后筛选；测试有效通道在异常通道前后两种顺序，尤其是前面已有有效通道但末记录截断，仍须整文件失败。
- Focused：`tests/test_zfd_format.py`、`tests/test_file_data_time_axis.py` 的 ZFD 用例、`tests/test_source_adapters.py` 的 ZFD 用例、IO notices、项目恢复与 Batch partial 集成用例。
- Gate：只有完整结构下可隔离的 type 4 异常被跳过；旧 65,535/65,536/65,537、大记录末点、非零 t0、单点、NaN/Inf 数据和真实截断保护均保持；metadata 对“结构完整”和“全部导入”的含义准确。

### T6：集成、前台与文档收口

- 核查新入口/状态在 hints、quickref 和当前用户指南一致；历史 release/spec 不改成“已完成”。正常和部分来源各抽一例经 GUI 与 adapter 比较数组、单位、时间、身份及诊断。
- 真实 Cocoa 验收用户 WWT、混合 TDMS、含缺口 CSV/XLSX、部分 ZFD、失败文件。核对可操作性、摘要、详情换行/滚动、恢复后详情、文件关闭后清理，并记录窗口几何/截图。offscreen 不能替代前台证据。
- Boundary 按实际触及范围运行：IO 中立依赖用 `tests/ui/test_import_boundaries.py`、`tests/test_signal_no_gui_import.py`；若新增模块/导入则加 `tests/test_packaging_imports.py`；MainWindow/UI 接线用 `tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`；新圆角控件用 `tests/ui_kit/test_qss_border_shorthand.py`。Batch 变更必跑 RunReporter gate。
- 不因本轮导入修改而跑所有 `tests/ui`，不无条件加入 pg_canvas/renderer gate。仅实际触及渲染边界才加对应测试。
- 本计划覆盖多格式 IO→GUI→Batch 边界，最终稳定集成点允许一次全套验收，由单一执行者负责：先检查现有 pytest 及 cwd，记录前后 HEAD/工作区指纹；先跑主套件 `--ignore=tests/acquisition_ui`，完成后另起进程跑 `tests/acquisition_ui`。不并发、不重复；源文件变动、崩溃或中断标 `UNVERIFIED`。
- Windows frozen Full/Lite 属后续发布验收，本计划完成不能声称已验证。缺少 Cocoa 环境则前台 gate 标未完成。

## 6. 最终验收矩阵

| ID | 必须证明 | 负责阶段 |
| --- | --- | --- |
| R1 | 用户 WWT 5 通道、24,941 点、24.94 s 与原值一致，空记录有提示，正常打开 | T1/T6 |
| R2 | 空 Zeit 不改编号、不穿透所属边界；重同步不会把伪头当记录 | T1 |
| R3 | WWT 真实截断/超大声明仍明确失败，其他已加载来源保持 | T1/T2 |
| R4 | warning/partial 可重复查看；只载数据、拒绝布局、项目恢复均不漏报 | T2/T6 |
| R5 | CSV/Excel 原信号缺口保留，时间不自动补造；普通文件数值与时间不变 | T3 |
| R6 | NaN/Inf 所在计算窗口明确处理；无静默补值或成功的无效结果 | T3 |
| R7 | TDMS 局部无时基不拖累正常通道；全部无时基仍失败 | T4 |
| R8 | ZFD 只恢复完整结构下不兼容的局部通道；末通道真实截断仍不返回部分组 | T5 |
| R9 | Batch 目标缺失不改用其他通道，结果/manifest/resume 保留诊断、无重复记录 | T2/T4/T5 |
| R10 | complete/warning/partial/failed/UNKNOWN 不混淆，物理文件与逻辑组计数准确 | T2/T6 |
| R11 | Cocoa 实际控件与交互通过；平台未验收范围明确 | T6 |
| R12 | 正常输入、已有公开返回形状、旧项目、导入依赖边界与状态 ownership 不退化 | 各阶段/T6 |

每阶段记录新增测试的修复前失败原因、修复后命令与结果。未完成后续阶段时只能报告已完成阶段，不能把 T1 成功包装为跨格式容错全部完成。

## 7. 初始计划编写检查（历史记录）

本次只新增此计划：全文审读、相对引用/owner 路径检查、异常等级与验收矩阵一致性检查、`git diff --check`。不修改产品、测试或原始数据，不运行新的 runtime suite；上一轮 `8 passed` 只作为背景证据。

实施时按 project-lessons 读取相关项：MF4 共享时间轴、可移植合成 fixture；只有实际触及 WWT→UltraView 边界才应用其真实集成 gate。结束前检查 lesson 状态；新回归揭示可复用模式时再记录，不能为了文档任务制造无关 lesson。

## 8. 执行记录（2026-11-02–2026-11-03）

- T1：空 Zeit 回归先红后绿；客户原文件经真实 loader 导入成功，5 通道 × 24,941 点，0～24.94 s，SHA-256 不变。记录编号、空轴归属和重同步负例已覆盖。
- T2：新增中立诊断 schema、文件卡导入详情、GUI/Batch/manifest 传递；旧项目重读诊断，明确 manual Fs 的无 Time CSV/Excel 恢复仍可用；不将运行诊断写入项目。
- T3/T4：表格保留缺口，TDMS 隔离不可用通道。实施探针还证明了单位与数据类型的必要边界：已知 s/sec/ms/us/µs/ns 转秒并记录警告，未约定转换的 datetime/timedelta 时间拒绝；TDMS 自动消歧二次碰撞已修复。
- T5：完成 [ZFD 合同补充](../specs/2026-11-02-zfd-partial-import-addendum.md)，完整结构下局部 type 4 不兼容可跳过，真实末记录截断仍失败。
- 计算边界：FFT/FFT-Time/Order 输入有限值校验已先红后绿；FRF 沿用原有限值校验。新增真实 BatchRunner 回归发现预处理会先删缺口，故在原 `batch_preprocess.py` 增加内部策略：runner 频谱路径拒绝缺口，原始时域导出保留缺口；独立 helper 的默认旧合同保留。未改变 FFT/COT/FRF 数学公式。
- 定向结果：WWT/ZFD/IO notices 132 passed、11 skipped；表格/TDMS/FileData/MF4 117 passed、1 skipped；主协调者 Batch owner 317 passed；GUI 导入/恢复/提示及边界由 UI agent 分组验证通过。不同集合有重叠，不相加成总数。
- 独立控件 Cocoa：文件卡 288×70、详情按钮 24×24 位于卡内、详情对话框 640×440，截图无截字遮挡；整窗真实样本、XLSX 项目重读/关闭清理已通过，详见验收记录。证据保存在 `.state/import-recovery/`。
- 预先已有版本、dB reference、帮助及测试修改保留；本任务未发布、未提交、未改写客户原文件。

- T6：真实 Cocoa WWT/CSV/TDMS/ZFD/XLSX、恢复后重新生成详情、关闭来源删除详情、失败后保留其他来源通过；客户原文件最终哈希仍一致。Windows frozen 与本轮 Cocoa 布局导入分支未验收。
- 稳定快照主套件：14,123 passed、69 failed、71 skipped、3 deselected、2 errors，退出码 1，用时 14,318.13 s；独立采集 UI：369 passed、2 skipped，退出码 0。两套前后 HEAD/源文件内容均一致。
- 主套件 69 项失败中，3 项测试合同在收尾同步并定向通过；61 项在任务前副本复现，未扩修；5 项仅全套失败，原因 UNKNOWN。两个 teardown error 也在任务前复现。不能把这些结果称为全套通过。
- 收尾集成首次 61 passed、2 failed；同步提示队列预期及保留 ZFD 时基硬失败表述后，两项补测通过。全套结束后未改 Python 产品代码，只改测试/帮助/验收文档，不重复运行四小时全套。
- 完整分类、命令结果、现场证据和剩余节点见[验收记录](../verify/2026-11-03-import-recovery-verification.md)。本轮 lesson 已归档，最终检查确认无待处理 lesson 要求。
