# Windows 启动提速与分析页面空闲预加载计划

- 日期：2026-09-22。
- 状态：**源码实施已到 Task 3；Task 0 的 Windows 基线、Task 4、Task 5 与冻结包验收未完成。** 执行记录在 `.state/startup-plan-execution.md`。本文仍不代表 Windows 性能已验证。
- 编写基线：`bcb23bdb23f8eb8e736e64243cfdbea17383917d`，`app_meta.py` 版本 `v8.3.1`；工作区存在另一项扩展安装器任务的未提交改动。执行前重新记录 HEAD 和相关文件指纹，不能把该基线当成后续固定源码。
- 用户观察：Windows EXE 双击后约 5–10 秒主窗口才出现；希望接近 macOS 终端启动的速度，并允许进入软件后自动准备非当前分析页面。
- 执行方式：默认单负责人顺序实施；不要求多代理。当前授权为编写计划，产品实现另行按接受后的计划执行。
- 主要策略：**减少首屏前的非必要导入，先使当前页面可操作，再在空闲时间分批预加载其他分析页面。**

## 1. 目标、范围与完成口径

### 1.1 用户体验目标

1. 主窗口出现时，文件入口、时域工作区、基本导航已经可以操作，不能先显示一个长时间冻结的空壳。
2. FFT、时频、FRF、阶次的非当前页面自动准备；用户提前点击时，目标页面优先。准备完成后切页复用同一实例。
3. 预加载不得触发分析计算、导入用户文件、切换当前 Section/View、改变选中通道、工程 dirty 状态或图表相机。
4. 预加载不能把启动卡顿转移到用户拖动、文件导入、绘图或切页期间。
5. 首次文件导入和首次分析也要测量，避免以转移等待时间冒充整体体验提升。

### 1.2 初始性能目标

以下是待 Task 0 校准的工程目标，**不是当前能力或收益承诺**。校准必须记录硬件、基线和调整原因，不能在结果不达标后悄悄放宽口径。

| 指标 | 初始目标 | 说明 |
| --- | --- | --- |
| Windows 热启动至主窗口可操作 | 中位数 ≤ 2.5 秒，且较同机同包型基线减少 ≥ 40% | 与用户的 5–10 秒观察分开，以正式基线为准 |
| Windows 重启后首次启动至可操作 | 中位数 ≤ 4 秒 | 单列冷启动；若主要时间在 Python 入口之前，按 Task 5 诊断 |
| macOS 源码启动 | 不出现超出重复测量波动的退化 | 同机同命令前后比较；不能用跨机器比值判定打包损耗 |
| 已预加载页面的切换 | 不比现状退化 | 同样的页面、数据与 View 状态比较 |
| 预加载构造步骤 | 主线程单步目标 ≤ 16 ms | 这是拆分预算；一个长构造函数不能靠定时器抢占 |
| 空白会话预加载期间响应 | 探针事件循环额外延迟 P95 ≤ 50 ms、最大 ≤ 100 ms | 扣除探针调度周期，记录原始序列；配合前台操作判断 |
| 空闲时预加载完成 | 首屏可操作后累计可用空闲时间目标 ≤ 5 秒 | 用户持续操作时允许更晚，不能为追赶截止时间抢占交互 |

“大幅提速达成”必须有目标 Windows 包的前后对照。只完成源码优化、启动提示或 offscreen 测试，不满足该结论。

### 1.3 范围限制

- 保留 PyQt5/pyqtgraph、`onedir` 和 `--noupx`；不在本计划引入 Nuitka、换 UI 技术栈或重新设计整个 MainWindow。
- 不删除受支持格式，不通过默认切换 Lite Modular 换取性能数字，不修改 DSP、采样率、单位和通道身份。
- 不默认关闭安全软件或配置排除项，不把签名当成已证实的启动加速方案。
- 启动提示仅作为入口前等待仍明显时的辅助项，不能代替主窗口可操作时间验收。
- 不改 `CLAUDE.md`、版本号、历史报告；不提交其他任务的改动。

## 2. 已有证据与待确认项

### 2.1 当前源码确认

| 路径 / 符号 | 当前事实 | 优化含义 |
| --- | --- | --- |
| `MF4 Data Analyzer V1.py` | Windows 构建入口；先分派 hidden probe/smoke 模式，再进入 `app.main()` | 计时和预加载必须兼容真实入口，不能让 child 模式启动主界面 |
| `mf4_analyzer/app.py:main` | 导入 MainWindow、应用字体/QSS、构造完整窗口之后才 `show()` | 首屏前存在可拆分工作；只在 `MainWindow()` 后加提示太晚 |
| `io/__init__.py`、`io/loader.py`、`io/source_adapters.py` | 包初始化串联 loader/adapter；pandas、MDF/异常类型、Excel 依赖在启动链导入 | 必须切断全部可达路径，不能只移动 loader 中一行 import |
| `ui/chart_stack/stack.py:ChartStack.__init__` | 一次创建四个 AnalysisSectionPage 及其首张图表，还创建 UltraViewPage | 首期延迟四种分析图表；UltraView 是否调整由计时决定 |
| `ui/analysis_section_page.py:AnalysisSectionPage.__init__` | `_cards = [self._make_card()]`，随后直接访问首张卡 | 需明确“页面容器存在”和“图表已就绪”两个阶段 |
| `ui/main_window/window.py:_init_ui/_connect` | 提前保存全部画布引用并连接 Section/View/Inspector 信号 | 延迟构造必须同时迁移接线，防止访问属性又把所有图表提前建出来 |
| `ui/inspector.py:Inspector.__init__` | 所有分析 contextual 控件启动即建 | 有潜在收益，但状态读写面较大，安排为有条件的独立阶段 |
| `tools/windows_bundle_policy.py`、三个 Windows builder | 已使用 onedir/noupx，并排除、裁剪部分无用依赖和资源 | 不重复把现有裁剪列为新收益；hidden-import/collect 并不等于运行时全部加载 |

### 2.2 本轮诊断观察

2026-09-22 在 macOS 源码环境运行单次 offscreen 探针，隔离 QSettings，正常退出码 0：

| 阶段 | 观察值 |
| --- | ---: |
| 入口与基础 Qt | 37.2 ms |
| UI 导入 | 411.4 ms |
| QApplication、样式、字体 | 111.5 ms |
| MainWindow 构造 | 1292.8 ms |
| show 与首批事件处理 | 158.7 ms |

构造内部包含 FileNavigator 86.2 ms、ChartStack 330.6 ms、Inspector 293.0 ms；四个 AnalysisSectionPage 合计 213.4 ms，**已包含在 ChartStack 中，不可重复相加**。包装计时器前还导入了待观测类，分段和不是严格端到端基线。

另一独立 `-X importtime` 进程确认导入 MainWindow 后已加载 pandas/asammdf/openpyxl/xlrd/qtawesome。两次进程缓存状态和测量方式不同，不能拼接时间。字体阶段出现 macOS 缺少 Microsoft YaHei 的告警，不能推断 Windows 有相同成本。

以上仅说明值得优化的路径，不证明 Windows 5–10 秒的根因。旧 [2026-07-13 调查](../reviews/2026-07-13-package-size-and-startup-optimization.md) 的包体、耗时和收益估计均为历史记录，不复用为当前基线。

### 2.3 Task 0 必须补齐

- 用户实际包型、构建版本、EXE/hash、CPU/架构、是否虚拟机、SSD/网络或共享目录、Windows 与安全软件环境。
- 同一 Windows 机器的源码与同提交 EXE 对比；本地 NTFS 完整解压目录作为受控位置。
- 外部启动到 Python 第一条计时标记之间的时间、首帧与真正可操作之间的时间。
- 启动时实际导入闭包，包括届时已合入的扩展 bootstrap；不能仅按目前 app.py 推断未来冻结入口。

## 3. 必须保持的设计合同

### 3.1 线程与调度

- QWidget、画布、字体注册、QPixmap 和 UI 信号绑定全部在 GUI 主线程执行。后台线程只用于经验证不依赖 GUI 的准备工作；首期不泛化并行 import，不引入一组抢 GIL/导入锁的“预热线程”。
- 主窗口首帧与基本交互就绪后才启动预加载。使用有界的单次调度，每完成一个小步骤归还事件循环；不使用循环 `processEvents()`、持续零毫秒重试或一次回调创建四张图。
- 调度预算不能中断一个已开始的 Qt 构造函数。目标机上单步超预算时必须拆分真实构造/绑定步骤；测出仍有长任务时，“无感”验收为未完成。
- 已加载页面仍驻留，首版不新增自动卸载、缓存淘汰或重复重建策略。

### 3.2 Owner 与生命周期

建议新增 `ui/main_window/startup_coordinator.py`，由 MainWindow 创建和销毁。它仅拥有待预加载队列、定时器、交互让行和关闭状态；ChartStack/AnalysisSectionPage 继续拥有图表，Inspector 继续拥有设置控件，ViewManager/AnalysisContext 继续拥有用户状态和执行上下文。

页面资源状态明确为 `uninitialized → preparing → ready`，失败进入 `failed`。状态由页面 owner 持有，协调器读取它，不复制另一套 readiness 真相。

- `ready` 必须意味着构造完成、接线完成、最新状态投影完成；半成品不能通过旧别名暴露给消费者。
- 请求同一页面只准备一次。用户请求提升优先级，不能在已有 preparing 实例旁边再建一份。
- 取消/失败只清理本次部分构造对象，断开相应信号并停止定时器；保留诊断。预加载失败不弹出一串模态窗口，用户进入失败页面时提供具体错误；编程错误进入既有异常钩子，不伪装成可选依赖缺失。
- 窗口关闭时取消队列并禁止回调访问已销毁对象；预加载状态不写入项目、preset 或 QSettings。
- 会话重置不必销毁已准备的图表，但所有待应用的会话内容必须失效。用户从工程 A 切到 B 后，只能投影 B 的当前状态，不能回放 A 的旧闭包。

### 3.3 页面访问与信号接线

- 提供明确的非创建查询和显式准备入口（例如 `peek` / `ensure_ready`，名称在实现时按现有风格确定）；遍历“已存在画布”不能隐式创建所有页面。
- 保持受支持的 `canvas_fft` 等兼容入口；必要时兼容访问显式触发准备，但首屏初始化、状态遍历、tick 更新不能走这些触发型入口。用导入/构造计数证明启动没有被兼容属性重新拖回 eager 路径。
- 同步兼容入口不能偷偷返回 Future/None，也不能用嵌套事件循环等待正在分步构造的对象。先列出同步消费者；确需兼容的同步路径保留显式同步准备能力，应用交互与预加载走异步 readiness 路径，二者共用同一实例状态。若 preparing 状态下仍存在不可改的同步消费者，先解决该调用合同再启用自动预加载。
- 每个新画布走统一绑定路径，涵盖 cursor/pin、markup、quality、slice、focus 和信号解除。首张图表与后续 split pane 共享必要的生命周期合同，避免另一份手写 connect 清单。
- ViewManager、轻量状态及页签容器可以先存在。不存在画布时，参数更新先由既有权威状态保留，准备完成后应用最新值；不能把“未构造”当成“没有 View/没有用户参数”。
- 切页/渲染遵守现有 TimeRenderGate、analysis restore 和 View settlement；新协调器不另建 render gate，也不扩大 state-ownership 白名单。

### 3.4 “空闲”与用户抢先操作

- 输入、鼠标拖动、模态对话框、文件导入/工程恢复、分析执行和渲染繁忙期间不启动新的可选步骤；读取或订阅现有 owner 状态，不新增散落的 MainWindow busy 标志。
- 输入后的初始安静窗口可设为 200 ms，空闲步骤之间初始间隔可设为 25 ms，均在 Task 0/3 根据实际延迟测量调整；这些是预加载策略，不能修改 canvas 既有 150 ms 质量 quiet timer。
- 用户点未就绪页面时，优先该页面，并立即显示可取消/可切走的轻量“正在准备”状态；其余页面继续等待。准备回调校验最新目标，快速 FFT→FRF→时域不会在完成时把用户拉回 FFT。
- 工程恢复、导出、UltraView 等真正依赖页面画布的非点击消费者也必须明确请求所需资源并等待就绪；不能靠用户先点过某页才正常工作。Batch 的中立计算/独立 renderer 不应为此依赖主窗口页面。
- 忙碌让行只阻止可选预加载。若工程恢复或当前用户操作本身需要某页面，所需准备属于该前台任务的依赖，沿现有安全调度点执行；不能因为 restore=busy 而永久阻止 restore 正在等待的页面。GUI 线程不做阻塞 wait/join，不通过嵌套事件泵解开等待。
- 空闲预加载只准备界面，不提前运行 FFT、读取文件或填充计算结果缓存。

## 4. Task 0：建立可信基线与启动分段计时

Owner：真实入口、`app.py`、既有 diagnostics；拟新增 `mf4_analyzer/startup_timing.py`（仅标准库）和 `tools/measure_windows_startup.py`。名称为拟新增，不是现存工具。

1. 在受控 `.state/startup-perf/<run-id>/` 中记录 HEAD、相关 dirty 文件 hash、依赖版本、包型、EXE/hash、机器信息和运行参数；计时关闭时不得增加目录扫描或重依赖导入。
2. 以 opt-in 环境配置启用打点，真实入口最早可行位置先记录时间，再导入 app；覆盖 `python -m mf4_analyzer.app` 的入口，并保留所有 hidden child/smoke 分支。
3. 记录阶段：外部 launcher 发起、Python 入口、GUI 模块导入结束、QApplication/样式完成、首屏构造完成、首帧、基本交互就绪、各页面 ready、全部预加载完成。预加载完成不能作为“应用可用”的前置条件。
4. 外部 launcher 使用单调计时，按同一 run-id 接收 ready/paint 标记并记录接收时间，避免直接相减未经验证同源的跨进程计时值。进程内阶段另用自身单调时钟。记录观测通道开销。
5. `show()` 返回和零延时定时器触发都不能单独代表可交互。工具在首帧之后发送排队交互探针并获得响应，确认主要入口已启用；前台另验证实际拖窗、文件入口和切页。`WaitForInputIdle` 只作辅助信息。
6. 每个基线/优化包做热启动 10 次，报告原始值、中位数、P95、最大值。冷启动至少 3 次独立重启后的首启，报告全部样本和中位数，不用 3 个样本包装成可靠 P95。更新/解压后首启单独分组；不通过重命名 EXE 或清缓存制造假冷启。
7. 构建脚本已有 smoke 热身，**热身后的测试不能称为冷启动**。基线与优化在相同路径、硬件、安全策略、依赖和用户设置条件下比较；普通空会话和打开工程分别测量。
8. 若 Python 入口前占主要时间，尽早执行 Task 5 的系统诊断；若其耗时已超过总目标，明确记录仅优化 UI 无法达标，仍可完成有独立收益的代码阶段。

Focused：拟新增 `tests/test_startup_timing.py`、`tests/test_startup_entrypoints.py`，验证禁用零副作用、缺标记/超时/异常退出非成功、child 不创建主窗、run-id 对应和计时文件失败可诊断。既有入口边界：`tests/test_acquisition_runtime_smoke.py`、`tests/test_importer_runtime_smoke.py`、`tests/test_packaging_imports.py` 中受影响节点。

退出标准：取得目标 Windows 基线与分段归因表。Windows 暂不可用时标 `UNKNOWN`，可以实施有独立证明的导入优化，但不能以 Mac 耗时预测最终 EXE 成绩，也不能宣称 Task 0 完成。

## 5. Task 1：缩短启动导入链

Owner：`io/__init__.py`、`io/loader.py`、`io/source_adapters.py` 及实际重新拉入依赖的 owner；冻结合同由 `io/runtime_dependencies.py` 维护。

1. 先添加独立子进程探针：真实 UI 启动至 interactive 标记之前，pandas/asammdf/openpyxl/xlrd 不应被导入；首期不预加载这些库，以保持断言和成本归属明确。只测 `import mf4_analyzer.ui` 不够，必须取得并使用 MainWindow。
2. 延迟数据格式实现导入，保留 DataLoader/FileData/adapter 的公共导出与类型语义；不在导入时创建 DataFrame，也不让类型注解或异常元组重新导入 MDF。
3. 兼容 `HAS_ASAMMDF/HAS_OPENPYXL/HAS_XLRD` 及 MDF monkeypatch 接缝：列出全部消费者，轻量发现与实际加载分离。`find_spec` 只能证明可发现，不能报告“原生库已经可用”；真实使用时保留依赖缺失/损坏/数据错误的区别。
4. 审查 `source_adapters` 的 `_AsamMdfException`、metadata probe、loader.MDF 访问及 pandas 类型判断，保证延迟后首次 MF4/Excel/CSV 和 Batch 仍正常。
5. 当前冻结合同扫描函数内第三方导入。移动 pandas 后必须明确登记 base 依赖及收集策略，不能为绕过扫描改成字符串动态导入，也不能未经评估直接 `collect-all pandas` 扩大包体。若需要区分“基础包由标准 hook 收集”和“格式资源需 collect-all”，只扩展现有合同，不新建第二份依赖表。
6. 记录优化后导入闭包、首屏收益，以及首次格式导入的额外耗时。首次导入继续经过已有 worker/progress 路径，不能改到 GUI 主线程同步执行。

Focused：拟新增 `tests/test_startup_import_boundary.py`；既有 `tests/test_mf4_loader.py`、`tests/test_excel_loader.py`、`tests/test_source_adapters.py`、`tests/test_channel_frame.py`，加 `test_main_window_smoke.py::test_load_csv_flows_through_navigator`。

Boundary：`tests/test_windows_runtime_dependencies.py`、`tests/test_packaging_imports.py`、`tests/ui/test_import_boundaries.py`、`tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py`、`tests/test_native_import_boundaries.py`。改动打包参数时追加相应 Full/Lite/Modular build-script owner 测试；实际格式读取仍须 Windows frozen smoke。

退出标准：重依赖不再进入空白首屏导入链；真实 MF4/Excel/CSV 行为保持；冻结合同没有漏包或无依据扩包。单独提交和记录收益后再进入 UI 生命周期改造。

## 6. Task 2：把分析图表改为可延迟构造

Owner：`ui/analysis_section_page.py`、`ui/chart_stack/stack.py` 及首张图表绑定 owner；MainWindow 仅做协作接入。

1. 先冻结 eager 模式下的页面状态、信号次数、首张/第二 pane、focus、pin、markup 和几何行为。保留 eager 构造作为兼容和回退路径，不批量改写无关测试。
2. 增加“容器/管理器先建、图表稍后建”能力；先以一个 FFT 页面走通，再推广至时频、FRF、阶次。独立页面测试可继续显式使用 eager，应用启动集成测试必须使用真实 deferred 路径。
3. 清理 `_init_ui/_connect` 的 eager 别名访问，将画布级绑定集中到一次性的 ready/bind 边界；早期可绑定的 manager/tabbar 信号保持早期绑定。
4. 区分所有页面状态遍历与现存画布遍历。tick、显示设置、时间范围、通道候选等在页面后建时必须使用最新状态；预加载本身不得调用模式切换或语义编辑槽。
5. 保持每页 pane 上限、split、View 身份、分析缓存和质量 settlement 的现有语义；隐藏构造不能临时 show 隐藏页、抢焦点或改变当前页布局。
6. 先支持明确请求的延迟准备，再接 Task 3 的自动预加载。不要一步同时延迟全部 UI、并发导入和改 Inspector。

Focused：`tests/ui/test_analysis_section_page.py`、`tests/ui/test_chart_stack.py`、`tests/ui/test_analysis_context.py`、`tests/ui/test_main_window_smoke.py` 中构造/切页/接线节点；补充“未创建→参数变化→创建后最新值”“首张图表只绑定一次”“即时切走”的回归。

Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`；触及 backref/画布构造时追加 `tests/ui/test_pg_canvas_backref_invariants.py` 和对应 canvas owner 测试。不得放宽 ratchet 白名单。

画布生命周期或首次绘制路径改变时，保留 `tests/ui/test_pg_timedomain_canvas.py` 的 `TestViewRestoreSettlement`、`TestDiscreteSettle` 与 paint-timer backstop；分析图表分别跑 `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_frf_canvas.py` 的相关初始化/AA 节点，不能以预加载为由改 ink 阈值或质量 quiet timer。

退出标准：首屏只创建当前图表，四个非当前图表均可被显式请求正确准备；准备前后项目状态等价，现有兼容消费者已分类接入。

## 7. Task 3：自动空闲预加载与前台优先调度

Owner：拟新增 startup coordinator、MainWindow 最小接入、页面 owner 的分步准备接口。

1. 默认空白启动完成后，按 FFT→时频→FRF→阶次顺序准备；顺序仅是初始策略，用户请求永远优先，不依赖机器本地历史偏好。
2. 按 §3.4 接入现有忙碌 owner 与输入事件，使用有界单次计时器。持续操作会推迟预加载，操作结束后继续；禁止忙碌期间零毫秒轮询。
3. 测量每个构造步骤及事件循环延迟。如果现有 `_make_card()` 在 Windows 上超过预算，继续在 owning canvas/card 内拆分可分阶段的初始化，保持 backref 声明，不复制 renderer 逻辑；重型不可拆步骤无法满足预算时如实记录，不能称为无感。
4. 优先请求不强制同步完成整页，进入准备状态后允许切走；重入时保留最新目标。准备资源与激活/渲染分离，旧回调不能覆盖新目标。
5. 将需要画布的工程恢复、导出、UltraView 捕获及分析结果交付统一经过 readiness 边界。资源就绪后继续既有 restore/compute 队列；工程打开后的非当前 View 自动重算合同保持。
6. 增加开发诊断开关，可关闭 idle-preload 或强制 eager 进行对照；不新增普通用户必须配置的选项，也不将该开关存入工程。
7. 若引入“正在准备/准备失败”等可见交互，同步 `ui/hints.py`、`ui/quickref.py`；正常预加载无需常驻进度条。

Focused：拟新增 `tests/ui/test_startup_preload.py`，覆盖优先级、去重、让行、恢复、超时/失败诊断、退出清理、快速切页和无后台计算。既有 `tests/ui/test_time_section_entry.py`、`tests/ui/test_view_switch_reentrancy.py`、`tests/ui/test_section_entry_presentation.py`。

集成节点：`tests/ui/test_project_session.py`、`tests/ui/test_session_reset_on_last_close.py`、`tests/ui/test_analysis_view_bridge.py`、`tests/ui/test_analysis_viewport_cold_restore.py`、`tests/ui/test_ultraview_project_session.py`、`tests/ui/test_pinned_cursor_lifecycle.py` 中与延迟资源相关的场景；`tests/ui/test_analysis_view_cache_residency.py` 防止准备过程清空缓存。

退出标准：空闲会自动完成全部页面；抢先点击、导入、工程切换和立即退出安全；Windows 前台事件响应与真实几何通过。单次 offscreen 无卡顿不能替代该验收。

## 8. Task 4：按测量结果补充优化 Inspector / 图标

这是有条件阶段：Task 1–3 后目标已达成则跳过，并记录原因；只有残余首屏成本显著时才执行。

- Owner：`ui/inspector.py`、相关 `ui/inspector_sections/`；图标由 `ui_kit/icons.py`/stylesheet owner 处理。
- 优先缩短当前可见控件的重复工作。非当前 contextual 延迟创建之前，先列明状态读取、project/preset 保存、AnalysisContext、signal picker、auto-NFFT provider 的调用合同；不能从“暂时没有控件”读出默认值覆盖用户配置。
- 若确有必要延迟 contextual，分别提供现存查询和显式 readiness 请求；用户参数继续由明确 owner 持有。保存未访问过的页面、打开工程直接分析、第一次切到隐藏页都要正确。
- 图标只优化测得的字体/资源热点，复用打包 PNG 与现有失败回退；不通过隐藏缺字、去掉中文支持或删除许可资源获得速度。
- 只有独立计时证明收益时才考虑 UltraView 空页面的延迟构造；其工程/捕获生命周期作为独立切片处理。

Focused：`tests/ui/test_inspector.py`、`tests/ui/test_inspector_first_show_layout.py`、`tests/ui/test_inspector_width_cap.py`、`tests/ui/test_analysis_context.py` 和受影响的 preset/project 节点；图标改动跑实际图标 owner 测试及 `tests/test_packaging_imports.py`。

Boundary：state-ownership、signal ratchet；改 QSS 时跑 `tests/ui_kit/test_qss_border_shorthand.py`。原生 macOS/Windows 比较首屏与首次切页的宽度、裁切、中文、焦点和布局跳动。

退出标准：有可归因收益且状态/几何保持；否则撤回该独立切片，不把任务扩展成整套 Inspector 架构重写。

## 9. Task 5：Windows 特有加载成本的条件诊断

触发：Task 0 或优化后数据表明 Python 入口前、原生模块加载或冷启动仍占主要时间。

1. 同机对比源码、Full、Lite；Modular 仅在对应扩展任务已交付可验证产物时参与，独立记录功能配置和 runtime 身份。
2. 先对比原部署目录与本地 SSD/NTFS 完整解压目录，记录路径差异；不能把更换机器或减少功能混入代码收益。
3. 必要时用 Microsoft Defender Performance Analyzer 和文件/DLL 访问跟踪确认扫描与 I/O，观察真实进程及路径；“冷热差大”只是线索，不能直接归因 Defender。
4. 若当前 PYZ/收集清单仍有可证实冗余，只在 `windows_bundle_policy.py` 与 runtime dependency 合同内做有针对性的调整；源码有 `collect-all` 不等于冷启动读取整包。
5. 如需更早反馈，可独立评估轻量启动提示。Qt 提示只能覆盖 Qt 初始化之后的等待；PyInstaller bootloader splash 属另一种方案，须测资源成本与平台兼容，不能用它声称 interactive 加速。
6. 输出归因和前后证据；若外部安全策略成为瓶颈，记录剩余时间与部署建议，不自动更改安全策略或承诺签名提速。

Focused：仅运行实际改动的 build-script、bundle-policy、runtime dependency 和 packaging owner 测试。所有包裁剪必须在最终 frozen 包执行既有导入、渲染和 Full 采集 smoke；不能只验证 EXE 出现。

## 10. 最终验收矩阵

| 场景 | 必须观察的结果 |
| --- | --- |
| 空白启动，用户不操作 | 首屏可操作，隐藏页随后自动 ready，无切页/计算/dirty |
| 主窗出现后立即拖动、打开文件、选择通道 | 操作有响应，可选预加载让行；首次导入有既有进度反馈 |
| 未就绪时快速 FFT→FRF→时域 | 仅最新意图激活，旧完成回调不切页，无重复实例/接线 |
| 预加载过程中关闭软件 | 无残留 timer/worker、访问已销毁对象或异常退出 |
| 工程 A 正在恢复时打开 B、清空或关闭工程 | 不回放 A 的通道/参数/相机；恢复任务沿既有取消与 dirty guard |
| 启动后直接打开多 Section、多 pane 工程 | 未访问页面也能正确恢复和按既有合同重算，不需先人工点页 |
| 未预加载前直接触发导出、Batch、UltraView | 明确取得所需资源，正确结果或明确状态，不能因页面未建而崩溃 |
| 页面 ready 后新增/拆分/删除 View，Pin/markup | 首张与后续画布行为一致，焦点/身份/连接次数正确 |
| 部分页面准备失败 | 错误可诊断，当前可用页面继续可用，无自动无限重试 |
| Full/Lite 的 MF4、CSV、XLSX/XLS 和代表性 MAT/音视频 | 格式支持与原包一致；未安装扩展的 Modular 按其原合同提示 |
| Windows 100%/125%/150% DPI 首屏和首次切页 | 中文、图标、布局和画布几何正常；没有先画错误尺寸再明显跳动 |

每个产物记录 `source implemented / focused verified / macOS foreground verified / Windows frozen verified / performance target met`，未跑的标 `UNKNOWN`，失败或异常退出标 `UNVERIFIED` 或具体失败，不能以其他列代替。

## 11. 验证、实施顺序与回退

1. **Task 0 → Task 1 → Task 2 → Task 3**；Task 5 可根据 Task 0 归因提前执行；Task 4 仅在剩余成本需要时执行。
2. 各阶段先建立对应失败探针/行为保护，再改 owner，先 focused 后适用 boundary。不要在每个阶段跑全套，也不要因修改 UI 就运行整个 `tests/ui`。
3. 本地 Qt 测试使用项目环境：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`。新 GUI 测试沿现有隔离 fixture；需要跨目录 gate 时保持根 conftest 修复，fixture 异常用 `tests/test_conftest_autouse_scope.py` / `tests/ui/test_qsettings_isolation.py` 诊断。
4. 性能前后比较使用未开启 importtime/cProfile 的普通进程；剖析结果另存。对照 fresh settings 与用户现有设置，首轮图标缓存和已有缓存分组，不能只选最快一轮。
5. Task 2–3 跨页面生命周期、工程恢复、导入和打包边界，最终稳定集成点由唯一负责人运行一次全套：先检查已有 pytest 进程及 cwd，记录 HEAD/dirty 指纹，顺序运行主套件 `--ignore=tests/acquisition_ui` 和单独的 `tests/acquisition_ui`。不并发、不重复跑同一稳定快照；期间相关源码变化则该结果为 UNVERIFIED。
6. 若仅交付 Task 1 的窄优化，则以其 focused/boundary/frozen 结果完成该阶段，不为“更全面”提前执行最终 UI 集成全套。
7. Import 优化、deferred page 能力、idle preload 分别形成可回退切片。出现前台停顿时先关闭 idle-preload，仍允许按需准备；生命周期有缺陷时回退应用启动为 eager；导入优化可独立保留。
8. 扩展安装器工作正在修改 runtime 合同：本任务只使用其已接受接口，编辑前检查实际状态，不覆盖其未提交文件。若接口改变，在同一合同内适配并追加实际影响的测试，不另写一套扩展加载器。

本次计划文档的验证只包括范围、文件/符号引用、合同一致性和 `git diff --check`，无需运行运行时测试；本文的未来测试清单不代表已经执行。

## 12. 交付物与依据

- 本计划及实施后按任务记录的完成状态。
- 可复用的分段计时和 Windows 前后对照工具；原始数据、环境/构建指纹与前台证据放 `.state/startup-perf/`。
- 一份简明验收记录：每阶段实际减少多少首屏时间、首次导入/切页付出多少成本、预加载最长停顿、剩余瓶颈；需要纳入版本库的最终摘要放 `docs/analyzer/verify/`，不提交运行缓存。
- 最终结论明确是“源码改善”“EXE 热启动改善”还是“冷/热启动及交互目标全部达成”。

相关项目约束：

- [冻结导入依赖单一合同](../../lessons-learned/codex-frozen-import-dependency-contract.md)
- [pandas 类型判断与冻结收集](../../lessons-learned/codex-pandas-lazy-import-avoids-collect-all.md)
- [延迟 Section 回调共享 render gate](../../lessons-learned/deferred-section-entry-shares-render-gate.md)
- [Windows 原生导入隔离](../../lessons-learned/codex-windows-native-import-guard.md)
- [正在推进的扩展安装器计划](2026-09-21-grok-implementation-followup-plan.md)

外部依据（本轮已核对）：[Qt GUI 线程约束](https://doc.qt.io/qt-6/threads-qobject.html)、[QTimer 短任务与事件循环约束](https://doc.qt.io/qt-6/qtimer.html)、[PyInstaller onedir/onefile 运行机制](https://pyinstaller.org/en/stable/operating-mode.html)、[Microsoft Defender 性能分析](https://learn.microsoft.com/en-us/defender-endpoint/tune-performance-defender-antivirus)。Qt 链接用于说明通用线程/事件循环限制，不代表项目升级至 Qt 6。
