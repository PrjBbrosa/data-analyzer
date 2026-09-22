# Grok follow-up 完成度审查（2026-09-22）

结论：**PARTIAL / NEEDS REVISION**。W4–W6 有实现和 focused 测试，但真实调用链仍有缺口，不能标记全部完成，也不能发布 modular 安装器。此次按用户要求保存并推送工作检查点，不实施下列产品修复。

审查基线：`bcb23bdb23f8eb8e736e64243cfdbea17383917d` 加本轮 49 个相关 dirty/untracked 文件。范围为 W3 下载收尾和 W4–W6 完成度；不替代全面安全审计。对照 follow-up plan、原 installer plan/spec 和 progress ledger。无关启动优化计划及 lessons INDEX 修改不纳入提交。

## Findings

### R1 · P1 · 真实 modular 启动路径抛出 NameError

`mf4_analyzer/app.py:157–165` 未导入 `MODE_SOURCE`，但 `:178` 在 `frozen=None` 的默认生产调用中引用它。现有测试显式传 frozen，绕开该表达式。以 modular 模式、默认 frozen 参数调用 bootstrap，复现 `NameError: name 'MODE_SOURCE' is not defined`。影响：modular 主程序进入窗口前失败。

关闭条件：真实默认参数入口测试先复现，再修复；bundled/source 分流及真实冻结入口分别验收。

### R2 · P1 · 安装引擎与真实仓库下载 API 不匹配

`tools/extension_manager/engine.py:113` 调用 `download(component)`；实际 `repository.py:1011–1017` 要求 `PackageRecord, app_root`。用真实 RepositoryClient 方法接入引擎即复现 `TypeError: RepositoryClient.download_verified_package() missing 1 required positional argument: 'app_root'`。影响：真实在线安装在下载前失败，测试替身通过不代表集成通过。

关闭条件：本地签名仓库夹具贯穿真实 RepositoryClient、包选择、引擎和事务；不以另一个宽松 fake 掩盖签名。

### R3 · P1 · 管理器默认入口没有仓库，离线接口也未接通

`tools/extension_manager/app.py:590–593` 的 `_try_make_repository()` 恒返回 None；`:631–650` 的 `run_app()` 默认构造 presenter 时没有注入仓库。`:595–605` 期望 `load_offline_bundle`，真实仓库提供的是 `repository.py:1191` 的 `from_offline_bundle`。影响：默认管理器无法实际检查/安装，不能仅归类为缺生产域名配置。

关闭条件：独立 manager composition root 建立真实仓库和受信配置，在线与离线两条真实入口均可通过本地夹具验证；应用环境仍不安装 TUF。

### R4 · P1 · 原生探针仍是文件占位检查，却能推进成功事务

`mf4_analyzer/extensions/probe.py:215–243` 明确是 stand-in，只检查 av/h5py 的 `__init__.py` 存在，不导入、不读取 WAV/MP4/MAT。`tools/extension_manager/transaction.py:136` 默认使用 `standin_executable()`，并非目标 TraceLab EXE。放入内容为 `raise RuntimeError(...)` 的 av 标记文件，探针仍返回 `ok: true`。`mf4_analyzer/extensions/runtime.py:261–329` 的可用性路径也没有完成 core build 变化后的冻结健康探针。

影响：损坏组件可被当成通过探针；W5 纵向链路及核心 A→B 复验尚未实现完成。关闭条件：目标冻结解释器执行固定格式读取，绑定 core_build_id + 组件 hash，失败不提交 active；Windows native gate 不得由文件标记检查替代。

### R5 · P1 · manager 构建和冻结验收工具仍为占位

`tools/build_windows_extension_installer.ps1:49–55` 只打印构建目录/说明，脚本中没有冻结命令，不生成 installer.exe。`tools/verify_extension_installation.py:264–298` 即便提供 EXE，真实验收模式仍恒返回 `FROZEN_*_CHECK_NOT_RUN` / exit 14。`tools/build_windows_folder_lite_modular.ps1:579–582` 在 manager 缺失时写占位。

影响：尚不能从这些脚本构建并证明可交付的独立 manager。关闭条件：补齐独立冻结任务、缺 manager 的发布失败门禁和实际 child 验收；bundled Lite 默认保持不变。

### R6 · P2 · Tk 回调同步运行下载/事务，取消无法及时响应

`tools/extension_manager/app.py:786–821` 的按钮回调直接调用 `run_engine()`；检查/更新操作亦在 Tk 回调直接运行。没有将这些阻塞工作移出事件线程。即使补齐仓库连接，耗时操作期间取消按钮/界面刷新也无法正常处理。Presenter 纯逻辑测试不覆盖这一事件循环行为。

关闭条件：工作线程执行下载/事务，主线程消费进度；真实 Tk 验证慢下载、取消、关闭及提交临界区。

### R7 · P2 · 启动异常全部降级成“未安装”，丢失锁/核心诊断

`mf4_analyzer/app.py:181–197` 捕获所有 ExtensionError，丢弃 reason_code 和租约信息，统一返回 COMPONENT_MISSING。注入 APP_RUNNING 后，两组件均显示 COMPONENT_MISSING。影响：安装进行中或核心损坏被误报为缺组件，违背规格的忙状态/修复反馈。

关闭条件：保留明确的错误分类及诊断，分别验证缺组件、锁忙、核心不一致和恢复要求。

## Session 与全套测试

- Cursor 会话 `7bc7b766-2c16-44ae-a3a9-42b7947c584a` 最近用户指令为早上“继续”；此前答复只称 source slices/focused 完成，尚未提交。
- 全套 PID 16070，07:49:25 启动，09:53:43 结束，耗时约 2 小时 4 分。日志停在 52%，已有 42 个 `F` 标记；缺失最终 summary，不能把它解释为准确失败节点清单或通过结果。
- 采样时接近 99% CPU，主线程涉及 GC 和 Qt setStyleSheet。属于长时间慢路径；没有证据证明是零 CPU 死锁，也未定位到单个失败测试。
- 用户授权停止后，SIGINT 未使它退出，随后 SIGTERM，退出 143。状态 **UNVERIFIED**。Cursor 自动重跑全套 PID 30487，先 SIGSTOP，再暂停其专属测试 shell PID 30462 后终止 pytest，阻止 shell 返回触发立即重试。测试已停止执行；专属 shell 保持暂停。Mac 锁屏阻止通过 UI 停止 Cursor 当前回合，已告知用户；不能称整个会话已停止，解锁后需点停止再清理该 shell。
- 原始日志、采样、源文件 SHA-256 快照与复现结果保留在本机 `.state/grok-closeout-20260922/`，不随代码发布。

## 本轮实际验证

在本次快照上运行以下已有 focused/boundary 检查，均正常退出 0：

| 范围 | 结果 |
| --- | --- |
| bootstrap / probe / runtime / layout / verification / modular builder / presenter / transaction / Windows locking | 82 passed, 1 skipped，1.72s |
| manager command / quickref / state ownership / UI import boundary / source adapters / extension and native imports / Windows builder | 122 passed, 11 skipped，6.57s |
| 真实 repository 测试 | 45 passed，2.39s |
| 合计 | **249 passed, 12 skipped**；不代表全套或 Windows 冻结通过 |

运行器为项目 `.venv/bin/python -m pytest`，Qt 检查使用 offscreen。Repository 测试通过既有文件内环境桥接加载独立 `.state/extension-manager-tuf/` 依赖，没有向应用环境安装 TUF。直接用独立环境启动 pytest 曾失败（`No module named pytest`），因此这项通过不能冒充独立解释器 gate 已通过。

额外四个确定性探针复现 R1、R2、R4、R7；现有 focused 测试绿并未覆盖这些生产路径。R3/R5/R6 为已读源码的具体缺口。Windows NTFS/LockFileEx、冻结外置模块、Tk 前台及 A1–A15 仍未验收。

## 后续关闭顺序

先修 R1/R2/R3/R7 的真实入口与错误分类，再完成 R4/R5 原生探针和构建闭环，补 R6 事件线程隔离。每项先增加真实边界复现，只跑 owner 和相关边界 gate；源代码稳定后由一个协调者运行一次集成门禁。当前记录和提交均不得标为 W4–W6 或 Task 0–7 全部完成。
