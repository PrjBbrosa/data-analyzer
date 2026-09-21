# TraceLab 可选扩展包与稳定安装器规格

- 日期：2026-09-21。
- 状态：**设计稿，待实施和冻结验证；不是现有能力说明。**
- 对应计划：[执行计划](../plans/2026-09-21-optional-extension-installer-plan.md)。
- 源码观察基线：HEAD `5d7868f1961f580263e7ae4ef85a994bfeab6edb`，同时存在打包渲染、项目生命周期等未提交修改；实施时重新核验实际快照。
- 用户目标：在 TraceLab 文件夹放置独立的 `installer.exe`，选择安装／卸载音视频、MATLAB 等支持；主程序频繁迭代时，兼容的扩展包和安装器继续复用。
- 本轮范围：编写 spec/plan，不授权产品实现、联网发布、生产密钥创建或修改当前安装。

## 1. 产品决策与边界

### 1.1 首版交付

采用 **基础分析包 + 两类官方扩展 + 独立扩展管理器**。`installer.exe` 是“TraceLab 扩展管理器”，不是主程序全量升级器，也不是任意 Python 包管理器。

| 归属 | 内容 | 边界 |
| --- | --- | --- |
| 基础包 | Python、Qt、NumPy、Pandas、图表及分析功能；MF4/MDF、WWT、HEAD HDF、BLF/DBC、TDMS、CSV/Excel 等现有基础格式 | 共享依赖始终由基础包拥有，扩展不能覆盖或卸载 |
| `media` 扩展 | PyAV、FFmpeg 及其专属依赖；沿用当前 `AUDIO_VIDEO_EXTS` | 首版包括当前所有音视频格式；不承诺未安装时仍能读 WAV |
| `matlab` 扩展 | 经验证的 SciPy MAT 读取闭包、h5py/HDF5 及专属依赖 | 包括传统 MAT 与 v7.3 MAT；不是 MATLAB 软件／许可证／MATLAB Runtime |
| 安装器 | 发现目标、兼容性检查、下载、离线导入、安装、卸载、修复及诊断 | 不运行 pip、不编译、不执行包内安装脚本、不安装系统 Python |

HEAD `.hdf` 仍由本项目 `head_hdf.py` 解析，不属于 h5py/HDF5 扩展。WWT 等轻量格式不拆成独立组件。基础包的转依赖若实际需要 SciPy/h5py，必须先证明可分离；不能因为设计归属表就强行排除。

首版只支持 Windows 本地可写 NTFS 目录、稳定发布通道、单一目录一套基础包。允许空格、中文、非管理员安装和目录整体移动。UNC／SMB／Parallels 的 Z: 共享目录可用于开发打包，但不承诺事务安装：安装器识别后说明“请将 TraceLab 文件夹复制到 Windows 本地磁盘后安装扩展”，不尝试弱化锁和提交保证。Program Files 等不可写目录首版提示迁移／联系管理员，不自动提权或转装另一处。

第一目标进程架构为 `win-amd64`，Windows ARM 上运行 x64 EXE仍选 x64 扩展；架构从目标 PE／运行时声明确认，不能用宿主 `platform.machine()` 猜测。原生 ARM64 组件不是首版验收范围。

### 1.2 不做的事情

不做热装卸、后台自动更新、强制终止主程序、第三方插件市场、任意 URL 安装、任意版本依赖求解、全机共享组件仓库或主程序原位升级。不改 DSP、数据结构、文件语义和 Qt 主界面缩放。

## 2. 当前代码事实与迁移约束

| 当前 owner | 观察事实 | 设计要求 |
| --- | --- | --- |
| `io/runtime_dependencies.py` | 统一清单按 Full/Lite 生成 collection args，当前将 av/scipy/h5py 都当作必需运行依赖 | 在原清单扩展组件归属及交付 profile，不另建矛盾清单 |
| `io/loader.py::load_audio_video` | 函数内 `import av` | 解析逻辑保留；扩展路径和可用性必须在首次 import 前建立 |
| `io/mat_format.py::load_mat_groups` | 懒导入 SciPy，v7.3 回退 h5py，缺失提示当前建议安装 Python 包 | 冻结模式提示安装 MATLAB 扩展；开发模式保留可操作依赖诊断 |
| `io/source_adapters.py::SourceAdapter.availability` | `find_spec()` 驱动 ready 状态，数据适配器共用于 GUI 和 Batch | 对模块化冻结模式增加兼容性和健康状态，不能把 find_spec 成功等同于 DLL 可加载 |
| `MF4 Data Analyzer V1.py` | 多个互斥 hidden child 模式先于 GUI 启动 | 初始化覆盖普通入口和全部相关子进程；新增探针仍用互斥、禁缩写入口 |
| `app.py::main` | 创建 MainWindow 前加载 UI 模块；已有 QApplication 生命周期规则 | 启动扩展的中立层先于可能触发可选依赖的 imports，不塞入 MainWindow 状态簇 |
| PyInstaller 冻结结构 | 一部分 Python 模块嵌在 PYZ／EXE，原生文件在 `_internal` | 单纯搬动 `_internal/av.libs` 不等于完整拆包；必须审计 PYZ、DLL 和 hook 副作用 |

现有完整 Lite／Full 保留为 `bundled` 交付模式；新模式名为 `modular`。产品 flavor 与依赖交付是两个独立维度。首版只发布 `lite + modular`，不改变现有脚本默认行为，直到新模式完成验收。

旧版 TraceLab 没有本规格的启动桥接和核心清单，不能靠下载 installer 获得组件能力；管理器应明确提示先安装支持扩展的基础版本。旧版完整包不能直接删除依赖来迁移，必须交付干净的 modular 基础目录。

## 3. 三类版本解耦

### 3.1 字段及单一来源

| 字段 | 意义／来源 | 何时变化 |
| --- | --- | --- |
| `app_version` | 用户看到的产品版本，唯一来源仍为 `app_meta.APP_VERSION` | 正常产品发布 |
| `core_build_id` | 完整核心产物及其构建清单的内容标识 | 每次不同产物；不能替代兼容标识 |
| `runtime_id` | 可加载原生组件的兼容环境指纹 | CPython 实际构建／ABI、架构、共享 NumPy 等版本／ABI、组件可能依赖的核心 DLL或运行时加载合同发生变化 |
| `component_api` | 主程序导入适配代码与官方组件的调用合同 | 使用不兼容依赖 API 或改变组件必须提供的能力 |
| `package_revision` | 某个组件包的发行序号和内容哈希 | 重打包、依赖升级、安全修复；不等于 app_version |
| `manager_version` | installer 的独立发行版本 | 安装器实现、UI、传输或安全修复；不跟随 app_version |
| `protocol_major/minor` | 核心清单、包容器、事务协议的版本 | 破坏协议时升 major；纯可忽略字段才升 minor |
| `min_manager_version` | 某核心／包／发布策略要求的最低安装器 | 只有确有协议能力或安全需求时提高 |

`runtime_id` 由规范化的、版本控制的“运行时配方”生成，不能包含任意源文件 hash、构建时间、产品版本或整个 EXE hash，否则每次 UI 修改都会让扩展失效。配方包含加载器合同版本和影响原生兼容性的共享依赖，改动由发布检查强制提示；首版精确匹配，不使用“同为 Python 3.x 应该能用”的宽松推测。

manager_version／最低 manager 版本使用严格 SemVer 比较；package_revision 为组件发行的递增整数，内容 hash 才是不可变身份。app_version 只作展示，不作为同 runtime 组件的精确相等条件。未声明的运行时配方变更必须让构建失败，不能由安装器猜测兼容性。

`component_api` 按组件声明支持的合同版本；相同 runtime 下改变调用 API 可仅升级该组件合同及组件包，不必改变 installer。安装器仅处理数据声明，不理解 PyAV/SciPy 的产品逻辑。

### 3.2 兼容性判定

安装／启动激活必须同时满足：核心清单有效且匹配实际目标、协议可理解、manager 达到相关最低版本（仅管理动作）、runtime 精确匹配、组件 API 合同相符、包未被已知有效策略撤销、包内容／来源验证成功、目标主程序原生探针通过。

已装组件的正常加载**不依赖 installer.exe 是否存在或是否最新**。安装器删除或落后时，已验证且兼容的组件仍可使用；管理器升级要求不能被错误地解释成“全部分析功能不可用”。

| 发布变化 | 已装扩展 | installer |
| --- | --- | --- |
| UI、帮助、项目逻辑／算法更新，运行时和组件 API 未变 | 复用，无需下载 | 复用，无提示升级 |
| PyAV API 需求变化，运行时相同 | 升级 media 包 | 通常复用 |
| Python、架构、共享原生依赖改变 | 新 runtime 组件并排安装；旧包不加载但保留 | 协议未变时复用 |
| 新增一种官方组件，仍为同协议 ZIP 和文件清单 | catalog 增加可选项，核心须先声明此 capability | 通常复用，不能单靠 catalog 给旧程序增加导入能力 |
| 包格式／事务协议破坏兼容 | 拒绝不支持的安装操作 | 必须更新 |
| manager 自身缺陷或安全修复 | 既有正常组件按各自策略继续使用 | 根据严重程度推荐／要求更新 |

## 4. 目录、清单与稳定发现入口

建议布局；带尖括号部分是运行时变量，不是固定文件名：

```text
TraceLab/
  TraceLabAnalyzer<version>.exe       # 实际名称来自 core.json，不新增产品版本常量
  installer.exe                       # 独立运行时，稳定复用的发布产物
  core.json                           # 极小的 v1 发现信封 + 核心身份／需求
  core-files.json                     # 核心文件哈希清单；不包含 extensions/
  _internal/                         # 基础运行时，仅主程序发行负责
  extensions/
    install-id                       # 本目录随机身份；不由产品版本生成
    store/<runtime_id>/<component>/<package_sha256>/
      package.json
      receipt.json                   # 核心探针结果及受信目标身份，不是自签名信任根
      site-packages/                 # 外置模块、数据、dist-info、pyd
      native/                        # 必要时使用，真实 DLL 目录由清单枚举
    active.json                      # 唯一激活指针，按 runtime 分组
    transaction.json                 # 单事务恢复日志
    .staging/<transaction_id>/
    .locks/
    cache/metadata/                  # 已验证的更新元数据
    cache/downloads/                 # 分块／part 文件，不可被加载
    logs/
```

目标定位优先显式 `--app-root`，否则 installer 自己所在目录；不使用当前工作目录，不递归猜测某个 TraceLab.exe。缺少／多个目标时显示“选择 TraceLab 文件夹”，先只读识别。路径规范化后验证 exe 在根目录内、PE 架构、exe/hash 与 core-files 一致，拒绝部分覆盖的新旧混合基础包。

`core.json` 的外层 `discovery_schema=1` 永久稳定，包含 `product_id`、实际 exe 相对路径、app_version、core_build_id、runtime_id、组件 capability/API、运行时协议版本、最低 manager 版本、已知稳定 manager 下载页。即使内层协议升级，旧 manager 也能读出最低版本和求助入口。发布方不得直接删掉 v1 发现入口；不理解外层的更旧程序依赖其内置固定官方网站链接告知人工恢复。

发现信封不是网络信任根：旧 manager 不得执行其中任意命令、使用其中任意公钥或接受任意下载站。在线安装目标只由受信更新仓库选出。核心清单由打包阶段生成并与核心文件绑定；版本来自 APP_VERSION，清单生成脚本不再写第二个产品版本。

`package.json` 至少包含：schema、component、package_revision、runtime_id、component_api、min_manager_version、Python／平台标签、模块根白名单、DLL 目录、依赖归属、逐文件相对路径／大小／SHA-256、最大展开大小、固定探针类型。不得包含可执行安装命令。未知 required feature 拒绝；未知非必需描述字段可忽略。

发布时 package.json 本身也作为独立受信 target，与 ZIP 通过组件／runtime／revision及清单 hash绑定；解包后必须逐字节匹配已验证的清单。receipt记录目标身份、验证过的元数据链和原生probe摘要。启动时用已保留的受信清单校验文件，不能相信被单独改写的 receipt／package.json；离线运行不重新施加下载元数据的新鲜度门禁，也不导入任何新信任根。

`active.json` 只含版本化相对引用和包 hash，例如某 runtime 的 media、matlab 选择；从未指向 staging／下载目录。禁止通过 active.json 的绝对路径、`..` 或符号链接跳出本安装根。不同 runtime 的激活映射并存，便于主程序回退，默认不跨安装目录共享。

## 5. 安装器何时更新、在哪里提醒

### 5.1 提示触发矩阵

| 情况 | 提示位置 | 行为 |
| --- | --- | --- |
| installer 缺失 | 主程序“帮助 → 扩展管理…” | 显示官方下载入口和放置目录；基础功能、现有组件不受影响 |
| 主程序频繁更新但合同兼容 | 无升级提醒 | 继续复用 |
| 打开扩展管理器，在线查到新版但旧版仍受支持 | 管理器顶部非模态条 | “扩展管理器有更新”；可稍后处理 |
| 核心／选中包要求更高 manager 版本 | 管理器顶部 + 对应安装按钮旁 | 说明原因与最低版本；禁止受影响的变更操作，保留查看／日志导出 |
| 已知 manager 安全撤销或不再支持事务协议 | 管理器显著状态条 | 阻止安装、升级、卸载等写操作；提供新版下载，不影响主程序基本分析 |
| 导入音频／MAT 时组件未装、不兼容或损坏 | 原导入错误反馈中显示组件名与“打开扩展管理” | 不自动下载，不丢失当前会话，不引导冻结用户执行 pip |
| 主程序更新后旧扩展不匹配新 runtime | “扩展管理”页面及首次使用相应格式时 | 显示“需要匹配此版本的扩展”，不要错误显示为“必须更新 installer” |
| 离线／检查失败 | 管理器状态栏 | “无法检查更新”，仍展示本地真实状态；已安装可用组件继续使用 |

主程序启动不为扩展更新联网、不反复弹窗。在线检查只发生在用户打开管理器或点击“检查更新”，使用超时和可取消请求；普通新版提醒可按版本忽略。已知最低版本限制不可通过忽略按钮绕过。

主程序在本地组件页面可显示“此版本需要安装器 ≥ X”；实际 installer 自报版本不是安全信任依据，管理器自己也必须重新检查全部约束。主程序不必在每次启动执行 installer 查询版本。

### 5.2 首版安装器更新方式

**不在运行中覆盖 installer.exe。** “下载新版安装器”先获取受信新版到 `extensions/cache/manager-updates/installer-<version>.exe` 并验证，提示关闭旧管理器后替换根目录 installer.exe；保留清楚的文件路径和版本。首版不实现自更新 helper、提权或延迟重启替换。

也允许用户从固定官方页面下载并手动覆盖。根目录 installer.exe 不持有组件数据；替换后从同一 core.json 和 extensions 读取状态，不要求重装已装组件。每个新基础发行包携带“已测试的 installer 发布产物”，可复用其原始字节／哈希，不因 app_version 改变重建 installer。

旧 manager 先读取独立、长期支持的 `manager-status-v1.json` 受信目标（见第 8 节），再解析可能较新的组件 catalog。这样旧 manager 即使不懂新版 catalog，也能说明为何要更新和去哪下载。v1 状态格式及旧信任根升级链不得随新 catalog 同时消失。

## 6. 主程序加载与共享依赖

### 6.1 唯一运行时 owner

新增中立的 `mf4_analyzer/extensions/`：合同、安装身份、激活状态、启动引导、组件可用性。启动层不导入 Qt、MainWindow、PyAV、SciPy 或 h5py，不联网、不安装；source_adapters 消费状态快照，不能直接管理目录。

启动入口在可选模块首次导入前完成：识别 modular frozen 模式 → 取得运行租约 → 验证核心身份和 active 指针 → 校验选中组件签名／文件完整性及兼容性 → 注册允许的模块和 DLL 目录 → 保持 DLL 搜索句柄和租约到进程退出。开发环境默认走现有虚拟环境依赖，只有显式测试开关才使用扩展夹；bundled frozen 不依赖 installer。

不向 PATH、PYTHONPATH 或系统注册表写全局搜索路径，不处理任意 `.pth`／`sitecustomize`。扩展的允许模块根为构建期声明的 av、scipy、h5py 及审计后的专属依赖；拒绝覆盖 mf4_analyzer、Qt、NumPy、Pandas、标准库等基础根。对冻结归档进行审计，确保同名可选模块没有残留在 PYZ 中抢先加载。

Windows DLL 目录由 `os.add_dll_directory()` 等受控加载方式注册，句柄不提前释放。目录顺序不能解决同名不同内容 DLL 冲突：包构建／联合安装必须检测基础与组件间、两个组件间的 DLL 冲突；无法证明兼容则拒绝组合或改变构建，不引入按运气加载的 fallback。

### 6.2 可用性与失败语义

组件状态至少有 `not_installed`、`ready`、`incompatible`、`corrupt`、`repair_required`、`revoked`；管理事务状态与运行状态分开。首次安装和核心 build 变化后，在目标冻结解释器的隔离 child 中运行固定导入探针。成功证据绑定 core_build_id + 组件 hash 组合；同一 runtime 的 UI 更新可复用包，只需重新快速验证，不需要下载。

不能仅靠 `find_spec()` 或缓存的“曾经安装成功”放行。首版优先完整验证所选组件文件（两类包规模可控），实现前测量耗时；若需缓存优化，必须先定义可信失效条件并保留加载前原生二进制验证，不以 mtime 相同作为不可篡改证明。

发现一类扩展失败时，仅禁用对应格式并留下可操作状态；MF4/WWT/HDF等基础路径继续可用。不得把所有 ImportError 都归为“请安装”：已安装组件的 DLL 故障、内部编程错误保留原始诊断并报告损坏／运行失败。GUI 与 Batch 使用同一 availability 判定和错误分类，不改变通道 composite identity 或 SourceDescriptor 返回协议。

所有隐藏探针用退出码和专属 JSON 传递结果，兼容 windowed EXE 的 stdout/stderr=None；结果文件不得覆盖用户数据、exe、权威 manifest 或既有证据。

## 7. 事务、并发与恢复

### 7.1 锁与运行租约

每个本地安装根有一个由操作系统持有的共享／独占文件锁：所有主进程和使用组件的 child 持共享运行租约；manager 变更阶段持独占锁。仅用 PID 文本文件、窗口标题或 exe 名称不足以证明未运行。锁身份绑定规范化目录／文件身份，目录别名不能绕过。

manager 可以在 TraceLab 打开时查看状态和下载，进入安装／卸载前要求关闭该目录下所有实例。主程序自行处理未保存内容，manager 不强杀。取得独占锁后重新读取 core identity、active generation 和空间／权限，防止等待期间目标改变。新启动的 TraceLab 遇到短暂写事务时显示“扩展正在更新，请稍后重试”，不能绕锁加载半成品。

Windows 实现首选 LockFileEx 共享／独占租约，异常进程退出由 OS 释放。事务探针 child 由持锁 manager 启动，用受控继承句柄／本机 IPC 传递该事务的只读 staging 授权；不是可由任意环境变量开启的“跳过锁／验签”模式。此处必须先做原生可行性测试。

### 7.2 安装／升级顺序

1. 验证目标和版本，解析一次受信目录快照，展示所选组件、下载大小、展开占用与所需磁盘空间。
2. 下载到独立 cache/part，校验上限、长度、SHA-256和受信元数据；未完成文件绝不能成为模块搜索路径。
3. 所有待安装包准备就绪后，取得独占锁，再核对 core_build_id 与 active generation 未变化。
4. 在与 store 同卷的 staging 严格解包；验证逐文件清单、模块/DLL归属和兼容性。写入已刷盘的事务日志，保存旧 active 和预期新 active。
5. 用**目标 TraceLab EXE**运行内置固定探针：media 至少 WAV＋MP4 音轨；matlab 至少传统 MAT＋v7.3 MAT；同时验证基础格式与联合装载。候选目录只对授权 child 可见，不能调用包自带脚本。
6. 全部通过后将候选目录发布为 hash 命名的不可变 store 条目；最后以同卷临时文件＋原子替换提交完整 active.json。一次勾选的多个组件只提交一次，任一失败均保持原 active。
7. 标记事务 committed，保留一个可回退的旧选择及有限诊断，释放锁；旧目录回收独立进行，失败不谎报安装失败或破坏 active。

下载取消／断网发生在提交前时不影响现有组件。提交的极短临界区不响应取消，结束后给出确定结果。缓存和 staging 不以用户可编辑状态声称验证成功。

### 7.3 卸载与恢复

卸载仅修改目标 runtime 的 active 映射，不碰 `_internal`、主程序、工程文件和其他组件；随后按实际引用回收未使用 store。另一个 runtime 或回退记录仍引用的包不能物理删除，页面说明保留原因。无需维护跨安装目录的引用计数，因为首版不共享仓库。

删除被杀毒软件占用的无引用文件时，记录 `cleanup_pending`，下次安全重试；运行可用性以 active 指针为准。禁止在主程序仍持运行租约时删除 DLL。

重启恢复首先取得独占锁：active 仍等于旧值则保留旧版本并清理候选；已等于完整新值且包验证通过则完成 committed 标记；否则停用受影响组件、保留现场并报告 repair_required，不能猜测最新目录。首版不承诺抵御任意硬件断电造成的磁盘损坏；必须验证强制终止、提交边界及可检测的损坏恢复。

## 8. 下载、信任与离线运行

使用成熟的 **python-tuf 客户端 + 官方组件仓库**验证下载元数据，应用层负责 ZIP 和事务；不自创签名规范或把同一下载站的裸 SHA-256 当成来源认证。manager 自带初始受信 root，生产 root 私钥不入仓库；发布策略支持签名根轮换、元数据版本／过期检查和撤销。具体依赖版本在实现时固定并记录许可证。

仓库受信目标分层：`manager-status-v1.json`（稳定更新引导）、版本化 component catalog、内容寻址的组件 ZIP 和 installer 产物。manager-status 包含稳定 schema、最新版／最低受支持 manager、原因码、受信新版 installer 目标引用和固定帮助页；先验证该目标再读取组件 catalog。不能用未知 schema 的 catalog 才告诉旧 manager 如何更新。

选择包由核心声明的 capability/API 和 runtime_id 过滤，catalog 不能任意增加主程序能力。没有精确兼容包时说明“暂无适配此运行时的扩展”，不能自动选最接近版本、降级主程序或强制更新 manager。

首版网络策略：HTTPS，证书校验开启；跟随重定向仍需 HTTPS 和受信来源策略；不记录令牌／凭据。连接／读取均有有限超时、可取消和最多有限次退避重试，不在 UI 线程下载。断点续传仅在长度和实体标识匹配时续接，最终仍完整校验。

解包拒绝绝对路径、父目录跳转、盘符、ADS、设备名、符号链接／reparse points、大小写归一后重名和超额展开；不接受 `.pth`、启动脚本或清单外文件。空间预算包含下载、候选、旧版本和恢复余量，磁盘不足在提交前报错。

“从本地扩展包安装”使用附带受信元数据的离线发行集合，通过相同版本、签名、长度和路径检查，不能导入任意 pip wheel。新安装／更新要求元数据在有效期内；过期离线集合提示取得更新集合，不关闭校验。已安装并已验证的组件不会因仓库证书／metadata 过期或网络断开突然停用。新获知的撤销状态保存并执行；离线时不能声称知道尚未获取的撤销。

首次取得 installer.exe 的信任仍依赖官方发布渠道和代码签名／已验证基础发行包，TUF 不能替用户认证一个未知来源的初始 EXE。首版默认不防御具有同等用户写权限、可替换整个主程序的本机攻击者；仍必须防止网络篡改和正常安装事务的越界写。

## 9. 安装器实现与分发

建议复用项目 Python 技术栈，installer 作为**独立 PyInstaller EXE**，使用轻量 Tkinter UI、自己的 Python/Tk、受信下载和事务库；不依赖目标 `_internal`、PyQt、NumPy、音视频或 MATLAB 包。即使核心扩展缺失／损坏，也能启动查看和修复。

共用合同代码限定为 stdlib 中立层，构建时分别冻结到 app 和 installer。协议一致不要求两者二进制或 Python版本一致。manager 不用自己的解释器 import 目标 `.pyd`；所有兼容性实测都经目标 EXE child 完成。

安装器体积、中文界面、独立启动及 Windows x64 打包需在第一个可行性任务测量。若 Tk/TUF 冻结链不能满足要求，先以证据修订技术选择；不能临时改为依赖主程序已安装 Qt 的“独立”工具。

正常 Lite modular 构建可选择复用已发布且满足最低要求的 installer.exe，并将其 hash／版本写入交付清单；只有 manager 源码或其自身运行时／依赖变化才重新构建 manager。没有已验证 manager 时，发布失败，而不是临时生成不受支持的版本。

## 10. 版本升级、回退与迁移

同一 runtime 的完整核心更新保留 extensions，旧包经新 core_build_id 探针确认后继续使用；不要求更换 installer。不同 runtime 的新核心保留旧目录，显示不兼容并安装新 runtime 的组件，基础功能继续运行；回退核心时重新选择对应旧 runtime 映射并验证。

installer 首版不负责主程序更新。主程序的未来更新机制必须保证核心整套原子切换或要求完全退出后完整替换，并保留 extensions。只替换 EXE、混入旧 `_internal` 的方式不属于支持路径；manager 的 core-files 检查应识别并阻止对混合核心安装。用户换新目录时，支持关闭所有进程后整体复制 extensions，重新验证其归属和 active 引用；不得复制缓存中的 staging 作为已安装状态。

完整 bundled 模式显示“音视频／MATLAB 支持随主程序提供，不支持在此版本单独卸载”；不冒充 modular。卸载扩展会影响依赖该格式的工程重载／Batch，UI 说明该影响，但不修改或删除用户源文件、项目引用。

## 11. 发布与兼容检查矩阵

必须验证基础包单独、仅 media、仅 matlab、两者联合；每一种组合验证基础格式仍工作。检查模块实际 `__file__` 和 DLL 来源，不能仅验证安装 UI 为“成功”。

跨版本重点：同 runtime app A→B、不兼容 runtime A→C、核心回退、旧 manager+新 catalog、新 manager+旧 core、缺失 manager、已撤销／过期元数据、离线、无匹配组件。其预期提示位置和可操作状态必须与第 5 节一致。

故障重点：下载中断、校验失败、解包越界、空间不足、权限变化、并行安装器、主程序多实例／子进程、探针失败／超时、每个提交点强制退出、卸载删除失败。失败后不得出现“UI 成功但新进程无法使用”或一半新一半旧激活组合。

### 11.1 机器可读结果

中立层给 UI 和日志返回稳定 reason_code，而非让界面匹配异常文案：至少包括 `COMPONENT_MISSING`、`COMPONENT_INCOMPATIBLE`、`COMPONENT_CORRUPT`、`MANAGER_TOO_OLD`、`PROTOCOL_UNSUPPORTED`、`NO_COMPATIBLE_PACKAGE`、`CORE_INCONSISTENT`、`APP_RUNNING`、`UNSUPPORTED_FILESYSTEM`、`VERIFICATION_FAILED`、`PROBE_FAILED`、`TRANSACTION_RECOVERY_REQUIRED`。离线、推荐更新、已知撤销分别建模，不复用“未安装”。

管理器自动化／探针模式输出指定JSON，退出码约定：0成功，2参数无效，3取消，10目标／兼容性不符，11安装器或协议过旧，12网络／受信元数据失败，13目标忙／文件系统或权限不满足，14校验／原生探针失败，15事务需恢复。详细阶段由reason_code描述；正常关闭只读管理器为0，不伪装发生过安装。日志带transaction_id、core_build_id及包hash，不泄露凭据。

现有 Lite 渲染问题按 [渲染加固计划](../plans/2026-09-21-lite-packaging-render-hardening-plan.md) 验收；本设计不能以组件化绕过 offscreen、DPI 和图像布局门禁。此前产物大小只能作为测量起点，不作为减包验收承诺。

## 12. 仍需发布方配置的事项

生产下载域名、仓库路径、代码签名身份、TUF 根密钥保管／轮换负责人、元数据更新和过期维护责任，在发布前确定。它们不阻止本地开发和测试，但缺失时线上分发标记 BLOCKED，不填虚构地址或生成正式私钥。

正式 runtime 配方、精确依赖闭包及包尺寸由 Windows 冻结可行性实验和构建锁文件确定，不能从本文示意值推导。规格实施完成后记录支持的 OS／架构及旧 manager 兼容范围，未运行的平台记 UNKNOWN。

## 13. 技术依据

- [PyInstaller 导入机制](https://pyinstaller.org/en/stable/advanced-topics.html)：冻结归档优先级影响外部模块是否真正被使用，因此拆包必须检查 PYZ。
- [Python DLL 目录 API](https://docs.python.org/3/library/os.html#os.add_dll_directory)：模块路径与原生依赖路径需要分别管理。
- [TUF 规格](https://theupdateframework.github.io/specification/latest/)：采用其元数据验证与信任更新机制；本规格自行定义组件协议、用户提示和文件安装事务。
- [Windows 文件锁](https://learn.microsoft.com/en-us/windows/win32/fileio/locking-and-unlocking-byte-ranges-in-files)：使用操作系统锁区分运行租约和独占安装，不依赖遗留 PID 文件。
