# 导入鲁棒性实施验收

日期：2026-11-17。状态：实施与针对性验证完成；完整测试 UNVERIFIED，Windows UNKNOWN，未发布。

对应 [优化计划](../plans/2026-11-17-import-native-crash-and-resource-hardening-plan.md)。HEAD 基线 `5bac5a2c9ae40e1ea7a45ac4fbab3d7d6a652867`；保留已有未提交修改。工作过程与机器证据在 `.state/import-robustness-20261117/`，不纳入 Git。

## 原始样本

原始附件 SHA256：`72d81a087e9816c7dca80633b20f5a899c0a484a6a80465b99a6d2f3c56cf5b3`。修复前独立进程 SIGSEGV；修复后 800 元素均与独立文件字节 oracle 相等。正式 `run_import("load_mf4", path)` 返回 471652 行、Time 加 52 个信号，耗时约 0.86 秒；时间轴哈希 `0a661d522593f5c5d98d18eb58f56230ea47cd7bd7c3d7b2f1c1c5867efe2fbc`。原有 937 条跳过记录及共享时间轴说明保留。

项目 `.venv` 安装 `asammdf 8.8.32+tracelab.1`，原生安全标记 1。wheel SHA256 `279e98b2a165abd9b22c0933b320d3981fd677415b6d67a53e3c91ffbe9c9277`；已加载 C 扩展 SHA256 `1c4ab7e0be835438b0a004073c5e38fce95d44e7194758560fd7fe76c59c84df`。安装使用 `--no-deps`，不变更其他项目依赖。

证据：`T1-report.md`、`t1-sample-result.json`、`integration/sample-broker.json`。这是数值与正式子进程结果，不能代替 GUI 或 Windows 冻结验收。

## 已完成的分层检查

所有 pytest 使用项目运行时；Qt 测试用 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。以下是阶段结果，不合并成一个虚假的全套通过数。

| 范围 | 结果 | 证据或命令 |
| --- | --- | --- |
| 首批资源准入及格式 owner | 217 passed, 5 skipped | `t2-owner-final.txt`，skip 为可选真实 corpus |
| 首批 IO 边界 | 3 passed | `t2-boundary-final.txt` |
| 项目已安装 wheel 的 MDF 数值与 loader | 73 passed | `integration/mdf-installed-runtime.log` |
| 其余格式资源准入/媒体形状/CAN 警告 | 226 passed, 1 skipped | `t2b-owner-final.txt` |
| 安全结果传输，包括 12 万 CAN 帧 | 40 passed | `t3-transport-final.log` |
| 实际子进程 adapter / acquisition / Batch dispatch | 76 passed | `t3-consumers-fixed-wheel.log` |
| broker / limits / 启动入口 | 36 passed | `tests/test_import_process.py tests/test_import_limits.py tests/test_startup_entrypoints.py` |
| Batch 读取中取消与单一 reporter | 20 passed | `tests/test_batch_import_cancellation.py tests/test_batch_run_reporter.py` |
| 构建源码、打包引用和帮助 | 87 passed, 13 skipped | `tests/test_import_packaging.py tests/test_windows_build_script.py tests/test_packaging_imports.py tests/test_help_content.py` |
| 新增 numpy 惰性依赖声明后的冻结合同 | 27 passed | `tests/test_windows_runtime_dependencies.py` |

首轮帮助/启动边界组合为 134 passed、5 failed；5 项均由新增 `import_limits` 的 lazy numpy 未登记冻结组件归属触发，已登记 base/standard-hook 并通过上述 27 项 focused 重测。不是 Windows EXE 实测。

进程/Batch 整合审查又修复了元数据预检取消被标为 blocked、子进程 leader 已退出但后代仍存活、损坏 MF4 被标为内部错误、临时结果存储错误被标为坏源等问题。对应组合 57 passed；追加 FRF 全量读取取消后，受影响组合 31 passed。构建的 Full/Lite/Modular 源码合同 39 passed、21 skipped，跳过项是 Windows 执行门禁。

最终构建/依赖/启动/帮助/导入边界组合为 **146 passed、34 skipped**（`integration/final-boundaries.log`）；Windows 执行项的跳过不算平台验收。自定义 broker 策略也强制输出上限不超过内存预算的一半，避免绕过独立数组交接的副本余量。

全格式真实子进程检查覆盖 CSV、固定宽度 ASCII、XLSX、TDMS、WWT document/groups、ZFD、MAT v5/v7.3、HEAD、WAV、BLF、ASC；正常、坏文件、输出超预算、清理和重新读取路径有独立检查。小型坏 XLSX/BLF 的错误分类曾失败，已按特定 reader 异常修正，受影响检查 12 passed。取消/崩溃/超时通过共用监督层注入验证，未逐格式重复注入；不将这些组合结果称为完整执行了计划的逐格式五路径矩阵。

## 最终原生 Cocoa 验收

`integration/native_probe.py` 使用实际 Cocoa MainWindow 和正式 broker，将 QSettings 导向测试目录。错误弹窗由探针捕获；取消及超时「延长并重试」按钮是真实 QTest 鼠标点击。截图已检查，原文件两条曲线可见，原有跳过通道提示保留。

收尾补丁合入后，最终源码指纹前后一致：`712267b455970ef730d10300ca53b1b5d87bf1a480d8261e098523084375200e`（全部 `mf4_analyzer/**/*.py`）。结果为 `integration/native-probe.json`、`native-final.log`；此前版本保存在 `integration/native-pre-exit-fix/`：

| 场景 | 实测结果 | 最大 GUI 心跳间隔 |
| --- | --- | --- |
| 原始 MF4 打开并绘图 | 导入 1.031 秒，471652×53 | 57 毫秒 |
| 慢 worker 中点击取消 | 点击后 2.130 秒完成，原文件保留 | 27 毫秒 |
| 本次 worker 注入 SIGKILL | native_crash / failed，主程序存活 | 22 毫秒 |
| 故障后正常 CSV | 0.351 秒成功 | 22 毫秒 |
| 读取超时，明确延长后重试 | 测试限时 1→2 秒；新 worker 成功，增加 1 个来源 | 60 毫秒 |
| 保存并恢复三个文件项目 | 1.609 秒完成；正常关闭 | 257 毫秒 |

测试注入的 1 秒限时只用于触发弹窗，产品默认仍为 1800 秒。截图：`cocoa-original.png`、`cocoa-timeout-retry.png`、`cocoa-restored.png`。

首次前台探针曾发现取消按钮不可见，已修复。最终超时场景首轮探针依赖窗口标题而未定位按钮；改为可见按钮定位后完整通过，期间没有更改产品源码。失败探针保留为 `native-probe-timeout-selection.json`，不计为通过证据。

关窗收尾补丁前，原样本另做独立 Cocoa 资源观测（`native-resources.json`，源码指纹 `63f13b9b82b2a11a34ab6ad580df55b023b4cbf2cc5fba2e55f0ce66722c2f6e`）：主进程峰值 RSS 604,028,928 字节（约 576 MiB），最大 worker 峰值 RSS 543,621,120 字节（约 518 MiB）；这两个独立高水位不能相加当作同时峰值。结果交接时本任务临时目录为 200,817,104 字节（约 192 MiB），不是解析器全部临时文件的全时段峰值。该探针前后源码指纹一致、正常退出；本次只变更关窗路径，未重复资源测量。实际临时目录清理合同仍由 broker 测试覆盖。

## GUI 与消费者收尾

普通打开、拖入、最近文件、项目恢复、Replay 和 BatchSheet 的 DBC 入口均接入异步监督。GUI 发布回滚、WWT 弹窗取消、FileData 扫描线程、旧项目保存目标、分析附加提示、WWT 重复附加与目标 View 交接竞态均有复现及针对性修复。

原同步消费者测试通过显式 `wait_for_imports` 等待，保留原断言；没有全局 fake、自动同步回退或 xfail。分批运行期间发生的产品变更使其不能充当稳定全套结论。最后 focused 结果：项目恢复/拖入 104 passed；BatchSheet 生命周期及边界 33 passed；WWT 目标交接/取消/批量选择 10 passed；时间轴诊断与 Replay 9 passed；分析附加提示 4 passed。完整交接为 `t4-handoff.md`、`consumer-migration-status.txt`。

最终 broker/transport/worker/冻结入口及产品 DataLoader 可达调用链只读复核未发现未闭合 P0/P1，记录于 `.state/final-broker-review.md`。这是源码复核，不替代原生和冻结验收。

## 首轮全套中断与生命周期闭环

首轮全套运行中，已观察到 3 个失败标记；同时测试逐渐变慢。只读最小复现确认 QApplication-owned coordinator 强引用 host，使 close + shutdown + GC 后 20/20 宿主残留。对照组与弱引用实验均为 0/20。已停止该轮，归档于 `integration/interrupted-gc-leak/`；前后源码指纹一致，但退出码 -15，因此明确为 **UNVERIFIED**，未运行该轮 acquisition_ui，也不把完成的前半段当作全套通过。停止过程的 KeyboardInterrupt 测试错误不归为产品失败。

修复只涉及 coordinator 与其 owner 测试：host 改弱引用并检查 sip.isdeleted，继续由 QApplication 保持活动监督对象直到安全回收。红测 3 failed / 1 passed → 4 passed；协调器、BatchSheet 和边界 64 passed，独立 Replay 8 passed，原 20-host probe 全部回到 0 残留。见 `t4-weakhost-handoff.md`。此后曾完成 Cocoa 和资源实测；关窗补丁后的最终交互实测与此前资源指纹在上节分别列出。

首轮 3 个失败定位于 `tests/test_frozen_batch_acceptance.py`：其模拟冻结 helper 将 sys.executable 指向假 EXE，新增 broker 正确尝试启动该文件后失败。测试显式使用捕获的真实解释器启动 worker；保留实际 broker、解析、渲染及全部产物断言。该文件 44 passed；预绑定非空 extension runtime identity 的独立检查 1 passed。没有改产品冻结路径，不能据此宣称 Windows EXE 通过。

生命周期是新增实证产品缺陷，因此修复后建立新的稳定集成里程碑，允许重跑一次全套。新 runner 增加仅写 `.state` 的当前测试项/失败即时记录，保留 harness 哈希；不改变产品或测试 fixtures。

## 收尾补丁与验证范围收敛

第二轮主套在稳定快照 `725c89e41c566389a28e0d98bbef689abfb4f49691f61bbdd9218383de32f8f1` 上运行 4709.52 秒，前后 HEAD/文件哈希一致。用户指出持续修改/测试后，协调者主动停止过宽检查，最终约 78%，退出码 -15，明确为 **UNVERIFIED**；acquisition_ui 未启动。这是验证安排范围过大的结果，不是一次完整通过，也不是在测试期间持续修改源码。保留 `integration/full-result.json`、`full-main.log` 与失败记录，不再重跑全套。

该轮仅观察到两条失败：一条签名检查仍指向已拆分的注册 facade，修正为检查实际 `_prepare_file_data` owner 并保留委托与禁止 TypeError 文本判断的断言；另一条精确提示顺序遗漏新增取消提示和 HEAD 已存在的项目持久化提示。仅更新测试预期，不改变提示排序或降低断言。

另一个只读退出探针发现 BatchSheet DBC 取消后立即关闭最后窗口，事件循环可能先于监督线程退出，留下一次自有 worker 孤儿；探针已清理其自身进程。修复先在隔离副本准备，主套停止后才合入：Sheet 保存无宿主强引用的关闭意图，取消后等待 drained 再继续关闭；MainWindow 在已完成 dirty/Batch runner 离开决策后保持事件循环，直到 DBC 回收。Sheet 自身 close/reject、取消后关主窗及重入都纳入测试。

主工作区最终针对性组合：**54 passed in 20.89s**，证据 `integration/post-gate-focused.log`。包括 Batch DBC owner、真实进程退出、Batch 关闭、dirty guard、弱宿主 GC、状态归属、import/lambda 边界及上述两条修正后的断言。两个补丁共六个文件，合入前后逐文件校验了隔离交接的 SHA256；`integration/post-gate-patches.json` 记录范围。没有重新跑主套，也没有将隔离副本的通过数冒充最终工作区结果。

最终真实 Cocoa 退出探针 `batch-parent-exit-cocoa/20261117-133315/report.json`：idle、读取中关闭、取消后关闭、手动等待回收对照四种场景全部退出码 0；aboutToQuit 和 exec 返回时 busy=False、线程已停止、worker 不再存活，未触发探针兜底清理。四个生命周期 owner 的前后 SHA256 相同。该结果与 offscreen 的五条真实进程退出测试分别保留，不能替代 Windows Job/EXE 验收。

## 未完成的验收与能力边界

- 完整主套及其后独立 acquisition_ui：UNVERIFIED；本轮已停止，不继续扩大验证。既有 Replay focused 结果仍独立有效，不能替代采集 UI 全套。
- 计划原列逐格式取消/退出矩阵未全部执行；实际是格式往返矩阵加共享监督层故障注入。
- Windows 原生 wheel 和新鲜 Full/Lite/Modular windowed EXE：UNKNOWN。尝试 `prlctl start 'Windows 11'` 返回 255 / `Operation canceled`，随后 exec 提示 VM 未启动，仍处于 suspended。未反复启动；当前 macOS wheel 不能用于 Windows。
- OS 硬内存限制、持久 mmap 交接不属于本次已交付能力；GUI 超时延长交互有 focused 与 Cocoa 实测，Windows 原生交互仍待验收。

资源和取消边界：Windows Job 当前用于进程树生命周期，未设 OS 内存硬限；macOS/Linux RSS 为轮询观察。父端路径解析/stat、参数/结果文件 I/O 和临时目录清理仍是同步文件系统调用，断开的 UNC 共享可能阻塞这些步骤，不承诺任意 UNC 情况下 3 秒取消。禁止将这些未验证边界写成全平台防 OOM 或全平台发布通过。
