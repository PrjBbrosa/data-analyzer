# 批处理合包加固设计（Qt 渲染 + 紧凑 UI）

**日期：** 2026-08-02

**状态：** READY FOR IMPLEMENTATION

**依据：** `docs/superpowers/reports/2026-08-02-batch-qt-and-compact-ui-review.md`

**实施计划：** `docs/superpowers/plans/2026-08-02-batch-post-merge-hardening.md`

**唯一基线：** `main` @ `78e091a725c9de0d0751fcf173819aab4b3a3e3e`

**实施分支：** 从该基线新建 `codex/batch-post-merge-hardening`

## 1. 目标与当前门禁

本轮修复合并 `020a251`（Batch Qt 渲染）与 `85054ce`（紧凑 Batch UI）后暴露的契约、状态机、导入边界和 Qt lifecycle 问题，并完成合包后的 macOS Cocoa 前台验收。

三个门禁必须分开表述：

| 门禁 | 当前状态 | 本 spec 的责任 |
|---|---|---|
| Qt Batch renderer macOS Gate 4.5 | **PASS** | 修复不得造成回归 |
| 合并后紧凑 Batch UI Cocoa 验收 | **UNVERIFIED** | 本轮 C4 必须执行；只有 PASS 才能给合包 macOS GO |
| Windows full/lite onedir | **NO-GO** | 本轮不执行，继续作为独立发布门禁 |

本 spec 完成不自动改变 Windows 状态。若 C4 仅记录 gap，代码和文档可以收口，但合包 macOS 发布状态仍为 **NO-GO**。

## 2. 已冻结的产品与实现决策

以下不再留给实现阶段二选一：

| ID | 决策 |
|---|---|
| P1 | 紧凑 UI 继续只显示 XLSX 与 PNG 开关；背景、尺寸、DPI、线宽保持隐藏。GUI 权威输出固定为 PNG 1920×1080、144 DPI、白底、1.5 px、自动编号。 |
| P2 | `OutputPanel.get_outputs()` 直接写固定 `image_line_width=1.5`；禁止读取隐藏 legacy combo。导入旧配方不得把 2.0/3.25 等历史值带回 GUI 权威输出。 |
| P3 | FFT、FFT-vs-Time、Order 均使用同一个、稳定存在的独立“幅值单位”行；Time 隐藏该行。Z 色阶行只负责 heatmap 色阶，不再拥有单位控件。 |
| P4 | 用户再次点击当前分析方法是幂等操作，不发 `methodChanged`；程序化 `set_method()` / 完整配方应用仍保留刷新下游状态的能力。 |
| P5 | 隐藏的 resume/retry UI 控件、信号和 sheet handler 删除；`BatchRunner`、manifest、CLI/运行时 resume 能力不删除。GUI 配方继续固定 `resume_policy="none"`。 |
| P6 | Batch renderer 共用的字体族、render-profile、grid/native-auto helper 下沉到不经过 `mf4_analyzer.ui` 的模块；Batch 不通过修改 `ui/__init__.py` 懒加载来掩盖依赖。 |
| P7 | 根目录 `findings.md`、`progress.md`、`task_plan.md` 只取消 Git 跟踪并加入 ignore；实施前先复制到 `.state/planning-archive/2026-08-02/`，不得直接删除用户历史。 |

## 3. 范围

### A. 合并契约与 UI 状态机（P1）

#### A1. 固定 GUI 线宽为 1.5（D1）

- 修改 `mf4_analyzer/ui/drawers/batch/output_panel.py::OutputPanel.get_outputs`，固定 `image_line_width=1.5`。
- `apply_outputs()` 可读取旧配方以完成兼容迁移，但不得改变 GUI 权威固定值。
- 更新 `tests/ui/test_batch_output_panel.py`、`tests/ui/test_batch_smoke.py` 中仍断言 1.0 的契约。
- 验收：GUI preset、CLI 默认配方与 `BatchRenderOptions` 都为 1.5；旧配方带 `3.25` 后 GUI 仍返回 1.5。

#### A2. 恢复 FFT dB ↔ Linear（D2）

- 扩展 `mf4_analyzer/ui/inspector_sections/_helpers.py::_make_axis_settings_group`，增加默认保持现状的可选参数，使 Batch OutputPanel 可以把 `combo_amp_unit` 构造在独立辅助行。
- `OutputPanel` 选择独立“幅值单位”行：
  - `time`：隐藏；
  - `fft`、`fft_time`、`order_time`：显示；
  - Z 行仅在 `fft_time`、`order_time` 显示。
- 控件实例不得在方法切换时销毁或在两个 layout 间动态搬移。
- `_axis_state_by_method` 继续保存每种方法的 `amplitude_mode`；切换方法后原值可恢复。
- 红测必须证明：FFT 可见单位控件；Linear 后 `axis_params()["amplitude_mode"] == "amplitude"`；切换到 heatmap 再回来仍为 Linear；渲染 facts/轴标签进入线性路径。

#### A3. 只让用户重复点击幂等（D3）

- `MethodButtonGroup` 增加私有 clicked 路由：点击的方法等于 `_current` 时直接返回，不调用 `set_method()`。
- 程序化 `set_method(method)` 保持现有显式刷新语义，包括相同 method；不得以全局 `method == _current: return` 代替 clicked 防护。
- 红测：
  1. 应用内置预设后再次点击当前方法，预设卡与 `preset_state` 不变；
  2. 对同方法调用 `BatchSheet.apply_preset()`，完整配方仍重置稀疏字段和输出/轴状态；
  3. `apply_params({})` 作为增量 patch 仍是 no-op。

#### A4. 方法切换先落状态、后校验（D4）

`BatchSheet` 的 `methodChanged` 消费顺序固定为：

1. `InputPanel.set_method`
2. `OutputPanel.apply_method_defaults`
3. `_on_recipe_method_changed`
4. `_recompute_pipeline_status`

红测从 FFT 手动 Hz 范围切到 Time，捕获第一次 footer/status 投影，禁止短暂 blocked 或复用旧 Hz 轴错误。

### B. 渲染鲁棒性与导入边界（P2）

#### B1. subplot 保留单位标签（D5）

- 删除 `_builder.py` 中“有 panel title 就清空左轴标签”的 callback。
- panel title 与左/右轴单位同时存在；双单位仍走已有双 Y 轴。
- 结构测试直接检查 AxisItem label；PNG 探针使用不同 unit 的上下 panel，人工确认单位不裁切。

#### B2. 切断 Batch renderer 到 `mf4_analyzer.ui` 的导入链（D6）

按以下模块边界实施：

- 字体候选常量下沉到 `mf4_analyzer/qt_chart_fonts.py`，`ui.pg_canvas.fonts` 与 `batch_render_qt._fonts` 共同引用。
- `ui.pg_canvas.render_profile` 的纯 render-profile 模型/分类/桶宽逻辑下沉到 `mf4_analyzer/render_profile.py`；旧模块只做兼容 re-export。
- Batch 使用的 `_hide_native_auto_button` 与 `show_major_grid_left_bottom_only` 下沉到 `mf4_analyzer/qt_plot_helpers.py`；`ui.pg_canvas._shared` 可兼容 re-export。
- Batch ticks 直接依赖无 Analyzer UI 上层副作用的 `mf4_analyzer.ui_kit.ticks_math`。
- `batch_render_qt/**` 禁止 import `mf4_analyzer.ui` 或其子模块。

`BatchRunner._resolve_effective_outputs()` 只在 renderer probe 阶段处理后端缺失：

- 允许降级：缺失 `PyQt5`、`pyqtgraph`、`mf4_analyzer.batch_render` 或 `mf4_analyzer.batch_render_qt...`；
- 必须上抛：`mf4_analyzer.ui...`、普通 `RuntimeError`、`ValueError`、renderer 已导入后的 writer/render 错误；
- data+image 请求可在 probe 前降为 data-only；image-only 仍明确失败；输出 reservation 之后禁止降级。

新增 `tests/test_batch_render_import_boundary.py`，至少覆盖：

1. 导入 `mf4_analyzer.batch_render` 后 `sys.modules` 无 `mf4_analyzer.ui` / `mf4_analyzer.ui.main_window`；
2. 允许的后端缺失遵循现有 data-only 降级合同；
3. 模拟 `ImportError(name="mf4_analyzer.ui.plot_helpers")` 必须上抛；
4. writer-time `ImportError` 继续触发原子回滚，不得降级。

#### B3. 空 QImage 防护（D10）

- `render_scene_image()` 创建 QImage 后和 `save_png()` 写出前均检查 `image.isNull()`。
- 空图抛 `RuntimeError`，不得创建目标文件或父级之外的半成品。
- 正常 PNG 的 exact pixel、DPI、metadata 合同保持不变。

### C. 生命周期、死代码、仓库与验收

#### C1. DbReference delegate lifecycle（D7）

D7 是本合包暴露但早于 Qt renderer 分支存在的间歇性 lifecycle 缺陷，不把它归因成 Qt renderer 回归。

- `updateEditorGeometry` 在调用 `setGeometry` 前用 `PyQt5.sip.isdeleted(editor)` 防护。
- 若检查后仍收到 `RuntimeError`，仅当再次确认 editor 已删除时返回；其它 `RuntimeError` 上抛。
- 专项测试直接覆盖已删除 editor wrapper，并覆盖 dialog 打开后立即关闭、`deleteLater()`、`processEvents()`。
- `tests/ui -q -p no:randomly` 连续两次均不得出现 Fatal Python error / SIGSEGV；两次通过是稳定性证据，不替代专项回归。

#### C2. 删除隐藏 resume/retry UI（D8）

- 删除 `OutputPanel` 的隐藏 resume/retry buttons、signals、resume-policy combo 和相关接线。
- 删除 `BatchSheet` 仅由这些隐藏 signals 触发的 handlers。
- 不删除 `BatchRunner`、manifest schema、runtime `resume_manifest` / retry scope 处理。
- 旧配方 `resume_policy="manifest"` 进入紧凑 GUI 后迁移为 `none`，并保持其它输出字段可用。

#### C3. 根目录 planning 文件退出版本控制（D11）

实施步骤固定为：

1. 创建 `.state/planning-archive/2026-08-02/`；
2. 复制根目录三文件到该目录并核对 hash；
3. 对根目录文件执行仅取消跟踪的操作，工作区副本保留；
4. `.gitignore` 加入精确根路径 `/findings.md`、`/progress.md`、`/task_plan.md`；
5. 禁止历史重写，禁止清理其它 `.state` 或 worktree。

#### C4. 合并后紧凑 UI Cocoa 前台验收（D12/D13）

- 使用真实 TraceLab 前台，不以 offscreen/pytest 替代。
- 固定检查 1080×760 与 1440×900，至少覆盖 Time、FFT dB、FFT Linear、FFT-vs-Time、Order、file modal、running/completed。
- 验收 dB 摘要不重复、1080 信号选择器不截断；若缺陷仍在，本轮修复，不记为默认 wontfix。
- 报告写入 `docs/superpowers/reports/2026-08-02-batch-compact-ui-cocoa-acceptance.md`，逐项给 PASS/FAIL 与截图路径。
- 只有该报告全项 PASS，合并后紧凑 UI 才可标记 macOS GO。

## 4. 非目标

- 不恢复 SVG/PDF 或 matplotlib。
- 不恢复高级导出、resume/retry 的可见入口。
- 不执行 Windows full/lite onedir 四组 smoke。
- 不修复与本合包无关的 split-pane 基线失败。
- 不重写 `_builder.py` 架构，不改变 BatchSeries、CSV/XLSX 数值或物理 X 数据。
- 不删除其它分支、worktree、用户生成文件或历史提交。

## 5. 验证矩阵

```bash
# 确认测试读取实施 worktree，而不是其它 checkout
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -c \
  'import mf4_analyzer; print(mf4_analyzer.__file__)'

# A/B/C2 聚焦
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly \
  tests/test_batch_render_qt.py \
  tests/test_batch_render_qt_heatmap.py \
  tests/test_batch_render_qt_display_envelope.py \
  tests/test_batch_renderer.py \
  tests/test_batch_runner.py \
  tests/test_batch_render_import_boundary.py \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_runner_thread.py

# C1 专项与 UI 稳定性
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly \
  tests/ui/test_db_reference_controls.py

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly tests/ui
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -p no:randomly tests/ui

git diff --check
/usr/bin/python3 scripts/lessons/check.py
```

固定视觉探针至少包含：`fft-linear.png`、`subplot-units.png`、`gui-default-linewidth.png`。Cocoa 报告使用单独前台截图，不混入 offscreen 证据。

## 6. 完成定义

- [ ] 从 `78e091a` 建立实施分支，测试导入路径指向该 worktree。
- [ ] A1–A4 红测先失败、实现后全绿。
- [ ] B1–B3 全绿，Batch renderer 导入不执行 `mf4_analyzer.ui`。
- [ ] 允许的 probe 缺失可降级，非允许 ImportError 与 writer 错误不会静默降级。
- [ ] C1 专项全绿，`tests/ui` 连续两次无 SIGSEGV。
- [ ] C2 删除的仅是隐藏 UI，Runner/manifest resume 回归仍全绿。
- [ ] C3 archive hash 一致，根目录三文件不再被 Git 跟踪且本地副本仍存在。
- [ ] 批处理聚焦套件全绿；相对 `78e091a` 无新增批处理失败 nodeid。
- [ ] C4 Cocoa 报告存在；只有全项 PASS 才给合包 macOS GO。
- [ ] Windows 状态仍明确为 NO-GO，未用本轮证据替代 onedir gate。
- [ ] 将提交 SHA、测试数字、视觉证据和剩余 gate 追加到 review 报告“执行记录”。
