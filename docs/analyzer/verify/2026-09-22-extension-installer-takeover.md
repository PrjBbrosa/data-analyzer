# 2026-09-22 扩展安装器接管交付记录

状态：**源码修复与专项验证完成；原生交付验收 BLOCKED，尚不可宣布全部计划完成或发布 Modular**。

用户授权接替 Grok 完成后续工作并 commit/push。本轮从 `f42c91ed3a48011748c00dc0ec316231304d8476` 接管；[先前审查](../reviews/2026-09-22-grok-followup-completion-review.md)的 R1–R7 是本轮修复基线。应用版本与 Full/Lite bundled 默认保持原样。启动速度优化计划属于另一任务，本次不实施、不提交。

## 已完成的源码工作

| 审查项 | 当前实现与证据 | 尚未获得的证据 |
| --- | --- | --- |
| R1 默认启动 NameError | 导入 MODE_SOURCE，覆盖默认 frozen 参数；扩展路径设置后才导入/绑定 source adapters | 新 Windows 冻结入口 |
| R2 仓库 API 错配 | 真实选择 PackageRecord，再调用 download_verified_package(record, app_root)；签名本地仓库贯穿实际下载与事务 | Windows 在线端到端 |
| R3 仓库/离线入口空缺 | manager composition root 读取随安装器分发的受信配置；离线选择完整发行目录，通过同一内置信任根验证；实际离线仓库贯穿事务测试 | 发布方真实域名/信任根、发布元数据与离线发行物 |
| R4 文件占位探针 | 默认调用识别到的目标 EXE；父子继承管道绑定请求 digest；校验包文件、模块与 Windows DLL 来源，真实 DataLoader 读固定 WAV/MP4/MAT/v7.3；首次或 core/hash 变化重验并缓存 | Windows 外置原生库与 DLL 实测、core A→B 真实产物 |
| R5 构建/验证占位 | 独立 Tk/TUF onefile manager 构建与 frozen self-test；manager-build.json 绑定版本、SHA、大小；Modular 构建强制真实 manager；目标 EXE 四种组合和卸载后读取验证工具已接入后置 gate | 实际运行 PowerShell 构建及新冻结产物验收 |
| R6 Tk 同步阻塞 | 单工作线程处理刷新、下载与事务，Tk 主线程轮询结果；取消与提交阶段协调，关闭等待工作结束 | Tk 前台慢下载、取消、关闭、中文与 DPI |
| R7 错误分类丢失 | APP_RUNNING / CORE_INCONSISTENT 等保留原原因并记录诊断；明确更新中/重新安装提示 | Windows 窗口反馈 |

额外真实边界修复：

- 在拿到独占锁并重新检查资格之后才写 staging/journal；清理完成后释放锁，拒绝覆盖未恢复事务。
- 核心文件与已装包 receipt/文件逐项校验；同 hash 的损坏目录经隔离后可以重装；恢复过程不再仅检查 package.json 存在。
- 真实 SciPy/PyAV 导入暴露的误判已修：只保护顶层基础依赖命名空间；不同 Python 限定名的扩展模块不按共享 DLL 的 basename 冲突处理。共享 DLL 同名不同内容仍拒绝；规格 §6.1 同步澄清。
- 应用、在线管理器和离线管理器使用同一撤回记录路径 `extensions/cache/metadata/observed-revocations.json`。中立解析器不依赖 TUF；已撤回组件不进入搜索路径，损坏记录不能当作“没有撤回”。两个新增测试先复现启动仍为 ready/未报错，再验证修复。
- 仓库专属失败码保持原分类，不强塞进有限的核心 reason 枚举；格式错误的健康缓存触发重验而非 AttributeError。两项新增负例先失败再修复。
- hints、quickref、用户指南同步管理器入口、离线目录和取消行为。

测试替身仍用于协议/故障注入单测，但生产默认不调用 stand-in。source 子进程真实读取与 Windows frozen 读取是两种证据，不能互换。固定样本位于 `assets/extension-probe/`，均为本地产生的合成数据。

## 本机验证

运行环境：macOS，项目 Python 3.12.14；Qt 使用 offscreen。结果之间有重叠，不汇总为一个总数。

| 检查 | 结果 |
| --- | --- |
| `tests/test_extension_*.py` + verify extension installation + modular builder | 231 passed, 1 skipped；7.33s，exit 0（撤回连接补充之前） |
| source adapters、native/packaging/import、Windows builder/runtime、GUI command/quickref/state ownership 边界 | 145 passed, 12 skipped；6.74s，exit 0 |
| hints + quickref 更新后复验 | 89 passed；1.68s，exit 0 |
| 独立 manager 解释器运行 `tests/test_extension_repository.py` | 47 passed；2.40s，exit 0（已给独立环境安装 pytest，应用环境未安装 TUF） |
| 撤回补充：runtime/repository/bootstrap/native boundary | 74 passed；5.75s，exit 0 |
| 撤回补充：neutral import/runtime/repository | 55 passed；2.76s，exit 0 |
| 最终修改后：repository/native probe/transaction/runtime/neutral import/bootstrap | **99 passed；6.59s，exit 0** |
| 最终修改后：独立 manager 解释器 repository | **48 passed；2.45s，exit 0** |

源码原生读取专项包含媒体、MATLAB 和联合组合，记录真实解码及模块来源；不是 Windows DLL 证据。原始日志在本机 `.state/installer-takeover/`，不加入 Git。

### 串行集成门禁：FAIL，已确认两个前置失败

本轮仅运行一次稳定快照集成门禁，两阶段顺序执行，各使用 `--maxfail=1`，遇首个失败即结束，未完成全套覆盖。记录：`.state/installer-takeover/integration/20260922T024531-pid20303/run.json`；HEAD 为 `f42c91ed`，执行前后 dirty fingerprint 同为 `961435115eb3d9286a3edfe7fc835bc283ae5b7d05d0a89fbd5058c085f84bc7`。

| 阶段 | 结果 | 定位 |
| --- | --- | --- |
| 主套件 `--ignore=tests/acquisition_ui --maxfail=1` | 1 failed, 717 passed, 2 skipped, 3 deselected；12.80s | `test_batch_qt_render_parity.py::test_text_overlap_guard_measures_ink_not_layout_boxes`：353 行放大字体后，ink collision 仍返回空 |
| 独立采集套件 `tests/acquisition_ui --maxfail=1` | 322 passed, 2 skipped, 1 error；12.51s | `test_state_machine.py` 第 413 行延迟回调访问已删除 QMessageBox，在后续测试 setup 报错 |

以 `git archive f42c91ed` 创建隔离源码副本，使用相同项目解释器复现：渲染同一节点/断言 1 failed；采集 owner 文件 18 passed, 1 error，同源第 413 行回调在另一个后续节点触发。因此这两个失败在接管修改前已存在；本次没有改动渲染器或采集状态机，也不把它们标为已修。

运行器第一次预检将 Grok 已暂停 shell 的命令文本识别成仍在运行的全套，未启动测试。此次专用协调脚本只在 PID 30462 确实为 T、其子 PID 30487 为 Z 时排除该记录，保留其余进程检查。未并行启动两个全套。此次集成结束正常，没有再次耗时数小时。

**集成之后增加了撤回连接、错误分类和缓存防御修复及对应专项门禁。上述集成 FAIL 仅属于记录的先前稳定快照，不作为最终提交的完整全套结果。** 已知失败未改变，因此不重复启动整个套件。

## 发布方配置与下一次原生验证

`tools/build_windows_extension_installer.ps1 -RepositoryConfig <实际配置文件>` 使用独立 Windows x64 Python/Tk 环境冻结 `installer.exe`。配置格式如下；示例域名只是格式示意，不能作为发布配置：

```json
{
  "schema": 1,
  "bootstrap_root": "root.json",
  "metadata_base_url": "https://updates.example.invalid/metadata/",
  "target_base_url": "https://updates.example.invalid/targets/",
  "trusted_origins": ["updates.example.invalid"]
}
```

`root.json` 必须由发布方提供，在配置目录内；离线包不能自带另一信任根替换它。构建器归一化并打包这些资源，运行 frozen self-test 后生成 `manager-build.json`。随后用 `tools/build_windows_folder_lite_modular.ps1 -ManagerSource <installer.exe>` 构建，保留邻接 `manager-build.json`；后置 gate 运行真实 base 缺失检查与 disposable copy 中的四种组合。Python 产物生成 helper 的无 manager 模式仍限于源码实验；Modular 发布脚本会拒绝缺少 manager。

Windows Python 子进程继承句柄实现依据 [Python subprocess](https://docs.python.org/3/library/subprocess.html) 与 [msvcrt](https://docs.python.org/3/library/msvcrt.html)；DLL 来源采集依据 [Microsoft EnumProcessModules](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-enumprocessmodules)。这些 API 依据不能代替运行结果。

## 未完成项与明确阻塞

- Parallels 最初显示 Windows 11 运行，但 guest exec 无法建立会话；之后 VM 停止，启动返回 Operation canceled。本轮无法在 Windows 执行构建、NTFS/LockFileEx、冻结外置模块和四组合 gate。
- Mac 锁屏，无法前台操作 Cursor/Tk；项目 Python 没有 `_tkinter`。工作线程逻辑通过测试不等于 Tk 前台验收。
- 发布域名、官方 bootstrap root、正式签名元数据/离线发行物尚未提供；未创建生产密钥或伪造生产信任根。
- Task 0 原生可行性、Task 5 真实交付、Task 7 A1–A15（含异常终止恢复、进程并发、core A→B/manager 复用、旧 manager 更新等）仍不完整；详见原计划逐项验收要求。
- Grok pytest 已停止，专属 shell 仍暂停；Cursor 回合本身未能通过锁屏 UI 点停止。不能声称整个 Grok 会话已关闭。

本轮提交是经过专项验证的源码修复交付，不是新的 Windows release。剩余原生 gate 和前置全套失败明确保留，不能由 focused 通过替代。
