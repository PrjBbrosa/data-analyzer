# 8.4.8 导入与对话框后续优化 Plan

日期：2026-11-17。状态：**源码已按本计划落地，R01 未关闭**。结果见 [执行报告](../reviews/2026-11-17-import-budget-and-dialog-recovery-report.md)。下文保留当时的任务合同。

依据：[Review](../reviews/2026-11-17-import-budget-and-dialog-regression-review.md) · 执行合同：[Spec](../specs/2026-11-17-import-budget-and-dialog-recovery-spec.md)。本轮只交付分析/文档/本地诊断，未授权实施、提交、推送、发版或启动agent。

## 1. 顺序与交付边界

优先级首先是MF4能安全打开（R），同时把两个已定位的UI缺陷做成可独立交付的小修（U）。默认单一实施者；不把所有旧对话框一次性重写，不重跑无关全套。

```text
T0 冻结本次失败与资源证据
 ├─ T1 内容型提示与工作窗几何分离 → T2 导入进度布局/状态
 ├─ T3 资源错误结构与显式重查重试（UI展示依赖T1）
 └─ R 复用原生采样Plan M0–M6，补目标低预算/Windows门禁
T1+T2+T3 → T4-U 真实平台UI验收
R + T4-U → T4-R 文件可打开、数据正确、Windows交付验收
```

T1–T3不等待整项原生采样迁移完成；UI改动可先验收。**只完成U不能宣布图1已解决。** 原生采样涉及全部取数消费者、分析与旧项目兼容，不将它伪装成几行预算修复，也不再复制一份可能漂移的M0–M6执行计划。

## 2. T0：固定现场与最小可重现失败

Owner：本任务测试fixture/`.state`证据；产品先不改。

- 重新记录HEAD、dirty文件与相关源码hash。当前调查基线为`c126fcae`；保留`CSER TTR/`及其他并行变更，不stash/reset。
- 记录用户已确认8.4.8；如Windows环境可得，补包类型/hash、Qt/PyQt、平台style、有效字体、DPR与availableGeometry。不能因这些缺失延误源码可复现的T1。
- 将本轮生产组件探针转为**会失败的行为测试**：短未保存提示最终高度符合内容公式；内容型窗口允许高度<200；工作窗仍拒绝真正退化尺寸；frame二次修正不把短提示拉高。
- 进度测试覆盖未知阶段、已知阶段、读取完成但注册失败、取消后下一个任务；真实QSS下测轨道与按钮右端。不要用截图中绿色块宽度作为进度断言。
- 预算固定为截图值；历史事故样本仅本机读取，记录hash，不进Git。匿名fixture验证同样“原生小、公共表大”的计费路径。计费Spy与RSS探针分开，记录同一时间线的父/worker峰值，不相加各自独立最大值。
- 核对图2文件是否可取得，缺少时登记外部输入UNKNOWN；本轮此前样本只用于图1精确错误复现，不能偷换文件。

Focused既有：`tests/ui_kit/test_message_dialog.py`、`tests/ui_kit/test_dialog_geometry.py`、`tests/test_import_limits.py`、`tests/test_mdf_reader_safety.py`。拟新增断言放在这些owner及`tests/ui/test_import_coordinator.py`；真正新组件的测试在T2添加。

Exit：每条发现有复现/状态/owner，现有通过与新红测区分。没有通用全套基线任务。本轮已得到75项既有owner通过，但不能当未来变更后的结果。

## 3. T1：修短提示尺寸，保留工作窗保护

Owner：`mf4_analyzer/ui_kit/dialog_geometry.py`、`message_dialog.py`；必要的Batch/UltraView用途接线由同一实施者整合。不得修改CLAUDE.md。

1. 给几何应用路径增加显式用途或约束，兼容既有导出与调用默认。短消息框明确走content策略；工具窗按自身内容minimum和已有恢复流程工作。
2. 首次拒绝、frame补偿、延迟relayout都沿同一策略。不要全局删除200保护，不按中文title判断，不仅设置`setFixedHeight(134)`。
3. 保留AppMessageDialog正文可滚动、按钮独立、平台按钮顺序、默认/退出/一次性结果；短→长→短必须回到内容高度。
4. 复核当前实际helper调用者，按content/workspace/popup/embedded分类。只迁移有证据需要的调用者；其余保留并记录，不用大规模类重构解决一个用途参数。
5. 本次自有消息框关闭无功能的帮助问号。若共享guard合同需文档说明，先比较AGENTS和CLAUDE的语义；没有必要不改指令文件，更不能擅改CLAUDE。

Focused：上述两个ui_kit owner、`tests/ui/test_tool_window_screen_fit.py`、`tests/ui/test_project_dirty_guard.py`、`tests/ui/test_layout_probe.py`。按实际改到的caller补其单个owner，不能直接跑所有tests/ui。若改QSS才加`tests/ui_kit/test_qss_border_shorthand.py`。

Exit：Spec G01/G02，生产QSS渲染/几何通过；真实Cocoa短框确认。Windows留给T4单独判定，不能凭offscreen宣布修好Windows。

## 4. T2：统一导入进度的布局和状态

Owner：拟新增`mf4_analyzer/ui_kit/import_progress_dialog.py`和`tests/ui_kit/test_import_progress_dialog.py`；`ui/main_window/import_coordinator.py`负责请求显示状态；现有`_project_io_mixin.py`/`acquisition_ui/replay_tab.py`仅接线。

1. 建立只展示snapshot/发送取消意图的控件。复用QSS/token与几何content策略，标题、bar、footer共用同一内容列。显式处理长文件名/完整路径访问与标题栏关闭。
2. 同一请求的stage/fraction供状态栏和弹窗。单一owner保存计时与终态，不增加跨mixin可变状态簇；未知busy、阶段百分比、注册、成功、失败、取消语义按Spec。
3. broker返回1.0不触发导入整体成功；现有事务完成后才终态。程序关闭不能触发取消；父销毁/目标失效/队列后续任务沿既有回收合同。
4. 接普通打开（含拖入/最近）、项目恢复、Batch DBC预读及Replay四种真实路径。Batch runner自己的reporter不改；Lite不导入acquisition_ui。
5. 失败或超时选择时进度进入等待处理，防止busy窗口在错误提示后继续制造正在加载的错觉。

Focused：拟新增组件owner；既有`tests/ui/test_import_coordinator.py`、`tests/ui/test_load_progress_and_heavy_confirm.py`、`tests/ui/test_compute_progress_integration.py`、`tests/ui/test_mf4_import_flow.py`；接线后分别跑`tests/ui/test_project_session.py`中恢复相关用例、`tests/ui/test_batch_blf_dbc_context.py`及独立新进程的`tests/acquisition_ui/test_replay_tab.py`。

Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`；新模块冻结收集涉及时跑`tests/test_packaging_imports.py`/`tests/test_import_packaging.py`。只改UI不要求Batch数学或renderer parity。

Exit：Spec P01/P02，实际按钮取消/关闭测试及几何/像素证据；busy轨道和满条可区分。若Windows未测，只标U源码完成，P01 Windows待验。

## 5. T3：资源错误结构化与安全恢复

Owner：`io/import_limits.py`、`io/import_worker.py`、`io/import_process.py`、必要的`io/import_transport.py`；`ui/main_window/import_coordinator.py`、`_project_io_mixin.py`；错误展示复用ui_kit。

1. 在异常/有界envelope保留资源类型、单位、需求/上限/阶段/分项，旧message/detail保持兼容。把channel count与byte用法明确分开；MemoryError/磁盘满/未知字段不生成假数字。
2. 加协议红绿测试：结构化错误跨真实子进程不丢信息；缺字段、坏字段、超长详情、不支持kind可控；程序错误仍保留traceback，不能都变成resource_limit。
3. 普通文案显示未导入、MiB及可行动建议；技术label放详情，动作有稳定ID。保留纯文本和可复制完整信息，不自动发送日志。
4. “重新检查并重试”只面向可重新评估的内存预估拒绝：先确认旧worker回收、源/target有效，再取得新default_limits并生成新request。不可使用旧request.limits快照来伪装重查，也不提高默认比例/硬上限。
5. 多文件只重试失败项，已成功项目不重注册；切项目/删目标取消旧意图；失败不写最近文件/成功toast。超时延长与内存重查保持独立语义。
6. 同步hints、quickref、主帮助/用户指南受影响入口。新能力尚未实现前，不能先将帮助写成用户已经可以重试。

Focused：`tests/test_import_limits.py`、`tests/test_import_process.py`、`tests/test_import_transport.py`、`tests/test_import_resource_preflight.py`；UI用`tests/ui/test_import_coordinator.py`、`tests/ui/test_import_diagnostics.py`、`tests/ui/test_mf4_import_flow.py`以及对应帮助检查`tests/test_help_content.py`。

Boundary：`tests/test_native_import_boundaries.py`、`tests/test_signal_no_gui_import.py`和上述UI ownership/import/lambda gates；只在Batch编排实际变更时补`tests/test_batch_run_reporter.py`。

Exit：Spec E01/E02。资源仍不足时拒绝是正确终态；这一阶段不保证原文件成功，不能关闭F1的低内存根因。

## 6. R：MF4低内存根因闭环，复用既有M0–M6

Owner/文件/逐阶段测试沿用[原生采样Plan](2026-11-17-mf4-native-sampling-plan.md)，与本计划共享IO/coordinator文件时按顺序整合，不同时维护两个预算实现。

实施前重新校准该历史计划的前置状态：import-hardening已在`161e5387`集成；原文“另批未提交”是当时快照，不是当前事实。其原生数据模型、数值oracle、项目迁移与消费者门禁依然适用，本轮不改写历史记录。

附加本次验收约束：

- M0：加入Review中精确字节账本、固定498,988,944 memory/≤249,494,472 output的匿名与原样本场景；冻结支持范围及Windows目标环境，先分项计费与同时峰值观测。
- M1/M2：原生数组和真实生命周期账本替代公共表展开；复用结构化资源错误。不得只把`copies=3`改小，或在native旁保留整份隐藏shared table。
- M3–M5：时域、分析、游标/统计、项目、导出、Replay按原计划闭环。恢复原来跳过的单点/通道时，不能为了“保持52信号”丢掉它们。
- M6：在正式adapter→broker→transport→GUI路径按固定预算成功；源hash不变且逐点正确。图2文件有独立hash与结果，缺失仍标UNKNOWN。Cocoa与Windows各自测内存/交互，不用23.9MiB buffer统计代替进程RSS。
- 无法满足目标预算时先报告实际必需峰值和瓶颈，状态needs revision；禁止事后调大测试预算或开启不安全绕过刷绿。

本轨道的最终成功条件为Spec R01及原生Spec F01–F12/性能平台合同。原生默认切换只在所有必需消费者和兼容门禁通过后；U的提前交付不授权半迁移路径成为默认。

## 7. T4：平台验证、关闭条件和验证成本

T4-U聚焦三个截图及相邻导入入口；不等待R才检测UI。先源码focused/boundary，再Cocoa生产组件，再新鲜Windows Full/Lite。记录HEAD/dirty指纹、包hash、Qt/style/字体/DPR、实际工作区、客户区/frame/正文/bar/button几何与截图。

Windows100%必测，再选125%或150%；普通/紧凑工作区、长文件名、短提示、长详情开合、未知/已知进度、成功/失败/取消。自动断言右边缘差≤1逻辑像素、短框多余高度≤8，并实际点取消/保存/不保存/安全退出。不得为了截图误点用户未保存项目，使用隔离测试工程。

T4-R需要R轨道及Windows原文件导入；8.4.8旧包与新candidate分列。没有Windows环境则其状态UNKNOWN，不重复无效启动VM、不用Mac截图冒充。没有图2原文件则该样本项UNKNOWN，列明无法验证范围。

U改动只运行相关owner/boundary与平台矩阵，**不要求全套**。R是跨IO/数据/分析/项目的迁移，完整集成门禁只复用原生Plan M6的唯一一次：检查pytest进程及cwd，稳定源码前后hash；先主套`--ignore=tests/acquisition_ui`，完成后另启进程跑`tests/acquisition_ui`，不得并发。中断/崩溃/快照漂移为UNVERIFIED，不反复重跑同一套。

回退：按本任务文件/提交单元撤销候选启用点，保留既有隔离、数组安全修复及工作窗保护，不回滚整个8.4.8，不改用户文件。提交、版本升级、发布另遵循实际授权和版本合同，本计划不自动触发。

## 8. 本轮文档交付检查

本轮已执行：精确预算错误复现、生产AppMessageDialog几何/截图及进程内反事实、进度组件range/几何探针、75项既有ui_kit owner测试。它们是Review证据，**不是本计划实施后验收**。

完成前检查三份文档全文、相对链接/源码符号/既有测试路径、拟新增标记、F→Spec→任务映射、低预算与UI分层状态一致性、`git diff --check`。无产品可执行变更，文档本身无需运行runtime/full suite；此前75项仅用于证明测试漏检，后续不重复。

发现的共享guard用途误扩大是可复用教训，按project-lessons记入短条目；不将尚未实现的修复测试写成已通过。临时脚本/截图/JSON留`.state`，不加入Git。
