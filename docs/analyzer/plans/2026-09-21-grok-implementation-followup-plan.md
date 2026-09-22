# 2026-09-21 实现收敛与扩展安装器后续优化计划

- 状态：**PARTIAL / NEEDS REVISION（2026-09-22 复核）**。W4–W6 仅有部分实现及 focused 证据，真实启动、仓库接线、原生探针、manager 构建与 UI 线程仍有缺口；详见[完成度审查](../reviews/2026-09-22-grok-followup-completion-review.md)。bundled Lite 仍是默认；本轮提交为工作检查点，不代表产品 Task 5 或 A1–A15 完成。
- 审查基线：`21a8868763c88d54ded73a01f50e3ee3c0af9d06`。执行起点：`5cea434b`。当前 HEAD：`bcb23bdb`（已含大部分 W0–W3）。实验性 Lite modular packager 不等于 Task 5 完成。
- 输入：[本轮审查](../reviews/2026-09-21-grok-implementation-and-day-commits-review.md)、[扩展规格](../specs/2026-09-21-optional-extension-installer-spec.md)、[原执行计划](2026-09-21-optional-extension-installer-plan.md)、[Lite 渲染计划](2026-09-21-lite-packaging-render-hardening-plan.md)。
- 目标：修复已确认缺陷，把独立模块打通为最小可验证链路，然后继续原 Task 0–7；保留主程序／installer／组件独立版本策略。
- 默认顺序执行；不要求多代理，不批量重构，不修改 DSP。历史代码缺陷与今天引入的问题分别记录。

## 1. 顺序与完成口径

1. **W0：还原真实进度与验收环境。** 只把确实完成的子项标为 done。
2. **W1：修复当前应用和工具缺陷。** FFT Pin、dirty 徽标、验证工具输出保护、跨平台测试替身。
3. **W2：统一扩展合同并打通受信 ZIP 的解包链。** 一个 fixture 穿过真实模块边界。
4. **W3：让仓库变更授权失效机制完整。** 过期／撤销／过旧 manager 不能绕过；保留离线运行和 manager 更新恢复。
5. **W4：完成 Windows 可行性和运行时身份实验。** 证明外置 av/MAT、基础依赖闭包、DLL、NTFS 锁和独立 manager 可行。
6. **W5：先交付 media 安装／卸载／失败恢复的纵向链路。** 通过后加入 MATLAB 与组合事务。
7. **W6：接入用户界面和分发，再执行原 A1–A15。** 正常 Lite bundled 作为回退路径。

W1 与 W2/W3 逻辑独立，但任何发布仍须等待 W4–W6。本计划不授权直接发布、创建生产密钥或覆盖用户 dist。

## 2. W0：状态账本、依赖环境和证据

Owner：扩展计划／构建验收文档与测试环境配置。

- 为原计划每项建立 `source complete / focused verified / Windows frozen verified / blocked` 四列；Task 0 是审计完成、原生实验未完成；Task 3 是解包子项完成、事务未完成。
- 将当前只在 `.state/extension-installer/` 存在的关键集成决策整理成可提交文档。保留历史观察基线，不把日期旧文档伪装成当日验收。
- manager 测试使用固定依赖的独立环境。应用普通测试可不安装 TUF；专用 manager gate 必须在缺依赖时失败，不能因为 `.state` 不存在就整组 importorskip 后声称通过。
- 记录本次基线的 F1–F7、canonical digest 红项和 UI 组合慢路径；每个修复只跑对应失败节点和必要 owner 门禁。
- 执行前检查当前 HEAD、相关 dirty scope、已有 pytest 的 cwd。未完成新 modular 脚本先审查，不能因文件存在就视为产品 Task 5 完成。

验收：状态与实际文件/命令一致，链接有效，`git diff --check`；文档阶段无需运行时全套基线。

## 3. W1：当前应用与诊断工具修复

### W1a · F2：FFT Pin 样本类型

Owner：`ui/pinned_cursor_facts.py`、`ui/chart_stack/pinning/sampling.py`、`presentation.py` 中实际生产和消费占位样本的边界。

- 保留现有复现失败测试；增加最小 unavailable/unchecked 频域样本探针，先明确正确的 DTO 或明确的状态展示通道。
- 修正生产端或边界适配，不改变 FFT 数学、通道身份，也不通过 `.value=0` 或 getattr 默认值隐藏错误。
- 覆盖有数值／无结果／未勾选／缺失来源、单光标／双光标、工程 A→B 恢复；异常不能留在 Qt 事件循环。

Focused：上述失败节点，`tests/test_pinned_cursor_facts_rules.py`，受影响的 pin lifecycle/presentation 节点。Boundary：若改 canvas backref，跑 `test_pg_canvas_backref_invariants.py`；若改 MainWindow 写路径，跑 `test_main_window_state_ownership.py`。用实际频谱页面验证 Pin 及恢复，不以 offscreen 代替前台。

### W1b · F5：保存状态投影

Owner：`ProjectDirtyState`/`ProjectIOMixin`，toolbar 只消费状态。

- 由唯一 dirty owner/funnel 通知 bool 状态变化，刷新徽标、窗口标题和必要 QAction；同一事件不重复刷新。
- 同步覆盖 save、save-as、open、close、Undo/Redo 回到保存点、restore guard。编辑不触发工程序列化或磁盘写。
- 避免每次鼠标移动／绘制执行 `style.polish` 或全 toolbar 重建；只更新实际变化的显示值。

Focused：在 `tests/ui/test_project_dirty_guard.py`／`test_toolbar.py` 中验证“真实语义编辑→星号出现→保存／Undo→消失”；另跑 `test_session_reset_on_last_close.py` 的解绑、保留工程和取消节点。Boundary：state ownership、signal ratchet；涉及样式时 QSS gate。前台验证短名／长名、中文、未命名会话。

### W1c · F6：诊断产物不可覆盖输入

Owner：`tools/verify_lite_importer_runtime.py`；必要时共享已有路径保护 helper。

- 在创建 fixtures、启动 child、写日志之前，规范化 evidence、exe、输入、权威结果路径并检查别名。
- 对已存在文件用文件身份判断硬链接；覆盖正常路径、相同路径、符号链接／Windows junction 的适用边界。
- 无论 child 成功、失败、超时，非法 evidence 目标都退出参数错误且原始字节不变，不启动 child。
- 横向检查现有 frozen render verifier 的同类入口，确认是否有同样的历史缺口；改动时保持证据保留能力。

Focused：`tests/test_importer_runtime_smoke.py`，若共用 helper影响 render 则加 `tests/test_frozen_batch_render_smoke.py`。Windows 原生路径别名测试与 macOS 单元测试分别记录。

### W1d · F7 与既有红项

Owner：`tests/test_run_test_gate.py` 及相关测试 fixture；不得为修测试放松生产错误分类。

- 修复不存在的 WinDLL 属性注入，保证 monkeypatch 还原；8 个失败节点先通过，再跑 `tests/test_run_test_gate.py`。
- Windows 本机跑实际进程树 fallback：核对 ctypes 函数签名、HANDLE 宽度、Process32First/Next 的错误与正常枚举结束；模拟空表不等于原生验收。
- canonical digest 失败先证明“合法当前-schema项目”与“故意缺字段的fixture”各自合同。如果当前 codec 正常补默认值，测试比较规范化语义；另保留迁移的预期变化负例，不能直接删断言。
- UI 大组合慢路径按失败前后的最小节点集合诊断 QApplication 样式、顶层控件和 teardown；toolbar 隔离通过不关闭该问题。不要反复跑整个 UI 目录。

验收：focused命令正常退出、无Qt事件异常；已有红项有归因与修复，不靠 skip/xfail/固定顺序掩盖。

## 4. W2：一个共享合同，一条受信包验证链（F3/F4）

Owner：`mf4_analyzer/extensions/contract.py`、`state.py`；`tools/extension_manager/repository.py`、`unpack.py`。

建议数据流：

```text
TUF 已验证目标
    → RepositorySnapshot（稳定状态 + catalog + 元数据身份）
    → VerifiedPackage（ZIP目标 + 独立package.json目标 + 合同对象）
    → 解包及逐文件校验
    → 已校验候选（尚未激活）
```

- 中立 contract 是 schema、版本比较、reason code、FileEntry 的单一 owner；工具层显式 import，不再用宽泛异常兜底选择另一套合同。
- repository/catalog 在边界严格解析一次，内部使用确定的数据类型；unpack 消费 `FileEntry` 或唯一显式适配器，禁止调用方自行拼三套键名。
- `VerifiedPackage` 必须将 component/runtime/revision/API、ZIP hash/length、manifest target hash/length 绑定到同一次验证快照。
- package.json 是独立受信 target；ZIP 内同名清单逐字节一致。receipt 是验证结果记录，不是本地自签名信任根。
- 正式解包接口要求每个文件 size+SHA-256。解包失败必须清理本次已经创建和当前写到一半的文件；不得因失败留下同名非空 staging 使修复无法重试。
- manager 更新路径复用同样 target binding：manager-status 中的 installer 哈希必须与 target 相同；显示版本绑定受信声明，调用方不能随意注入另一个 status。
- 统一 Windows 相对路径校验。active 必须精确落在 `store/<runtime>/<component>/<hash>`，检查组件/hash一致、大小写归一、ADS/device/reparse；禁止 `.STAGING`／`CACHE` 大小写变体绕过校验。

Focused：extension contract/compatibility/repository/unpack。新增边界测试至少涵盖：真实 fixture贯通、真实 ZIP成功解包、独立manifest缺失/错配、hash缺失、installer声明错配、途中校验失败清理、active非法引用。

Boundary：`tests/test_extension_import_boundary.py`；中立层不引入TUF/网络/Qt。此阶段无需改变主程序入口、UI或运行时包搜索路径。

## 5. W3：仓库状态与操作资格（F1）

Owner：repository 的一次刷新快照和后续 engine 的操作前检查。

- 将“上次成功数据可用于展示”与“当前可执行变更”显式区分；refresh失败撤销当前操作资格，不必清除用于诊断的缓存。
- 每次操作使用一次受信快照，校验有效期、仓库代次、已知撤销、核心协议／最低manager、组件能力／API/runtime、包最低manager。校验后等待锁时还需重新验证必要条件。
- 过旧manager可读取稳定状态并下载合规新版installer；不能继续组件安装／升级／卸载。catalog无法读取时仍显示已验证的稳定更新指引。
- 普通断网与元数据过期分别返回原因。新的离线安装使用有效离线集合；已装组件正常运行保持不依赖下载元数据新鲜度或installer存在。
- 持久化撤销缓存的损坏应可诊断，不能静默解释为“从未获知任何撤销”；选择包和提交前都不得忽略已知撤销。
- 下载取消返回取消语义；错误类别保留原始诊断。下载层/仓库层不应把任意编程异常一律重分类为网络故障。
- 恢复续传必须核对 Content-Range 与实体标识；ETag不能只保存而不用。错误实体可丢弃part重新下载，最终仍验证全部hash。

必需新测试：同一client成功→时钟超期→refresh失败→select/download拒绝；成功→撤销→旧selection拒绝；manager最低版本提升；未知catalog但更新状态可读；installer升级允许而组件变更被挡；元数据在下载／等待锁期间到期；合法有效离线集合允许；已安装离线继续可用。

Focused：专用manager环境 `tests/test_extension_repository.py`，本地签名测试仓库；不得访问生产仓库。不是只断言 refresh.ok，必须调用后续API验证不能绕过。

## 6. W4：补齐真实冻结实验与 runtime 身份

Owner：运行时配方、Windows实验脚本和构建审计；沿原 Task 0，不提前宣称 modular 交付完成。

- 在本地可写 NTFS 的独立目录记录 x64 Python构建、PyInstaller、Qt、NumPy和关键DLL身份，输出带hash的实验账本。宿主是ARM不等于目标EXE是ARM。
- 运行最小 base + 外部 av，读取WAV/MP4；再外置SciPy/h5py读传统MAT/v7.3；联合装载、检查PYZ和实际模块/DLL来源，基础格式仍能读取。
- 配方明确 CPython实际构建标识、ABI、架构、NumPy ABI/版本、相关共享DLL内容身份、加载合同。app_version/源码hash/构建时间/整个EXEhash不得加入runtime_id。
- 改UI或算法：core_build_id变化而runtime_id不变；换同版本号但不同兼容构建的原生运行时：按明确策略检测并改变runtime_id或拒绝构建。测试不能只比较人工填写的版本字符串。
- 同名不同内容DLL拒绝组合；确定Python模块与native文件的精确归属，避免重复复制共享依赖。
- 独立Tk/TUF EXE移走目标 `_internal` 仍能启动；保留中文与DPI读数。验证NTFS共享/独占租约、别名、多实例、异常退出、授权probe child和网络目录拒绝。

验收：原 Task0 的原生实验结果齐全；本机VM可提供目标x64运行证据，原生x64平台未跑继续列UNKNOWN。不得用bundled产物冒充外置模块成功。

## 7. W5：先 media 纵向闭环，再组合事务

Owner：新增engine/transaction/locking/runtime/probe，按原计划职责分工。

- 第一个可验收切片：识别核心 → 下载一个受信media包 → 同卷staging校验 → 独占锁 → 目标EXE授权probe → 发布immutable store → 一次atomic active提交 → 重启实际读取WAV/MP4。
- 主程序及所有相关child持共享租约；installer不强杀用户进程。需要关闭程序时由现有未保存内容guard处理。
- 同一个事务包含core身份、active generation、候选hash组合；stage名称不能作为“验证成功”的证据。
- active是唯一提交点；取消只在可回退阶段生效。崩溃恢复明确保留旧／完成新／repair_required；不猜测目录中最新版本。
- 卸载先撤激活，再清理；旧runtime／回退引用保留，占用删除失败记cleanup_pending。
- media通过后加入MATLAB。两包联合probe、一次提交，任一失败都不出现半套新选择。

Focused：新增 `test_extension_transaction.py`、`test_extension_windows_locking.py`、`test_extension_runtime.py`、`test_extension_probe.py`；逐阶段故障注入。运行source_adapters/importer及neutral/native边界。真实NTFS至少一次强制终止恢复、并发manager/主程序、probe超时进程树回收。

## 8. W6：UI、打包与最终发布门禁

- 沿原Task4–6接主入口和hidden child bootstrap；source/bundled/modular明确区分，GUI和Batch共享availability状态。
- 管理器只消费engine结果；主程序扩展入口沿command registry，缺失/不兼容/损坏给具体原因。更新 `ui/hints.py`、`ui/quickref.py`及用户指南。
- 新modular脚本必须生成核心清单、组件产物、清单审计及匹配manager；只追加exclude参数的启动器不等于完整产品。
- manager二进制是独立发布产物，普通app更新复用相同字节。已装兼容组件运行不要求manager存在；只有协议/安全/实现变化才提高最低manager。
- bundled Full/Lite的历史默认保持；首版modular只发布明确支持的Lite组合。继续保留offscreen/windows/四类导入等独立后置检查，失败聚合为非零。
- 强化后置检查的有界终止：只处理自己创建的进程树，不能在超时分支又无期限等待stdoutTask.Result；原生argv应测试空串、引号和带空格尾反斜杠路径。

发布验收沿原A1–A15，额外强制包含F1–F7的修复证据和跨模块链路测试。Windows测试不可用macOS skip冒充；既有Lite字体/DPI图像门禁继续有效。

所有owner focused与boundary通过后，固定HEAD和相关文件hash，集成负责人运行一次全套：先 `--ignore=tests/acquisition_ui`，再独立运行 `tests/acquisition_ui`。不与另一全套重叠，前后快照变化或异常退出为UNVERIFIED。

## 9. 交付与回退

每一波单独说明变更owner、复现先失败/后通过、真实平台验收和未完成项；不把历史pass数复制成当前结果。文档状态必须与实际命令一致。

先保留bundled Lite可交付；modular未通过原生门禁时不更改默认。生产下载源、签名身份、TUF密钥/轮换/过期维护责任由发布方配置；本地开发只使用测试密钥。

最终完成条件：已确认缺陷关闭、完整安装事务可恢复、app A→B复用包和manager得到真实产物证明、旧manager更新提醒可达、四种组件组合及全部A1–A15通过。仅完成installer界面或部分纯Python单测不满足这些条件。
