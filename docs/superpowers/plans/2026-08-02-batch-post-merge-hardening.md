# 批处理合包加固实施计划（Qt 渲染 + 紧凑 UI）

**日期：** 2026-08-02

**状态：** READY FOR IMPLEMENTATION

**设计：** `docs/superpowers/specs/2026-08-02-batch-post-merge-hardening-design.md`

**审查：** `docs/superpowers/reports/2026-08-02-batch-qt-and-compact-ui-review.md`

**基线：** `main` @ `78e091a725c9de0d0751fcf173819aab4b3a3e3e`

## 执行原则

- 严格从固定基线新建 `codex/batch-post-merge-hardening`，不得在旧 compact-UI 或 Qt-render feature branch 上继续叠加。
- 每项行为变更先增加能在 `78e091a` 失败的定向测试，再修改实现。
- A、B、C 各自通过 gate 后再进入下一批；Cocoa 前台只在源码和 offscreen gate 后执行。
- 保存每次测试的命令、导入路径、退出码和通过/失败数字；不得用历史数字代替本轮结果。
- 保留用户未跟踪文件和无关 dirty changes；Git 操作只触及本计划明确列出的文件。

## Task 0 — 建立可复核基线

1. 从 `main@78e091a` 新建 `codex/batch-post-merge-hardening`。
2. 记录：
   - `git status --short --branch`
   - `git show --name-status --oneline 78e091a`
   - `git merge-base --is-ancestor 020a251 78e091a`
   - `git merge-base --is-ancestor 85054ce 78e091a`
3. 使用计划指定的 Python 解释器打印 `mf4_analyzer.__file__`，必须位于实施 worktree。
4. 收集聚焦测试和 `tests/ui` nodeid；保存 `78e091a` 基线失败 nodeid，不先修无关 split-pane 失败。
5. 把本 spec/plan/report 纳入实施分支的文档范围。

**Gate 0：** HEAD、导入路径、dirty scope 和基线 nodeid 均已记录；否则停止。

## Batch A — 合并契约与 UI 状态机

### Task 1 — A1 固定线宽合同

**文件：**

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `tests/ui/test_batch_output_panel.py`
- `tests/ui/test_batch_smoke.py`

**步骤：**

1. 将现有 canonical-line-width 测试改成 1.5，并新增旧配方 `image_line_width=3.25` 仍输出 1.5 的红测。
2. 确认红测在 `78e091a` 因返回 1.0 失败。
3. `get_outputs()` 固定写 1.5；不读取 `_combo_image_line_width.currentData()`。
4. 运行两个定向测试文件。

### Task 2 — A2 独立幅值单位行

**文件：**

- `mf4_analyzer/ui/inspector_sections/_helpers.py`
- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `tests/ui/test_batch_output_panel.py`
- `tests/ui/test_batch_compact_contract.py`
- `tools/render_batch_compact_ui.py`

**步骤：**

1. 写 FFT 单位控件可见、Linear round-trip、跨方法状态恢复和 Time 隐藏的红测。
2. 为 `_make_axis_settings_group` 增加默认兼容的独立单位行构造选项；Inspector 原调用结果不变。
3. Batch OutputPanel 使用稳定独立行；Z 行只随 heatmap 显隐。
4. 更新 render probe，生成 `fft-linear.png` 和对应 geometry JSON。

### Task 3 — A3 用户点击幂等

**文件：**

- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- `tests/ui/test_batch_method_buttons.py`
- `tests/ui/test_batch_smoke.py`

**步骤：**

1. 红测“预设已应用 → 用户再次点击当前方法 → 无 methodChanged、预设仍选中”。
2. 红测同方法 `BatchSheet.apply_preset()` 仍完整刷新，稀疏 full recipe 恢复 schema 默认。
3. 只在 button clicked 路由拦截当前方法；程序化 `set_method()` 保持刷新语义。
4. 保持 partial `apply_params({})` 为 no-op。

### Task 4 — A4 方法切换时序

**文件：**

- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `tests/ui/test_batch_smoke.py`

**步骤：**

1. 用 signal spy 记录 FFT 手动 Hz → Time 的第一次 status/footer 投影，先得到失败证据。
2. 按 Spec A4 顺序重排 `methodChanged` consumers。
3. 断言单次切换内无旧轴 blocked 摘要，且 input/output/recipe method 一致。

### Gate A

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_smoke.py
```

打开 `fft-linear.png` 和 `gui-default-linewidth.png`；确认控件可见、文字不裁切、Line width 为 1.5。Gate A 失败不得进入 Batch B。

## Batch B — 渲染鲁棒性与导入边界

### Task 5 — B1 subplot 单位标签

**文件：**

- `mf4_analyzer/batch_render_qt/_builder.py`
- `tests/test_batch_render_qt.py`

**步骤：**

1. 新增不同 unit 的双 panel 结构红测，证明 title 存在时 unit 仍应存在。
2. 删除清空左轴 label 的 callback，保留 panel title 定位。
3. 覆盖左轴单 unit 和双 Y unit，生成 `subplot-units.png` 并目视。

### Task 6 — B2 下沉共享 helper 与收窄降级

**文件：**

- `mf4_analyzer/qt_chart_fonts.py`（新建）
- `mf4_analyzer/render_profile.py`（新建）
- `mf4_analyzer/qt_plot_helpers.py`（新建）
- `mf4_analyzer/ui/pg_canvas/fonts.py`
- `mf4_analyzer/ui/pg_canvas/render_profile.py`
- `mf4_analyzer/ui/pg_canvas/_shared.py`
- `mf4_analyzer/batch_render_qt/_fonts.py`
- `mf4_analyzer/batch_render_qt/_builder.py`
- `mf4_analyzer/batch.py`
- `tests/test_batch_render_import_boundary.py`（新建）
- `tests/test_batch_runner.py`

**步骤：**

1. 先写 subprocess import guard，确认 `78e091a` 会加载 `mf4_analyzer.ui.main_window`。
2. 下沉三类 helper；旧 UI 模块仅兼容 re-export，既有 UI import 无需批量改写。
3. `batch_render_qt` 改为只 import 顶层 neutral helper 和 `ui_kit.ticks_math`。
4. 在 backend probe 处按异常 `name` 识别允许的缺失模块；不在 writer/render 阶段捕获降级。
5. 红测 UI/internal ImportError 上抛、writer ImportError 原子回滚、data+image backend 缺失降级、image-only backend 缺失失败。
6. subprocess 再次确认 `mf4_analyzer.ui` 与 `ui.main_window` 未加载。

### Task 7 — B3 空 QImage

**文件：**

- `mf4_analyzer/batch_render_qt/_export.py`
- `tests/test_batch_render_qt.py`

**步骤：**

1. 用 null `QImage()` 写 `save_png` 红测。
2. 在创建后与保存前分别 fail-fast。
3. 断言目标文件不存在；正常 exact-size/DPI 测试保持绿色。

### Gate B

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly \
  tests/test_batch_render_qt.py \
  tests/test_batch_render_qt_heatmap.py \
  tests/test_batch_render_qt_display_envelope.py \
  tests/test_batch_renderer.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_batch_runner.py
```

另运行源码 grep：

```bash
rg -n 'mf4_analyzer\.ui' mf4_analyzer/batch_render_qt
```

预期无命中。Gate B 失败不得进入仓库/前台收口。

## Batch C — 生命周期、死代码与仓库卫生

### Task 8 — C1 DbReference lifecycle

**文件：**

- `mf4_analyzer/ui/db_reference_dialog.py`
- `tests/ui/test_db_reference_controls.py`

**步骤：**

1. 构造已删除 `ScientificReferenceSpinBox` wrapper，直接调用 delegate geometry path，得到 `RuntimeError` 红测。
2. 加 `sip.isdeleted` 前置与窄 RuntimeError 二次确认。
3. 覆盖 dialog 立即关闭、`deleteLater()`、`processEvents()`。
4. 先跑专项，再在 Gate C 跑 `tests/ui` 两次。

### Task 9 — C2 删除隐藏 resume/retry UI

**文件：**

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `tests/ui/test_batch_output_panel.py`
- `tests/ui/test_batch_smoke.py`
- `tests/ui/test_batch_runner_thread.py`
- `tests/test_batch_runner.py`

**步骤：**

1. 先锁定 Runner manifest/resume/retry 回归，证明底层能力仍可用。
2. 删除隐藏 buttons、signals、combo 与仅供这些 signals 使用的 sheet handlers。
3. 更新 GUI 测试为“无恢复入口、旧 policy 迁移到 none”。
4. 重跑 Runner resume 与 GUI compact contract。

### Task 10 — C3 根目录 planning 文件取消跟踪

**文件：**

- `.gitignore`
- Git index 中的 `/findings.md`、`/progress.md`、`/task_plan.md`
- `.state/planning-archive/2026-08-02/`（本地、不得 stage）

**步骤：**

1. 复制三文件到 archive，记录源/副本 hash。
2. 仅从 Git index 移除根目录三文件，确认工作区副本仍存在。
3. 加精确根路径 ignore，不添加泛化 `*.md` 规则。
4. `git status --ignored --short` 确认三文件为 ignored，archive 未被 stage。

### Gate C

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly \
  tests/ui/test_db_reference_controls.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_runner_thread.py \
  tests/test_batch_runner.py

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly tests/ui
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly tests/ui
```

两次 UI 全量必须完成到 100%，不得出现 Fatal Python error 或 exit 139。失败 nodeid 与 Gate 0 比较；不得把已有 split-pane 失败误报为本轮新增。

## Batch D — 合包 Cocoa 前台与收口

### Task 11 — C4 前台矩阵

1. 使用实施分支真实 TraceLab 和生产 QSS 启动 macOS Cocoa 前台。
2. 在 1080×760、1440×900 覆盖：
   - Time；
   - FFT dB；
   - FFT Linear；
   - FFT-vs-Time；
   - Order；
   - file manager modal；
   - running 与 completed footer。
3. 每个状态记录窗口尺寸、方法、关键控件可见性和截图绝对路径。
4. 重点检查幅值单位行、dB 摘要、1080 信号选择器、三栏滚动、footer 和输出摘要。
5. 任一 FAIL 回到对应 Task 修复并重跑受影响 offscreen gate 和完整 Cocoa 矩阵。
6. 写 `docs/superpowers/reports/2026-08-02-batch-compact-ui-cocoa-acceptance.md`。

**Gate D：** 全项 PASS 才能把合包 macOS 状态改为 GO；若报告存在 gap，保持 NO-GO。

## Task 12 — 最终回归、review 与记录

1. 运行 Spec §5 的完整 A/B/C 聚焦矩阵。
2. 运行 `git diff --check`、使用 `PYTHONPYCACHEPREFIX=/tmp/tracelab-hardening-pyc` 对本轮 Python 文件执行 `py_compile`，再运行 lessons gate。
3. 比较 Gate 0 与最终失败 nodeid，列出新增/消失/同族集合。
4. 检查 `git diff --name-status 78e091a...HEAD`，确保没有 SVG/PDF/matplotlib 恢复、无关 split-pane 修改或用户文件删除。
5. 将以下内容追加到外部 review 报告“执行记录”：
   - 实施提交 SHA；
   - 每个 gate 的命令与数字；
   - 三张固定探针路径；
   - Cocoa 报告结论；
   - macOS 与 Windows 最终门禁。
6. 做一次独立短 review；P0/P1 未清零不得合并。

## 提交建议

按 gate 保持可审查提交，不强制逐 Task 碎提交：

1. `fix(batch-ui): align compact output and method state contracts`（Batch A）
2. `refactor(batch-render): isolate shared Qt render dependencies`（Batch B）
3. `fix(ui): harden delegate lifecycle and remove hidden batch recovery UI`（C1/C2）
4. `chore(repo): stop tracking local planning state`（C3）
5. `docs(batch): record hardening and Cocoa acceptance evidence`（Batch D/收口）

每次提交前只 stage 本批文件；不得顺带纳入 Playwright 日志、截图、其它 worktree 状态或无关用户改动。
