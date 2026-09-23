# TraceLab 启动面板实施计划：B「雾蓝频谱」

- 日期：2026-09-23。
- 状态：**可交接实施；本轮仅完成计划，产品代码尚未实现。**
- 用户决策：采用 B；浅色但不要大面积纯白；不要 slogan；频谱峰顶完整、平滑；保留软件信息与 tips。
- 当前源码基线：`61c38e6eb9e9f5a2f882df257616a7d3eab2d189`；实际产品版本从 `mf4_analyzer/app_meta.py` 读取。实施前重查 HEAD/dirty，不把此基线当作永久状态。
- 设计基准：[启动 HTML demo](../ui-prototypes/2026-09-23-startup-animation-demo.html)，打开 `#cinematic`。只采用 `article#cinematic`，不采用 A/C/D/E。
- 编写时 demo SHA-256：`6cf49f384e6f9b0e0b15363a1cc0b4331a984d9be2ac676eae1feed36dc46f08`。它目前是未跟踪文件，后续交付须连同计划保留，不能清理掉或只提交计划而丢失设计依据。
- 执行方式：一名执行 agent 顺序实施即可；本计划不要求启动其他 agent。所有数值门槛是拟定验收目标，不是已测性能。

## 1. 目标和范围

Windows 用户双击 EXE 后，尽早看见明确的“正在启动 TraceLab…”面板；主程序加载期间动效与 tips 仍可更新；主窗口完成首帧并回到事件循环后，面板立即交接退出。

本次只实现启动反馈，不重新执行整个[启动提速与空闲预加载计划](2026-09-22-windows-startup-and-idle-preload-plan.md)，也不以启动面板的出现代替主窗口可交互时间。

默认覆盖 Windows 普通 GUI 启动，兼容 Full、Lite、Lite Modular。Windows 源码入口和 frozen 入口共用行为；macOS 源码可通过开发开关强制开启以做原生渲染验证，默认启动行为保持现状。隐藏 child/smoke、layout probe、默认 offscreen 测试均不启动面板。

不改 DSP、项目/文件身份、会话恢复、分析页面空闲预加载策略、包型选择、版本号或 `CLAUDE.md`。不引入 WebEngine、浏览器、QML、视频、联网资源、Tk/Tcl 或新增 native 编译工具链。不新增单实例机制，也不改变用户多次启动现有程序的语义。

## 2. 当前入口证据与方案选择

### 2.1 已核实的本地事实

| 文件/符号 | 当前行为 | 本次必须处理的边界 |
| --- | --- | --- |
| `MF4 Data Analyzer V1.py` 的 hidden-mode parser | `allow_abbrev=False`，所有隐藏模式在互斥组中；部分 child 在 app import 前返回 | splash child 必须加入同一组，不能靠字符串扫描绕过冲突校验 |
| 同入口 `_startup_mark` 后至 `main()` 的分支 | 导入 app 后先调用扩展 bootstrap，再分派 importer/Batch smoke，最后普通 GUI 进入 main | 普通 GUI 不能等这次 bootstrap 结束才启动面板；smoke 原有 bootstrap 仍须保留 |
| `mf4_analyzer/app.py:main`（编写时 313–357 行） | logging → extension bootstrap → DPI → MainWindow/ui_kit 导入 → QApplication → 样式 → 构造 → show/exec | 面板生命周期应从 extension bootstrap 前开始，不放进 MainWindow 构造末尾 |
| `app.py:_arm_startup_observation` | 当前受 timing 开关控制，观察主窗 Paint，再接排队交互测量；在 show 后安装 | 产品交接必须与 timing 开关独立，并在 show 前安装首帧观察；不把 splash paint 记成 main first_frame |
| `ui/main_window/startup_coordinator.py:StartupCoordinator` | 管理分析页面 idle preload，不负责进程启动 | 不把 splash/子进程状态塞进这个 coordinator，不等待全部预加载完成 |
| `ui/__init__.py` / `ui/widgets/__init__.py` / `ui_kit/__init__.py` | ui 根包是惰性；widgets 会导入 channel_tree、stats 等；ui_kit 会导入图标/控件等 | 面板模块放在轻量的 `ui/startup_splash.py`，不能经 widgets facade 或全局 ui_kit 加载 |
| 三个 `tools/build_windows_folder*.ps1` | 同一个根入口，onedir/windowed，已有 PNG 图标收集；排除 WebEngine/QML | 用已有 Qt Widgets + QPainter；验证三个 builder，而非只测一个 |
| `tests/test_startup_entrypoints.py` 的最后一个静态测试 | 断言入口没有任何 `add_argument("--startup` | 要替换这一过宽断言，新增明确的 splash child 隔离测试，不删除原有 timing/child 合同 |
| `startup_timing.py` | marks.jsonl 是单个进程的相对单调时钟，python_entry 去重；禁用时无写入 | splash 子进程不能继承该写入身份并把另一套时钟混入父进程文件 |

### 2.2 采用：轻量 Qt 面板子进程

| 方案 | 优点 | 缺点/结论 |
| --- | --- | --- |
| 主进程提前 show 一个 QWidget/QSplashScreen | 改动少，无第二进程 | 主线程导入/构造 MainWindow 时事件循环不能持续运行，动效和 tips 会停住；不作为本次交付方案 |
| 把 GUI 构造移到工作线程 | 表面上可让主循环空闲 | QWidget 必须在所在 GUI 进程主线程使用；不采用 |
| 独立轻量 Qt 子进程 | 主程序阻塞导入时，面板仍有自己的 GUI 主线程/事件循环；沿用已有打包依赖 | 增加一次进程和 Qt 初始化；需要 IPC、退出回收、实测成本；**本次采用** |
| bootloader splash / 原生专用 launcher | 可能覆盖更早阶段 | 是另一项构建/平台工程；本次不顺带引入，只有首显指标证明当前方案不够早时再给证据和后续建议 |

关键限制：子进程也是在父进程 Python 入口到达后才能发起，无法覆盖父 EXE 的 bootloader、系统扫描等入口前等待。不能承诺“从双击起零延迟”；必须测外部启动到真实首显。若它仍在几秒后才出现，功能代码可标完成，用户体验目标必须标未达成，不能只展示漂亮截图结案。

## 3. B 视觉和交互合同

### 3.1 必须还原的面板

- 名义宽度 **640 个逻辑像素**，高度以 B 的实际内容为准，约 470；不把 CSS px 直接当成高 DPI 设备像素。圆角 13、左右内容边距约 32。字体差异可微调高度，但不能挤掉内容。
- 底色渐变 `#e8edf1 → #dce5ec → #d2dfe8`；主文字 `#273d50`；次级文字 `#576e82`；状态/进度强调 `#426f94`。不是白底，不是黑底，不新增高饱和霓虹色。
- 顶部：现有 TraceLab PNG 图标（约 40×40）、TraceLab 字标（约 31 px）、右侧版本（约 11 px）。**不显示 slogan，也不拿其他宣传句替代。**
- 中部：16 层蓝灰/青蓝频谱，使用 demo 的精修公式和采样；下方保留“时域、频谱、时频、阶次、频响”。不再加入斜线扫描。
- 状态区：小型活动指示 + 当前启动状态；右侧“工程数据分析工作台”；2 px 不确定进度轨道。无百分比、无预计完成倒计时。
- tips 区：淡灰蓝分区，底色 `#ccdce88c` 叠加在底板上，分隔线 `#b4c6d680`；标题 `#3a627e`、正文 `#425b73`。保留小灯泡/点状轮换指示。
- 底部：TraceLab 信息与 `APP_CREDIT`；名称、版本和 credit 来自 `app_meta.py`。图标走已有 `asset_path`/PNG，不能另写产品版本常量。
- HTML 里的方案按钮、重播、暂停、下一条 tip、模拟场景、模拟就绪、计时、比较页标题、开发说明，全是**演示外壳，不进入产品**。不把整张网页截图贴进 QWidget。

### 3.2 图形、文字和动态

- 使用 QPainter/QPainterPath 绘制。16 层、每层 461 个样本；统一将原始 Y 范围映射到 SVG 参考坐标的 `[15,147]`，参考框 `640×184`。再映射到目标绘图区；留出描边半宽，不以剪裁制造“平顶”。
- 原型曾出现最小 Y≈−4.16、被 viewport 裁切的问题。本次应保护**完整路径及描边的边界**，并截取最高峰像素验证；不能仅测点数或字符串包含 path。
- 路径构建一次；仅尺寸/DPI/字体变化时重建必要缓存。不在 30 FPS timer 中重新生成数千点、重排文本或重读图标。
- 频谱透明度约 0.7↔1，周期约 5 秒；进度段约轨道的 32%，周期约 2.3 秒。动效上限 30 FPS，跟随实际经过时间，不能靠累计 tick 假设时间准确。
- 初次出现直接提供可读内容，不等 360 ms 淡入结束才可见；不为展示动画强制最短停留，不播放片头后才启动主程序。就绪后无额外演出。
- tips 每 5 秒轮换，至少完整保留上一条到下一次轮换；单次启动内无重复相邻提示；首条即可展示。文字与当前 `ui/quickref.py` 的操作语义一致。
- 初版使用 demo 的 5 条短提示：Home 查看已绘范围、P 固定单游标读数、保存 .tlproj、底栏 ? 操作速查、时频查看频率变化。不能为读取 tips 导入整套 quickref/widgets；可在面板侧保留这组小型静态内容，并用 focused check 对照来源，后续交互改名同步维护。
- 检测 Windows 关闭动画的系统偏好，提供静态频谱/活动状态文字；无高频闪烁。非激活应用不抢焦点、不反复 raise、不持续置顶。
- 窗口置于当前启动屏幕的 availableGeometry 中央。无普通窗口标题栏、不额外占任务栏按钮；不要遮住系统任务栏。100/125/150/200% DPI 与较小工作区均保持圆角和文字完整；空间不足时统一缩放画面而非裁掉 tips。
- 正常状态不提供取消/关闭主程序的按钮；系统关闭面板只允许关闭面板，不杀主进程、不自动重建面板。由真实前台验证 Windows Z-order/焦点，不能仅凭 Qt flags 推断效果。

## 4. 进程、状态与资源生命周期

### 4.1 文件职责建议

以下“新增”路径尚不存在，执行 agent 可因实际依赖边界小幅调整名称，但必须保持单一 owner。

| 文件 | 职责 | 允许的依赖 |
| --- | --- | --- |
| 新增 `mf4_analyzer/startup_feedback.py` | 父进程 controller、开关判断、spawn、状态队列、IPC 生命周期、回收 | 标准库；导入时无进程/线程/socket 副作用，无 Qt/主 UI |
| 新增 `mf4_analyzer/startup_splash_child.py` | child 验证连接、创建自己的 QApplication、事件循环、退出 | 标准库、轻量 Qt 支持、面板 view；不 bootstrap 扩展、不导入 app/MainWindow |
| 新增 `mf4_analyzer/ui/startup_splash.py` | 只负责 B 的显示、文字、动画和销毁 | PyQt5 Core/Gui/Widgets、math、app_meta；不访问 MainWindow/项目状态 |
| 按需新增 `mf4_analyzer/qt_app_support.py` | 仅迁移已有 `_configure_high_dpi` / `_load_app_icon` 供两个进程使用 | 原函数保持惰性 Qt imports；app 原符号保留兼容包装，不复制实现 |
| `MF4 Data Analyzer V1.py` | splash child 的早期互斥分派；保留其他隐藏模式 | 不在普通 import 时运行 GUI |
| `mf4_analyzer/app.py` | 持有 controller；在现有阶段发布真实状态；协调首帧交接/异常清理 | 不把新状态散写到 MainWindow mixins |
| `startup_timing.py` / `tools/measure_windows_startup.py` | 分开记录主窗口与面板事件，给出首显和交接证据 | 沿既有 opt-in 测量合同，不建第二套性能工具 |

面板不做新 QSettings/project 持久化；子进程不读用户工程、不持有扩展 runtime lease。Qt 对象都在 child GUI 主线程创建/销毁，IPC 的后台线程只处理纯数据。

### 4.2 入口顺序

1. 真实 launcher 保留互斥 parser。在早期 hidden 分支新增精确 `--startup-splash-child` 模式；session/endpoint/token 参数为其附属参数，单独出现、缺失、非法或缩写时以 2 退出，不能落回普通 GUI。
2. child 分支在 app、extension bootstrap、startup timing 主进程打点之前返回；禁止递归 spawn。所有现有 smoke/probe 分支都不产生 splash。
3. 对 importer/Batch/frozen acceptance 保留其现有 bootstrap 调用顺序。普通 GUI 改为只由 `app.main()` 执行 bootstrap；不能继续让 launcher 在 main 前重复抢先执行。已有 `_BOOTSTRAPPED` 幂等仍保留。
4. `app.main()`：早期 logging/exception setup → 创建可用的 feedback controller → `start()` 发起子进程 → 现有 extension bootstrap → DPI/UI imports/QApplication/样式 → MainWindow 构造 → 安装首帧观察 → show → exec。
5. `python -m mf4_analyzer.app` 也经过同一 controller 路径，不只修 frozen 根入口。source child 用 `sys.executable` 加根 launcher 的绝对路径；frozen child 使用实际 `sys.executable` 和 hidden 参数，`shell=False`，不依赖 cwd、BAT 或 PATH。
6. 全局绘图/样式初始化与扩展设置仍由原 owner 执行；不要为了 splash 把 MainWindow 或 Qt 构造搬到线程中，也不要加循环 `processEvents()` 或嵌套 event loop。

### 4.3 IPC 和异常收口

采用**仅本机 loopback 的临时 socket**，父 controller 持有唯一 server/child 句柄及随机 session token。父进程在 stdlib I/O worker 内等待连接与处理数据，`start/publish/finish` 对 GUI 调用方均不得等待 child 绘制/退出。

- 地址绑定 `127.0.0.1` 临时端口，不监听全部网卡；连接先验证一次 token/session。协议使用有限类型 JSON 行，单帧上限 4 KiB、有限队列，只发阶段枚举/诊断字段；不发源文件路径、用户数据或可执行内容。
- 初版消息：`hello`、`stage`、`painted`、`finish`、`closed`、`diagnostic`；包含 session 和递增序号。`finish` 是终态，优先于排队的普通 stage；关闭幂等，过时/跨 session 消息不能重新 show。
- child 在首次实际 paint 后的排队回调发 `painted`；不得把构造完成/show 返回/握手完成冒充首显。该通知只是首显代理信号，真实屏幕仍须录屏确认。
- Parent 的 subprocess spawn/IPC 出错只降级面板，记录阶段/退出码；主程序按原流程继续启动，不重试出第二个面板。编程错误保留 traceback，不能被 broad `except: pass` 隐藏。
- child 连接失败、协议错误或父连接 EOF 后退出；父进程 hard kill/异常退出必须让 child 无需依赖 atexit 也能退出。监听 socket 不被其他子进程意外继承，避免 EOF 被额外句柄延后。
- controller 使用已持有的 Popen 句柄回收，禁止按进程名清杀。启动/握手超时初始上限 5 秒（后台执行）；超时后撤销面板会话并记录失败，不能把此值当首显达标门槛。
- 正常 finish 后只允许很短的交接（目标 ≤200 ms）；最多 1 秒未退出则后台终止并回收这个 child，GUI 线程禁止 wait/join。即使底层 reap 失败，也必须记录而非卡住主窗。
- **主窗先就绪、child 后连上**：会话已终结，child 必须在 show 前读取终态并退出，不允许主窗口出现后再闪出启动面板。
- 正常/失败/用户关闭父程序的路径共享同一个 controller 的清理出口；socket、worker、计时器、Qt wrappers 和进程句柄都要有明确销毁 owner。
- 子进程不能与父进程共用同一个 RotatingFileHandler。优先通过 IPC 回传日志，连接前失败使用单独有界诊断文件/显式错误管道；不依赖 windowed EXE 的 stdout/stderr 非空。不能把 GUI 启动变成等待 stdout 的阻塞调用。
- 子进程清除继承的 `TRACELAB_STARTUP_TIMING`、`TRACELAB_STARTUP_RUN_ID`、`TRACELAB_STARTUP_PERF_DIR`、`TRACELAB_STARTUP_PROBE_HOST`、`TRACELAB_STARTUP_PROBE_PORT`、`TRACELAB_STARTUP_EXIT_AFTER_PROBE` 配置，不向父 `marks.jsonl` 写入、不连接测量工具的主窗探针。不随意重写 PyInstaller 自身环境变量；source/frozen 两路各自验证。

### 4.4 状态语义和交接

| 真实事件 | 面板状态 |
| --- | --- |
| child 首次显示，父程序尚在准备 | 正在启动 TraceLab… |
| 父程序开始扩展 runtime/GUI 模块准备 | 正在加载分析组件… |
| 父程序开始 MainWindow 构造 | 正在准备工作区… |
| 等待 ≥12 秒仍未完成 | 启动比平时久一些，请稍候…；继续保留最近真实阶段，不能显示已就绪 |
| 主窗完成首次 paint 后回到事件循环，窗口仍存活可见 | finish，关闭面板；主程序接管 |
| 父程序启动异常 | 关闭面板；记录原异常，并提供一次简洁失败提示/日志位置；保留非零退出 |
| 父进程死亡/连接丢失 | child 立即退出，不留无限旋转的孤儿窗口 |

12 秒只影响等待文案，不伪造阶段；绝不能沿用 HTML 的 8/20 秒自动成功逻辑。没有人为成功超时，不等待 idle preload、非当前分析页面、或全部后台文件任务才交接。

`_arm_startup_observation` 应做最小扩展，使首帧回调在生产路径可用、在 show 前安装；外部性能 probe 仍然只在 timing 开启时接入。首个 Paint 的 eventFilter 在绘制前触发，所以 finish 必须排队到这次事件返回之后，并再次检查主窗可见/未关闭。`show()`、一个与 Paint 无关的 0 ms timer，都不是 finish 条件。尽量复用同一观察者，不再给 MainWindow 添加第二套 flags/多处写入。

主程序未就绪而还活着时允许长等待，不把后台心跳或动画帧等同于主程序可交互。启动异常发生在 QApplication 前时，使用不会重新加载 MainWindow 的 Windows 最小错误提示；QApplication 已存在时使用已有错误对话框能力。失败提示不重新启动软件，也不吞掉异常。

## 5. 分阶段执行和测试

### Task 0：记录基线、冻结 B 和补可复现探针

- 重新检查 HEAD、dirty、所有上述入口和测试；先保留 HTML/hash，记录目标 Windows 包型、EXE SHA-256、部署路径、DPI、机器/VM。
- 基线仅跑受影响的入口、计时和 import focused 测试；不先跑全套。记录正常入口、hidden modes、layout probe 的现有行为。
- 在已有测量工具上先记录同机同包主窗口启动数据。准备受控“父程序加载前暂停约 5 秒”的诊断 probe，后面证明面板先出现且动画持续；故意延迟样本单独标注，不混入性能数据。
- 先加会失败的测试：普通入口反馈发生在 bootstrap 前；hidden modes 不反馈；parent ready before child suppress late show；父进程结束后无遗留 child；频谱所有曲线含描边位于画布内。
- Windows 暂不可用时可继续源码工作，但记录 native/performance `UNKNOWN`，不能把 Task 0 性能基线写成完成。

Focused（现有）：`tests/test_startup_entrypoints.py`、`tests/test_startup_timing.py`、`tests/test_startup_import_boundary.py`。新增测试在后续对应 owner 中编写，不新增与文档措辞一一映射的测试。

### Task 1：实现独立 B view，先冻结视觉

- 新增 `ui/startup_splash.py`，按 §3 绘制；输出固定逻辑大小、普通/长等待/静态动画偏好状态。
- 必要时仅迁移 Qt DPI/icon helpers，保留 app 原导出；避免 ui_kit import 链进入子进程首帧。
- 新增 `tests/ui/test_startup_splash.py`：路径边界与峰顶、所有 tips 文本容纳、字体/DPI、计时器释放、连续更新不重建路径、关闭后无回调。测试显式设置父对象/销毁 drain，使用既有隔离 fixtures。
- 运行真实 Qt 渲染，将 native 截图与 B 面板同尺寸对照；检查背景层次、tips 分区、阴影、四角透明、中文和峰顶。不能只对 CSS/QSS 常量做字符串断言。

Boundary：`tests/ui/test_import_boundaries.py`；如果使用 QSS，追加 `tests/ui_kit/test_qss_border_shorthand.py`；如果新增 connect，追加 `tests/ui/test_no_lambda_signal_connections.py`。不运行全部 tests/ui。

退出：独立 view 可渲染，B 的信息结构与外观完整，无 demo 外壳；本阶段仍不宣称启动集成完成。

### Task 2：实现父 controller、hidden child 与退出合同

- 落实 §4 的协议和 source/frozen 参数构造，补开发开关 `TRACELAB_STARTUP_SPLASH=auto|0|1`：auto 为 Windows 普通 GUI 默认；0 禁用；1 强制普通 GUI/source 渲染。hidden/layout 路径即使设 1 仍禁用；offscreen 集成测试仅通过明确测试入口开启。
- 新 child 模式加入原互斥 parser；限定唯一可展示的是普通 GUI controller 主动启动的 splash child，不能让其他 child 再 spawn 它。
- 更新过宽的 `add_argument("--startup` 静态禁止项：保留“不添加 timing CLI、先分派旧 hidden child”等合同，改测新模式的精确分派/冲突/缩写/非法 payload；不是简单删除断言。
- 新增 `tests/test_startup_feedback.py` 与 `tests/test_startup_splash_child.py`，覆盖乱序、终态幂等、连接前主窗就绪、spawn/连接失败、EOF、parent hard kill、child 停止响应、两个独立启动 session 不串线、无 console streams。
- 新增独立子进程 import probe：controller import 无 Qt；child 首显闭包不含 MainWindow、pyqtgraph、numpy/pandas/scipy/asammdf、io.loader、acquisition、ui.widgets、ui_kit。不要用 inspect 主进程已污染的 sys.modules 来证明。

Focused：新增 owner 测试 + `tests/test_startup_entrypoints.py`、`tests/test_frozen_batch_acceptance.py`（所有 hidden modes 两两冲突列表需包含新模式）、`tests/test_extension_probe.py` 中真实 launcher 节点。

退出：真实 child 动效在父主线程被受控阻塞时持续更新；能在无 QApplication 的父程序中安全 start/finish；清理测试没有残留进程。

### Task 3：接入普通启动、真实阶段与交接

- 普通入口去除 launcher 抢先 bootstrap；hidden importer/Batch 仍保留。main 在 bootstrap 前发起反馈；主窗逻辑的顺序和功能保持。
- early exception 先有诊断出口，MainWindow 成立后仍使用现有 toast/Qt/thread hooks；异常日志保留原 traceback。
- 首帧观察在 show 前安装，排队完成一次交接；timing 开关关闭时同样有效。发送 finish 后主程序继续既有 idle preload，不等待子进程回收，不新增预加载阻塞门槛。
- 增加 integration 用例覆盖 main.main 和根 launcher 两条普通入口、立即退出、慢 bootstrap、MainWindow 构造抛错、主窗先 ready、测量工具 exit-after-probe 自动退出等。
- 同步 `ui/hints.py` 与 `ui/quickref.py` 的启动说明：面板表示启动中、就绪后自动退出；它不是项目加载进度或分析百分比。不导入这些目录为子进程取 tips。

Focused：`tests/test_startup_entrypoints.py`、`tests/test_startup_import_boundary.py`、`tests/test_diagnostics.py` 与新增集成测试；`tests/ui/test_startup_preload.py` 和 `tests/ui/test_main_window_smoke.py` 中首次显示/关闭节点。

Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`。不放宽 whitelist，不扩展到图表算法测试。

退出：真实普通入口可完成“面板 → 主窗”；隐式探针/布局模式无面板；主窗前后的数据、预加载、错误语义保持。

### Task 4：测量与打包闭包

- 为 controller 事件增加 parent-side 收到 `splash_painted`、`splash_closed` 的诊断记录。子进程只发事件和自己的帧统计，不把其本地时间当父时钟。
- 扩展既有 `tools/measure_windows_startup.py`，保留主窗口 first_frame / interactive 探针身份；让外部测量进程收到面板事件并用自身单调时钟盖接收时间，不能靠相减两个进程各自的相对 mono_ns 算“启动到面板”。反馈事件从 controller 的纯 I/O 路径提前转发，不能等主窗 first_frame 才首次连接并集中补发。测量协议区分 feedback 与 main-interactive 消息角色，分别校验 run/session；事件传输延迟单列，首显以录屏交叉验证。
- 同时输出 feedback disabled/enabled 的首次可见时间、主窗可交互时间、child 收尾时间、进程峰值/残留；开启 splash 不能让工具误连到 child 的 QApplication。
- 检查三个 builder 的 frozen 导入闭包，直接静态 import 可被分析时不机械堆 hidden-import；仅为真正动态 seam 增补明确模块。沿已有 PNG 资源，不引入 HTML、网络字体、Matplotlib、WebEngine、QML/Tk。
- Full/Lite/Modular 都需保留新入口和 view，Modular child 不依赖 optional extensions；没有 media/MAT 扩展也必须显示面板。

Focused：`tests/test_startup_timing.py`、`tests/test_packaging_imports.py`、`tests/test_windows_build_script.py`、`tests/test_windows_lite_modular_build_script.py`、`tests/test_windows_runtime_dependencies.py`。修改 bundle policy 才追加 `tests/test_windows_bundle_policy.py`；修改 native/probe 边界才追加其 owner 测试。

退出：source 工具合同通过、三个冻结产物完成实际启动/退出验证；仅构建脚本测试通过不能宣称 frozen 已完成。

### Task 5：目标 Windows 验收和交付

- 使用 production `--windowed` EXE；不能用 console 构建替代。记录实际包路径/hash，完整解压到本地 NTFS；共享盘/VM 场景单列。
- 热启动每种配置 10 次，报告全部样本、中位数、P95、最大值；冷启动至少 3 次重启后首启，报告全部样本与中位数。build smoke 已热身的运行不能写成冷启动。
- 同一最终源码/同一包以开发开关 0/auto 做匹配对照，避免混入重新构建/路径/扩展变化。故意阻塞探针单独测，不能混入正常性能统计。
- Windows 100/125/150/200% DPI、多屏、非主屏启动、小工作区、前台被其他应用占用时检查：四角、阴影、峰顶、tips、任务栏、焦点、主窗交接、无晚到面板。
- 录制至少正常启动、受控长启动、父进程异常退出/强制结束三条连续视频；静态截图不能证明动画在加载时仍在运行或不存在闪烁。
- 执行一次可复现的 hidden modes 包级 smoke，确认不弹面板、不多出 QApplication/进程；Modular 未安装扩展场景单测。

初始验收目标（均须目标机器证据）：

| 项目 | 判定 |
| --- | --- |
| 外部发起至面板首次可见 | 热启动中位数 ≤1.0 s、P95 ≤1.5 s；冷首启中位数 ≤2.0 s；超标按入口前/子 Qt 启动分段归因，不能悄悄改目标 |
| 主程序真实加载时的面板响应 | 受控 5 s 父主线程停顿下，频谱/活动指示仍推进，tips 到期更新；正常样本无 >250 ms 的明显动画冻结 |
| 主窗可操作时间退化 | splash 开启比禁用的热启动中位数增加不超过 max(200 ms, 5% 基线)，并报告 P95/最大值；超过则优化或标未达标 |
| 主窗 ready 后交接 | 目标 ≤200 ms，绝不为了播放完成而等待；无主窗出现后新弹出的 splash |
| 清理 | 正常结束、父 hard kill 后目标 1 s 内无 splash 进程/窗口；连接失败不会阻塞主程序 |
| 视觉 | 没有 slogan/纯白大底/波峰缺口/demo 控件；四角、文本及频谱在全部 DPI 下完整 |
| 非 GUI 模式 | 所有既有 hidden modes/layout probes 无启动面板，不污染原退出码/JSON/计时文件 |

如果入口前延迟已经超过首显目标，仍可提交有价值的实现与证据，但状态必须是“功能实现，首显目标未达成”，另列 bootloader/native launcher 为待决策后续；不可未经授权把本计划扩成独立 launcher 工程。

## 6. 执行约束、回退和最终报告

1. 顺序推进 Task 0→1→2→3→4→5；每阶段先 targeted 再实际影响的边界。不要因为文件名有 ui 就运行整个 tests/ui。
2. 本地 Qt gate 使用项目运行时：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <对应测试>`。不要让源码探针写入真实 QSettings；沿既有 fixtures，跨目录问题保留根 conftest 修复。
3. 若仅按本计划增加隔离的反馈链，focused/boundary/native gates 足够；不默认跑全套。若实施扩大到全局入口/异常体系的大范围重构或进入 release/merge acceptance，记录扩大原因，由唯一负责人在稳定 HEAD/dirty 指纹上顺序执行主套件 `--ignore=tests/acquisition_ui` 与单独 acquisition_ui，一次即可，不重叠。
4. 回退入口是 `TRACELAB_STARTUP_SPLASH=0`：不启动 child、不创建 IPC、既有主程序照常运行；不影响 extension bootstrap、计时、项目或预加载。UI、controller、入口接入按独立切片提交，便于局部回退。
5. `.state/startup-splash/` 保存开发日志、帧序列、进程检查和原始测量；需要长期保留的验收摘要写入 `docs/analyzer/verify/2026-09-23-startup-splash-b-acceptance.md`。不把本机缓存/测试产物加入 Git。
6. 实施完成前检查 lesson 状态；只对确实新发现且可复发的模式记录 lesson，不为普通配色修改制造新 lesson。
7. 最终报告分别列 `source implemented / focused verified / macOS native rendered / Windows frozen verified / first-feedback target met / no-startup-regression verified`。缺机器、缺产物或未执行写 UNKNOWN；崩溃、超时、进程未回收写失败/UNVERIFIED。不互相替代。

## 7. 依据与本次文档验证

本轮已经阅读真实入口、app.main、startup coordinator、timing/tool 接口、hidden-mode 测试和三个 builder 的相关配置，并核对 B 的实际 HTML。既有启动提速计划是背景，不能将其历史性能记录当成本计划当前实测。

相关项目 lessons：

- [视觉还原必须检查真实渲染](../../lessons-learned/codex-visual-parity-rendered-screenshot.md)
- [已接受 HTML 的操作与状态映射](../../lessons-learned/codex-approved-html-operation-parity.md)；本例只映射 B 面板，明确排除 demo 控制台。
- [windowed child 不依赖 console streams](../../lessons-learned/codex-frozen-probes-do-not-require-console-streams.md)
- [Windows 构建验证覆盖全部 profile](../../lessons-learned/windows-build-validation-covers-every-profile.md)

已核对的官方依据：Qt GUI 对象须在 GUI 主线程使用，事件循环不运行时 timer 无法持续推进；因此单主线程中的长导入/构造不能靠 QTimer 维持动画。[Qt 5.15 Threads and QObjects](https://doc.qt.io/archives/qt-5.15/threads-qobject.html)、[Qt 5.15 QTimer](https://doc.qt.io/archives/qt-5.15/qtimer.html)。frozen 下 `sys.executable` 指向用户运行的 EXE，资源根与可执行路径不同，child 命令/图标路径需分别处理。[PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html)。bootloader splash 是单独的启动机制，不等同于应用里的 Qt 面板。[PyInstaller splash startup](https://pyinstaller.org/en/stable/advanced-topics.html#splash-screen-startup)。这些依据不要求升级项目的 Qt/PyInstaller。

**本次只是计划文件变更**：检查文档范围、路径/符号引用、设计 hash、阶段间一致性及 whitespace；不运行运行时测试。以上测试和性能表是未来执行清单，不是已通过的结果。
