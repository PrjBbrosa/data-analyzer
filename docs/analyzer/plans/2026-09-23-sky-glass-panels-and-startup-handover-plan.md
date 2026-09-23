# 晴空蓝白面板、文字与阴影修正、启动交接实施计划

日期：2026-09-23。状态：**方案已确定，代码问题已验证，待执行；不代表原生视觉已通过。**

用户确认：采用「晴空蓝白」。初选滑杆为 65 / 15px，随后改为 **75% 不透明、磨砂 25px**；同时优化启动面板和底栏 **「?」打开的操作速查面板 QuickRefPanel**。不是 Toast，也不是所有鼠标悬停 Tooltip。

执行方式：一名 agent 顺序实施，无需派生并行 agent。当前核查 HEAD 为 `e35aae9d2b7c5273e54393e2c3d079c91d27dd6e`，执行时重查。现有 `collapsible.py`、`test_collapsible_motion.py` 的未提交修改与本任务无关，不得覆盖。

## 1. 本计划优先级与设计基准

- [配色原型](../ui-prototypes/2026-09-23-startup-glass-color-demo.html)：选择 `#azure`，玻璃不透明度 **75%**、磨砂 **25px**。这是当前用户参数，优先于原型里曾经的 78%/24px 和 65%/15px。
- [已记录的文字/阴影反馈](../specs/2026-09-23-startup-and-bottom-tip-visual-feedback.md)与[Windows 截图](../ui-prototypes/screenshots/2026-09-23-startup-native-feedback.png)均为验收依据。
- 本计划替代[原 B 计划](2026-09-23-startup-splash-b-implementation-plan.md)中的**雾蓝配色、自绘外阴影、主窗首帧之后才关闭 splash**三项合同。旧文档保留历史原貌，其余轻量入口、独立 child、诊断、导入边界和生命周期合同继续有效。
- 不改频谱图案、采样、布局、logo、产品版本和提示语义；不增加 slogan。QuickRef 保留信息结构、搜索、置顶、拖动、Esc、失焦关闭、帮助入口和底部提示开关。
- 不改图表/DSP、项目会话、Toast、普通 Tooltip 或全应用主题。不要借此扩大为启动提速或 UI 重构项目。

## 2. 当前问题与证据等级

### 2.1 启动面板晚退：已确认代码问题与本地复现

1. `mf4_analyzer/app.py:275–314, 422–425`：先 `window.show()`，观察主窗首次 Paint，再排队调用 `feedback.finish()`。因此当前设计本身允许主窗出现后 splash 仍可见，和用户新要求冲突。旧测试 `test_paint_finish_queued_after_paint_not_on_show` 也在保护这个旧行为，实施时必须替换合同。
2. `startup_splash_child.py:157–162, 303–354, 441–444`：reader 是 Python 后台线程，其调度函数直接执行 `QTimer.singleShot(0, callback)`；callback 是普通 `_SplashSession` 的绑定方法，没有 GUI QObject 接收者。此路径没有可靠地把执行转交到 GUI 线程。
3. 用当前真实 controller + 真实 Qt child 做本地独立进程探针，已收到首帧后发送 finish，输出：

   ```json
   {"painted_before_finish": true, "finish_to_exit_ms": 1022.3,
    "returncode": -15, "closed_ack": false}
   ```

   同时日志出现 `startup splash child still alive after finish; terminating`。与 `startup_feedback.py:55, 442–457` 的 1 秒兜底回收吻合。
4. 第二个确定性探针提取生产 `schedule` 函数，使用真实 QApplication 事件循环，从 Python worker 调用真实 `_SplashSession._handle_message(finish)`：300ms 后 `finish_received=true`、`view_closed=false`。这隔离验证了跨线程关闭投递缺失，而非主线程事件循环未启动。
5. `_SplashSession.shutdown()` 先断 socket，再关闭 view；正常 finish 没有发回 `closed`。`notify_user_closed()` 虽有消息，却是在调用 `close_splash()` 前发送。**现有 `child_closed` 不能直接充当“已不可见”的可靠确认。**
6. 当前 child 测试 `_FakeSplash.show()` 自行排队 `app.quit()`，最后 `child_main()` 的 cleanup 也能令 fake 变为 closed；这样的测试不能证明 reader 的 finish 真正触发了 GUI 关闭。父 controller 测试主要是纯协议 fake peer，覆盖不了该缺陷。

证据边界：以上实测环境是 **macOS + Qt offscreen**，生产逻辑未修改。证明当前源码有调度和交接缺陷；尚未在用户当前 Windows EXE 上测得重叠时长，不将 1022.3ms 当成该机器实测。原始本地数据位于 `.state/startup-glass-plan/real-child-probe.json`、`dispatch-probe.json`，是临时证据，不纳入 Git。

复现方法：在独立进程中设置 `QT_QPA_PLATFORM=offscreen`、`TRACELAB_STARTUP_SPLASH=1`，用项目 `.venv/bin/python` 实例化 `StartupFeedback`，显式 `start(allow_offscreen=True)`；等待 `painted`，保存 `Popen` 引用，记录调用 `finish()` 到该句柄 `poll()` 返回的时间/退出码。最多等待 8 秒首帧、3 秒退出，finally 调用 `close()`；不得把手动 `app.quit()` 当正常 finish 成功。正式回归须将此路径固化在现有 owner 测试中。

### 2.2 阴影来源已确认；字体根因仍需 Windows 字形证据

| 对象 | 核查结果 | 实施含义 |
| --- | --- | --- |
| 启动面板 | `ui/startup_splash.py:560, 569–578` 主动绘制 3 层偏移实心半透明圆角块；并没有真正模糊这些块。已有 `NoDropShadowWindowHint` | 删除自绘外部投影；仅添加 Qt flag 无法消掉当前灰色台阶 |
| QuickRefPanel | `ui/quickref_panel.py:64–71, 893–915` 绘制 2 层偏移填充阴影；已有禁原生阴影 flag；14px 外边距用于阴影 | 同时移除其自绘阴影，整理多余透明边距及定位计算；不能只修 splash |
| 启动文字 | `startup_splash.py` 的状态、tips、功能标签等多处独立指定 Segoe UI；child 只创建 QApplication，没有主应用字体配置 | 中文依赖回退是明确的排查点；截图不能证明具体回退到了哪一种字体 |
| QuickRef 文字 | 使用 QLabel/QSS，字体受全局 QSS、应用 font 及局部字重影响；绘制路径与 splash 不同 | 必须测真正生效的字体和 rich-text glyph runs，不能把两者根因直接等同 |
| 透明材质 | splash 的背景渐变 QColor 目前不透明，QuickRef 内卡也是不透明白色 | `WA_TranslucentBackground` 只是能力开关，不代表已实现背景磨砂 |

## 3. 最终视觉合同

### 3.1 晴空蓝白

| 参数 | 确定值 |
| --- | --- |
| 面板底色 | 白色 → `#f4faff`，使用玻璃填充层 alpha **0.75**（约 191/255） |
| 透明度解释 | 沿原型滑杆语义：75% 不透明、25% 背景透过；不是 alpha 0.25 |
| 磨砂 | **25 CSS/参考逻辑 px** 的 HTML 外观基准，DPI 换算只做一次；原生映射见 §3.3 |
| 冷色光晕 | 右上 `(73,142,252)` / 0.17，左下 `(24,193,229)` / 0.10；轻量局部渐变 |
| 频谱四色 | `#17b6df → #1e85ed → #5773ed → #23bbd0`，沿用原位置/图形 |
| 主/次文字 | `#223a58` / `#576f8c`；强调蓝 `#1976e9` |
| tips | 同系青蓝浅洗色；标题 `#2468ac`，正文 `#405e7c` |
| 外部阴影 | **两款面板均无自绘外阴影、无原生厚投影**，以细亮边区分面板边界 |

透明度仅作用于玻璃背景。文字、图标和频谱保持各自正常透明度；禁止通过 `setWindowOpacity(0.75)` 或整窗 opacity effect 令正文也变淡。HTML 的阴影也不属于最终合同，以本表的新要求为准。

频谱仍为 16 层 × 461 点、参考 Y `[15,147]`；描边/峰顶完整。保留当前原生面板尺寸与显示比例，不把原型的 640×470 强行改成更小的生产窗口，不引入新的全窗缩放动画。QuickRef 只迁移视觉语言，不能把它重排成启动面板。

### 3.2 两款面板的文字

- 在轻量共享 helper 中解析实际可用的 CJK 无衬线字体；Windows 优先核查 Microsoft YaHei UI / Microsoft YaHei，macOS 使用系统适用字体，缺字时明确回退。不要仅用 `QFont.exactMatch()` 判断整句中文能否正确显示。
- 同一个正文 role 的整句（含 Home、Pn、数字等）使用一致的字体策略和真实 Regular 字重；标题/状态只使用明确的强调 role。普通文字与加粗文字都要测，不以“全部取消粗体”充当修复。
- `QTextLayout.glyphRuns()` / `QRawFont`、实际字号/字重、DPR 与截图一起作为证据；不要逐字混拼字体、反复描字、给文字加阴影或使用图片缩放代替正常排字。
- 绘制与测量使用同一份 font/metrics。字号取逻辑像素，再由 Qt 处理设备 DPR；核查当前显示比例，不重复乘 DPI。
- QuickRef 的标题、说明、行内容、按键 chip、搜索输入和 footer 均检查 QSS 最终生效结果；必要的 CSS/QSS 改动限定 objectName 范围，不修改全应用 QWidget 字体。
- 不直接导入 `qt_chart_fonts.py` 到 child：其模块级 numpy 等依赖违背 splash 轻量闭包。可以复用已验证的字体选择原则，新增小型 PyQt-only helper，不搬入整个 chart 字体验证系统。

### 3.3 原生磨砂的实施选择与能力边界

先做一个 Windows 原生最小探针，再把验证成功的表面实现同时用于两款面板：

1. 首选官方系统 backdrop：在支持的 Windows 11 上验证 `DWMWA_SYSTEMBACKDROP_TYPE` / `DWMSBT_TRANSIENTWINDOW` 的浅色 Desktop Acrylic 与现有 PyQt5 顶层 HWND、无边框、圆角和透明背景是否能共存。检查实际 HRESULT、系统设置与像素，不仅检查 API 是否存在。
2. 此系统 API 选择的是**系统材质**，没有 CSS 的 `blur(25px)` 半径参数。25px 仍是用户选定的视觉参考；原生结果要与相同背景下的 HTML 对照。不能把枚举值写成 25，也不能宣称完全等同的高斯半径。若视觉差异明显，标记磨砂目标未达成，并给出实际对比与可行改法，不悄悄改目标。
3. 能力不足、系统关闭透明、高对比模式或原生调用失败时，使用明亮蓝白的高不透明度回退，确保字可读；记录一次明确降级原因。回退可用性通过不等于磨砂外观通过。不要替用户启用 Windows 透明开关。
4. 禁止把 `QGraphicsBlurEffect` 加到整张面板上（会糊文字）；禁止截图桌面伪造实时背景；不新增 WebEngine/QML、第三方 DLL 或窗口注入。`DwmEnableBlurBehindWindow` 在 Windows 8 起不再产生旧式 blur，不能以返回成功证明磨砂。
5. QuickRef `_card` 和 group 背景目前会盖住外层：由真正拥有 surface 的控件绘制材质/颜色，内层透明或受控浅色填充；核查四角、搜索与 hover 背景，防止矩形底色堵住圆角。
6. HWND 创建/销毁、QuickRef pin 导致窗口 flags 变化、show/hide 重复打开、DPI/屏幕变化都须正确重应用/释放原生效果；不在 paint timer 中反复调用 Win32 API。

官方依据：[DWM_SYSTEMBACKDROP_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)（最低 Windows 11 Build 22621，材质由系统控制）、[DwmEnableBlurBehindWindow](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmenableblurbehindwindow)。原生与 HTML 是不同渲染路径，本计划不把浏览器参数当作已存在的 Win32 参数。

## 4. 新启动交接：先隐藏，再显示主窗口

### 4.1 正常时序

```text
主进程构造 MainWindow（尚未 show）
  → 异步请求 splash finish，进入唯一的 handover owner
  → child GUI 线程停止动画/轮换、hide + close
  → 已不可见后发送 hidden 确认（发出后再断 IPC / quit）
  → parent GUI 收到本 session 的确认
  → 主窗 show（仅一次），按原逻辑进入正常工作
  → child 进程在后台回收；无需等进程退出才显示主窗
```

主窗的 first-frame/interactive timing 仍观察**真实主窗**，仅作为测量，不再驱动 splash.finish。这明确替代旧的“先主窗 paint 再关 splash”，也不等待 idle preload、文件加载或全部分析页完成。

### 4.2 具体实现合同

- child 在 GUI 线程创建并持有 QObject dispatcher，以明确 `Qt.QueuedConnection` signal/slot 接收 reader 的纯数据命令；回调运行线程必须可断言。不要在没有 Qt 事件循环的 Python reader 中调用无 QObject 接收者的 singleShot。
- 父侧 `StartupFeedback` 继续 stdlib-only；由 app 持有的小型 Qt handover 对象桥接数据通知到 GUI。不要把控制状态散写到 MainWindow 或 `startup_coordinator.py`。
- 增加语义清楚的 `hidden` 协议消息（或严格重定义既有消息并同步所有测试/工具），包含 session/seq 和关闭原因。它必须在 view 实际隐藏后发送；show 前被终态抑制时确认 never_shown。不能用 finish 发出、socket EOF 或握手成功替代 hidden。
- 父发送 finish 前建立确认监听，避免快速 ACK 丢失；迟到 session、重复 ACK、确认后的 stage 均不能触发第二次 show。finish 在队列中优先，终态不逆转。
- finish 前就已关闭/确认进程退出、明确 disabled/未 spawn 时直接继续。child 尚在启动时先取消会话，禁止它在主窗出现后再 show；原子终态检查与 GUI show 顺序、迟到握手必须有竞态测试。
- 主 GUI 线程不得进行阻塞 `sendall`、`wait/join`、sleep、轮询 processEvents 或嵌套 event loop。当前 `_enqueue_locked()` 会直接 `sendall`，回收还可能持锁终止进程，须在本 owner 中收口为后台 I/O/回收；GUI 只发布请求/处理通知，不能等待回收锁。
- app 在暂时没有可见主窗时维持事件循环；取消/退出不能被迟到通知复活。关闭定时器、断开 signal、释放 QObject 的顺序要对称。
- 不做淡出、不设置最短停留、不等待动画结束。目标正常 hidden 确认及主窗揭示在请求后 **200ms 内**，但可见顺序必须是 splash_hidden ≤ main_visible；200ms 不是允许主窗后遮挡的时间。
- 若 child 在 **250ms** 内无 hidden 确认，后台终止这个已持有句柄的 child；收到明确进程退出后再 show。禁止按进程名杀进程。异常兜底从请求起最多 **1.5 秒**：仍无法确认退出时，为避免主程序永久不可用，允许降级显示主窗并记录 handover_failed。该异常样本必须计为交接失败，不得算“无重叠通过”。
- 异常/EOF/用户关闭 splash 共用幂等清理；主进程死亡时 child 自动退出。正常链路不能靠 reaper terminate 成功收尾，也不能通过缩短 1 秒 timeout 掩盖当前投递问题。

线程依据：[Qt 5.15 Threads and QObjects](https://doc.qt.io/archives/qt-5.15/threads-qobject.html)。Qt GUI 操作必须在 GUI 线程；有接收者的排队信号提供线程间交付，本文实测已证明当前普通 Python callback 路径不满足要求。

## 5. 文件 owner 与实施顺序

建议共享模块 `mf4_analyzer/qt_panel_style.py`：只含这两款面板的字体 role、颜色与按需调用的原生 surface helper；std library + 惰性 PyQt/ctypes，不进入 ui_kit 包初始化，不缓存跨进程 QWidget。若已有同等轻量 owner 可用则复用，不创建通用主题框架。

| 阶段 | 改动 owner / 工作 | focused 与退出条件 |
| --- | --- | --- |
| 0：冻结证据 | 重查 HEAD/dirty、阅读本计划与反馈；把 Windows OS build、包型/hash、DPI、透明设置记录到 `.state/`；复现旧关闭链路 | 先运行既有 startup child/feedback/integration 相关测试作为受影响基线；建立失败用例，不先跑全套。缺 Windows 时将 native 标 UNKNOWN |
| 1：修交接 | `startup_feedback.py`、`startup_splash_child.py`、`app.py`；必要时新增一个 app 持有的轻量 Qt handover owner；更新 `startup_timing.py` 与测量工具相关事件 | `tests/test_startup_feedback.py`、`test_startup_splash_child.py`、`test_startup_splash_integration.py`、`test_startup_timing.py`；真实 child 正常退出0、不触发强杀；hidden 在 main.show 前 |
| 2：字体/材质最小探针 | 共享 helper + `ui/startup_splash.py` 的独立 view；先确认 Windows 原生表面能力、字体和四角，再接 QuickRef | `tests/ui/test_startup_splash.py`；新 helper 有行为测试：字体覆盖/role、支持与失败回退、资源释放。不能用 token 断言充当玻璃效果验收 |
| 3：两款面板统一 | `ui/startup_splash.py`、`ui/quickref_panel.py`；移除两处手绘阴影；QuickRef 内卡及局部 QSS；只在确有需要时改 scoped 全局规则 | `tests/ui/test_quickref_panel.py`、`test_quickref_status_hints.py`、`test_quickref.py`，加真实绘制文字/圆角/外边界检查；原频谱路径/峰顶用例继续通过 |
| 4：边界与文案 | 校正 `ui/hints.py`、`ui/quickref.py` 现有启动说明中的交接措辞，两者同步；清除仍要求首帧后 finish 的测试/工具语义 | `tests/ui/test_hints.py`；下面适用的导入/生命周期/打包边界；不改其他交互说明 |
| 5：Windows 验收 | 目标机器 source + frozen Full/Lite/Modular 的生产窗口链路、字体及材质；输出截图、连续帧与 timing | §7 条目逐项签署；未验证写 UNKNOWN，未达标写 partial/fail，不用本地通过替代 |

原测试 `tests/ui/test_quickref_panel.py::test_shadow_layers_stay_light_and_inside_shell_margin` 仅约束阴影 token，必须随新无阴影合同替换为真实 surface 外侧 alpha/像素及边界检查。不要为了过旧测试保留用户不要的阴影。

新增控件测试显式持有父对象、清空 queued callbacks / deferred deletes、恢复修改过的全局 QSS/font，避免污染用户 QSettings。将新测试放在正确 conftest 作用域，不依赖特殊命令顺序。

## 6. 必须补齐的行为用例与边界门禁

交接行为：

1. 真实 Python reader → GUI dispatcher：stage 更新、finish、EOF 都在 GUI 线程处理，关闭前没有测试主动 app.quit；普通 Qt timer 只做失败 watchdog。
2. 主窗构造完毕、未显示时发 finish；hidden 确认前不能 show，确认后只 show 一次；真实首帧独立记时。替换旧首帧后 finish 测试。
3. 正常真实 child：received painted → finish → hidden → 自然退出0；确认退出不依赖1秒 reaper，记录关闭原因。user_close 与 finish_close 都验证 hide-before-ack。
4. 快启动、child 延迟启动/握手、finish-before-show、跨 session/重复 ACK、先用户关闭 splash、父窗口退出、父进程硬退出、EOF、协议错误。
5. 不响应 child：GUI 心跳继续，后台只回收本次句柄；fallback 不能永久遮挡/等待，失败原因可观测。
6. timing 开/关、splash auto/0/1、源码两入口与 hidden/layout probes；不得产生双主窗/孤儿子进程或 child 重启。

适用边界（在 owner 测试后运行一次）：

- `tests/test_startup_entrypoints.py`、`tests/test_startup_import_boundary.py` 与 child import-closure 测试：child 首显仍无 numpy/pandas/scipy/pyqtgraph/MainWindow/ui_kit。
- `tests/ui/test_import_boundaries.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`tests/ui_kit/test_qss_border_shorthand.py`。
- `tests/ui/test_startup_preload.py` 及 `test_main_window_smoke.py` 与首次显示/退出相关节点，确认 idle preload 未成为交接前置条件。
- `tests/test_packaging_imports.py`；若增加打包动态模块或资源，再跑实际受影响的 `test_windows_build_script.py`、`test_windows_lite_modular_build_script.py`、`test_windows_runtime_dependencies.py`。不机械修改三个 builder。
- 标准运行环境：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <上述对应节点>`。不默认运行全套或全部 tests/ui；只有出现新的跨域风险或进入发布验收才扩大范围，并记录原因。

## 7. 真机验收与交付

### 启动交接

- 在当前 Windows 机器上，普通热启动至少 10 次、重启后的首启至少 3 次，记录 OS build、包型/hash、DPI、原始帧序列与全部时序样本。
- 连续画面确认 splash 完全消失发生在主窗首个可见帧之前或同帧；**主窗已显示仍被 splash 遮挡即失败**。隐藏 ACK 和 QWidget 状态只验证代码顺序，不能替代 DWM 合成后的屏幕观察。
- `finish_requested`、`hidden_received`、`main_show_called`、`main_first_frame`、`child_exited` 分开记录；消息原因区分正常关闭、用户关闭、未展示、超时强杀。通过父/外部观察者同一单调时钟记录接收顺序，不相减两个进程的相对时钟。
- 正常退出码0、无强杀日志、无 orphan；主窗构造后不人为延迟。报告隐藏→主窗首显的空白间隔，目标 ≤100ms；如目标机首绘慢，标未达标并优化真正影响首绘的局部原因，不退回叠盖显示。
- Full/Lite/Modular 至少各一条实际 frozen 正常链路，禁 splash 与 enabled 对照；主窗可交互耗时不比禁用基线增加超过 max(200ms, 5%)。能力/机器不足明确标 UNKNOWN。

### 两款面板外观与操作

- 100/125/150/200% Windows 缩放，白色、彩色、深色背景；检查 Regular/Bold 中文、英文、数字、混排，字形与粗细一致、无缺字/裁切。
- 检查整块面板底边、四角和外部透明区域，不能再有偏移圆角块形成的灰色底座；频谱路径与布局保持，峰顶完整。
- 磨砂确实作用于身后内容，移动背景时变化合理；文字不随底色透明度变淡。关闭系统透明时回退仍清楚；报告所用原生材质与 25px HTML 参考的实际差异。
- QuickRef 搜索、分组过滤、置顶/取消、拖动、多屏边缘、失焦、Esc 两步语义、关闭后焦点恢复、重复打开、隐藏底部提示开关均保持；pin 引起 HWND 变化后材质与无阴影不能丢失。

交付：产品代码与 focused 结果、两款面板前后图、Windows 连续启动片段、实际包标识、剩余差异和降级说明；验收摘要放 `docs/analyzer/verify/2026-09-23-sky-glass-panels-acceptance.md`，临时原始输出放 `.state/startup-glass-plan/`。仅代码完成时不得写成 Windows 视觉完成。

## 8. 本轮已做与未做

本轮只进行源码核查、两项有界独立进程探针、官方资料核对与计划文档编辑。已确认旧交接顺序、跨线程关闭投递缺陷和两处自绘阴影来源。**尚未修改产品代码、尚未构建 Windows 包、尚未确认字体实际回退与原生磨砂外观。**

文档交付检查：引用路径、参数/新旧合同一致性、git whitespace；不因计划文档改动运行运行时全套。实施所需测试在 §5–7，不能把清单当成已通过。

相关 lessons：[透明 popup 的实际像素 owner](../../lessons-learned/translucent-popup-chrome-must-self-paint.md)、[文字检查实际绘制文档](../../lessons-learned/cursor-layout-tests-must-use-painted-document.md)、[跨线程关闭需真实 GUI 接收者](../../lessons-learned/splash-thread-dispatch-needs-real-gui-receiver.md)。
