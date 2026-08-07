# TraceLab 全量 Qt 门与跨平台发布加固实施计划

- **日期：** 2026-08-07
- **状态：** READY FOR IMPLEMENTATION
- **固定基线：** `main@4df9d603eb5ed09e94b9e2c1900e2a7747b9f7df`
- **建议实施分支：** `codex/qt-gate-release-hardening`
- **发布版本：** `v7.9.4`

## 1. 目标与最终判定

按严格顺序完成三道门：

1. 修复完整 pytest 收集/执行上下文中的 Qt `LabelItem` 生命周期崩溃；
2. 清零已确认的测试红项，修复 clean-checkout 可复现性与 `git diff --check`；
3. 在真实 macOS Cocoa 前台和真实 Windows 桌面上完成源码/冻结包发布验收。

最终只能有以下结论：

- `SOURCE GO`：完整默认 pytest 在新进程中正常退出并得到汇总，零失败；
- `MACOS GO`：真实 Cocoa 前台矩阵通过；
- `WINDOWS FULL GO`：新构建的默认 windowed Full 包通过构建、冻结 smoke 和前台矩阵；
- `WINDOWS LITE GO`：新构建的默认 windowed Lite 包通过构建、导入 smoke 和前台矩阵；
- `RELEASE GO`：上述四项全部为 GO，且证据绑定同一最终提交 SHA。

任一项缺证据、被中断、使用 offscreen/Console 包替代或只跑到部分 dots，结论必须是
`NO-GO` 或 `UNVERIFIED`，不得写成“基本通过”。

## 2. 明确排除范围

用户已明确“旧 HDF 不用管”。本计划不得：

- 为旧 `.tlproj` 增加 HDF 截断名到完整名的迁移或兼容别名；
- 修改 `mf4_analyzer/io/head_hdf.py`、HDF 名称恢复策略或 HDF channel-key 合同；
- 回滚固定基线里已经存在的四个 HDF/View 提交；
- 把 Vector/ECU 实车 bench 当成本轮 Windows 发布验收的一部分。

当前 `main` 比 `origin/main` ahead 4；这四个提交只作为固定基线保留。实施、提交和发布
必须单独确认范围，不得顺手 push、改写或合并 HDF 逻辑。

## 3. 已核实的当前基线

### 3.1 Git

- HEAD：`4df9d603eb5ed09e94b9e2c1900e2a7747b9f7df`
- `origin/main...HEAD`：behind 0 / ahead 4
- 工作树：核实时干净
- Qt 崩溃首次进入的大波次：`e5b3706a`，随后合入 `e9d40cc0`

### 3.2 Qt fatal 基线

当前 HEAD 运行：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -vv -k acquisition_ui --tb=no
```

稳定结果：`exit 139`。崩溃发生在
`tests/acquisition_ui/test_review_handoff.py::test_analyzer_main_window_has_public_load_file`
开始前的 pytest-qt 事件排空阶段：

```text
pyqtgraph/graphicsItems/LabelItem.py:84 in resizeEvent
RuntimeError: wrapped C/C++ object of type LabelItem has been deleted
Fatal Python error: Segmentation fault
pytestqt/plugin.py:220 in _process_events
```

已知边界：

- `tests/acquisition_ui` 单独运行不 segfault；
- 完整收集时忽略 `tests/ui/test_analysis_axes.py` 不 segfault；
- 仅运行 acquisition + `test_analysis_axes.py` 也不 segfault；
- 因而 `test_analysis_axes.py` 是当前复现的必要因素之一，但不是充分根因；
- 不允许把 `--ignore=tests/acquisition_ui` 或 `--ignore=test_analysis_axes.py` 保留为最终方案。

### 3.3 当前红项

定向重放当前为 `3 failed, 1 passed`：

1. `tests/ui/test_batch_runner_thread.py::test_sheet_preview_and_result_share_channel_metadata_reference`
   - Batch pipeline 有 150 ms debounce；约 100–200 ms 后产品 UI 能正确显示
     `1×metadata`，当前测试在 timer 结算前同步读取；
2. `tests/ui/test_hint_nudges.py::test_view_compact_tabs_ranks_between_coaxis_and_custom_action`
   - 新的、已发布的 `batch.export_options` discovery hint 以 priority 45 合法进入队列，
     精确列表测试仍是旧期望；
3. `tests/acquisition_ui/test_review_handoff.py::test_analyzer_load_file_delegates_to_load_one`
   - 产品现在按合同向 `_load_one` 传 `progress_callback`，测试 lambda 仍只接一个参数；
4. `tests/test_gen_help_screenshots.py::test_import_screenshot_uses_real_checked_in_samples`
   - 本机因存在未跟踪 `testdoc/` 而通过，干净 Git archive 会失败；测试名声称
     “checked-in samples”，但 `git ls-files testdoc` 为空。

### 3.4 `diff-check` 与发布标签

以下命令当前失败：

```bash
git diff --check b886a30e338514df31da5fe4874e992f5be110eb..HEAD
```

已确认问题：

- `docs/analyzer/verify/main-window-state-baseline.txt` 5 处尾随空格；
- `docs/analyzer/verify/ui-splits-baseline-ui.txt` 5 处尾随空格；
- `mf4_analyzer/batch.py` 末尾多一个空行。

另有发布标签漂移：

- `tools/run_windows_exe.bat` 默认仍是 `TraceLab7.6`；
- `tests/test_packaging_imports.py` 仍硬编码 `build/spec/TraceLab7.6.spec`；
- 当前测试没有把启动包装器默认版本与 `APP_VERSION=v7.9.4` 绑定，所以漂移未被阻止。

## 4. 执行总规则

1. 三阶段严格串行：Qt fatal 未清零，不得开始“清红”；源码门未全绿，不得进行发布验收。
2. 行为改动先有能复现问题的最小测试/探针；测试合同过期则先证明产品当前行为正确，再改测试。
3. 不修改 site-packages，不 monkeypatch `LabelItem.resizeEvent`，不吞
   `RuntimeError`，不加 xfail/skip，不通过拆分命令规避 fatal。
4. Qt widget 必须有明确 owner；测试创建的顶层 widget 使用 `qtbot.addWidget()` 或等价显式
   teardown。`close()`、`deleteLater()`、DeferredDelete 和事件排空各自的语义不得混写。
5. 所有 pytest 使用仓库 venv 和可写临时目录；测试证据记录命令、解释器、导入路径、
   退出码及最终汇总。
6. macOS offscreen、Cocoa 前台、Windows source、Windows frozen 是四种不同证据，不互相替代。
7. 生成的截图、JSON、EXE 和目录必须记录绝对路径、SHA-256、平台、Qt/Python 版本和提交 SHA；
   不能用旧 artifact、别名路径或 Console 诊断包冒充生产 windowed 包。

---

## Phase A — 修复全量 Qt `LabelItem` segfault

### Task A0 — 建立隔离实施分支与证据目录

执行时：

```bash
git status --short --branch
git switch -c codex/qt-gate-release-hardening 4df9d603eb5ed09e94b9e2c1900e2a7747b9f7df
mkdir -p .state/qt-gate-evidence
PYTHONPATH=. .venv/bin/python -c \
  'import sys,mf4_analyzer,pyqtgraph; from PyQt5 import QtCore; print(sys.executable); print(mf4_analyzer.__file__); print(QtCore.PYQT_VERSION_STR); print(QtCore.QT_VERSION_STR); print(pyqtgraph.__version__)'
```

将下列输出保存到 `.state/qt-gate-evidence/`，该目录不提交：

- `git status --short --branch`
- HEAD / merge-base / ahead-behind
- Python、PyQt、Qt、pyqtgraph、pytest、pytest-qt 版本
- fatal 命令的 stdout/stderr、退出码

**Gate A0：** 分支、导入路径、固定 SHA 和 fatal 日志可复核；否则停止。

### Task A1 — 缩小到最小收集/执行序列

目标不是先“猜修复”，而是回答两个问题：

1. 哪个测试或 widget 留下了带 queued resize 的已删 `titleLabel`？
2. `test_analysis_axes.py` 的模块级 import 为什么改变了这个对象的创建/销毁时序？

步骤：

1. 保留完整收集并用 `-k acquisition_ui -vv` 固定复现。
2. 以测试模块为单位做 delta-debugging；找出包含
   `tests/ui/test_analysis_axes.py` 的最小 crash 模块集合。
3. 对最后 2–5 个 acquisition nodeid 做前缀/后缀缩减，找出产生 dangling item 的前驱测试；
   不以“崩溃显示在哪一条”直接认定该条是创建者。
4. 临时诊断中记录：
   - `QApplication.topLevelWidgets()`；
   - `PlotItem.titleLabel` 的 Python id、`sip.isdeleted()`、`scene()`、`parentItem()`；
   - `QObject.destroyed` 时刻；
   - `QEvent.DeferredDelete` 前后对象状态。
5. 临时诊断代码只保留在 `.state/` 或最终删除；不要把大面积 debug print 提交进产品。

**Gate A1：** 得到能在 30 秒内稳定 PASS/SEGFAULT 的最小序列，并能指出错误 owner 或 teardown
边界；没有 root-cause 证据不得改第三方 pyqtgraph 或加入全局兜底。

### Task A2 — 先写生命周期回归，再修 owner/teardown

预计涉及文件由 A1 证据决定，优先级如下：

1. 产生悬空对象的具体测试文件；
2. `tests/ui/test_analysis_axes.py` 的 import/fixture 边界；
3. 共享 Qt fixture（只有证明是全局 owner 问题时才允许）；
4. 产品 `pg_canvas` teardown（只有证明前台产品路径也能产生悬空对象时才允许）。

回归必须验证：

- widget 被测试 fixture 明确持有；
- `close()` 后按需要 `deleteLater()`；
- `QApplication.sendPostedEvents(..., QEvent.DeferredDelete)` 与 `processEvents()` 后无 Qt event-loop exception；
- 最小复现序列正常退出，而不只是没有打印 traceback；
- 修复不会跳过 `test_analysis_axes.py` 的轴、title-row 和真实 `GraphicsLayoutWidget` 断言。

禁止方案：

- 捕获/忽略 pyqtgraph `LabelItem.resizeEvent` 的 RuntimeError；
- 在全局 fixture 中无条件 `gc.collect()`/多次 processEvents 来碰运气；
- 修改 pytest 顺序、把 acquisition 拆成独立 job 后宣布修复；
- 将测试标记为 xfail、skip、slow 或 `--ignore`。

### Task A3 — Qt fatal 稳定性门

依次执行：

```bash
# 最小复现序列：连续 10 个新进程

# 保留完整 collection 的触发命令：连续 3 次
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -k acquisition_ui --tb=short

# UI 全量：连续 2 次，必须到最终汇总
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/ui

# acquisition 单独门
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/acquisition_ui
```

此阶段允许仍看到 Phase B 列出的普通 assertion failure，但不允许：

- `Fatal Python error`、exit 139、macOS `EXC_BAD_ACCESS`；
- `Exceptions caught in Qt event loop`；
- hang、超时或只跑到部分 dots。

若 UI 全量卡住，保留 PID、进度、elapsed 和 `sample <pid>`，再终止仅由本计划启动的进程；
卡住仍是 Gate FAIL。

**Gate A：** 上述所有进程正常退出并生成汇总，Qt fatal 为零，才进入 Phase B。

---

## Phase B — 清理既有红项、clean-checkout 和 `diff-check`

### Task B1 — Batch metadata preview 测试等待真实 debounce

**文件：**

- `tests/ui/test_batch_runner_thread.py`
- 产品文件仅在“等待 150 ms 后仍失败”时才允许修改

步骤：

1. 保留“同步立即读取为等待解析”的基线证据。
2. 测试改用 `qtbot.waitUntil` 等待 `1×metadata`，timeout 必须明显大于 150 ms debounce，
   但不得调用私有 `_recompute_pipeline_status()` 绕开真实 timer。
3. 继续断言实际 `BatchRunner` 结果的 `db_reference_source == "metadata"` 和数值一致。
4. 新增/保留“pending row 时必须显示等待解析”的反例，避免为了绿测移除正确的 pending 状态。

**成功条件：** UI preview 和最终 result 都走同一 metadata resolution；无需产品改动则只改测试。

### Task B2 — Hint discovery 队列同步已发布能力

**文件：**

- `tests/ui/test_hint_nudges.py`
- 如实际合同不符才修改 `mf4_analyzer/ui/hints.py`

当前实现表明 `batch.export_options` 是 `ship="now"`、priority 45、在 `batch_open` 后退休的全局
discovery hint。按该已发布合同：

1. 精确队列测试在 `chart.custom_action_slot` 后加入 `batch.export_options`；
2. 增加它在 `batch_open` discovered 后不再出现的断言；
3. 不通过把 hint 改成 `ship="later"` 或无条件过滤来清红。

如果产品负责人希望 Batch hint 只在 Batch surface 出现，那是新的 UX 决策，必须单独改 HintState/scope
合同，不在本清红任务里暗改。

### Task B3 — Analyzer handoff 测试跟随 progress contract

**文件：**

- `tests/acquisition_ui/test_review_handoff.py`

步骤：

1. mock `_load_one` 接受 `progress_callback`；
2. 同时记录路径和 callback，断言路径对 `str`/`Path` 均正确、callback 可调用；
3. 保持产品 `load_file → _open_data_paths → _load_one` 路径不变；不为旧 mock 降级产品 API。

### Task B4 — 帮助截图测试在 clean checkout 中可复现

**文件：**

- `tests/test_gen_help_screenshots.py`
- 必要时 `tools/gen_help_screenshots.py`

不提交真实/大体积/可能受限的 `testdoc` 数据。采用确定策略：

1. 单元测试固定 `IMPORT_SAMPLES` 的格式与配置合同；
2. 用 monkeypatch 的不存在路径断言截图工具 fail-fast，并列出所有缺失样本；
3. 用小型临时文件或 fake loader 覆盖“路径存在时进入导入流程”，而不是依赖开发机私有样本；
4. 真正生成帮助截图仍允许要求 operator 提供 `testdoc`，但默认 pytest 不因私有样本缺失而红。

**Gate：** 从 `git archive HEAD` 创建的干净目录中，该测试必须通过。

### Task B5 — 发布版本标签与 Windows 包装器同步

**文件：**

- `tools/run_windows_exe.bat`
- `tests/test_windows_build_script.py`
- `tests/test_packaging_imports.py`

步骤：

1. 将运行包装器默认值更新为 `TraceLab7.9.4`；仍允许第一个参数覆盖 AppName。
2. `test_windows_run_built_exe_wrapper_pauses_after_exit` 增加当前版本断言。
3. `tests/test_packaging_imports.py` 不再硬编码 `TraceLab7.6.spec`：
   - 要么从当前 `APP_VERSION` 派生 build artifact 名；
   - 要么在 spec 缺失时维持“build artifact，先运行 builder”的明确 skip；
   - 不提交本机生成的 `.spec`。
4. 搜索发布表面，确认不存在非历史文档中的活动 `TraceLab7.6` 路径。

### Task B6 — `diff-check` 清理

**文件：**

- `docs/analyzer/verify/main-window-state-baseline.txt`
- `docs/analyzer/verify/ui-splits-baseline-ui.txt`
- `mf4_analyzer/batch.py`

只做机械清理：删除尾随空白与多余 EOF 空行，不改 snapshot 的可见文字、失败 nodeid 或产品逻辑。

执行：

```bash
git diff --check b886a30e338514df31da5fe4874e992f5be110eb..HEAD
git diff --check 4df9d603eb5ed09e94b9e2c1900e2a7747b9f7df..HEAD
```

两条都必须无输出、exit 0。

### Task B7 — 清红聚焦门

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_batch_runner_thread.py \
  tests/ui/test_hint_nudges.py \
  tests/acquisition_ui/test_review_handoff.py \
  tests/test_gen_help_screenshots.py \
  tests/test_windows_build_script.py \
  tests/test_packaging_imports.py

PYTHONPATH=. .venv/bin/python tools/windows_runtime_dependencies.py \
  --verify --requirements requirements.txt \
  --build-script tools/build_windows_folder.ps1 \
  --build-script tools/build_windows_folder_lite.ps1
```

### Task B8 — 源码最终门

在干净实施 checkout 中连续运行两次默认全量，不能拆分：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q
```

要求：

- 两次均正常退出并到最终汇总；
- `failed=0`；允许按仓库默认 marker 出现明确 skipped/deselected；
- 无 Qt event-loop exception、Fatal Python error、hang；
- 第二次必须是新的 Python 进程，验证 teardown 不依赖进程首次状态。

再从 Git archive/干净 worktree 运行至少：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_gen_help_screenshots.py \
  tests/test_windows_build_script.py \
  tests/test_packaging_imports.py
```

**Gate B / SOURCE GO：** 全量两次零失败、clean-checkout 聚焦门通过、两条 diff-check 通过。

---

## Phase C — macOS Cocoa 前台验收

### Task C0 — 真实前台环境确认

必须在已登录、未锁屏、窗口可见的 macOS 桌面运行。记录：

- `sw_vers`、机器架构、屏幕分辨率与 DPR；
- Python/PyQt/Qt/pyqtgraph 版本；
- `QApplication.platformName() == "cocoa"`；
- 最终源提交 SHA；
- 使用的真实输入文件路径与 SHA-256。

禁止把 `QT_QPA_PLATFORM=offscreen`、`widget.grab()` 单独结果或后台无窗口运行写成 Cocoa 前台通过。

### Task C1 — Cocoa 自动化真实窗口矩阵

运行现有探针：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. \
  .venv/bin/python scripts/batch_qt_foreground_heartbeat.py \
  --source testdoc/X04C_Ripple.mf4 \
  --output-dir .state/release-acceptance/macos/gate45

TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. \
  .venv/bin/python scripts/focus_routing_cocoa_smoke.py

TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. \
  .venv/bin/python scripts/per_pane_controls_cocoa_smoke.py
```

heartbeat 必须：

- 实际 platform 为 cocoa；
- 50 ms heartbeat 的 max gap ≤ 200 ms；
- 真实 `BatchRunnerThread` 产生至少 20 个有效 PNG；
- 无 crash、无超时、无残留 worker/thread；
- JSON 和 PNG 都位于本轮唯一目录，不能复用旧结果。

### Task C2 — 前台主应用发布路径

用真实启动入口：

```bash
PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"
```

在 1080×760 与 1440×900 两种窗口尺寸覆盖：

1. 启动、关闭、再次启动；
2. 导入至少 CSV + MF4/项目支持的真实测量文件；
3. Time overlay/subplot、双 View focus、缩放/恢复；
4. FFT、FFT-vs-Time、Order/Order-time 的计算与模式切换；
5. Batch 打开、配置、metadata preview、代表预览、运行、输出目录；
6. 帮助页、QuickRef、右键菜单、tooltip/popover；
7. 关闭分析窗口、Batch、主窗口后无 Python 崩溃报告。

证据采用自动截图/接触表集中比对，不要求逐张人工浏览。每个尺寸至少保留：

- 主 Time/分屏；
- FFT；
- 两类 heatmap；
- Batch 配置和最终图；
- popup/tooltip 四角；
- 关闭前最终稳定状态。

检查文字裁切、中文缺字、轴边界、圆角矩形底、焦点框、tooltip backing、窗口溢出。

### Task C3 — macOS 结果报告

写入：

`docs/analyzer/reviews/2026-08-07-qt-gate-and-cross-platform-release-acceptance.md`

先填写 macOS 段，包含命令、退出码、JSON、截图绝对路径、失败/通过项。任一核心路径 FAIL，
状态保持 `MACOS NO-GO`，修复后必须重跑受影响的 offscreen 门和完整 Cocoa 矩阵。

**Gate C / MACOS GO：** 自动探针和主应用矩阵全通过，无 crash、无明显 UI blocker。

---

## Phase D — Windows 冻结包发布验收

### Task D0 — Windows 主机与源码一致性

必须使用真实交互式 Windows 10/11 x64 桌面。记录：

- Windows build、Python bitness、屏幕/DPI；
- Git SHA，必须与 `SOURCE GO`、`MACOS GO` 的最终 SHA 完全一致；
- 构建前 `git status --short --branch`；
- PyInstaller、PyQt、Qt、pyqtgraph 版本。

Windows checkout 若不是同一 SHA，停止；不得用旧 `dist/` 继续验收。

### Task D1 — Windows 源码/打包合同预检

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_windows_build_script.py `
  tests/test_windows_runtime_dependencies.py `
  tests/test_windows_runtime_verifier.py `
  tests/test_native_import_boundaries.py `
  tests/test_acquisition_runtime_smoke.py `
  tests/test_importer_runtime_smoke.py `
  tests/test_frozen_batch_render_smoke.py `
  tests/test_frozen_batch_acceptance.py
```

确认解释器路径真实存在；所有测试通过才允许构建。

### Task D2 — 新构建默认 windowed Full 包

```powershell
$env:PIP_DEFAULT_TIMEOUT='60'
$env:PIP_RETRIES='10'
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1
```

要求：

- 不带 `-Console`、`-KeepPrevious`；
- 输出为 `dist\TraceLab7.9.4\TraceLab7.9.4.exe`；
- PyInstaller exit 0，`qwindows.dll`/`qoffscreen.dll` 存在；
- 构建结束后的 offscreen/windows frozen render smoke 均为 fresh PASS；
- `packaged-runtime-smoke.json` 为 fresh、`ok=true`、`frozen=true`，命令路径指向该 EXE；
- 记录 EXE SHA-256 和整个 onedir 文件数/字节数。

网络 vendoring 失败仍是 Gate FAIL；只允许在确认是传输错误后用上面的 bounded retry 重跑，
不得松 pin 或接受旧 smoke JSON。

### Task D3 — 新构建默认 windowed Lite 包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_folder_lite.ps1
.\.venv-build-win\Scripts\python.exe tools\verify_lite_importer_runtime.py `
  --exe dist\TraceLabAnalyzer7.9.4\TraceLabAnalyzer7.9.4.exe
```

要求：

- 不带 `-Console`、`-KeepPrevious`；
- frozen offscreen/windows render smoke fresh PASS；
- legacy MAT、MAT v7.3/HDF5、WAV、MP4 audio 四类 importer smoke 全部通过；
- acquisition 包与 pyxcp/pya2l 不进入 Lite bundle；
- 记录 EXE SHA-256、onedir 文件数/字节数。

### Task D4 — 冻结 Batch 真实产物验收

对 Full 和 Lite 的生产 windowed EXE 各运行一次：

```powershell
<EXE> --frozen-batch-acceptance `
  --batch-source <source-1> `
  --batch-source <source-2> `
  --batch-source <source-3> `
  --output-dir <new-empty-output-dir> `
  --json <new-result-json> `
  --frozen-smoke-json <same-package-frozen-smoke-json>
```

三个输入必须含 acceptance contract 所需通道，输出目录必须新建且为空。验收必须证明：

- `sys.frozen`、canonical EXE 路径和 SHA 与同包 smoke JSON 一致；
- CSV/PNG/manifest 是唯一、真实、位于请求目录的物理文件；
- 图像不是空白，中文/刻度/colorbar 证据通过；
- source/result/smoke/EXE 路径无 alias；
- 不存在额外 auto-numbered 或上次运行遗留文件。

### Task D5 — Windows 真实桌面前台矩阵

在 100%、150% DPI（如目标客户使用 200%，再增加 200%）分别启动 Full 和 Lite：

1. 必须直接双击或运行默认 windowed EXE；Console 包只能诊断，不能作为 PASS；
2. 覆盖 macOS Task C2 的 Analyzer/Batch 主路径；
3. Full 打开 Cockpit，验证无硬件时是可解释的 unavailable 状态，不发生 0xC0000005；
4. Lite 打开采集入口，验证明确显示“分析版不含采集”，主 Analyzer 不退出；
5. 运行 `scripts/probe_signal_picker_popup_shell.py`，使用 topmost host、frameGeometry 和真实
   `QScreen.grabWindow(0)` 证据检查 popup 四角；
6. 检查 CJK、缩放、菜单、tooltip、窗口最小尺寸、圆角、轴标题、热力图、关闭重启；
7. 查看 Windows Event Viewer/可靠性记录，确认本轮没有 application error/access violation。

每个包/DPI 组合保留全桌面截图、关键 crop、平台/Qt/DPI/geometry JSON。任何截图必须绑定对应
EXE SHA，不能用源码窗口截图替代冻结包。

### Task D6 — Windows 与最终 Release 判定

将 Windows Full/Lite 的命令、JSON、截图、EXE SHA、目录清单和 GO/NO-GO 追加到 Task C3 的同一
验收报告。报告明确保留：

- Vector/ECU 实车 bench：`NOT IN SCOPE / UNKNOWN`；
- Windows source tests：PASS/FAIL；
- Windows Full frozen：PASS/FAIL；
- Windows Lite frozen：PASS/FAIL；
- Windows foreground：PASS/FAIL。

**Gate D：** Full 与 Lite 的新 windowed 包、冻结 smoke、真实产物和真实桌面矩阵全部 PASS。

---

## 5. 最终收口与提交顺序

建议提交保持可审查边界：

1. `fix(test): eliminate Qt LabelItem lifecycle segfault`
2. `test(ui): reconcile async preview and current hint/load contracts`
3. `test(help): make screenshot checks clean-checkout reproducible`
4. `chore(release): sync Windows launch labels and repository hygiene`
5. `docs(release): record macOS and Windows acceptance evidence`

每个提交前：

```bash
git status --short
git diff --check
git diff --stat
/usr/bin/python3 scripts/lessons/check.py --status
```

最终再执行：

```bash
git diff --check b886a30e338514df31da5fe4874e992f5be110eb..HEAD
git diff --check 4df9d603eb5ed09e94b9e2c1900e2a7747b9f7df..HEAD
git diff --name-status 4df9d603eb5ed09e94b9e2c1900e2a7747b9f7df..HEAD
```

确认 diff 中没有 HDF 兼容实现、用户数据、`testdoc` 真数据、生成 spec、`dist/`、build tree、
临时 JSON/PNG 或无关格式化。

## 6. 停止条件

出现以下任一情况立即停在当前 Gate，不继续向后包装结论：

- root cause 未明确但通过 skip/order/ignore 让 segfault 消失；
- 默认全量没有正常到最终汇总或仍有失败；
- macOS 实际 platform 不是 cocoa；
- Windows 构建不是同一最终 SHA、不是 fresh windowed onedir；
- smoke JSON 缺失、过期、路径/SHA 不匹配；
- 只有 Console/offscreen/源码证据，没有真实冻结包前台证据；
- 任一环境出现 Python crash、EXC_BAD_ACCESS、0xC0000005、明显 UI blocker；
- 为清红需要进入本计划明确排除的旧 HDF 兼容范围。

上述情况的结论只能是 `BLOCKED/NO-GO`，记录证据后回到对应 Phase 修复。
