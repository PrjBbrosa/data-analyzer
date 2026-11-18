# 大规模提交质量补强 Plan

日期：2026-11-18。状态：**已按任务实施，交接点 partial，未发版**。执行记录见 [验证摘要](../verify/2026-11-18-large-commit-quality.md)。基线`main@b802b382e38cedc896af4f34f51637aecd819238`，改动尚未提交。

合同：[Spec](../specs/2026-11-18-large-commit-quality-spec.md)。证据：[Review](../reviews/2026-11-18-large-commit-quality-review.md)。本计划补充[原生采样收尾 Plan](2026-11-18-mf4-native-completion-plan.md)，优先处理R01–R07；旧C1–C7按当前成果接收，C6/C7未完成项继续有效。旧文档不改写为当前已通过。

## 1. 执行组织与范围

默认串行执行。owner是代码责任边界，不表示已分派agent；本轮没有启动子agent。共享`analysis_signal_prepare.py`、`window.py`、`_frf_mixin.py`由同一集成人协调，每个任务完成合同和focused后再交接，不同时修改。

顺序：**T0证据接收 → T1显示坐标 → T2请求预算 → T3滤波质量 → T4 FRF原点/轻量描述 → T5 Replay选择 → T6帮助 → T7定向集成与余项交接**。前三个实际修复优先处理P1；T4接收T2预算接口，T3接收T1显示绑定，T5保留已有导入生命周期。

不修改native默认政策、版本号、用户原始数据、ink/AA门槛；不扩展分数延时或全格式迁移。不要重修已经通过的RPM解包、prepared Fs、整数精度、抗混叠频带、GUI Excel和逻辑取数。Review S01只在相关owner本来需要改动时补边界回归，不新增`order_time`范围功能。

运行focused时使用项目venv和隔离设置：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本任务测试> -q --tb=short`。真实Cocoa另开进程将平台改为`cocoa`，使用隔离QSettings与明确Qt所有权，退出时回收timer/worker和deferred delete。

## 2. T0：接收成果，固化可失败的真实路径

Owner：集成负责人；仅`.state/`证据与对应owner测试。

1. 检查当时HEAD、branch、dirty和pytest进程，保留`CSER TTR/`等无关文件。若基线已变，逐项核对R01–R07是否仍成立；不按旧行号盲改。
2. 接收Review的196/362/256通过组、3个帮助失败、2个Cocoa恢复、9个Replay观察；不相加为全套，也不为Task0跑全套基线。先在即将修改的owner增加失败测试/可重复probe。
3. R01/R02/R05使用报告的小型MF4输入，经正式broker和真实widget路径；R03/R04/R06使用小数组及production caller spy。临时脚本在`.state`，持久回归放现有测试owner；不可依赖本机未提交的旧probe文件。
4. 每条新测试先看到与报告相同的失败，再修代码。数值测试冻结独立期望，不仅以另一路当前实现作为oracle。现有红测不设xfail、不删约束。

Exit：输入、调用链、预期/实际、源码快照清楚；没有复现的项标needs investigation，不据历史记录擅自修复。T0不要求先把其他owner测一遍。

## 3. T1：修正显示绑定与画布消费（R01）

Owner文件：`ui/time_curve_bindings.py`、必要的`ui/time_xaxis.py`、`ui/pg_canvas/overlay_axes.py`/`renderer.py`；`ui/main_window/window.py`只做绑定接线。路径均位于`mf4_analyzer/`。

- 先在`tests/ui/test_native_signal_consumers.py`/`test_pg_timedomain_canvas.py`用Custom-X数值断言实际PlotDataItem，覆盖首次attach与refresh；不能只断言上层rows。
- 扩展现有绑定承接实际显示X/Y、记录索引与原始quality/query，避免canvas无条件换回`display_time`。保留cursor、marker和断线，不通过删除query修表象。
- 覆盖Time-Y/Custom-X选区、invalid/复位、单点、同名跨源以及View恢复。涉及新状态时唯一owner初始化/清理；不增加跨mixin隐式属性。
- 用正式native导入的Cocoa MainWindow完成angle 10–19.99反例、View切换及保存恢复，记录实际曲线数组/轴范围和截图。

Focused：上述新增用例与`tests/ui/test_mf4_native_product_path.py`相关入口；涉及恢复则运行`tests/ui/test_mf4_native_project_migration.py`相关用例。Boundary：`tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_main_window_state_ownership.py`，以及`test_pg_timedomain_canvas.py`中既有恢复settle/paint timer保护。未改QSS不运行额外样式矩阵。

Exit：Spec §2通过；初绘与刷新使用angle且gap/marker不回退，原始buffer不变；Cocoa结果单列，不以offscreen代签。

## 4. T2：请求总预算与生产接线（R03；衔接旧C6）

Owner文件：`analysis_signal_prepare.py`、必要的中立`io/import_limits.py`与资源调用接缝；`batch_compute.py`、`ui/main_window/_frf_mixin.py`薄接线。不能把DSP放进IO/UI，也不能把导入一次性账本冒充应用级释放账本。

1. 在`tests/test_analysis_signal_prepare.py`增加三条红测：同轴pair合计超额、两点高目标率输出超额、低预算拒绝前hash次数为0。另覆盖pair第二侧失败无残留、预算边界和非法shape/Fs；用spy，禁止大内存耗尽测试。
2. 冻结一份请求成本描述：输入/输出数量、驻留共享buffer、拟新增copy/mask/hash/grid/算法工作区、重叠峰值。计算数量先用标量和检查过的索引，不生成目标数组。区分输出计费字段与峰值估计。
3. 单路与pair共用准入及生命周期；左右不能各拿完整额度。把hash与物化移到准入之后，保留原始数据及错误分类。取消/异常必须释放本请求占用，结果持有转交唯一owner。
4. GUI/Batch从同一中立资源入口取有效额度并传入准备，测试生产调用传参及资源错误反馈，不仅测试helper接受`byte_limit`。T4后新增FRF描述路径继续复用此接口。
5. 对接旧C6：应用级存活源、绑定结果、cache、同时任务仍由其统一reservation/LRU工作承担。若该接口尚缺，在同一owner下补齐必要接缝并明确余项；不另建平行资源框架或提高上限。

Focused：`tests/test_analysis_signal_prepare.py`、`tests/test_import_limits.py`；生产接线用`tests/test_batch_source_integration.py`及`tests/ui/test_native_signal_consumers.py`/`test_frf_main_window.py`相关用例。Boundary：`tests/test_native_import_boundaries.py`、`tests/test_signal_no_gui_import.py`；若改变Batch状态/错误出口，加`tests/test_batch_run_reporter.py`。

Exit：小预算在hash/DSP/grid前拒绝、pair总量正确、GUI/Batch确实受控，正常请求通过。局部修复可关闭R03反例；旧C6未完成则资源整体仍partial，不签发峰值或20轮RSS通过。

## 5. T3：时域滤波质量准入（R02）

依赖T1显示绑定和T2准入。Owner文件：`ui/time_curve_bindings.py`、`analysis_signal_prepare.py`的既有中立质量准备、`ui/main_window/window.py`滤波接线；只有算法owner证据要求时才改`signal/filters.py`。

- 在`tests/ui/test_time_filter_overlay.py`与`test_native_signal_consumers.py`增加真实生产绘图反例：invalid千值脉冲不能进入滤波；检查无companion、有原因且原始曲线保留。不要只mock滤波输出。
- 在准备owner冻结选区/halo、精度、Fs、shape和quality的拒绝语义；先验证再调用现有滤波。合法选区不被远处坏点牵连，不滤全源再裁图。
- 复用现有绘图issue反馈；滤波关闭/失败、换View、换源后清掉旧companion，不影响合法通道。Custom-X伴随滤波仍按原时间计算。
- 用零输入oracle、NaN/Inf、复位、短段、int64精度边界覆盖数值；真实Cocoa重做50Hz六阶反例和合法段恢复，保存数组及截图。

Focused：上述UI owner、`tests/test_analysis_signal_prepare.py`新增质量用例、`tests/test_filters.py`受影响算法合同、`tests/ui/test_time_filter_panel.py`相关状态。Boundary：`tests/test_signal_no_gui_import.py`、`tests/ui/test_main_window_state_ownership.py`；不重跑全部UI。

Exit：Spec §3通过；没有把无效值改零/删点拼接的隐式修复，拒绝后原始曲线可用且说明明确。

## 6. T4：FRF原点、范围与轻量描述（R04/R06）

依赖T2，沿同一DSP owner串行完成。Owner文件：`analysis_signal_prepare.py`、必要的`io/signal_access.py`已有元数据接口、`ui/main_window/_frf_mixin.py`与`batch_compute.py`。共享契约由此任务统一，不让GUI/Batch各自校正时间。

1. 先用`tests/test_batch_source_integration.py`及`tests/ui/test_frf_time_range_surface.py`固定`.1001`生产反例；在`tests/test_analysis_signal_prepare.py`固定原origin/网格/halo及真正fractional offset拒绝。
2. 引入/扩展既有请求描述，保留原始时钟、双方identity/revision、segment及目标网格边界。按共同网格取halo和有效输出；从数值上证明合法范围请求，不通过放宽原点容差蒙混过关。
3. 先在生产`_frf_prepare_native_pair(materialize=False)`及cache lookup增加hash/copy/抗混叠计数红测，同时覆盖同轴与跨率。将描述与物化分开，预览不走两次`load_native_channel`重准备；待扫描质量留待受控worker验证。
4. 确保lookup描述与实际作业的参数/有效范围规划一致，双方revision变化及派生修改使cache失效。准备语义改动更新数值policy/cache身份，不把缓存对象写入项目。
5. 用2/4/8比率、快慢两方向、非零origin、known gain/delay多正弦验Spec §5数值门槛；接收已有抗混叠oracle，不重写冻结滤波器。真实GUI范围输入与BatchRunner正常入口各至少一例，不仅调用私有方法。

Focused：上述文件；`tests/ui/test_frf_main_window.py`、`test_frf_coordinator.py`及`test_frf_explicit_result_contract.py`按实际改动选用，保留prepared Fs和旧同轴行为；必要的cache回归在`tests/ui/test_analysis_cache_pinning.py`。Boundary：`tests/test_native_import_boundaries.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`；Batch报告行为变更才加reporter gate。

Exit：任意合法范围不再制造“原点不一致”，数值oracle通过；同轴/跨率真实轻量caller完整hash/copy/DSP次数均为0。数据规模性能只报告实测，未做原C6/C7性能矩阵则仍UNKNOWN。

## 7. T5：Replay段选择和播放状态（R05）

Owner文件：`acquisition_capture/backends.py`、`acquisition_ui/replay_tab.py`及现有Replay DTO；新控件沿现有Qt组合，不增加采集数据框架。

- 在`tests/acquisition_ui/test_replay_tab.py`先固定加载复位文件后Play错误启用的红测，验证直接play也受守卫；backend单元覆盖保留事件到所选段的转换。
- 为`segment_required`增加明确的待选状态、段列表与回调；展示时间范围/记录数/质量。按原轴身份处理段选择，不能跨独立时钟用局部index自动合并。不同轴关系无法支持时给明确原因并保留该验收项，不宣布全矩阵完成。
- 选中段后从已保留store/events构造播放源，不重开解析worker；空段禁用、有数据才ready。切段停timer/backend并清buffer；重复时间按记录顺序，invalid不造值，时间条以所选段为准。
- 覆盖选择取消、全invalid、单点、多率、不同复位关系、播放/暂停/切段/重播、替换文件和父关闭。继承已修broker回收/迟到守卫，只有新反例才改导入coordinator。
- 用真实Cocoa ReplayTab完成6点复位反例：两段各发出对应3个值，有可见选择入口，未选不能播放。保留截图和实际输出事件，不仅看状态文字。

Focused：先单独运行`tests/test_acquisition_capture_backends.py`与`tests/test_mf4_native_export.py`中的native Replay/segment用例；涉及控制器状态时加入`tests/test_acquisition_capture_controller.py`相关用例。退出后新进程运行`tests/acquisition_ui/test_replay_tab.py`，不能把采集UI与主套放同一个pytest进程。Boundary：若触及native导入接缝，主进程加`tests/test_native_import_boundaries.py`；新增信号连接不得使用lambda。

Exit：Spec §6可操作状态闭环；所有声称支持的时钟/段组合逐项有证据。未支持的独立时钟映射保留partial，不以单轴例成功关闭多轴余项。

## 8. T6：帮助、短提示与现有红测（R07）

Owner文件：`ui/hints.py`、`ui/quickref.py`、`help/frf-guide.html`及受影响帮助页；对应`tests/ui/test_hints.py`、`tests/test_help_content.py`。T1–T5交互定型后一次同步。

- 恢复WWT提示职责，native导出使用对应说明和生命周期；4条超宽短提示压缩到既有18字宽约束，详细信息放quickref/帮助。
- 更新FRF旧全文断言为当前同轴/显式整数比/拒绝未知关系的语义测试，保留相位安全与用户明确请求的约束。不能删除失败断言又不补真实合同。
- 段选择、滤波质量反馈和多率入口差异同时进入hints/quickref；不把尚未验收的对齐或默认启用写成已完成。

Focused：`tests/ui/test_hints.py`、`tests/ui/test_quickref.py`、`tests/test_help_content.py`，新增交互若影响面板则选`tests/ui/test_quickref_panel.py`相关用例。没有新增行为的措辞调整不另造测试。真实Cocoa查看受影响短提示和Replay控件布局，按几何/可读性记录，不为措辞跑全套。

Exit：Review列出的3个当前红测全部通过，语义正确且长度约束未放宽；hints/quickref与实际产品操作一致。

## 9. T7：定向集成、旧C6/C7余项和交付

Owner：唯一集成人；负责验证状态和文档更新，不另起功能清理。

1. 在各任务focused通过后，仅检查交接点：R01+R02的Custom-X滤波/quality，R03+R04/R06的FRF真实预算/预览/物化，R05选择/重载与导入回收，R07当前入口说明。用同一份稳定源码记录HEAD、dirty文件及必要hash。
2. 复用本轮未受改动影响的导入、MDF安全、Windows脚本、db参考、UltraView命中和对话框恢复成果；不因“质量补强”再次全部跑一遍。出现新问题先登记，不自动扩展到无关模块。
3. 每个R编号列owner测试、真实操作、数值/截图及平台证据，分别PASS/FAIL/partial/UNKNOWN。移除调试临时产物，证据只放`.state`；需要耐久交付的摘要置`docs/analyzer/verify/`，不提交大截图/日志。
4. 旧C6继续：全局资源共存计费、按字节LRU、20轮生命周期、双游标/Replay/导出热路径。旧C7继续：完整编辑保存重开、Pin/比较矩阵、事故样本及图2、原Spec性能、Cocoa与新鲜Windows Full/Lite。逐项列未验原因，不用本轮有限Cocoa截图填满平台矩阵。
5. 本计划局部修复完成不强制新增全套基线；若进入旧C7的正式整合/发版里程碑，由唯一owner在稳定候选跑一次全套。先检查同checkout pytest进程/权威结果，主套`--ignore=tests/acquisition_ui`完成后独立新进程跑采集UI；前后快照变化、crash、timeout或中断均UNVERIFIED。不得并发全套或反复重跑同一通过快照。
6. 发版、默认策略变化仍需旧完整门禁；未通过则只交付明确修复和剩余项，不自行宣称完整native优化完成。提交/推送仍按届时用户授权和文件范围执行。

本轮文档交付检查：全文核对Review→Spec→T1–T6映射、旧已修项与C6/C7继承、路径/链接和新文件whitespace；不因文档再跑运行测试。检查lesson状态，复用已有原生质量/真实消费者/准入规则，无需再写同义lesson。
