# Windows 启动面板首显提速：原生动效与随机提示统一计划

日期：2026-09-25。状态：**待执行；本轮仅编写计划，不修改启动产品代码、不重新打包。**

基线：编写时 HEAD `c653b848`，工作树包含前轮图表切换、Batch 导出、View 蓝线及用户原有 Inspector 修改。实施前重新记录 HEAD/dirty；这些修改不属于本计划的清理对象。版本唯一来源仍为 `mf4_analyzer/app_meta.py`，本计划不要求升版。

本计划针对 Windows 普通 GUI 启动。用户要求“面板尽快出现，同时保持动效和随机操作提示”。采用单人顺序实施，不要求委派子 agent。下文时间指标均为**拟定验收目标，不是性能承诺或已测结果**。

## 1. 产品决策：首屏就动，同一个面板显示到结束

采用 **Windows 原生轻量启动器 + 从首屏持续运行的原生面板**。

- 首次可见时就完整显示品牌、版本、频谱、状态、随机提示和软件信息。首帧后立即有活动指示转动、进度条移动，频谱按原有节奏呼吸；不等待 Python/Qt 就绪，不先展示几秒静态截图。
- 同一个 HWND、同一套动画时钟、同一条提示序列贯穿启动全过程，直到主窗口准备显示。
- **取消“静态原生首帧 → 第二个 Qt 动态面板 → 主窗口”的推荐路线。** 它引入两次视觉交接、提示重抽和动画相位重置风险。原生路径不再启动现有 Qt splash child。
- “首帧有动效”指首帧已有动画元素，后续帧立即推进；第一张图本身不可能表达运动。首次呈现不加淡入等待，不为了看动画或看完提示强制停留。
- 系统减少动态效果时，遵从当前策略：静态活动指示、停止频谱呼吸/轨道移动，提示仍每 5 秒轮换。

这是一项 Windows 启动入口和原生渲染工程，**不是几行移动调用的小改动**。代价是引入一个小型原生构建目标和双渲染器对齐检查；收益是面板可见性不再等待 Python 和 Qt。源码开发、macOS 开发强制预览及备用启动路径继续使用既有 Qt 面板。

## 2. 现状与证据边界

| 已核实的位置 | 当前行为 | 对方案的影响 |
| --- | --- | --- |
| `MF4 Data Analyzer V1.py` 顶层与 hidden 分派 | 导入 extensions.probe 等后解析入口 | 移动 start 只能省去部分前置工作，覆盖不了 Python 入口前的等待 |
| `app.py:main` | setup_logging → feedback.start → 扩展 bootstrap → Qt/主窗 | 反馈已经早于重型 UI；不能再把全部延迟归为 MainWindow 加载 |
| `startup_feedback.py:build_child_command` | frozen 使用同一个 sys.executable 加 --startup-splash-child | 当前面板需要第二次 EXE/Python 启动及 Qt 初始化 |
| `ui/startup_splash.py` | 640×470 逻辑尺寸；33 ms tick；呼吸周期 5 s、轨道 2.3 s、旋转 1 s | 原生实现保持这些效果和节奏，不随意重新设计 |
| 同文件 TIPS / __init__ / _on_tick | 当前 26 条；构造时随机选起点，之后每 5 s 顺序轮换；12 s 后慢启动文案 | 随机序列和时间轴需要一个 owner |
| `startup_handover.py` | finish → hidden/can_reveal → 唯一 owner 显示主窗口 | 继续保持“先隐藏面板，再显示主窗”，不用主窗 paint 反过来触发隐藏 |
| 三个 Windows builder | `--onedir`，Full/Lite/Modular | 当前不是 onefile 解压等待；三个包型都要接入同一启动器 |
| Windows splash surface policy | 自绘圆角底板；不使用 DWM Acrylic；无外投影层 | 对齐当前实际 Windows 外观，不恢复旧设计中的厚重阴影或矩形 DWM 背板 |

前轮 Windows 11 Parallels 从共享目录启动现成 8.4 包，两次外部 spawn 到 splash 首绘通知约 **2.234 s / 1.778 s**。它们不是冷/热基准：使用系统账户，非交互桌面，完整交互验收未完成。第一次还遇到计时工具的 `event` 参数冲突；临时绕过后第二次仍因未完成主窗交互探针而超时。不能据此承诺优化后的数值，或将主程序判为启动崩溃。

本地原始证据位于 `.state/view-marker-startup/`；不把这些运行产物提交 Git。既有历史计划只提供背景，不改写其“无原生构建链”的旧范围；**本计划明确将原生启动器作为新范围**。

## 3. 首屏视觉与动效实现

### 3.1 唯一视觉数据源

新增 stdlib-only 的 `mf4_analyzer/startup_visual_contract.py`，承载：

- 稳定 tip ID、标题/正文、顺序、阶段文案、慢启动文案；
- 面板几何、配色、字体角色、频谱几何参数、动画周期、5 s/12 s 阈值；
- 供构建生成使用的纯数据函数，不导入 UI、Qt、numpy 或业务计算。

将当前 splash 专属事实迁到该 owner，Qt 面板消费它；`qt_panel_style.py` 继续拥有通用材质/字体策略，生成器读取其公开轻量接口，不复制第二套通用 palette。版本和品牌来自 `app_meta.py`，不可另外写死 `8.4`。保留现有 `startup_splash.TIPS` 等受测公共导出作为兼容别名。

构建脚本生成 UTF-16 原生资源、频谱点集及含 schema/content hash 的只读 manifest，并编译进启动器。应用运行时不启动 Python 来生成它们，也不扫描安装目录/字体目录/全部资源。

### 3.2 原生渲染边界

原生目标建议放在 `native/startup_launcher/`，使用 C++、Win32、GDI+ 和系统提供的 DLL；不引入 Qt、.NET、WebView、浏览器、Tcl/Tk。MSVC/Windows SDK 是新增的**构建依赖**，不要求终端用户安装开发环境。

- 使用带 alpha 的离屏缓冲和分层窗口，圆角外部透明；窗口不激活、不新增面板任务栏项。首屏前完成 DPI awareness 设置。
- 按现有 Windows 自绘样式画渐变、内部高光、边缘和 Logo；不增加外阴影/DWM 背板。字体沿用现有 Windows 中文优先级及统一字重，不拼接不同字体来补个别字。
- 16 层 × 461 点频谱几何由同一构建输入生成，缓存路径；每帧只改变现有透明度呼吸。旋转弧和不确定进度轨道原生绘制，不预存数百张整窗动画图片。
- 缓存静态底板、品牌和当前文字布局；tip/stage/DPI 改变时才更新对应缓存。初次字体选择只检查规定候选，不枚举所有系统字体。
- UI 消息循环只做绘制/状态应用。CreateProcess、管道读写、等待退出和日志写入不阻塞动画线程。
- 先完成原生首帧，再立即让工作线程启动 Runtime；不为了“播放开场动画”额外等待。首次绘制失败时立即直接启动 Runtime，不阻止使用软件。
- 不要求 Qt/GDI+ 的抗锯齿像素逐点一致；要求信息、字重层级、换行、位置、圆角及动效视觉一致。字体裁切/错字、峰顶缺口、矩形背板不可当作渲染差异豁免。

Windows 屏幕选择和产品缩放复用现有规则：跟随启动时光标所在显示器；大工作区产品倍率 1.5，否则 1.0，空间不足再缩小；OS DPI 只应用一次。发生 DPI/工作区变化只重建布局，不重置 tip/动画时钟。

## 4. 随机提示：只选一次，内容与时间不跳变

### 4.1 用户可见规则

1. 每个正常启动 session 用系统随机源只选一次 `initial_tip_id`。保留当前“随机起点 + 顺序轮换”，不改成每帧或每 5 秒重新抽签。
2. 从**首次成功呈现**记 `visible_elapsed = 0`；第一条完整显示 5 秒后切下一条。进程创建、IPC 连接、加载阶段变化均不能重置计时或重新抽签。
3. 以 `floor(visible_elapsed / 5000)` 推算轮次，取列表循环索引，不累计 timer tick。UI 暂停后直接到当前轮次，不快速连播补帧。
4. 同一窗口更新标题、正文和底部指示点；阶段消息只修改状态行。tip 变化不改变窗口尺寸。
5. 主窗提前就绪立即关闭面板，不等满 5 秒。启动慢于 12 秒只改变状态，不打断提示序列。
6. 不新增跨次启动历史和“保证上次不重复”的产品语义。两次独立启动偶然同一条是允许的；若将来要求不重复，单独设计持久化。

### 4.2 唯一 owner 与兼容

- 原生路径由 NativeSplashSession 独占 tip 起点、列表 hash、首次呈现时刻和动画相位。Python 只可发送阶段/结束消息，不发送 random seed 来让另一端重算。
- Qt 备用路径保留独立 session 的随机起点；`StartupSplash` 增加可选初始 tip ID/时钟注入，用于确定性测试，默认行为保持一致。现有 TIPS 二元组兼容导出不承担稳定身份。
- 正常原生路径只有一个面板，**不需要同步两个窗口的随机数或轮换时刻**。自动降级原则是“首屏前选择另一后端”，一旦原生已显示，IPC 异常也不再弹第二个 Qt 面板；允许失去阶段更新，但旋转、提示继续，最终由故障清理释放。
- 原生资源生成器校验唯一 ID、非空正文、顺序及 hash。Python 和原生必须来自同一构建输入；构建时发现不一致直接失败。禁止手抄提示到 C++、把随机选出的文字烘焙为固定启动截图，或通过 import quickref/hints 拉入整个 UI。
- 当前 tip 文案不重写；若实施需要改变用户可见说明，同步 `ui/hints.py`、`ui/quickref.py`。相关版本/help 合同继续执行。

## 5. 进程结构与交接

### 5.1 包布局与入口

外部常用 EXE 名仍为 `$AppName.exe`，成为原生启动器；PyInstaller 产物在**同一安装目录**命名为 `$AppName-runtime.exe`，继续使用现有 `_internal/` 布局。不要把 Runtime 移到更深层导致 resolve_install_root、Modular extensions、资源或相邻文件定位改变。

- public launcher：负责早期面板、启动 Runtime、准确转交参数及退出码。
- Python Runtime：负责所有现有业务和 MainWindow。
- 原生面板隐藏后停止绘制计时器并释放图形资源；launcher 可保持无窗的轻量等待，直到 Runtime 结束，返回其退出码。该进程是有意保留的启动/退出代理，不算“面板泄漏”；Runtime 退出后两者必须都结束。
- 多次双击保持当前多实例语义，每次独立 session，不擅自增加单实例锁。关闭面板仅隐藏反馈，不取消 Runtime。

普通 public 启动使用原生路径；直接运行 Runtime/source 默认沿用旧 Qt 路径作为恢复入口。`TRACELAB_STARTUP_SPLASH=0` 完全无面板。新增后端诊断开关（例如 `TRACELAB_STARTUP_BACKEND=auto|qt|none`）只用于明确对照/恢复，原有 splash=0 优先级最高；无已验证 native session 的 `native` 模式不能伪造连接。

原生入口不能偷改 hidden/smoke 参数语义。已有 hidden 模式、`--help`、layout probe、offscreen 必须无面板直通；Unicode、空格、引号、末尾反斜线、工作目录、环境、stderr/stdout 和退出码都要验证。原生只做受限分派，不取代现有 Python 参数互斥/缩写/错误校验。非法/未知选项保守走无面板 Runtime 解析，不先闪出反馈再报错。

### 5.2 native → Runtime 的会话通道

建议两个匿名管道组成双向通道，启动器持有 Runtime 进程句柄；仅在该次 CreateProcess 的环境块中传递协议版本、session、受控继承句柄等 bootstrap facts。不用命名临时文件轮询，不向网络暴露服务。

- 消息沿用有界 JSONL 的思想，最大 4096 bytes；明确版本、session、序号、允许事件、终态幂等。原生 JSON parser 固定版本并随构建管理；不手写不完整的字符串匹配解析。
- Runtime 初始化时将继承句柄转为自身 I/O owner 管理，清除 bootstrap 环境并关闭不需要的句柄；后续 acquisition/extension/splash child 不得继承该 session。
- 审计现有扩展 probe 的继承句柄和 stdio。普通 GUI 的限制继承列表不能套用到 hidden passthrough 而丢掉其 staging/auth 管道。相关真实 child gate 必须保留。
- Runtime 的适配器 `NativeStartupFeedback` 对接现有 StartupHandover 所需的 start/publish/finish/close、listener、snapshot、session、launch_screen 语义；不伪造“child pid”字段来代表反向父进程。协议数据可共享，进程所有权保持不同，不把 native 构建逻辑塞入 MainWindow。
- IPC 在工作线程进行，状态应用投递到原生 GUI 消息循环。Python 侧 reveal 继续走现有 GUI QObject queued bridge，不在 reader 线程创建/显示 QWidget。

### 5.3 完整生命周期

| 事件 | 处理 |
| --- | --- |
| native 首屏呈现 | 冻结 initial tip 和屏幕，记首显事件，持续动画；启动 Runtime |
| Runtime 尚未到 Python | 面板显示“正在启动 TraceLab…”，本地动画和 tips 持续推进 |
| Runtime 发送阶段 | 只更新阶段状态；不重置任何视觉时钟 |
| 主窗口构造完成 | Runtime 请求 finish；native 在 GUI 线程停止绘制并隐藏，确认不可见后回复 hidden |
| Runtime 收到 hidden | StartupHandover 在主 GUI 线程只 show 一次；屏幕延续启动选择 |
| hidden 丢失/native 无响应 | 使用现有 0.25 s/1.5 s 故障窗口的等价有界策略；只针对已验证的本次 launcher 进程句柄清理，不能按进程名杀进程；失败可显示主窗，但必须记录 handover_failed，不能算通过 |
| 用户提前隐藏面板 | 不关闭 Runtime，不再次弹面板；后续 finish 得到已隐藏确认 |
| Runtime 启动失败/异常退出 | native 停止 loading，记录错误；普通 GUI 提供简短可关闭错误反馈，hidden 模式只传退出码；销毁面板/管道/进程句柄 |
| native 被杀/管道 EOF | Runtime 继续启动，不补弹 Qt 面板；无阻塞降级显示主窗并保留诊断 |
| 迟到/重复消息 | terminal 状态不复活、不二次显示、不重启计时器 |

不使用“等待主窗口 paint 之后再关面板”作为正常交接，不强制把主窗置顶，不通过长时间睡眠掩盖竞争。进程组/Job 的设计不得让终止 launcher 连带杀死已运行的 Runtime。

## 6. 测量与验收标准

先修复测量工具，再收基线。已有 `note("splash_feedback_received", **feedback)` 与 feedback.event 冲突必须有红绿回归；增加 native 事件时同步更新允许事件集合，不能把新事件一律记 ok=false。

外部测量器使用**同一个工具时钟**盖 launch request、native first-present、动画第二帧、runtime spawn、Python entry 通知、main first-frame/interactive 等接收时刻。内部 QPC/QElapsedTimer 只用于各自持续时间，不相减不同进程相对时钟。首显通知不是屏幕实拍，需连续帧交叉证明。

native 的首显/第二帧通知由其诊断工作线程直接发给外部测量器的现有本地 probe 接收端，不经过尚未就绪的 Python Runtime 转发；统计通知投递延迟，不能把排队到 Python 启动后的时间当首显。诊断开关关闭时不连接 probe、不落性能文件；通知丢失不影响产品启动，但对应指标为 UNKNOWN。

| 项目 | 初始目标/要求 |
| --- | --- |
| public EXE 启动至面板首次可见 | 本地 NTFS、真实登录桌面：热启动 median ≤300 ms、P95 ≤500 ms；冷首启 median ≤1.0 s |
| 面板开始运动 | first-present 后 ≤100 ms 出现可辨识的动画变化；减少动态效果模式除外 |
| 主程序受控停顿 | Python 启动/主线程阻塞 5 s 时，原生动画不冻住，tip 第 5 s 正常更换；不允许 >250 ms 连续无更新 |
| 原有视觉 | 26 条提示、三种阶段与慢状态逐一渲染；无裁切；圆角外透明；峰顶完整；字体角色/布局与当前 Windows 面板对齐 |
| 交接 | 主窗显示前面板已隐藏；只有一次 show；无第二个 splash、重影、抢焦点、晚到复活 |
| 主窗可交互成本 | 与相同 Runtime、原有 Qt splash 后端配对比较，热启动 median 回退不超过 max(100 ms, 基线 5%)；报告完整分布，不只报面板收益 |
| 资源 | 无整窗逐帧图集；记录新增包大小、launcher working set/CPU；隐藏后停 timer、释放绘制缓存，Runtime 退出后无残留 |
| 失败/禁用/hidden | fallback 可观察；无不应出现的窗口；保持真实退出码/参数/继承句柄 |

热启动每个最终包/后端至少 10 次，冷启动至少 3 次重启后首启，报告所有样本、median/P95/max 和硬件/架构/DPI/包 hash。共享盘、系统账户、VM 单列；不能冒充普通用户本地运行。Full/Lite/Modular 均执行包级场景；Windows x64 与 ARM64 仅对实际发布支持的架构分别编译/验收，不把模拟运行计为原生通过。

目标不达成时按首屏前字体/图形初始化、原生启动器自身、OS/磁盘等分段调查，不通过取消 tip、静态停顿或擅改指标宣称完成。

## 7. 顺序实施任务与 gate

### T0 — 修计时工具，锁定可靠基线

Owner：`tools/measure_windows_startup.py`、`startup_timing.py` 的诊断合同及对应测试。

- 为 event-key 冲突、允许事件及只收到 splash 而主窗未就绪补失败用例；工具异常不得被报为应用崩溃。
- 在实际登录 Windows、目标包位于本地 NTFS 下测旧 Qt 路径；记录包哈希、冷/热分类和首次运动连续帧。
- 固定视觉参考：当前实际 Windows 面板，不以早期 HTML 或 macOS backdrop 为准。

Focused：`tests/test_startup_timing.py` 及测量工具对应 owner 测试（先通过 rg 定位，缺失则新增）；不跑全库 baseline。

退出：工具能完整测到 main interactive；拿不到有效基线则性能比较保持 UNKNOWN，仍可推进独立的渲染/协议测试。

### T1 — 提示与视觉合同单源化

Owner：新增 `startup_visual_contract.py`、生成器、`ui/startup_splash.py` 的消费接口及 owner 测试。

- 迁移当前事实，冻结 26 条 ID/文字/顺序、版本、几何和动效参数；不改视觉。
- 生成原生只读资源/header，版本来自 APP_VERSION；支持确定性 seed/clock 测试，正式随机只在 session 初始化一次。
- 测 0/4999/5000/9999/10000/12000 ms 边界、长启动、tip 列表空/非法 ID 的构建拒绝、阶段/DPI/重绘不重抽、不重置。

Focused：`tests/ui/test_startup_splash.py`、新增合同/资源生成测试、`tests/test_startup_splash_child.py`。
Boundary：既有 splash import-closure 和 `tests/ui/test_import_boundaries.py`；禁止引入 ui_kit/主窗重依赖。资源与 Python hash 对齐是构建 gate。

### T2 — 原生同窗动态面板与受控 Runtime

Owner：`native/startup_launcher/`、独立构建脚本（拟 `tools/build_startup_launcher.ps1`）、native 单元/渲染 harness。

- 实现 native window、绘制缓存、动画时钟、tip owner、DPI/字体、减少动态效果、关闭语义。
- 先接受控假 Runtime：延迟 5/15 s、阶段乱序、立即完成、启动失败/进程退出；验证面板不依赖 Python。
- 给 C++ 状态机与 tip 时间函数写单元测试，Win32 集成测首次呈现、帧推进和隐藏；不要用 Python 假对象替代真实原生消息循环。

Focused：native owner tests；冻结时间/固定 tip 的截图几何和像素区域比对；Windows 真桌面动态录像。
退出：首显/动效和当前外观达到目标，尤其四角、字体、5 s 提示切换。若失败先修该 owner，不接入发布包掩盖视觉缺陷。

### T3 — 协议适配与主窗口交接

Owner：新增 `mf4_analyzer/startup_native_feedback.py`、反馈工厂、`app.py` 最小选路、`startup_handover.py` 必要兼容、新协议测试。

- 明确 start/finish/listener/snapshot 在 disabled、EOF、already-hidden 情况下的行为；原生路径不得启动 Qt child。
- 最早接管继承通道，清理子进程环境；阶段更新/结束请求均不阻塞 GUI。
- 用真实 native launcher + Python Runtime 验证完整交接；强杀/断管只作用于测试自己持有的进程。

Focused：`tests/test_startup_feedback.py`、`tests/test_startup_splash_child.py`、`tests/test_startup_splash_integration.py`、新增 native feedback 合同测试、handover owner 测试。
Boundary：`tests/test_startup_import_boundary.py`、`tests/test_startup_entrypoints.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`。不扩展 MainWindow 跨模块 mutable state。

### T4 — 三种 Windows 包接入与兼容

Owner：三个 `tools/build_windows_folder*.ps1`、入口/包策略/验证脚本、原生资源生成。

- 自动定位受支持的 MSVC/Windows SDK；缺失明确报构建失败，不悄悄产出外观相同但无早期反馈的包。原生/Runtime 架构一致，发布包不依赖开发机私有 DLL。
- 在独立输出目录构建 Runtime，再安装同名 public launcher；不覆盖用户正在运行的包。资源/version/file identity 同步。
- 审计所有 sys.executable、程序重启、hidden child、安装根、Modular extensions 定位和 exe basename 假设；同层 Runtime 保留当前根路径语义。
- package policy 把两个 EXE、生成资源及必要 runtime DLL 纳入白名单/哈希，不静默绕过已有 prune/import/真实 smoke。
- 测 public 和 runtime 两个入口的 hidden probes、Unicode argv、错误码、继承认证句柄、无控制台 stdout/stderr，以及无扩展的 Modular 普通启动。

Focused：`tests/test_windows_build_script.py`、`tests/test_windows_lite_modular_build_script.py`、`tests/test_packaging_imports.py`、`tests/test_windows_runtime_dependencies.py`、修改到的 bundle policy owner；`tests/test_extension_probe.py`/`tests/test_frozen_batch_acceptance.py` 中入口/句柄场景。
退出：三个 fresh frozen 包的真实测试通过。源码静态检查不替代 frozen 运行。

### T5 — 最终性能、视觉与发布门槛

按 §6 执行冷/热对照；100/125/150/200% DPI，主/副屏、小工作区、浅/深背景，正常/慢/减少动效/失败/多实例/用户隐藏均覆盖。26 条提示自动遍历，不要求用户逐条肉眼查看。

先验收 owner 与集成 gate。只有进入正式发布/合并里程碑时才做一次稳定快照的全库 gate；此前不反复全库测试。若全库有必要，先查已有 pytest 进程，main suite 与 acquisition_ui 分两个顺序进程，记录前后 HEAD/dirty。

更新面向用户的启动说明（`ui/hints.py` 与 `ui/quickref.py`），记录哪些指标已达成、哪些 UNKNOWN。未收到 commit/push/release 授权不发布。发布切换前保留同一个 Runtime 的 Qt 后端作为可验证回退，不要求回退业务代码。

开发阶段默认后端保持既有 Qt 路线；原生路径在独立试验包中 opt-in。只有 T2–T5 的原生视觉、兼容性和性能 gate 均通过，才把正式包的 auto 路线切为原生；不能仅因代码编译通过就替换用户常用 EXE。

## 8. 本轮文档验收与执行风险

本轮只新增 plan：检查链接、现有 owner/test 路径、用户要求覆盖、当前源码与历史约束差异，以及 `git diff --check`；不为文档修改运行软件测试。

执行阶段最主要风险是字体/alpha 合成与原有外观不一致、public/runtime 双入口对 hidden probes 的影响、原生 native toolchain 新依赖，以及未在真实登录桌面测量却声称秒开。对应风险均有 T0–T5 的具体 gate。当前任务只把方案写成可实施和可验收的计划，**不宣称已经实现原生面板或达到 300 ms**。

参考：

- [既有 Qt splash 实施背景](2026-09-23-startup-splash-b-implementation-plan.md)
- [现有面板材质与交接计划](2026-09-23-sky-glass-panels-and-startup-handover-plan.md)
- [GUI 接收者与隐藏确认教训](../../lessons-learned/splash-thread-dispatch-needs-real-gui-receiver.md)
- [Windows DWM 圆角背板教训](../../lessons-learned/windows-dwm-backdrop-can-fill-rounded-splash-corners.md)
- [Microsoft UpdateLayeredWindow](https://learn.microsoft.com/zh-cn/windows/win32/api/winuser/nf-winuser-updatelayeredwindow)：原生逐像素 alpha 合成的基础。
- [Microsoft WS_EX_NOACTIVATE 行为](https://devblogs.microsoft.com/oldnewthing/20240919-00/?p=110283)：不激活窗口仍需验证 hover/焦点边界。
- [PyInstaller splash 限制](https://pyinstaller.org/en/stable/usage.html#splash-screen-experimental)：目录包焦点问题、半透明限制，故本计划不直接采用其内建 splash。
