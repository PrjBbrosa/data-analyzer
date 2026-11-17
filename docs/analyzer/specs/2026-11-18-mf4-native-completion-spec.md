# MF4 原生采样提交后收尾与发布门禁 Spec

日期：2026-11-18。状态：**needs revision / partial；两个native修复及导入恢复followup已合并，功能和数据正确性仍有阻断，尚不可整体验收或发布。**

配套：[收尾 Plan](../plans/2026-11-18-mf4-native-completion-plan.md)。

Supersedes：[2026-11-17 原生采样 Spec](2026-11-17-mf4-native-sampling-spec.md)中的实施快照、缺陷状态和后续优先级；原文 §3–10 的数据、身份、预算、性能及完整产品验收合同继续有效，本文明确细化的条款优先。旧文件保留历史，不回写成已完成。本文同时接收[导入恢复补充 Spec](2026-11-17-import-recovery-review-followup-spec.md)的 H01–H06；必要反例在本文重述，不要求执行者依赖未提交文档或本机 `.state`。几何/进度/重试仍遵守[导入恢复 Spec](2026-11-17-import-budget-and-dialog-recovery-spec.md)，不另建一套 UI 方案。

本轮授权仅核对提交及创建新 Plan/Spec；没有修改产品/持久测试，没有派发实施 agent、提交、推送或发布。

## 1. 当前基线与两个提交实际完成的范围

native审查基线：`398e16ed6d534f590084c14a50b3905956161ba6`，`APP_VERSION=v8.4.8`。开始审查时 tracked 工作区干净；已有未跟踪 `CSER TTR/` 与两份 `2026-11-17-import-recovery-review-followup-*` 文档，保留不动。文档收尾时另一工作流先合入PR #41，HEAD变为 `67c64205ee603587098b4e4dc8faea9831010833`；其实现 `240ab4b0` 只改UltraView `author_geometry.py::pixel_rects_intersect` 及7个相关测试，不是第三个native修复。已读增量diff，本文数值/导入/导出反例涉及的owner源码未变；最终UltraView集成须继承该成果，不能回退。随后导入恢复实现 `2c08c890` 经合并 `ad373c7c68a78e06d16b49c2e75d4e380ae21992` 进入当前工作区，改变了Batch wrapper、派生通道、MDF版本兼容、精度与释放；本文已按此新基线重新归类并复跑受影响探针。两份原未跟踪followup文档现已由该工作流提交，其草稿备份见该工作流记录。本轮不移动它们。以后执行必须重新核对快照。

`git log --no-merges c848fdb1..398e16ed` 确实只有以下两个实现提交。提交元数据记录 Cursor 协作署名，不能据此证明实际使用了哪种模型。

| 提交 / 合并 | 已存在的实现，应接收而非重做 | 不能由此推断 |
| --- | --- | --- |
| `63619b1ca9e46b9aadbdc9c9d56eed071872208a` / PR #43，merge `68013e34` | 十进制采样率的浮点网格判定；read_signal邻点halo；部分GUI/Batch消费者改为通道时钟；时频先取选区；刷新保留失效断线；游标按轴分配marker | 全部消费者已迁移、RPM质量完整、所有子图/Pin/Cocoa路径已验收 |
| `0bde62867eb40a17210ca770c798600807c58f37` / PR #44，merge `398e16ed` | schema6保存的native policy接入项目恢复；Replay UI改走native；整数倍率FRF对齐和显式降采样helper；GUI预览/统计/Excel/WWT分支 | F08/F09完整通过、实际FRF作业使用正确Fs、导出精度保持、资源预算已接入 |

仅上述两次native提交合计涉及27个不同文件，改动集中在原 B1–B5 的部分实现；两次提交均未附新的完整验收报告，也未修改旧 Plan/Spec。因此“Grok所述native后续做了两个提交”在该区间属实；但当前树还包含导入恢复followup，不能再称全部相关工作只有两次提交。“计划已经做完”仍不成立。`02d15a61` / `c848fdb1` 是更早的基础实现，不计入这两个后续提交。

### 1.1 接收旧问题，避免重复派工

| 旧编号 | 当前接收状态 |
| --- | --- |
| N01 | 十进制率旧反例已有修复与focused测试；ULP、声明冲突、空/单点/大原点/真实抖动的完整合同仍需接收，不能把一个容差常量当完整精度证明 |
| N02 | 多个GUI入口已改；Batch wrapper阻断已由新followup修复并经本轮真实Runner复验；RPM/Custom-X/FRF仍有缺口，整体partial |
| N03 / N06 | 失效点刷新、子图marker旧反例已有持久回归且本轮通过；完整生命周期、双轴/滤波/Pin及Cocoa几何仍待验 |
| N04 | RPM裁切邻点旧反例已修复；有效性丢失和Batch对齐另见L02/L03，不能关闭整个Order合同 |
| N05 | 时频选区先解析的旧反例已修复且测试通过；完整pane/cache/失败原因/预览成本仍在联合验收内 |
| N07 / N08 | 应用级资源、热路径和完整兼容矩阵未关闭；见L05/L09–L11 |
| N09 | enum共享与重名transport已在更早的基础提交修复；本轮transport测试通过。旧“identity physical”报错不是当前重做依据；事故样本GUI/逐点/平台R01仍不能推断已通过 |
| F08 / F09 | 已有真实数值helper测试并去掉两个xfail，不能继续写“函数不存在”；现有频带与生产接线不足，见L04–L06，仍partial |
| H01–H06 | 最新followup已修H01/H02/H04/H05及H03基础取数；接收其定向证据，不重复派工。H03完整项目重开仍partial；H06已有Cocoa工作窗/真实重试证据，完整生命周期及Windows未关闭 |

### 1.2 实际入口政策

| 入口 | 当前源码 |
| --- | --- |
| 普通打开、拖入、最近文件、MDF adapter默认、Batch按路径load | 仍 `load_mf4`，低预算公共轴问题不会因两个提交自动解决 |
| 显式 `request_explicit_native_import` | native broker→transport→GUI |
| `.mf4/.mdf` 项目ref的 `sampling_policy="native"` | 显式native恢复；旧policy仍legacy |
| ReplayTab选择文件 | 已直接请求 `load_mf4_native`；这是已经改变的用户路径，需要立即纳入兼容/取消/资源验收 |
| `ReplayRecorderBackend.source_from_mf4` | 仍 `run_import("load_mf4")`，与Replay UI存在入口差异 |

不能再写“全部默认入口都保持legacy”；也不能写“整个产品已切native”。后续不得用自动回退掩盖不支持或质量失败。新开默认native仍是完整目标，只能在所有必需门禁通过后切换；旧项目legacy复现和旧公开loader保留。

## 2. 本轮证据及其边界

本轮使用项目 `.venv`，`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`：

```text
python -m pytest tests/test_native_signal_store.py tests/test_signal_access.py
  tests/test_analysis_signal_prepare.py tests/test_mf4_native_fidelity.py
  tests/test_import_transport.py tests/ui/test_native_signal_consumers.py
  tests/ui/test_order_multirate_rpm.py tests/ui/test_mf4_native_product_path.py
  tests/ui/test_main_window_state_ownership.py -q --tb=short
152 passed, 3 warnings in 8.06s

另一个新进程：python -m pytest tests/acquisition_ui/test_replay_tab.py -q --tb=short
9 passed in 3.29s
```

上面的换行是命令排版，实际第一组是一个pytest进程。第二组在第一组退出后运行。没有全套、真实Cocoa交互或Windows Full/Lite验收。源码与测试快照为依次散列排序后的 `mf4_analyzer/**/*.py`、`tests/**/*.py` 相对路径和内容：开始SHA256为 `78e1c0a0e11185e24087c34f271b60942d9043005635771f31d36a4f659bbd31`；收尾因上述PR #41变为 `ba2e5780a06efe934d5009d4f25af166b5ae38153bd492d6e2e75c830e802c80`。因此152/9只保留为本轮命令的focused观察，不能签署新HEAD稳定整树验收。新增几何diff未改本轮数值/导入owner和所列测试，没有据此重跑相同focused；最终联合状态仍UNVERIFIED，C7按届时稳定快照验收。

临时证据位于 `.state/native-followup-20261118/`：`focused.log`、`replay.log`、`probe.py`、`probe-results.json`、`versions.json`、快照JSON。它们不作为分发依赖；以下保存重建输入和实际结果。探针是生产函数/Runner/文件回读证据，非新增持久回归测试；后续实施先固化为owner红测。152条通过不能抵消新反例。

### 2.1 最终接收 `ad373c7c`

已读 `67c64205..ad373c7c` 受影响owner增量及[导入恢复执行记录](../verify/2026-11-18-import-recovery-followup.md)（以 §8 合并接收为准，不沿用前文旧状态）。该工作流记录合并focused **183 passed**，新增跨率精度红测后受影响owner **73 passed**；不累计为当前全套。本轮复用这些已有证据，不重跑同组。H02真实编辑器、H04实际broker版本矩阵、H01终态weakref以及Cocoa工作窗/重试属于该工作流证据，不冒充本轮执行。

本轮在最新HEAD重新运行生产方法/Runner/文件回读探针，结果保存在 `.state/native-followup-20261118/current-ad373c7c/`：原Batch wrapper不再报LegacyAxisUnavailable，原始时域导出done；派生abs可read_signal；不可精确整数准备rejected。L02、GUI RPM质量、L04–L07反例仍成立；不重叠时钟的Custom-X请求现在能走完整Runner并返回done，未验证时钟关系。Batch失效999已转为空值导出，不能继续声称该路径仍输出999。新staged API已由真实编辑器回归覆盖，不拿旧tuple探针报错判为回归。

最终产品/测试SHA256为 `283fb1802c4416f5f0b43fc97e3dd2bfea2bfd10397b7fb6d0c778bbb51d5879`（同上算法），HEAD为 `ad373c7c68a78e06d16b49c2e75d4e380ae21992`。本轮没有新增全套或平台验收。后续以本节和下表状态为准，L编号保留历史追踪，不等于全部仍待修复。

## 3. 当前剩余阻断与缺失验收

路径均相对仓库根；当前状态对应ad373c7c，历史反例明确标注，后续以符号定位。

| ID / 严重度 / 证据 | 当前问题与可重建反例 | 完成条件 |
| --- | --- | --- |
| L01 / 原P1，当前定向已修复 | 旧 `_run_sequential` / 分组wrapper访问legacy data；followup已改为 `_source_has_channel`。本轮最新HEAD真实Runner时域导出done，无LegacyAxisUnavailable | 接收修复，不再派重写wrapper；保留普通/分组/resume/probe及失败后继续的产品覆盖，整体Batch完成由L02/L03/L04和C3判断 |
| L02 / P1 生产方法数值错误 | `batch.py::_rpm_values` 把 `_task_channel_arrays` 返回的 `(values,time,fs)` 解包为 `target_time,...`。信号t=`[0,1,2]`、y=`[.2,1,1.8]`，RPM同t、值`[100,200,300]`，实得`[120,200,280]`，应为`[100,200,300]` | 按真实时钟对齐，信号幅值改变不改变RPM；同源/跨源、显式rpm_signal及rpm_channel、选区/邻点、单位倍率、真实覆盖一致。保留禁止端点延长合同 |
| L03 / P1 GUI与完整Batch请求复现 | GUI `_order_rpm_for` 仍未传validity：t=`[0,1,2]`、RPM=`[100,999,300]`中点失效仍返回999。Batch已在 `_task_channel_arrays` 将失效点转NaN，本轮CSV中该点为空，不再视为同一失效。Custom-X仍丢 `_x_time`；信号t=`[0,1,2]`、X时钟=`[10,11,12]`等长且不重叠，真实Runner请求返回done而未拒绝关系 | RPM质量/segment完整；Custom-X明确拒绝或显式对齐，补图与表输出实值oracle。空值导出不代表原record/quality可追溯性已完成。native时域单点/unknown Fs不能被频谱Fs要求误拒 |
| L04 / P1 GUI与Batch准备及真实DSP调用复现 | `_frf_mixin.py:497` 与 `batch_compute.py::_prepare_native_frf_task` 仍用 `pair.left.source_fs`。输入2000Hz、输出1000Hz、80Hz增益2，同原点4秒，显式对齐后网格1000Hz，生产DTO仍2000Hz；`compute_prepared_frf` 报 `relative_jitter=1` | 运算、窗长/NFFT、频率轴、cache与effective facts统一使用实际prepared目标Fs；原始Fs仅作来源。测试两种高低率方向、GUI真实作业和Batch真实作业 |
| L05 / P1 预算与质量helper复现 | `analysis_signal_prepare.py:783` `_align_uniform_pair` 直接 `del byte_limit`。8000点@2000Hz与4000点@1000Hz，`byte_limit=1`仍ready并记录102400bytes；慢轴内部index1000置NaN后仍ready且输出含NaN。同轴/单路还有hash先于准入、pair按单侧预算等审计点 | 统一shape/质量/精度/segment/预算预检；非法请求明确rejected，所有大分配之前准入，双侧/FFT/filter/输出总量计费，取消/失败释放。底层helper不能依赖某个GUI调用者恰好先过滤 |
| L06 / P1 F08反例复现，F09覆盖不足 | 当前8阶、cutoff=0.45×目标Fs的滤波不满足广泛60dB声称。源4000Hz、N=40000、目标500Hz，300Hz和510Hz正弦降采样后RMS抑制约20.03/56.86dB；现测试只用1500Hz，恰为目标率整数倍，不能证明其他带外频率。FRF现有新测试只覆盖零延迟80Hz、2:1、H1窄带 | 按 §4 冻结真正的通/阻带、支持比率、边缘和phase预算；独立频率/相位扫描与实际产品作业通过；不靠设计字典或删除xfail宣布完成 |
| L07 / P1 导出回读复现 | `window.py::_native_excel_frame`→`_do_export_excel:5497` 直接pandas数值单元格；`2**53+3`回读变为`2**53+4`。现已有中立原生导出writer，但真实GUI未复用其精度/分片合同 | GUI调用同一可靠导出owner；大整数文本、跨sheet行数限制、记录/segment/质量、选定派生通道保留，真实保存回读。不得静默skip取数失败通道后报整体成功 |
| L08 / 原P1-H02/P2-H03/H05，基础修复已接收，产品链partial | followup真实编辑器abs→derivative已全4；应用派生可统一read_signal，本轮再验成功；`[2**53+3,2**53+5]`准备现明确rejected。精度helper也已接到跨率pair且policy升为 `m4-same-axis-2` | 不重做派生存储/精度helper；保持shape/quality/revision和拒绝原因。H03真实编辑→应用→保存→open_project→继续派生/分析完整链仍须C5验收；GUI Excel另归L07，不因计算准入修复关闭 |
| L09 / 原P2-H04，支持标量矩阵已修复 | followup按版本处理dtype/conversion/validity并加MDF2/3读前安全检查；执行记录已验证2.14/3.30/4.10 × 空/单点/多点、integer/float/endianness、identity/线性转换的真实broker，不再沿用旧conversion size unknown反例 | 接收既有测试，不重写reader；Replay UI已native，应补真实入口兼容/取消与全平台，未支持布局明确拒绝；合成标量通过不等于事故样本R01或所有MDF布局通过 |
| L10 / 资源/性能partial；H01基础释放已修复 | 完整hash、FRF `materialize=False`仍准备、Replay逐点tuple和应用级reservation/LRU仍待闭环。followup现于drain后清空 `_last_call`/workflow/回调，H01终态weakref已有定向证据，不能再写owner未变 | 保留H01清理与重试生命周期；补尚未覆盖的Cocoa父销毁/退出/共存峰值，元数据预览不完整DSP，真实平台性能按原门槛验收；不重做已完成引用释放 |
| L11 / 产品及平台UNKNOWN/partial | 对齐请求参数在准备层可读，但未找到GUI设置 `align_then_compute` 的控件接线；Replay复位segment有helper而真实选择闭环未证；默认/旧项目迁移、Pin/比较/UltraView、帮助、事故样本注册/逐点、图2、Cocoa/Windows仍缺完整证据 | 按 §6 实际操作路径验收与帮助同步；没有权限/样本/平台就保留UNKNOWN，不删合同提前放行 |

## 4. 分析数值合同补充

1. **每次运算携带完整输入事实。** 值、原轴、有效性、segment、单位/表示、source/physical identity/revision、请求范围与halo不可分离。只把tuple顺序改对不足以关闭L02/L03。空/短/非有限、dtype/shape冲突必须有确定返回，禁止min截长、reshape掩盖错误维数或跨gap补值。
2. **prepared Fs是实际计算率。** source_fs保留来源，target_fs与输出时间间隔一致；FRF两端prepared Fs一致后才能调用核心。GUI/Batch preflight、缓存、窗口、结果facts及导出统一使用它。原始数组/hash保持；更新准备policy version和缓存中的算法/对齐设计身份，已有 `m4-same-axis-2` 精度升级必须保留；后续对齐设计变化继续更新身份。
3. **F08具体频带。** 首先验证均匀连续输入的降采样：目标Fs为Ft，通带至少覆盖 `[0,0.30Ft]`，阻带为 `[0.50Ft,0.50Fs_source)`，两者之间为过渡带；通带幅值偏差≤0.1dB，阻带抑制≥60dB。具体滤波器、padding、延迟补偿、halo/有效边缘须在实现前冻结并用独立参考证明。旧用户滤波不因本条重写。当前300/510Hz反例不得移入“非目标”消掉失败。
4. **防止有利采样点掩盖混叠。** 用扫频/多正弦覆盖阻带边缘、中段、折叠进通带的频率以及不同初相位；不要只测恰落在新网格零点的1500Hz。输入4000→500、2:1/4:1/8:1为最低回归矩阵，短段/非零origin/端点另测；输出误差与滤波响应都验证。
5. **F09与可支持范围。** 现有同origin整数比是候选能力，不是任意整数比都已验收。至少验证2/4/8比率、高速输入与高速输出两种方向、同原点非零起点、范围裁切后的共同网格、增益2/已知延迟/多正弦、H1/H2/coherence。安全通带0.05–0.30×较低Fs：coherence≥0.99、增益误差≤0.1dB、相位误差≤1°。请求选区不能先裁掉halo或把同一原origin误判为不同起点。
6. 非整数比、fractional delay及未知时钟关系在未通过独立oracle前保持明确unsupported；不得假同步，也不得仅凭“值能算出来”开启。实际支持集合及其与原目标的差异必须列出，不能自行将未完成的合同变成非目标。UI提供明确请求/原因，用户应用后才计算，项目保存可复现意图。
7. **质量与数值表示。** 所选段及必需halo内失效/非有限默认拒绝，段外不相干坏点不污染合法段。整数转float64前验证精确可表示：`2**53+1/+3/+5`拒绝，`2**53/+2`等精确值可接受，正负、int64/uint64极值覆盖。raw与原始导出保持dtype/整数精度；不新增隐式有损选项。

## 5. 资源、逻辑通道与导出合同

- 沿既有中立IO资源owner完成应用级存活源、绑定结果、任务临时量和输出的reservation；准备LRU上限仍 `min(128MiB, admission_memory/8)`。不能靠 `PrepareByteLedger` 局部数字或 `ImportBudget.used_bytes`单调账本宣称应用峰值已受控。包括hash拷贝、mask、FFT complex/反射padding、重采样grid、Replay事件/时钟对象及GUI导出物化。
- 源、任务、View、缓存各有唯一owner；成功/失败/取消/关闭/替换项目最终对称释放，运行worker可持只读源，迟到结果不得发布。`_last_call`活动/重试与完成诊断拆开，诊断不持bound method、大kwargs或widget；先保住线程回收，再清理终态引用。
- 暂存与应用后派生不是只有`(values,unit)`；保持轴、quality、segment、revision和依赖身份。目录与read_signal统一解析，删除/隐藏/同名不偷偷回退raw store；保存仅引用与配方，重开可复算。不新建平行存储框架。
- 数值导出与图像导出分开。GUI、Batch与中立writer共用原始采样导出合同：同轴组或长表、原record/segment/质量、大整数文本及足够浮点往返精度；多率不自动插值成横表。超Excel行数明确分片/替代格式，不截断。部分失败须显式列出，不能把silent continue包装为整体成功。
- 保留现有source/channel复合身份、扭矩默认`1e-6 Nm`、Nm/nm区分；不得借本轮改ink/AA/150ms quiet window、版本号或其他格式存储策略。

## 6. 产品与发布验收

每个矩阵单元分别记录 PASS（输入/源码/命令/平台证据）、FAIL、partial 或 UNKNOWN，xfail/skip不是PASS。owner单元通过与真实UI/Runner通过分列。

| 路由 | 必须证明 |
| --- | --- |
| 导入/恢复 | 普通、拖入、最近、显式native、旧schema与schema6策略；取消/坏文件/重试后下一文件正常，源变化不半注册；MDF2/3/4与事故样本真实broker |
| 分析 | FFT、时频、Order、Order-vs-Time、FRF、时间滤波真正点击计算/任务完成；合法段可算，非法段准确拒绝。GUI/Batch同请求parity加绝对oracle；编辑/预览/切View不隐式计算 |
| 时域/查询 | 原始/滤波、单/双游标、区间统计、Custom-X、单点/重复/复位/失效、双Y/子图/overlay、隐藏/重排/移除；保留N03/N06回归，并补Pin/比较B面/UltraView与真实几何 |
| Batch | 普通/分组、已加载native与路径probe/load、RPM显式/名称、Custom-X错位、尺寸建议、表/图输出、resume与取消；取数失败准确单次终态 |
| 项目/编辑/导出/Replay | 暂存多级配方→应用→绘图/分析→保存重开→继续派生/导出；旧项目显式迁移预览/取消。Replay UI与直接API各标policy，重复记录/segment选择/启动停止/父销毁实际执行 |
| 兼容/文案 | legacy MF4、CSV/HDF/BLF受影响边界和混合源；帮助/hints/quickref说明真实可用能力，不沿用“Replay仍legacy”“F08函数缺失”等过期状态 |
| 资源/平台 | 原Spec §8完整性能合同、20轮生命周期；Cocoa与新鲜Windows Full/Lite独立。无平台不推测PASS，图2缺样本保留UNKNOWN |

R01固定memory **498,988,944**、output **≤249,494,472** 字节；事故样本SHA256仍为 `72d81a087e9816c7dca80633b20f5a899c0a484a6a80465b99a6d2f3c56cf5b3`。新证据必须包含正式adapter→broker→transport→GUI注册及逐点/目录oracle，计费与父/worker同时间线RSS分列；不得调高预算或降低安全检查。图2 `2.W04_360_1s_rt_11201724.mf4`单独验证，不用事故文件代替。

性能继承原Spec §8：同内容耗时/同时峰值RSS≤基线1.20倍；20ms heartbeat间隔p95≤50ms、max≤200ms，取消可见响应≤200ms；既有Cocoa绘图first/pan/resize/checkbox/paint门槛不改，5次冷进程/30次热交互与20轮释放，源码/机器/DPR/输入指纹齐备。新的取数/预览层不得在每帧完整hash/物化/重采样；性能是实测门禁，不是本轮承诺。

最终放行要求L01–L11、继承N/F/H与U/R门禁无遗漏、已修项证据接收且剩余必需数值和平台项通过，再对含实际启用点的稳定候选做唯一联合全套。普通打开未切native不能证明共享代码或已切换的Replay安全；两次提交已经合并也不等于允许发版。若用户另行决定限定交付范围，另写具体范围与影响，执行者不得自行删目标。
