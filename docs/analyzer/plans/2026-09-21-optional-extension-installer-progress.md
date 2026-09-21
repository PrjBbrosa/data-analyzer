# 2026-09-21 可选扩展安装器进度账本

- 状态：**实施中（follow-up W0 起）**。
- 权威执行计划：[后续优化计划](2026-09-21-grok-implementation-followup-plan.md)。
- 原计划：[可选扩展包与稳定安装器](2026-09-21-optional-extension-installer-plan.md)（历史“待实施；本轮只写文档”头部保留为当时观察，不以它冒充当日完成）。
- 审查：[实现结构与当日提交审查](../reviews/2026-09-21-grok-implementation-and-day-commits-review.md)。
- 规格：[可选扩展与稳定安装器 spec](../specs/2026-09-21-optional-extension-installer-spec.md)。
- 执行起点 HEAD：`5cea434b2c5c01dedf67b0d5dbbdca0ebbf564f1`（审查基线 `21a88687` 之后多了实验性 Lite modular packager）。
- 本文件把原先只写在 `.state/extension-installer/` 的绑定决策提升为可提交记录。`.state/` 仍是实验证据，不是产品完成证明。

## 1. 执行时工作区

| 项 | 值 |
| --- | --- |
| HEAD | `5cea434b` |
| 审查基线 | `21a88687` |
| HEAD 相对审查的增量 | `tools/build_windows_folder_lite_modular.{ps1,bat}` + `tests/test_windows_lite_modular_build_script.py`。提交说明为 experimental，**不等于原 Task 5 完成**。 |
| Dirty（执行开始） | `docs/lessons-learned/INDEX.md`（既有，勿纳入本波）；本账本与 follow-up 计划为新文档。 |
| pytest | 启动时未发现本 checkout 的全套 pytest。各波只跑 owner focused / boundary。 |
| 全套门禁 | 未授权。集成负责人只在 W6 全部 owner 通过后跑。 |
| 生产密钥 / 用户 dist | 不创建、不覆盖。 |

## 2. 原计划完成口径

四列含义：

- **source complete**：源码职责已落到 owner 模块且有 focused 测试，不等于原生冻结通过。
- **focused verified**：本机（多为 macOS offscreen / 纯 Python）owner 测试正常退出 0。
- **Windows frozen verified**：目标 x64 NTFS 冻结 EXE / LockFileEx / 外置模块实测。
- **blocked**：缺平台、缺依赖或上游缺陷，不能把 skip 写成通过。

| 原任务 | source complete | focused verified | Windows frozen verified | 当前判断 |
| --- | --- | --- | --- | --- |
| Task 0 冻结可行性 | 审计与实验说明已写在 `.state/extension-feasibility/` | 源码审计 PASS；原生实验未跑 | **UNKNOWN / BLOCKED** | 审计完成，原生实验未完成。不得开始产品 Task 5。 |
| Task 1 合同 / schema | schema、兼容、recipe、modular `--exclude-module` 已落地 | 审查时合同/兼容/import boundary 绿 | 真实 core 产物绑定无构建闭环 | **partial** |
| Task 2 仓库 / TUF | repository + download + 本地测试仓库已落地；W2 接通 VerifiedPackage / FileEntry / installer 哈希 | 应用层 77 passed；manager gate 32 passed；**F1 仍开** | 未跑 | **needs revision**（W3 操作资格） |
| Task 3 安装事务 | ZIP 解包已接 contract FileEntry；锁 / probe / active / 恢复未实现 | 解包 focused 绿 | 未跑 | 解包子项完成，事务未完成（W5） |
| Task 4 启动桥接 | 未开始 | — | — | 未完成（W6） |
| Task 5 构建拆分 | 仅有实验性 lite modular 启动器副本 | 源码合同测试存在，证明“另起脚本、默认 bundled 未改” | 无 PYZ/外置模块/core 清单产物 | **blocked / 非产品完成**。文件存在 ≠ Task 5。 |
| Task 6 管理器 UI | 未开始 | — | — | 未完成（W6） |
| Task 7 A1–A15 | 未开始 | — | — | 未完成（W6） |

`.state/extension-installer/WAVE1.md` 的 complete 只覆盖 Wave 1 有限子项（协议 + unpack 安全 + TUF 客户端测试）。它把 Task 0/3 标成 done，**不能**替代上表。

## 3. 已确认缺陷（F1–F7）与既有红项

| ID | 严重度 | Owner 波次 | 状态 |
| --- | --- | --- | --- |
| F1 刷新失败仍复用旧安装授权 | P1 | W3 | 未修。确定性复现：过期 / `MANAGER_TOO_OLD` 后 `select_package`/`download_package` 仍成功。 |
| F2 FFT Pin 时域 DTO 进入频域展示 | P1 | W1a | **focused 已修**（占位行走 diagnostic 状态通道，FFT 展示按 numeric/status 分支）。计划指定命令 103 passed；前台 Cocoa UNVERIFIED。 |
| F3 contract 清单与 unpack API 未接通 | P2 | W2 | **focused 已修**。unpack 只消费 `FileEntry` 或唯一 `ManifestFile` 适配器，强制 size+SHA-256。应用层 77 passed。 |
| F4 installer 下载未绑定 manager-status 哈希 | P2 | W2 | **focused 已修**。status sha256 必须与 TUF installer target 一致，否则 `VERIFICATION_FAILED`。manager gate 32 passed。 |
| F5 dirty 变化不刷新名称徽标 / 窗口标题 | P2 | W1b | **focused 已修**（dirty bool 翻转才通知 chrome；toolbar 投影去重后才 polish）。前台短名/长名/中文/未命名会话 UNVERIFIED。 |
| F6 验证工具 evidence 可覆盖被测 EXE | P2 | W1c | **focused 已修**（`mf4_analyzer/frozen_evidence_paths.py`；非法目标退出 2 且不启动 child）。importer 16 passed；render+acceptance 62 passed。Windows junction 仍 UNKNOWN。 |
| F7 macOS 上 `ctypes.WinDLL` monkeypatch 崩溃 | P2 | W1d | **focused 已修**（`raising=False` 注入 `_FakeToolhelpKernel32`；`tests/test_run_test_gate.py` 42 passed, 1 skipped, 退出 0）。生产代码未改。Windows 本机进程树 fallback 仍 UNKNOWN。 |
| canonical digest 负例 | 既有 | W1b | **focused 已修**。合法当前-schema roundtrip 哈希不变；缺 `time_filter` 的 fixture 补默认后哈希变化保留为迁移负例。 |
| UI 大组合慢路径 | 既有 / 未归因 | 协调者记录 | 审查时 toolbar 附近 `setStyleSheet` 长时间重算；隔离 toolbar 节点通过。不反复跑整个 `tests/ui`。 |

## 4. 从 `.state/extension-installer/` 提升的绑定决策

历史观察基线仍在 `.state/extension-feasibility/`（当时 HEAD `464396fa`）。下列决策继续约束后续波次：

1. **不要开始产品 Task 5**（改 `build_windows_folder_lite.ps1` 默认或宣称 modular 可交付），直到 Windows amd64 NTFS 跑完 `experiments.md` §1–§8，并留下 PYZ toc + `__file__` / DLL origin 证据。
2. Modular 收集不是“去掉 collect-all”。`pyinstaller_collection_args(..., profile="modular")` 必须带 `--exclude-module av,scipy,h5py,hdf5storage`。bundled 默认不变。
3. 不要把 Lite OpenBLAS 文件删除策略无证明复用到 MATLAB 组件闭包。
4. 同名不同内容 DLL → 拒绝该组合，不用 `add_dll_directory` 顺序掩盖。
5. 新 hidden probe 进入现有互斥、`allow_abbrev=False` 组；真相走 exit code + JSON；不得覆盖 exe / core-files / active.json / 用户数据。windowed `stdout is None` 不能用 console 构建代替。
6. **不要**把 `python-tuf` 或 Tk 装进应用 `.venv`。Manager 环境独立：`.state/extension-manager-tuf/`（gitignored）+ `tools/extension_manager/requirements.txt`（`tuf==7.0.1` 等）。不要清理 leftover `dist/TraceLabAnalyzer8.3.1`。
7. 中立层共享类型：`ReasonCode`、`DiscoveryEnvelope`、`evaluate_install_compatibility`、`evaluate_load_compatibility`、`verify_receipt`、`parse_manager_status_v1`、`RuntimeInputs`、`compute_runtime_id`、`SemVer`。工具层显式 import，禁止宽异常再选另一套合同。
8. `manager-status-v1.json` 必须匹配 `parse_manager_status_v1`：integer `schema`、`minimum_supported_manager_version`、`installer_artifact`。Installer 字节落到 `extensions/cache/manager-updates/`，不原地覆盖 `installer.exe`。
9. python-tuf `DownloadLengthMismatchError`（`DownloadError` 子类）及 cause-chain 长度/hash 错误映射为 `VERIFICATION_FAILED`，不是 `NETWORK_CHECK_FAILED`。
10. 事务引擎只在 TUF/manifest 验证之后调用 `validate_zip` / `extract_verified_zip`。不要在 `transaction.py` 再实现一套 ZipSlip/ADS/device 检查。
11. `5cea434b` 的 modular 启动器是实验副本：另起 `build_windows_folder_lite_modular.ps1`，原 Lite bundled 构建器未改。它**没有**生成 core 清单、签名组件、匹配 manager，也没有冻结外置模块证据。follow-up W6 才允许把它升级为产品 Task 5。

## 5. Manager 测试环境合同

- 应用普通测试（合同、unpack 纯逻辑、import boundary）使用仓库 `.venv`，**不**安装 TUF。
- 专用 manager gate（`tests/test_extension_repository.py` 及后续 engine 测试）必须在固定依赖的独立环境运行，当前约定：`.state/extension-manager-tuf/` + `tools/extension_manager/requirements.txt`。
- 缺 TUF 依赖时该 gate **必须失败**（非零退出或明确 error），不能因为 `.state` 目录不存在就整组 `importorskip` 后声称通过。
- 当前测试文件在 import 时 `pytest.importorskip("tuf")`。W2/W3 修改该文件时改为：独立环境可运行；在默认 `.venv` 下缺依赖则失败而不是静默 skip-pass。协调者验收以专用环境命令为准。
- 测试仓库只使用本地签名夹具，禁止访问生产仓库或生成生产密钥。

## 6. 实验性 modular 脚本审查（非 Task 5）

`5cea434b` 合同测试只钉住：

- 原 `build_windows_folder_lite.ps1` 仍是 bundled，不含 `--profile modular`。
- 新脚本是独立副本，调用 `--flavor lite --profile modular`，独立 build/spec/evidence 目录，输出名带 `-modular`。
- 不复用 Lite `libscipy_openblas*.dll` 删除；跳过 lite importer smoke，不把它算进独立后置检查。

缺口（保持 blocked）：无 core.json / 组件 ZIP / 清单审计 / 匹配 manager 复制；无 Windows PYZ 与外置 av/MAT 运行证据；新脚本不是产品默认路径。W4 未完成前不得把默认发布切到 modular。

## 7. 本轮波次与文件所有权

细节见 `.state/followup-20260921/OWNERSHIP.md`。摘要：

| 波次 | 内容 | 并行 |
| --- | --- | --- |
| W0 | 本账本、环境、指纹 | 协调者 |
| W1a–W1d | F2 / F5+digest / F6 / F7 | 文件不重叠，可并行 |
| W2 | F3/F4 合同与受信解包链 | 与 W1 并行；独占 repository/unpack/contract |
| W3 | F1 操作资格 | **W2 之后**（同读 `repository.py`） |
| W4 | Windows 冻结与 runtime 身份 | 需 x64 NTFS；本机 macOS 只能准备脚本/账本 |
| W5 | media 纵向事务 | W3+W4 之后 |
| W6 | UI / 打包 / A1–A15 | W5 之后 |

不授权直接发布。bundled Lite 仍是可交付回退。
