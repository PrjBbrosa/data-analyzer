# 测试基础设施横向审查与优化计划

- 日期：2026-09-19。状态：**审查完成；修复待实施**。本轮只写计划和 `.state/` 诊断探针，没有修改正式测试或产品源码。
- 基线：`c75c47e3cba6e41fd5208affaa966f972336b434`，叠加当前未提交的 Pin 实现；不是干净的发布基线。执行前重新记录 HEAD、dirty 文件及内容指纹，不覆盖其他任务修改。
- 目标：解决测试自身的隔离、生命周期、等待与诊断缺陷，使失败可定位、运行有界；不是通过跳过测试、放宽断言或改业务行为来“全绿”。
- 执行方式：单协调者，顺序小步；不要求 agents，不自动提交或发布。与 Pin / View 结构治理对 `tests/ui/conftest.py` 的修改串行协调。

## 1. 审查结论与证据边界

确有测试基础设施缺陷，且不止一个。但不能把所有 `F` 或之前应用闪退都归因于测试。

本次检查了根 collector shim、三处目录 conftest、pytest 配置、隔离守卫、代表性 Inspector/ChartStack/FFT/Batch worker/性能测试，并扫描 `tests/**/*.py` 的直接阻塞式 subprocess 调用。**这是横向基础设施审查，不是逐条审完所有业务测试断言。** 对 grep/AST 命中的候选区分人工核查与待确认项。

上一轮主套件约 79% 被中断，结果是 **UNVERIFIED**；不是完成、通过或确定死锁。原进程 PID 517 在约 95 分钟时 CPU 接近 100%、RSS 约 4.4 GB，日志仍从 75% 推进到 79%。两次原生采样主线程分别落在 `QApplication.setStyleSheet/setStyle`，不支持把这次慢跑解释为等待用户点弹窗。后台终端显示的 2h48m 也不是该 pytest 进程的实测运行时长。

### 1.1 分级发现

| ID / 级别 | 发现、影响与证据 | 判定 |
| --- | --- | --- |
| F01 / P1 | `tests/ui/test_inspector.py:2532`、`:2558`、`:2849`、`:2918`、`:2946` 直接构造真实 `QSettings("MF4Analyzer", "DataAnalyzer")` 并 `remove()` 折叠状态或预设键。`tests/ui/conftest.py:217` 仅替换产品 factory，挡不住测试自己的构造。可修改开发者偏好，并且清理的不是控件实际使用的临时 store。 | **源码及只读路径探针确认**；没有运行这些破坏性节点。 |
| F02 / P1 | `tests/ui/conftest.py:273` 的 ChartStack 清理只有 `deleteLater/processEvents`；`:104` 放开强引用并 GC，也未显式清空 DeferredDelete。四节点探针在一个 item 完整 teardown 后仍有 1329 widgets / 101 top-levels；显式 DeferredDelete drain 后为 0 / 0。旧对象会进入下一测试，也扩大后续全局 QSS 工作量。 | **可复现的跨 item 延迟销毁**；不是无界泄漏证明，也未量化它解释了多少全套耗时。 |
| F03 / P1 | `tests/ui/conftest.py:164` 每次 exec 启动不可取消的 `singleShot(800)`，成功返回不撤销。复用同一 dialog 时，第一次残留回调误关第二次 exec；第二次自身的 timed_out 标记仍为空，因此静默返回 Rejected。 | **新探针确认**：首次 Accepted；第二次计划 650 ms 后 Accepted，实际约 498 ms 被 Rejected，无超时异常。 |
| F04 / P2 | 全局样式恢复发生时生命周期 pin 尚持有旧控件；长跑的两个原生采样均显示 QSS/style 热点。`tests/conftest.py:52` 对“setup 时尚无 app”的分支仅清 QSS，遗漏后来创建 app 的 style/font/palette。UI 与 tests 层恢复是条件式，不能简单称为每项重复 polish。 | **热点采样及源码确认**；具体长期保留 owner、各阶段成本尚待计量。 |
| F05 / P2 | `tests/ui/conftest.py:229` 改 QSettings 默认格式/路径不回收；`test_qsettings_isolation.py:39` 允许整个 `tmp_path.parent.parent`，并未证明逐 item 隔离。`test_fft_cursor_layout.py:319,375` 使用固定 `/tmp/*.ini`；`test_chart_stack.py:3242,3260,3276` 使用固定 `.pytmp/test_hints/*.ini`。 | **源码确认**的隔离缺口；固定路径具体失败顺序尚未复现。 |
| F06 / P2 | `test_batch_runner_thread.py:58–76,108–118` 只等 result 信号，未以 finally 保证线程退出。业务结果到达不等于 `QThread.finished`；等待超时或断言失败时更缺少取消/收尾保护。 | **源码确认的异常路径风险**；未声称已复现本次闪退。 |
| F07 / P2 | 43 个直接 `subprocess.run/check_call/check_output/call` 调用点中，21 个未给显式 timeout，包括 `tests/test_conftest_autouse_scope.py:76` 的嵌套 pytest 和 import boundary 检查。子进程卡住可无限占住一个节点。 | **AST 清查，代表点人工核验**；不是所有 subprocess API/别名的完整数据流分析。 |
| F08 / P2 | `tests/ui/conftest.py:118` 每项扫描整个 `gc.get_objects()`；`:115` import 的任意异常被吞掉，守卫可静默失效；`:126` 允许留下一个 filter，不能证明 item 无泄漏。另有两次 GC（`:105,346`），第一遍发生在 lifetime pin 仍持有时。 | **源码确认**；耗时占比未测，不能直接删 GC 或 filter 哨兵。 |
| F09 / P2 | `pytest.ini` 没有 phase 日志/栈超时配置；现有 modal guard 依赖 Qt 事件循环、只包 QDialog exec，挡不住 CPU 阻塞、其他嵌套等待或子进程。仅进度百分比无法区分 setup/call/teardown，也不能及时保留失败详情。 | **配置/守卫范围确认**，属于运行诊断与有界执行缺口。 |

P1 应优先处理：真实偏好安全、跨用例 Qt 所有权、守卫自身误动作；P2 按下述依赖收口。P1 不代表已经证明全部历史卡死/崩溃由这些位置造成。

### 1.2 本轮验证记录

1. 复用前轮两个原生样本：`/tmp/tracelab-pytest-517-sample.txt`、`/tmp/tracelab-pytest-517-sample-2.txt`。第一份 264 个主线程样本中 149 为 setStyleSheet、115 为 setStyle；第二份 178 个主线程样本为 setStyleSheet。
2. 前轮四个 `test_toolbar.py` 节点，观察版 4 passed / 2 warnings / 1.23 s；相同节点加诊断性 drain 为 4 passed / 2 warnings / 0.96 s。这是对象清理因果探针，**不是 22% 提速结论**，两轮并未控制系统负载/字体缓存。
3. 本轮 `.state/test-infrastructure-review/probe_modal.py`：fresh offscreen 子进程，外层 15 s 上限；复现 F03，正常退出。
4. 本轮只读 `probe_settings.py`：在隔离 fixture 已生效时，直接构造的 NativeFormat store 仍为 `~/Library/Preferences/com.mf4analyzer.DataAnalyzer.plist`，factory 为独立临时 INI。探针没有 set/remove/clear/sync 真实键。
5. 现有守卫聚焦运行：`tests/test_conftest_autouse_scope.py tests/ui/test_modal_exec_guard.py tests/ui/test_qsettings_isolation.py`，**5 passed in 1.92s**，外层 60 s 上限。说明已有守卫能通过，但尚未覆盖 F01/F03，不说明全套健康。

本轮没有重跑全套、整个 `tests/ui` 或那些会删除真实设置的 Inspector 节点。探针和原生样本为本机证据，不作为可移植交付物；实施时将故障场景转换成正式回归测试。

## 2. 不可牺牲的边界

- 保留 `_PINNED_TOPLEVELS` 的 paint 生命周期保护；不能先放掉引用再盲目 pump，也不能以删除 GC、关闭隔离换速度。
- 不把 `allWidgets()==0` 作为通用标准：session/module scope 的合法控件可以存活。应验证**本 item 拥有对象已销毁，允许存活对象回到明确 baseline**。
- 不遍历并强制删除所有 top-level、不调用 `QThread.terminate()`、不吞清理异常、不扩大 app filter 的允许数量。
- 保留 root `conftest.py` collector identity 修复；通过 fixture closure 比较检验，不通过固定测试顺序、sleep 或 xfail 掩盖。
- 遵循已有 QSS 隔离和 offscreen modal lessons，但修复守卫遗漏。历史 lesson 中整文件命令不替代当前聚焦门禁原则。
- 默认不引入 xdist 并行 UI，不把每个 GUI item 都拆子进程掩盖同进程污染；单独进程用于 native-crash/hang、import 隔离及既有 acquisition 边界。
- 不重新设计 DSP、不改变产品 Pin 行为，不在产品代码中加入 `if pytest`。守卫查询若需适配 Pin Router 拆分，与其单 owner 合同对齐，不维护第二套产品生命周期。

## 3. 实施顺序与任务

推荐：**T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7**。每任务先有会失败的回归/诊断证据，再改最小 owner。每轮 focused 通过即收口，不每改一处就全套。

### T0 — 稳定快照与最小证据集

**归属：** `.state/test-hardening/`（不提交）；必要的新基础设施回归文件。

- [ ] 确认无同 checkout 全套 pytest；记录 HEAD、dirty、相关源码/测试/config 的内容 hash、平台、Python/Qt/pytest/pytest-qt 版本。不得读取无关私密文件。
- [ ] 将 F01/F02/F03 转成最小回归：设置测试只能操作沙箱/替身 store；modal 测试包含早退后复用；Qt 生命周期测试观察完整 item teardown 后的 owned-object 状态。
- [ ] 生命周期/全局状态守卫优先用有外层 timeout 的最小 pytest 子工程测试真实 fixture 时序，不能在测试 body 尚未 teardown 时断言“清理完成”。
- [ ] 冻结 paint 存活、fixture re-entry、设置隔离、当前真实 QSS 几何的既有保护；故障复现红是预期证据，不改为 xfail。
- [ ] 先记录上一轮失败为 UNKNOWN 清单，不猜既存失败归属。无需全量 pre-change baseline。

**Gate：** 新回归先红；既有 collector/modal/settings 5 个守卫仍通过；必要的四节点 toolbar 序列。完成标志是可重复命中具体缺陷，不是再等到 78%。

### T1 — 偏好、路径和全局状态隔离（F01/F05）

**归属：** `tests/ui/conftest.py`、`test_qsettings_isolation.py`、上述 Inspector/FFT layout/ChartStack 节点及清查命中的测试；确有复用需求再加窄测试 helper。

- [ ] 将测试中直接 org/app 构造和固定 INI 路径迁到 `tmp_path` 或与产品 factory 相同的注入 store。需要验证持久化的测试在**同一测试自己的文件**上重开，不能连到开发者偏好。
- [ ] 扩查测试、测试调用的 tools 的 QSettings alias、直接构造、`setValue/remove/clear`；输出逐调用点 disposition。测试专用 org 也不得作为机器级持久化隔离。
- [ ] 加防回归检查：产品 store 不得从测试直接写入；factory 路径必须属于当前 item 的 `tmp_path`，而非 pytest session 的公共祖先；不同 item 文件相互不可见。覆盖 package re-export、batch factory、bare QSettings、持久化测试自己的 store。
- [ ] 显式恢复可恢复的默认格式；Qt 的 setPath 没有对称 getter，不假装能任意快照回滚。优先通过注入避免逐项改进程全局路径；确需 path 行为测试放 fresh 子进程。Windows native registry 与 macOS plist 都以“不得触及真实 store”为合同。
- [ ] 对已有真实用户设置**不自动 clear、不修复、不回写**；只消除未来污染路径，历史被删数据不能凭猜测恢复。

**Gate：** `test_qsettings_isolation.py`、`tests/test_conftest_autouse_scope.py`，迁移到沙箱后的精确 Inspector/FFT layout/ChartStack 节点；临时原生域 sentinel 或构造审计验证“测试未向真实 store 发出写操作”。不得为了验证先写开发者 store。

### T2 — Qt teardown 顺序、所有权与样式成本（F02/F04/F08）

**归属：** `tests/ui/conftest.py`、`tests/conftest.py`；新增 `tests/ui/test_qt_fixture_lifecycle.py` / `test_app_style_isolation.py`（拟建）；直接遗漏注册的测试 owner。

- [ ] 用 phase 计数确认当前 hook/finalizer 顺序及 pytest-qt 的实际版本实现；明确哪些对象属于当前 item、哪些由更长 scope 持有。`qtbot.addWidget` 是弱引用，不能当成已保证 Python 生命周期。
- [ ] 建立安全顺序合同：停止 owned producers/线程 → 保留强引用完成 close/待处理事件 → 调度 owned deleteLater → 有界排空 DeferredDelete → 恢复全局外观 → 最终释放 guard/GC 与验证。实际 hook 位置由顺序回归确认，不能仅靠 fixture 名字排序。
- [ ] 包括 teardown 新建的 parentless dialog/menu；销毁前检查 `sip.isdeleted()`，仅捕获已解释的预期 Qt wrapper 异常。长寿命窗口不得被 `_auto_discard_unsaved_project_on_close` 无差别改写/关闭。
- [ ] baseline widget/filter/timer/worker 差集验证；已注册对象即使测试异常也能清理。未注册残留应带 nodeid/type/owner 信息报错，而不是悄悄扫掉下一项的对象。
- [ ] 样式只在变化时恢复；统一明确 app-before/app-created-in-test 两条路径的 stylesheet/style/font/palette 基准。中立测试不应为了 snapshot 主动加载 Qt，但创建 app 的工具测试仍须受隔离覆盖；无法安全得到默认基准的路径显式进程隔离。
- [ ] 测量两次 GC 和全堆 filter 扫描成本，再合并冗余工作。优先使用 test-owned weak registry 或 scope 内构造跟踪，并用定期诊断全扫描交叉校验，不能只让新 registry 自证正确。
- [ ] filter guard 不吞任意 import error；断言回到 baseline，不允许每项额外遗留一个。Pin 结构拆分后监测真实 Router 安装状态，保持销毁/隐藏卸载保护。

**Gate：** 新生命周期/样式回归；四个 toolbar 节点；`test_pinned_cursor_lifecycle.py` 对应 filter 销毁节点；`test_pg_dense_raster.py` 中资源节点、`test_pill_switch.py::test_parent_hide_and_delete_later_stop_animation`、`test_channel_widget.py::test_delegate_paints_channel_names_with_middle_elision`（后者只证明 paint 路径，不代替新增 teardown-crash 回归）。QSS 工具污染链选 `tests/test_verify_ultraview_visuals.py` 与一个敏感几何节点顺序、反序；不跑整个 ChartStack 文件来碰运气。原生 paint-crash 回归以有外层上限的 fresh 子进程验证。

**完成：** owned widgets 在 item 边界销毁、合法 session 对象未被清掉；同样式零额外全局恢复；异常路径也回到 baseline。受控重复相同小型混合序列，报告 setup/call/teardown p50/p95、样式调用及 widget 数；RSS 仅作趋势，不要求分配器返还全部内存。没有同负载对照就不宣称提速比例。

### T3 — 可取消的弹窗守卫与真实超时边界（F03/F09）

**归属：** `tests/ui/conftest.py`、`test_modal_exec_guard.py`、`pytest.ini` 中 marker 说明（必要时）。

- [ ] 每次 exec 使用有 owner、可 stop 的 single-shot timer，finally 覆盖成功、reject、异常及 dialog 删除；回调不触及下一次 invocation，不遗留对 item/request 的长期强引用。
- [ ] 超时仍携带 nodeid、dialog class/title，且确实失败；保留800 ms默认语义，若真实交互节点需特殊预算，应显式说明，不取消整个进程 watchdog。
- [ ] 回归包含：忘记关闭、快速 accept/reject、同对象两次打开、嵌套不同 dialog、期间销毁、异常退出、无晚到回调。优先可控调度的逻辑测试，加一条真实 Qt event-loop 集成，避免依赖狭窄时间容差。
- [ ] 清查 QMenu.exec、QMessageBox 静态方法、QFileDialog/native 与模态豁免。能 stub 确认 seam 的测试就 stub；真正验证交互的按实际路径驱动。不要假设 patch QDialog 覆盖所有阻塞 API。
- [ ] 明确 Qt timer 只能保护仍在派发事件的嵌套循环；CPU 卡死和 teardown 卡死交给外层进程监督（T5）。

**Gate：** 扩展 `test_modal_exec_guard.py`；`test_smart_default_weighting.py` 相关确认节点、dirty guard 真正对话框节点（精确选择）；旧遗忘弹窗守卫继续失败得明确且有界，F03 先红后绿。

### T4 — Worker、子进程与失败路径收尾（F06/F07）

**归属：** `test_batch_runner_thread.py`，实测同类 QThread/QThreadPool/future 测试，附录 A 的调用点；必要的窄 subprocess helper。

- [ ] worker 测试同时验证业务 result 和 `QThread.finished`；finally 中 request_cancel，并在预算内继续 GUI 派发直至退出，确保随后才撤销 worker 会用到的 monkeypatch。
- [ ] 不在 GUI 线程无界 `wait/join`：Batch 渲染依赖 GUI 回调，直接阻塞等待可能死锁。提前失败、渲染异常、取消、等待超时都要覆盖。
- [ ] 永不合作的故障注入放独立子进程；禁止 terminate QThread 作为常规清理。关闭仅本测试拥有的 worker，不干预其他任务。
- [ ] 清查所有阻塞 subprocess 别名、Popen communicate/wait、multiprocessing/join，补命名预算及失败输出；附录 21 处是起点，不是全部 API 清单。保留 import-negative oracle 与 `sys.executable`/cwd/env 合同。
- [ ] 正常、非零退出、timeout 均保留 stdout/stderr/命令/耗时。可能有后代进程的 helper 必须清理自己创建的进程树，不能只杀父进程或按宽泛进程名 kill。

**Gate：** `test_batch_runner_thread.py` 受影响节点，相关取消/预览 worker 节点；`tests/test_conftest_autouse_scope.py`、附录涉及的 import boundary 文件及新 timeout 故障注入测试。每个子进程检查预算留足正常冷启动余量，不用统一 1 s 阈值制造 CI 抖动。

### T5 — 一次权威运行、阶段日志和外层 watchdog（F09）

**归属：** 拟新增 `scripts/run_test_gate.py` 及其轻量测试，pytest 诊断 helper；运行证据保存在 `.state/test-runs/<run_id>/`。先确认仓库是否已有可扩展入口，避免重复造 runner。

- [ ] 运行前检查 pytest PID/cwd；同 checkout 不重叠两个全 gate。主套件与 acquisition 两个 fresh 进程严格串行；禁止自动无限重试。
- [ ] 记录 run_id、命令、cwd、PID/owned process group、开始时间、依赖版本、HEAD 和 dirty 内容指纹；结束再次核对。源码变动、异常退出或中断标 UNVERIFIED，不复用通过数冒充验收。
- [ ] 及时落盘当前 nodeid 与 setup/call/teardown 开始/完成、耗时、失败 traceback；周期 heartbeat 含最后进展和累计时间。不仅依赖 `-q` 百分比或 pytest 结束时的汇总。
- [ ] 可选 faulthandler 栈转储与低频资源采样；明确 faulthandler 超时**只打印栈、不停止运行**。测试进程无法调度时由独立 watchdog 负责。
- [ ] soft deadline 先记录诊断，hard deadline 后仅中止自己启动的测试进程树，保存证据并报超时。预算按测试类别和实测冷启动配置；本任务不接管或中止别人启动的旧进程。
- [ ] 主套件正常完成但失败仍可串行收集 acquisition 的独立结果；主套件超时/崩溃先确认进程树退出再决定是否继续，绝不重叠。两阶段结果分别记录，只有都满足验收才汇总绿。
- [ ] watchdog 自测正常退出、assert失败、sleep卡住、CPU循环、teardown卡住、派生子进程、用户中断；都有有界退出与完整日志，没有 orphan。

**Gate：** 用临时小型 pytest 项目测试 runner，不为测试 runner 发起真实全套。边界恢复与 timeout 日志均验证后才允许 T7 使用。

### T6 — 横向清理与失败分类，不削弱覆盖

**归属：** 实际命中的 tests/helpers 和目录 fixtures；每个修复独立最小 patch。

- [ ] 将 `tests/acquisition_ui/conftest.py`、`tests/ui_kit`、`tests/perf`、根目录调用 GUI tools 的测试纳入生命周期/状态矩阵；当前主 UI 的 modal/settings/pin 保护并不自动覆盖兄弟目录。只复用必需的低层 helper，不把 MainWindow autouse 强加给所有测试。
- [ ] 查环境变量、cwd、logging handlers、随机种子、进程级 cache、全局注册表修改及其恢复，追实际写点；命中不自动算 bug。跨用例复现或明确异常路径遗漏才立项。
- [ ] 真实性能测量保持 opt-in：`tests/perf/test_timedomain_pan_perf.py` 已标 slow、只报告测量值；`test_timedomain_hotpath_perf.py` 是调用次数合同，保留默认 gate，不能仅因名字含 perf 就移走。
- [ ] 固定等待只在等待异步完成时改为有 deadline 的信号/状态等待；验证150 ms settle等真实时序合同的等待不能机械删掉。wall-clock 性能门槛与行为不变量分开，性能结论需要控制负载与重复测量。
- [ ] 对从别的 test module 导入 `_entry/_result` 等 helper 的地方，仅提取确实共享的纯数据 builder；不以文件长、私有访问多为由拆所有测试。真实 seam 与 fake 合同漂移逐例核实，不把缺字段归咎于产品。
- [ ] 将上一轮 F 对应节点和 traceback逐项归类：产品回归 / 测试缺陷 / 顺序污染 / 环境差异 / UNKNOWN。以独立节点 → 最小前序链复现；无证据保留 UNKNOWN，不批量 xfail、skip 或调期望值。
- [ ] 记录默认 `not slow` 和 parked CRC policy 的收集/skip 清单。默认主套件成功不等于 slow/原生平台也通过；不擅自启用已经停用的旧策略。

**Gate：** 每个确认缺陷的 owner 节点及两种有意义顺序；fixture 变更保留 collector/settings/lifetime 守卫。新增中立 helper 运行相应 import boundary，未触及产品则不泛化添加全部架构 gate。

### T7 — 稳定集成验收

- [ ] T1–T6 focused 和各自边界通过，证据对应稳定快照；无残留测试 owned widgets/filter/timer/worker/process，无真实设置写入。
- [ ] 选择代表性短序列重复测量，覆盖 ChartStack 创建销毁、真实 QSS、工具到 UI 的跨目录切换和异常收尾。记录对象基线是否回归，分阶段耗时是否随轮次恶化；解释仍存在的增长，不直接把 allocator RSS 当泄漏。
- [ ] 此任务改变跨目录 fixture，最终稳定里程碑有理由跑一次主套件，再单独跑 acquisition；由唯一协调者经 T5 入口启动。实际 pytest 子命令保持：

  ```bash
  TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest --ignore=tests/acquisition_ui
  TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui
  ```

  两条严格顺序，外层 watchdog 不能省。没有新修改/新失败/新证据，不再重跑同一全套。
- [ ] 原生 Qt 生命周期/崩溃探针与 offscreen 分开记录；本测试基础设施任务不代替产品 Cocoa 前台和 Windows frozen 验收，也不宣布 Pin 应用闪退已修。
- [ ] `git diff --check`、相关路径/引用、lesson status；仅提交本任务文件（若用户另行要求提交）。

## 4. 总验收标准与停止条件

| 合同 | 必需结果 |
| --- | --- |
| 设置安全 | 不操作真实 org/app store；逐 item 文件隔离及共享 factory 一致；不自动回写历史偏好 |
| 生命周期 | item-owned 对象正常/异常都销毁；session baseline 存活；paint 安全 guard 保留；无跨项 filter/worker 累积 |
| 弹窗安全 | 单次遗忘会明确失败；早退取消 timer；重复/嵌套 dialog 无旧回调误操作 |
| 外观与成本 | QSS/style/font/palette 无串扰；未变化不恢复；减少成本有同条件证据而非放宽覆盖 |
| 有界等待 | worker、子进程、suite 都有 owner 和预算；超时保留具体 node/phase/stack，退出无 orphan |
| 结果真实性 | 默认/slow/parked/native 区分；失败逐项归类；中断或快照变化只记 UNVERIFIED |

若发现必须修改产品线程、渲染、状态协议才能修复，先报告产品 owner 与最小复现，作为独立修复项；不得塞进 fixture 中掩盖。若生命周期优化重新触发 native crash，暂停该优化路径并保留诊断，不能通过延长 sleep、移除危险测试或放宽过滤器数量继续。

## 附录 A — 缺少显式 timeout 的直接 subprocess 调用候选

由本轮 AST 扫描生成的路径/行号快照；实施时复查调用参数、嵌套 helper 和正常时间预算，不机械套相同阈值：

```text
tests/test_analysis_presets.py:318
tests/test_analysis_time_axis.py:45
tests/test_batch_output.py:748
tests/test_batch_render_import_boundary.py:28,68,111
tests/test_batch_render_qt.py:1308,1340,1376
tests/test_batch_series_spool.py:259
tests/test_batch_validation.py:188
tests/test_channel_frame.py:232
tests/test_conftest_autouse_scope.py:76
tests/test_custom_x_paths.py:474
tests/test_p0_a2l_probe_import_safety.py:23
tests/test_pinned_cursor_state.py:764
tests/test_render_profile.py:140
tests/ui/test_import_boundaries.py:461
tests/ui/test_ultraview_state.py:271,304
tests/ui_kit/test_control_style.py:141
```

这份计划替代“再跑一轮看卡在哪里”的验证方式，不替代业务缺陷修复清单。执行后回填各任务真实命令/结果，禁止把本轮 5 个守卫通过写成实施后的全套验收。
