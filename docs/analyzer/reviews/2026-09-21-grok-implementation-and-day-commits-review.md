# 2026-09-21 实现结构与当日提交审查

- 审查基线：`21a8868763c88d54ded73a01f50e3ee3c0af9d06`，比较基点 `b1bc412b`；覆盖当天 9 个提交的变更清单，重点追踪产品接线、扩展合同及打包门禁。
- 结论：**needs revision；扩展安装器整体仍为 partial，不能按“installer 已完成”验收。** 不需要推倒方案，优先修复已确认问题并打通模块边界。
- 本轮只增加审查与[后续优化计划](../plans/2026-09-21-grok-implementation-followup-plan.md)，未修改产品源码、测试或构建脚本。
- 证据目录：`.state/review-20260921-grok/`。源码、offscreen Qt、模拟仓库、原生 Windows 冻结证据严格分开。

## 1. 按严重程度排列的问题

### F1 · P1 · 刷新失败后仍复用旧的安装授权状态

位置：`tools/extension_manager/repository.py:623–659`、`:738–805`。

成功刷新后缓存 `_updater`、`_last_catalog`；下一次 refresh 遇到过期／错误时仅返回失败，没有取消旧状态的操作资格。`select_package()` 和 `download_package()` 仍使用旧对象，后者也不要求本次刷新成功。

**确定性复现**：本地签名 TUF 仓库正常刷新 → 将验证时钟推进 2 小时 → refresh 返回 `METADATA_EXPIRED` → select 仍 `ok=True`，新的组件下载仍成功。另一个探针中，manager-status 要求 manager ≥9.0.0，当前 1.0.0 的 refresh 返回 `MANAGER_TOO_OLD`，但仍可选中并下载组件。

影响：后续安装引擎若按这两个公开方法接线，会使用已经失效的元数据授权新安装。当前尚无安装事务，所以这是**接入发行前的阻断问题**，并非已经观察到用户安装被篡改。已装组件离线运行的允许条件应独立保留。

修复方向：把“可展示的旧快照”和“可用于本次变更的受信快照”区分；变更入口校验新鲜度、核心／manager／包限制及撤销状态。旧 manager 下载新版 installer 的恢复入口与组件变更权限分开。

### F2 · P1 · FFT Pin 恢复路径把时域 DTO 送入频域展示器（遗留缺陷）

位置：`mf4_analyzer/ui/chart_stack/pinning/presentation.py:460–476`；异常落在 `ui/chart_stack/cursor_display.py:715`。

恢复带 FFT 单光标 Pin 的工程时，展示路径收到 `CursorDisplayChannel`，却按 `FrequencyCursorChannel` 读取 `.value`，触发 Qt 事件循环内的 `AttributeError`，Pin 重投影失败。

**独立复现**：`tests/ui/test_project_session.py::test_open_project_does_not_write_old_fft_pins_into_new_project`。这次测试失败是 DTO 异常，不能将测试名称直接解释成“已证明旧 Pin 污染新工程”。相关分派代码 blame 为 9 月 19 日、字段读取为 9 月 16 日，**不是今天新引入**，但当前树仍携带它。

修复方向：追踪 unavailable／unchecked 占位样本的生产 owner，保持频域样本合同，或让状态占位展示走明确的非数值路径；不要给所有 DTO 增加含糊的 `.value` 兼容属性或吞掉异常。

### F3 · P2 · 合同清单与解包 API 尚未接通

位置：`tools/extension_manager/unpack.py:264–287`；对端 `mf4_analyzer/extensions/contract.py:568–584`。

合同使用 `FileEntry(relpath, size, sha256)`，JSON 字段为 `relpath`；解包只接受自己的 `ManifestFile` 或 `relative_path/path/name` 字典。直接传 `parse_package_manifest(...).files` 抛 TypeError；直接传合法 fixture 的 `files` 字典也报“missing a relative path”。

影响：两组单测各自通过不能证明受信 package.json 能进入解包。未来调用者被迫自行转换，还可能丢失 SHA-256；解包 API 当前允许不带 hash 的声明。

修复方向：一个显式、受测的合同适配边界；完整链路必须用真实 contract fixture，而非为每个模块单独手写一种清单格式。

### F4 · P2 · 下载 installer 时未绑定 manager-status 中的产物哈希

位置：`tools/extension_manager/repository.py:820–859`。

`_load_status()` 保留了 `installer_sha256`，下载时却只使用 TUF target 的哈希，不比较两者。

**复现**：签名 manager-status 声明全零 SHA-256，TUF installer target 为另一个合法哈希；refresh、download_manager_installer 均成功。TUF 对下载字节的校验仍然存在，但发布清单内部不一致被接受，展示的新版本声明不能可靠绑定实际下载物。

修复方向：状态声明、target 身份和下载字节三者绑定；不接受任意调用方字典作为“已经验证”的状态来源。补目标错配、过期快照和缺 SHA-256 的失败用例。

### F5 · P2 · 项目 dirty 变化没有刷新新加入的名称徽标／窗口标题

位置：`mf4_analyzer/ui/main_window/_project_io_mixin.py:90–95`、`:2209–2264`；`ui/toolbar.py:778–791`。

今天加入的项目徽标显示 dirty 星号，但常规 mutation funnel 只更新 `ProjectDirtyState`，不通知 chrome。保存／打开／文件信息刷新才会投影。

**offscreen owner 探针**：绑定 `A.tlproj` → `_on_markup_revision_changed()` → dirty=True，但徽标仍是 `A.tlproj`，实际窗口标题没有星号；调用 `_project_window_title()` 计算的应有标题带星号。

影响：修改标注等内容后，用户看到的保存状态可能滞后。此证据证明显示不同步，不等于退出防丢失 guard 失效。

修复方向：dirty 布尔值变化、保存、恢复、Undo 回到保存点时，统一发出轻量状态投影通知；不在每次绘制或标注移动时重新序列化工程。

### F6 · P2 · 导入验证工具的证据路径可覆盖被验证 EXE

位置：`tools/verify_lite_importer_runtime.py:185–190`。

新增 `--evidence-json` 最终无条件写入，未在运行前排除与 exe／输入／权威结果文件的别名。传入与 `--exe` 相同的路径时，即使子进程验证失败，也会把 EXE 覆盖成 JSON。

**隔离复现**：临时 fake.exe 哨兵文件，模拟 child 返回 1，调用 `verify(fake_exe, evidence_json=fake_exe)`，哨兵消失并变成 JSON。未对实际发行产物执行此探针。构建脚本当前自动生成的路径没有这一冲突，但工具公开参数仍存在破坏性边界缺口。

修复方向：所有验证先于启动和写文件，拒绝规范化路径相等／已有文件 samefile 等别名；为失败路径同样保留此门禁。复用项目已有 frozen evidence 安全规则。

### F7 · P2 · 今天新增的跨平台 Windows 测试替身在 macOS 上先行报错

位置：`tests/test_run_test_gate.py:716–724`，来自 `5d7868f1`。

`monkeypatch.setattr(ctypes, "WinDLL", ...)` 使用默认 `raising=True`，macOS 的 ctypes 没有该属性，8 个测试在安装替身时抛 AttributeError，根本没有进入待测 Windows 分支。

修复方向：正确注入平台不存在的属性并在 teardown 恢复；必要时使用明确的 Win32 API 适配对象。保留跨平台替身测试和真实 Windows 测试，不通过扩大 skip 掩盖失败。

## 2. 结构评估及完成度

值得保留的边界：bundled 默认保持不变；基础／media／matlab 的归属来自原清单；中立 extensions 层不导入 Qt/可选大库；TUF 独立环境；ZIP 对路径、大小写及展开大小有保护；渲染修复将像素所有权和输出 DPI 放在各自 owner。

需要收敛的结构：repository 重复定义部分 schema／SemVer／reason code，通过 `_load_contract()` 的宽异常 fallback 容忍共享合同缺失；unpack 又有另一种 FileEntry。问题是共享边界没有集成验证，不能仅根据文件行数进行拆分。

| 原计划任务 | 当前观察 | 审查判断 |
| --- | --- | --- |
| Task 0 冻结可行性 | `.state/extension-feasibility/` 是审计和实验说明；外部 av/MAT、NTFS 租约、Tk/TUF EXE 未实测 | partial，原生关键门禁仍 UNKNOWN |
| Task 1 合同 | schema、兼容函数、配方与依赖 profile 已实现；真实核心产物绑定尚无构建闭环 | partial |
| Task 2 仓库 | TUF／下载／离线测试已实现；存在 F1/F4，独立 package.json target→ZIP→receipt 完整链未接通 | needs revision |
| Task 3 安装事务 | 当前只有 ZIP 解包与磁盘预算 helper | partial，锁／probe／active 原子提交／恢复未实现 |
| Task 4–7 | 基线没有启动桥接、完整管理器、组件构建与 A1–A15 冻结验收 | 未完成 |

`.state/extension-installer/WAVE1.md` 的 complete 指有限子任务波次；其 Task 0/3 的“done”不能替代原 plan 的完成标准，TASK3-INTEGRATION 也明确列出剩余事务工作。原 spec/plan 的“待实施”头部同样已经落后，应补一份可提交的进度账本。

还有几个应在下一步实施前明确的边界：runtime 配方必须取真实 CPython 构建／共享 DLL 身份，不能只用 `python/numpy` 两个名称；active 引用应由 store/runtime/component/hash 严格生成；Windows 大小写及 reparse 路径统一验证；新组件不应因 installer 的重复硬编码列表而被无故要求升级管理器。

## 3. 当日提交覆盖

| 提交 | 主题 | 本轮检查 |
| --- | --- | --- |
| `0a5458b9` | 时间范围意图与执行分离 | PersistentTop、window、analysis/view owner 及范围专项测试 |
| `3fdc4a05` | Pin 标题／布局 | 文本投影、pill、presentation、overlay、生命周期接线 |
| `0b81fd3c` / `236b0ef3` | 优化计划／原型 | 作为历史设计背景，不当作运行证明 |
| `5d7868f1` | v8.3.1、Pin 接线与测试工具 | owner 查找、单游标坐标、side-panel、runner／selector、相关测试；发现 F7 |
| `56f81b7f` | Lite 字体、DPI、像素及脚本 | 字体/GUI线程、DPI、QImage副本、验证器、构建脚本；发现 F6 |
| `e75d91ee` / `464396fa` | 项目关闭解绑／名称徽标 | close/save/last-source/restore、命令、toolbar；发现 F5；复现遗留 F2 |
| `21a88687` | 扩展基础设施 | 完整读取扩展 spec/plan，检查合同、状态、配方、repository/download/unpack、fixture及测试；发现 F1/F3/F4 |

这是风险聚焦审查，145 个变更文件不代表每个 UI 场景均已前台验收；测试工具等大模块以本次 diff 和相关分支为范围。

## 4. 验证结果与限制

| 检查 | 结果 |
| --- | --- |
| 扩展合同／兼容／import boundary／仓库／解包／依赖清单 | **109 passed**，正常退出 0 |
| batch render、frozen smoke、Windows script合同、importer、packaging、native/render/signal边界、runner/selector | **196 passed，8 failed，13 skipped**，正常退出 1；8 个失败均为 F7 |
| 原 UI 组合检查 | **UNVERIFIED**：执行变慢，保留 sample 后主动中断，最终退出 143；不累计为通过 |
| UI 失败隔离 | **2 failed，1 passed**，退出 1；F2、canonical digest 负例；toolbar 节点在独立运行通过 |
| 时间范围剩余节点（新进程） | **33 passed**，正常退出 0 |
| Pin／side-panel／owner／signal／QSS剩余节点 | **UNVERIFIED**：独立进程在120秒预算内未完成，由自有进程组watchdog结束（退出 -15）；无完成总结，不累计为通过 |
| F1/F3/F4/F5/F6 确定性探针 | 见 `reproduce.py`、`reproductions.json`；均为临时目录、模拟仓库／child或offscreen owner，无真实安装写入 |
| 原生 Windows 新包、真实 x64、前台 UI、A1–A15 | **本轮未运行**；不能由上述通过数推导 |
| 全套 pytest | 未运行；本轮只跑有明确 owner 的检查 |

canonical digest 的失败位于 `tests/ui/test_project_dirty_guard.py:309`：测试样本不含 View `time_filter`，load 时补入默认字段，导致哈希变化。该 codec／原测试早于今天，需区分旧 fixture 与合法项目的规范化合同；本轮不将其宣称为用户文件损坏。记录为下一轮必须处理的既有红项。

UI 大组合在 toolbar 节点附近长时间消耗于 `setStyleSheet`／Qt 样式重算。该节点隔离后通过，当前只证明组合运行有未解决的性能／污染迹象，不足以归因于某一产品提交。

审查中出现额外未提交文件 `tools/build_windows_folder_lite_modular.bat`、`tools/build_windows_folder_lite_modular.ps1`、`tests/test_windows_lite_modular_build_script.py`；它们不在上述基线或验收范围。已审查的受版本控制代码仍位于同一HEAD；预先存在的 `docs/lessons-learned/INDEX.md` 修改保留。其他任务随后变化也不得反向计入本次结果。
