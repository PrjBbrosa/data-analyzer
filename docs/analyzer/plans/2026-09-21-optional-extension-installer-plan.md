# TraceLab 可选扩展包与稳定安装器执行计划

- 日期：2026-09-21。
- 状态：**待实施；本轮只写文档。**
- 规格：[可选扩展与稳定安装器 spec](../specs/2026-09-21-optional-extension-installer-spec.md)，下文以 S1–S13 指代其章节。
- 观察基线：HEAD `5d7868f1961f580263e7ae4ef85a994bfeab6edb` 和当前未提交工作树。渲染、项目生命周期工作正在同一 checkout 发生，实施前必须取得稳定源码快照，不覆盖其他任务的改动。
- 推荐交付顺序：协议／冻结可行性 → 可信文件事务 → media 纵向链路 → MATLAB 与联合装载 → 旧版本更新体验 → 完整发布验收。
- 所有步骤默认顺序执行；本计划不要求多代理。全套门禁与冻结验收只有一个集成负责人。

## 1. 最终可见效果

1. 用户把 `installer.exe` 放在支持 modular 的 TraceLab 文件夹内，运行后看到目标路径、主程序版本及音视频／MATLAB 状态。
2. 选择所需组件，确认下载大小和关闭程序要求；安装成功后重启 TraceLab 即可使用。无需 Python、pip 或管理员权限。
3. 安装器关闭／删除后，已安装且兼容的组件仍可用。
4. 主程序 A→B 仅改 UI／算法且 runtime、组件 API 未变时，组件继续复用、installer 不要求升级。
5. 运行时不兼容时提示更新**扩展包**；只有协议或 installer 自身原因才提示更新**安装器**，两者不能混淆。
6. 网络断开、安装被取消、管理器崩溃、坏包或试加载失败不会破坏既有可用安装；不支持的共享目录提前说明。

## 2. 变更 owner 与文件规划

下表中的“新增”是计划文件，不表示已存在。实施可根据具体函数规模缩减文件数，不能扩散职责。

| owner | 现有／拟新增路径 | 职责与约束 |
| --- | --- | --- |
| 依赖合同 | 现有 `mf4_analyzer/io/runtime_dependencies.py`、`tools/windows_runtime_dependencies.py` | 扩展 component ownership、bundled/modular profile；保留 Full/Lite 语义及历史默认 |
| 中立扩展层 | 新增 `mf4_analyzer/extensions/contract.py`、`state.py`、`runtime.py`、`locking.py` | schema、兼容性、状态、启动路径和租约；不得 import Qt、UI或可选大库 |
| 原生探针 | 新增 `mf4_analyzer/extensions/probe.py`；现有 `MF4 Data Analyzer V1.py` | 固定 child 协议与验证；互斥模式，windowed 无 console 也可运行 |
| 适配器状态 | 现有 `io/source_adapters.py`、`io/loader.py`、`io/mat_format.py` | 统一 GUI/Batch 可用性和缺失提示；不改读取算法和返回结构 |
| 安装引擎 | 新增 `tools/extension_manager/engine.py`、`repository.py`、`transaction.py` | 使用中立合同、TUF、文件事务；无产品 GUI／DSP 依赖 |
| 管理器界面 | 新增 `tools/extension_manager/app.py`、入口 `tools/extension_installer.py` | Tk 状态展示、后台 I/O、取消、版本提示；不把业务规则藏在控件中 |
| 主程序入口 | 现有 `ui/command_registry.py`、`ui/main_window/command_coordinator.py` 及实际导入错误展示 owner | “扩展管理…”命令、组件状态／打开 manager；继续使用现有 command owner |
| 构建／发布 | 现有 `tools/build_windows_folder_lite.ps1`；新增 `tools/build_windows_extension_installer.ps1`、`tools/build_windows_extensions.py` | 复用 manager 发布物，生成干净 base 和签名组件、清单及锁文件；不靠删目录模拟拆包 |
| 验收 | 扩展 `tools/verify_lite_importer_runtime.py`，新增 `tools/verify_extension_installation.py` | 组合、更新、回退及原生来源验证；复用真实 importer，不复制解析算法 |
| 用户文档 | `ui/hints.py`、`ui/quickref.py`、现有用户指南 | 说明扩展安装、缺失提示、更新地点、离线和本地目录限制 |

installer 独立构建环境的锁定依赖与目标 TraceLab 运行时配方分开管理。运行时配方、schema 和发布元数据放 `tools/extension_manager/` 下的有版本清单；不得在多个 PowerShell 文件手写相同依赖列表。产品版本仍只读 APP_VERSION。

## 3. Task 0：最小可行性与冻结边界证明（S1/S2/S6/S9）

### 目的

先证明现有 PyInstaller 结构能安全外置依赖，避免先完成 installer 界面才发现组件仍在 PYZ、存在 DLL冲突或旧核心不能读取扩展。

### 工作

1. 记录 HEAD、受影响文件指纹、dirty scope、现有 Windows Python／PyInstaller／Qt／NumPy 版本、EXE 和关键原生库哈希；相关代码变化期间不开始权威构建。
2. 读取仅相关 lessons：frozen-import-dependency-contract、frozen-probes-do-not-require-console-streams、Lite prune、native stderr 与原生 argv；既有保护不得删除。
3. 在 `.state/` 下建立独立构建／输出目录；保持用户当前 dist 不动，不默认清理所有构建缓存。
4. 创建最小“基础 EXE + 外部 av 组件”实验：base 不包含 av 模块／DLL；加载前通过受控路径注册；实际读取 WAV 与 MP4，记录 `av.__file__` 和加载 DLL 来源。
5. 对 SciPy/h5py 做同样实验；审计 asammdf、hook 等间接导入，证明排除后的基础 MF4/WWT/HEAD HDF/BLF/TDMS/Excel 路径正常。模块放回 base 才通过不算成功。
6. 检查 media+matlab 的共享 DLL／模块冲突，划定精确依赖闭包；NumPy/Pandas/Qt 仍来自 base。没有证据不要复制整个 site-packages。
7. 用本地 NTFS 验证 LockFileEx 的共享／独占租约、多实例、进程异常退出和授权探针 child；验证 UNC、映射网络盘能被识别并拒绝变更。
8. 制作可独立启动的最小 Tk/TUF manager EXE，移走目标 `_internal` 后仍能显示中文错误／恢复入口。测量体积、启动和基本 DPI 可读性。

### 门禁

新增确定性实验说明 `.state/extension-feasibility/`；原生 av、MAT 两类冻结 child 均通过且路径指向候选组件；基础格式没有回归，租约竞争符合合同。新模块的纯 import 测试不得引入 GUI或可选库。

若字体 UI／外部原生包／锁机制不可行，先修订具体技术选择和证据，不能以“先做 UI”跳过。这里不运行全套 pytest，也不发布生产仓库。

## 4. Task 1：版本、schema 与兼容规则（S3/S4/S5）

### 工作

- 新增 contract 与 state 的纯逻辑；为外层 `discovery_schema=1`、协议 required features、版本比较、路径字段和尺寸上限定义类型及明确错误。
- 从构建运行时配方生成 runtime_id；精确列出哪些共享依赖影响指纹。对 app_version、源代码 hash、构建时间做排除测试，防止频繁 app 发布无意改变 runtime_id。
- 生成 core.json/core-files.json，包含真实可执行名称和核心身份；对应实际 exe，不依赖固定 `TraceLab.exe` 名。
- 定义 package manifest、active 映射、事务日志 schema；S4 的字段落成实际测试 fixture，正常／缺字段／未知重大版本均有样本。
- 将 S11.1 的 reason_code 和退出码纳入合同；UI 不通过字符串匹配判断“需要更新安装器”。包清单作为独立受信 target 的绑定和 receipt 验证也需有负例。
- 明确 installer 的版本独立来源，新增稳定 manager-status-v1 fixture；最新版本和最低要求分开。

### 测试与门禁

新增 `tests/test_extension_contract.py`、`tests/test_extension_compatibility.py`：覆盖同 runtime UI 升级复用、Python/NumPy/架构变化拒绝、组件 API 变化、旧 manager 读新版发现信封、未知 required feature、SemVer比较（不能字符串字典序）、混合核心清单拒绝。

沿用 `tests/test_windows_runtime_dependencies.py`：检查交付 profile 从原统一清单推导，所有 lazy dependencies 都有“base 或组件”的归属；不能通过删掉声明来绕过 gate。文案／JSON排版不单独增加镜像测试。

## 5. Task 2：受信元数据与下载（S5.2/S8）

### 工作

1. 引入固定版本 python-tuf及其依赖到独立 manager 环境；在 `.state/`／测试 temp 创建临时测试仓库和测试密钥，生产密钥不生成、不提交。
2. 实现先读取受信 manager-status-v1，再读兼容 catalog；包候选必须同时满足核心 capability、runtime、组件 API 和最低 manager。
3. 实现 HTTPS 下载、有限超时／重试、取消、长度上限、part 缓存及完整性验证；网络 I/O 不阻塞 UI线程。
4. 本地离线发行集合走同一信任链；已安装组件运行不依赖网络／metadata新鲜度。
5. 下载 installer 新版到隔离更新目录，提供关闭后替换说明，不实现自覆盖 updater。

### 测试与门禁

新增 `tests/test_extension_repository.py`：测试受信正常目标、签名／长度／hash 错误、过期、回滚、撤销、根轮换、时间异常、错误目标架构、无匹配包、旧 catalog／新 catalog、先发现最低 manager再拒绝新版 schema、重定向策略、断网／取消／part 重用。

测试仓库在本地控制，不访问生产服务；联网失败状态不能写成 not_installed 或触发卸载。独立执行的 manager 能识别旧 core 并给出稳定下载帮助入口。

## 6. Task 3：安装状态机、锁和恢复（S7/S8）

### 工作

- 独占事务 engine 与 UI 分离。明确阶段 `prepared → verified → probed → committed → cleanup`，每阶段结果和旧／新 active 可恢复。
- 所有写路径限定在已识别的 extensions；解包验证、空间预算、权限检查和 same-volume staging 先于提交。
- Windows 共享运行租约与独占修改锁联动；下载期间可不持独占锁，真正写前重新核对 core_build_id 和 active generation。
- 一次多组件选择作为一个事务提交；用目标 exe probe 候选整体，不能用 manager Python测试 `.pyd`。
- active.json 是唯一提交点；不可变 store +日志先落盘；卸载先变更引用后清理，无引用删除失败记 cleanup_pending。
- 处理目录移动、复制、大小写／路径别名；状态不依赖旧绝对盘符。不要存任何用户数据位置到组件激活协议。

### 测试与门禁

新增 `tests/test_extension_transaction.py`、Windows 专用 `tests/test_extension_windows_locking.py`。逐阶段故障注入，包括下载、解包、probe、store rename、active替换前后、日志结束前、旧文件删除。每次重启只能得到完整旧状态／完整新状态／明确 repair_required，不能得到半套选择。

覆盖 ZipSlip、ADS、reparse、同名大小写文件、设备路径、ZIP展开上限、磁盘不足、两个 manager、多主进程及其 child、杀毒软件锁文件、网络盘拒绝。对超时 probe 终止并回收其进程树，确认退出后才清理候选。

用真实 Windows NTFS 完成至少一次强制终止恢复和租约竞争；macOS模拟或 mock Windows API不能替代。所有操作只针对测试目录，不终止用户正在使用的 TraceLab。

## 7. Task 4：主程序启动桥接与可用性（S6）

### 工作

1. 在主入口、相关 hidden children 和直接 app 入口核对初始化时机；core 身份与租约必须在组件使用前建立。Windows DLL搜索句柄保持到退出。
2. bundled/source/modular 三种模式显式区分。source 默认用项目 venv，bundled 默认用内置依赖，不误读旁边的 extensions。
3. 在 SourceAdapter availability 对 modular 消费组件状态，不把 find_spec 当原生可用性证明；保留 ready/limited/unavailable 的公开兼容含义，可通过结构化 reason 增加组件细节。
4. av/MAT 缺失和损坏由原导入反馈展示；Batch复用同样状态，不重复新建异常吞掉真实错误。
5. core_build_id变化时在 child 重新验证现有兼容包，无需重下；不兼容 runtime 的包不进 sys.path，基础格式继续工作。
6. 无 manager、旧 manager或网络不可用都不能阻止已装兼容组件运行。

### 测试与门禁

新增 `tests/test_extension_runtime.py`、`tests/test_extension_probe.py`；运行 `tests/test_source_adapters.py`、`tests/test_importer_runtime_smoke.py`。覆盖 stdout/stderr=None、互斥／缩写 hidden flags、错误 evidence 目标、DLL故障、首次健康probe失败、多来源身份保持、缺失组件不影响基础格式。

边界运行 `tests/test_native_import_boundaries.py`、`tests/test_batch_render_import_boundary.py`、`tests/test_signal_no_gui_import.py`；新增 subprocess 检查 extensions 合同／状态层导入不带 Qt或可选包。若触碰 Batch reporter／编排才运行 `tests/test_batch_run_reporter.py`，不因提到 Batch而直接扩大修改。

## 8. Task 5：构建拆分、清单和包所有权（S1/S2/S9/S10）

### 工作

- 将 `flavor=full/lite` 和 `dependency_profile=bundled/modular` 分开，默认仍为 bundled；首次仅接受 lite+modular 发布组合，未支持组合明确报错。
- 依赖统一清单导出 base与组件的收集／排除集；分离构建环境并固定 lock，避免开发环境 extras将 av/scipy/h5py 又带回核心。
- 组件以可独立导入的 Python模块／pyd／资源／dist-info形成 ZIP；不得塞一个必须另启动的 PyInstaller Python归档冒充 site-packages。
- 基础 EXE的 PYZ、COLLECT清单和 `_internal` 必须审计，确认无组件模块／专属 DLL残留、无共享依赖重复；实际冻结 import 来源也要验证。
- 当前 SciPy裁剪策略不可无证明复用：保留／移除 OpenBLAS均以目标组件闭包和四类样本验收为依据，所有树修改先于冻结 smoke。
- 输出 core/包清单、许可证与依赖列表；使用内容寻址包名、可追溯构建配方和签名目标元数据。
- modular交付中复制已测试 manager二进制；同一 manager hash 可服务多次 app发布。不要无条件把当前 app_version作为 manager_version。
- 现有 Lite后置渲染检查继续执行；扩展导入门禁按“base无组件预期缺失”和“安装组件后可用”分别验证，不能因为新设计永久 skip。

### 测试与门禁

运行 `tests/test_windows_runtime_dependencies.py`、`tests/test_windows_build_script.py`、`tests/test_packaging_imports.py`，新增 `tests/test_extension_package_layout.py`。Windows原生 argv、stderr、失败退出码回归保持通过。

四种组合均有冻结证据：base、base+media、base+matlab、base+两者；同时保留旧 bundled 模式构建合同。统计基础包、各扩展、installer及压缩传输体积，不能把各目录大小直接相加当作功能净减量。

## 9. Task 6：管理器界面与提醒（S5）

### 管理器界面

- 顶部显示实际目标目录、主程序版本、管理器版本及需处理的更新提示；正常无需强调内部 ABI/hash。
- 组件行显示名称、用途、未安装／已安装／不兼容／需修复状态、版本和下载大小；提供安装、更新、卸载、修复、从本地包安装。
- 点击操作后显示计划和关闭程序要求；下载可取消，提交临界区说明正在完成，不出现假取消。
- “检查更新”只检查管理器和当前支持组件；结果分别展示，不用一个笼统“软件过期”。
- 更新 manager按钮下载已验证新版并说明关闭、替换的位置；没有在线信任状态时提供固定官方帮助，不执行未知 URL 的内容。
- 出错时优先说明失败阶段和下一步，提供本次日志路径；日志不含访问令牌。

### 主程序界面

通过现有 command registry增加“扩展管理…”入口，放入现有帮助相关入口，不为此新建传统菜单栏或大面板。若具体帮助承载位置与当前 UI 不同，实施时沿实际 command消费路径定位；不扩展 MainWindow多文件状态。

组件缺失时沿当前导入反馈增加“打开扩展管理”操作。主程序可以打开 manager，但安装需用户关闭目标程序后进行；不得自动关闭含未保存分析的窗口。

更新 `ui/hints.py`、`ui/quickref.py`及用户指南，明确安装器放哪里、何时要更新、离线说明、HEAD HDF与MAT区别、可写本地磁盘要求。

### 测试与门禁

新增管理器 presenter/state tests，Windows真实 Tk前台验证中文、100%／150%／200%缩放、取消、进度、失败、过旧manager和离线展示。不能只看 mock 界面。

主程序只跑受影响命令／导入入口测试与 `tests/ui/test_quickref.py`；新增必要的扩展入口测试。涉及 signal接线／QSS时运行对应现有 ratchet，状态 ownership变更时运行 `tests/ui/test_main_window_state_ownership.py`，不修改其白名单。

## 10. Task 7：跨版本、故障与发布验收（S10/S11）

### 固定验收矩阵

| 编号 | 场景 | 必需结果 |
| --- | --- | --- |
| A1 | 干净机器、无系统 Python，base无扩展 | 基础格式和分析可用；音视频／MAT给出安装入口 |
| A2 | 单独安装 media／matlab，及两者联合 | 样本实际读取，数据长度／单位等沿原 importer合同；模块/DLL来自预期目录 |
| A3 | 卸载一个组件 | 仅对应能力关闭，另一个组件及共享基础功能继续正常 |
| A4 | app A→B，runtime/API相同 | installer字节不变，扩展包hash不变，重新探针后可用，不要求重下载 |
| A5 | app A→C，runtime不同 | 旧组件不加载；基础可用，提示安装匹配扩展；协议相同时installer不要求更新 |
| A6 | 新组件API／新包最低manager要求 | 根据合同准确区分更新扩展、更新manager、无匹配组件 |
| A7 | 旧manager + 新catalog/schema | 可读稳定发现／manager-status入口，明确提示最低版本，不崩溃或误装 |
| A8 | 新manager + 旧core／bundled core | 兼容支持范围内管理，旧版不支持时明确提示；不删除内置依赖 |
| A9 | 核心回退、目录移动、两套TraceLab并存 | runtime映射与目标正确，绝不修改另一个目录 |
| A10 | 离线／仓库不可用／metadata过期 | 已装兼容组件可用；新安装需有效离线集合，不关闭验证 |
| A11 | 缺失／被删除 installer.exe | 已装组件仍可用；管理入口说明恢复方式 |
| A12 | 断网／取消／坏签名／越界ZIP／磁盘满／只读 | 事务未提交，旧active和组件不变，说明具体原因 |
| A13 | 多实例、并行manager、probe超时、强制终止 | OS锁生效、正确回收、可恢复，无半安装组合 |
| A14 | installer下载更新后手动替换 | 组件状态保留，新manager可接管；运行中旧EXE不被强制覆盖 |
| A15 | Z:共享目录或UNC | 明确阻止写事务，指导迁移本地；不误报安装完成 |

### 执行约束

所有冻结验收绑定稳定源码快照与产物hash；相关文件在验收中变化则结果记 UNVERIFIED。新 Windows x64本地目录为权威安装事务环境；Parallels ARM运行x64包是附加环境，不能替代原生x64平台说明。

沿用现有 Qt渲染加固门禁，确认模块化不影响 offscreen/windows字体、导出DPI及布局。Full仍保持 bundled，不能由Lite modular结果宣称Full新模式受支持。

这是跨入口／打包／运行时的集成里程碑：在所有focused门禁通过、快照稳定后，可运行一次全套。先检查现有pytest及cwd；主套件 `--ignore=tests/acquisition_ui` 完成后再独立运行 `tests/acquisition_ui`，不并行、不在每个任务重复全套。进程异常退出记UNVERIFIED。

## 11. 发布准备、非源码阻塞与回退

开发／测试可用本地TUF仓库与测试密钥完成；对外分发前必须具备真实HTTPS源、官方固定下载页、签名身份、生产root及轮换保管流程、metadata更新责任和有效期策略。此项由发布负责人配置，缺失时“线上分发未完成”，不以占位URL冒充可用。

新modular能力先作为显式构建选项交付测试；全部验收通过后再讨论是否成为默认。回退时继续分发原bundled Lite，原用户数据不变；已装扩展夹不自动删除，也不能让bundled包误加载它。

发布记录包含：app／manager／组件版本、runtime_id、合同版本、构建配方、来源清单、许可证、大小、测试矩阵、签名元数据版本、已知平台限制、未完成门禁。installer版本升级理由必须具体，不允许仅写“配合主程序更新”。

## 12. 完成判据与本轮文档检查

产品完成必须满足 A1–A15及对应 owner/boundary gates；可选项中任何缺失须明确标记，不将界面完成等同于分发链路完成。新增持续性失败模式按 project-lessons记录，既有课程不重复抄写。

本轮仅新增 spec 和本 plan，验证方式：完整读取两份文档、检查引用文件、schema／字段／版本词汇一致性、旧标识和承诺冲突、相互链接及 `git diff --check`。未修改运行行为，因此不执行运行时测试，也不启动构建或生成生产密钥。
