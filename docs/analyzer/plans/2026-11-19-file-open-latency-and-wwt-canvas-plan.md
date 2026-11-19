# 文件打开延迟与 WWT 首帧稳定性实施 Plan

2026-11-19 · 已实施并完成本机验证，Windows EXE 待验收 · 基线 `630bf656` · [需求、数据合同及验收目标](../specs/2026-11-19-file-open-latency-and-wwt-canvas-spec.md)

实施从 T0 开始。默认 MF4 的优先项是预热与交接，多采样率的优先项是时间轴分段。WWT 有可独立复现的画面问题，可在 T0 留下前台基线后修复。本计划给出后续实施顺序和验收口径，实施结果见[验收记录](../verify/2026-11-19-file-open-latency-and-wwt-canvas-verification.md)。

| 工作 | 依赖 | 交付与判断 |
| --- | --- | --- |
| T0 建立用户路径基线 | 当前代码和可取得的 EXE | 找出点击至可用的耗时分布，冻结数据与视觉对照 |
| T1 原生分段快速路径 | T0 的原生样本 | 交付可独立合入的数值优化 |
| T2 一次性进程预热 | T0 的启动计时 | 将初始化移到空闲期，验证冷启动、取消和退出 |
| T3 结果交接 | T0 的读写计数 | 先消除重复扫描，再按剩余瓶颈决定是否合并存储块 |
| T4 WWT 视口与轴宽 | T0 的前台几何 | 两项分开验证，修复稳定视口与一次成帧 |
| T5 进度反馈 | T0 的阶段边界 | 修正慢任务阶段提示、短任务闪窗和用户等待 |
| T6 集成验收 | 已通过各自门禁的改动 | Windows EXE 与 Cocoa 各自出具结论 |

### T0　同机分段，冻结对照

1. 确认反馈所用 Full／Lite／Lite Modular、版本与多采样率设置，若有用户样本，在允许的本机位置读取。仓库工作区已有 `testdoc/mf4/2.W04_360_1s_rt_11201724.mf4`、`testdoc/mf4/5.W04_180_10s_rt_11210854.mf4`。WWT 使用 `testdoc/wwt/NLTNP_000089.wwt` 和 `testdoc/wwt/U-Can_D6-CSER double_00479.wwt`。记录 HEAD／包版本、样本 SHA-256 和模式，保留旧包时用它建立可正确读取样本的体验对照。
2. 以请求 ID 串起 GUI、broker 和一次性 worker。测量排队、进程启动到就绪、扩展初始化、读取器加载、文件检查／解析／对齐、写交接结果、父端校验／解码、FileData 准备、注册并可选择、首个有效 paint；另记清理及人工停留。进程内计时用单调钟，父端测端到端，标记嵌套耗时，避免重复相加。记录交接文件数／字节、内存及 GUI 心跳。阶段事件用可关闭的诊断记录，每次请求每阶段一条。
3. 用真实主窗口分别跑冷开、就绪后开及连续开；WWT 自动接受排版，先开 NLTNP、无变化重绘两次，再开 U-Can。记录每帧各可见轴范围、内部 ViewBox 左右边界、外框、设备缩放及父卡片的背景暴露。补一轮仅加载数据作为绘图耗时对照。
4. 保存原始表及前台几何到 `.state/`。本阶段只跑涉及的入口，相关入口测试为 `tests/ui/test_mf4_import_flow.py`、`tests/ui/test_wwt_import_flow.py`。Windows 暂缺时先记录 UNKNOWN，本机可独立推进 T1–T5。T6 仍缺目标机结果时保留该项未验收。

### T1　优化多采样率时间轴扫描（I3）

- 修改点为 `mf4_analyzer/io/native_signal_store.py::build_segments`。先将现有通用分段结果固定为 oracle，用相同输入逐项比对。覆盖空／单点、严格递增、跨块重复或倒退、连续 NaN／±Inf、非连续视图、整数边界和大于 2^53 的时间戳，保持原接受类型及维度合同。
- 用有界块快速确认全有限且严格递增，跨块也比较上一末值和下一首值。任一条件不成立即走通用路径。父端与子端继续使用同一中立实现。门禁为 `tests/test_native_signal_store.py`、`tests/test_import_transport.py` 的原生往返案例和 `tests/test_native_import_boundaries.py`。
- 在 12 MiB 文件对比完整原生读取，检查全部轴、段标志、采样信息、原始／物理值、质量掩码和 revision。对照记录的 1911 → 775 ms 只用于核对优化方向，最终看 Spec 的 Windows 指标。

### T2　预热一次性读取进程（I1、I2）

- 由中立导入监督层管理候命进程与回收，桌面导入协调器发出空闲预热和关闭请求，由监督层在导入请求进入时领取候命进程。复用 `import_process.run_import` 的监督、异常分类、预算、快照和取消语义。`StartupCoordinator` 现有职责是预加载分析页面，预热读取器应有独立生命周期。Batch／项目恢复保有按需入口。
- 为隐藏入口和 worker 定义“候命就绪 → 收到唯一请求 → 现有解析 → 退出”的握手。请求到来时在同一所有者内原子决定候命或按需；正在预热但尚未就绪时避免争抢资源或双解析。分配请求时读取最新预算并验证运行时身份。预热阶段崩溃仅丢弃该候命进程。文件已交付后的错误仍向当前请求报告，按原重试流程处理。
- 实现顺序为按需入口的等价探针、首次可交互后预热、Windows Job 入组后放行、宿主关闭／休眠超时清理。验证连续请求、预热中关窗、领取瞬间取消、解析崩溃、空闲租约失效、超时后重试，以及原文件／旧 View 完整。每次至多一个活动解析，默认只保留一个候命名额。启动时立即打开文件也要能工作。
- 门禁为 `tests/test_import_process.py`、`tests/ui/test_import_coordinator.py`、`tests/test_import_packaging.py`、`tests/test_batch_import_cancellation.py`。核查 `MF4 Data Analyzer V1.py` 的隐藏入口和打包依赖。Lite Modular 实测核心／扩展核验与健康缓存的耗时及租约释放；若仍占主导，单列优化，不跳过组件核验。Windows Job 回收与实际 EXE 启动以目标机记录为准。

### T3　合并交接读写，必要时合并数组文件（I1、I4）

1. 在 `mf4_analyzer/io/import_transport.py` 的 `_Writer`、`_Reader` 分别统计实际打开次数和顺序读写字节。先校验清单预算和数组声明，再按预算分配缓冲。将写入摘要并入输出流，合并父端校验与解码，对同一文件句柄、同一组字节完成验证和构造。完整验证后才向调用者返回。用前后对照区分摘要 CPU 成本、重复读取和临时目录清理。
2. 再看两类负载。共享轴重点看约 191 MiB 大表；原生重点看约 1183 个小文件。若文件创建、读取或清理仍占显著耗时，给 MF4 增加带明确版本的紧凑块表示，优先复用现有清单、引用图、字节预算及返回对象。目标是与数组数解耦，验证共享引用、写权限、端序、形状、对齐、零长和缺口。维持 worker 退出、临时目录立即删除后的可用性。持久化项目无需迁移。
3. 先覆盖内容损坏、偏移越界／非法别名、截断、身份错配、超预算、写满临时盘、取消和半成品清理。再对真实样本逐通道比对，共享轴含时间列与 NaN 位置，原生含记录键及 raw／physical／validity。门禁为 `tests/test_import_transport.py`、`tests/test_import_format_roundtrips.py`、`tests/test_import_process.py`。更新与旧物理布局绑定的测试时，保留它原先保障的去重、预算或损坏检出断言。小 WWT 做速度及记录共享往返对照。

### T4　消除 WWT 绘图区横移及范围重设（V1、V2）

1. **先锁定范围变化。** 真实打开 NLTNP 接受排版，首次完成后连续刷新。捕捉无选择变化仍走 `try_apply_selection_delta` 的路径。在 `pg_canvas/canvas.py` 依据实际可见性或布局变化决定是否重新定轴；在 `main_window/window.py::_plot_time_on_canvas` 尾部区分刻度投影与主动重设范围。验收两轴在刷新后仍为 −10…10、0…460，同时验证 Home、实际隐藏／重显、滤波伴线切换和用户缩放。
2. **再锁定首次绘制的边界。** 在现有 `overlay_axes.py::_realize_overlay_axis_columns` 和普通 View 的最终 settle 中，根据最终刻度处理主左、第一右和额外右轴。沿用现有字体度量和布局激活，并检查负号、长标签及高 DPI。用 U-Can 复核前两帧左界曾移动 11.5 逻辑像素的反例。对照还需包含普通 overlay、subplot 和多 View 切换，确保首次绘制时没有空曲线或空白背景闪帧。若几何已稳定仍观察到背景暴露，再检查进度更新触发的事件循环及既有页面过渡；以帧证据决定是否扩大修改。
3. 门禁为 `tests/ui/test_wwt_initial_view_contract.py`、`tests/ui/test_overlay_grid_ticks.py`、`tests/ui/test_overlay_shared_axis.py`、`tests/ui/test_pg_timedomain_canvas.py::TestViewRestoreSettlement` 和 `tests/ui/test_pg_canvas_backref_invariants.py`。如涉及过渡或 Pin，再加 `tests/ui/test_page_transition_integration.py`。最后记录 Cocoa 与 Windows 的前台首帧和稳定帧，按 Spec §5 判定。

### T5　短导入状态栏先行，长任务显示真实阶段（I5）

- 由 `ImportCoordinator` 持有与 request ID 绑定的一次性延迟显示计时器，沿用已有进度快照与终态；`_bind_import_progress` 接入。先以 250 ms 做短／长任务边界，终态、取消和关窗立即撤销待显示动作。状态栏即时显示，慢任务保留取消；WWT 排版等待和资源重试可及时出现，恢复后的阶段与提示准确。
- 验证快成功、恰好跨阈值、弹窗前失败、长读取取消、请求连续切换、等待排版与收尾。用可控时钟或信号验证生命周期，真实 EXE 用屏幕记录验证闪窗。门禁为 `tests/ui/test_import_coordinator.py`、`tests/ui_kit/test_import_progress_dialog.py` 和 `tests/ui/test_import_recovery_followup.py`。如引入新的用户操作或更名，同步 hints 和 quickref。

### T6　用交付包验收

重复 T0 的相同样本与操作，按 Spec §5 填表。以反馈对应的包型为主，Full／Lite 分别验证冻结后的隐藏入口、可用时间及退出；Lite Modular 单列核验就绪与失效。冻结版、源码版和 offscreen 的结果分开。每一实施步骤只跑归属测试与实际受影响的边界；发布或稳定集成节点按仓库规则最多安排一次全套。

| 报告须回答的问题 | 尚待取得的验收证据 |
| --- | --- |
| 默认 MF4 是否恢复到秒开体验？ | 同机当前包／候选包及可用的旧包，冷开、候命就绪、连续打开，点击至可用和至首图的中位数与最慢值 |
| 多采样率提速是否保留数据？ | 两种模式各自的数值等价；原生分段逐项对照、端到端耗时及读写文件数 |
| 隔离及资源代价是否可接受？ | 首窗可交互耗时、空闲／活动内存、GUI 心跳、取消／崩溃后下一文件成功、Job 和临时资源回收 |
| WWT 是否还有可见跳动？ | 两端平台的开启与重复刷新帧序列，绘图区位移、X/Y 范围、背景暴露和控件操作对照 |

若 Windows 仍耗时数秒，按最慢区段决定下一轮：启动核验、真实解析、交接或 GUI 注册分别归各自 owner。记录已省下的毫秒数和剩余差距，不以缩短弹窗可见时间关闭性能问题。
