# 批处理 Phase 1：正确性与可复现性 Implementation Plan

> 执行规则：TDD-first；每个 task 先得到可解释的红测，再做最小实现。不得撤销工作区中无关的 `.playwright-cli` 文件。

> 执行状态：**COMPLETE（2026-07-28）**。Phase gate 独立复核为 core 175 passed、batch UI 110 passed、compute-progress 25 passed；`git diff --check` 与相关模块 `compileall` 均通过。

## Goal

建立一个完整、可验证的 batch recipe；消除 stale current state、静默参数损失、Qt worker 渲染、输出覆盖与极端图像范围问题，为 Phase 2/3 提供稳定接口。

## Ownership

| Lane | 建议 agent | 独占文件 |
| --- | --- | --- |
| P1-A recipe/UI | `pyqt-ui-engineer` | `ui/drawers/batch/sheet.py`、`method_buttons.py`、`input_panel.py`、`ui/main_window/window.py` 与对应 UI tests；不改数值算法 |
| P1-B runner/numeric | `signal-processing-expert` | `batch.py` 数值、校验、dB/extent 与 `tests/test_batch_runner.py`；所有数值改动 TDD-first |
| P1-C renderer/IO boundary | `refactor-architect` 或 worker | 新 renderer/recipe/atomic-output 模块与边界测试；不重设计算法 |

共享 dataclass/schema 由主 agent 集成，agents 不得同时编辑同一文件。

## Task 0 — Baseline and literal checklist

**Files:** read-only baseline.

- [x] 记录 `git status --short --branch`，保留无关未跟踪文件。
- [x] 跑现有 batch focused suite，保存通过数。
- [x] 建立 C1–C10 checklist；grep `db_reference_mode`、`nfft_mode`、`t_win_s`、`manual_rpm`、`samples_per_rev`、`_last_batch_preset`、`QApplication`。

## Task 1 — Normalized recipe contract

**Files:**

- Create: `mf4_analyzer/batch_recipe.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/batch_preset_io.py`
- Tests: `tests/test_batch_preset_io.py`、new `tests/test_batch_recipe.py`

- [x] 写参数化红测：四方法的完整 params normalize/JSON round-trip 等价。
- [x] 定义 method schema、公共字段、类型规范化、未知字段保留策略和 `recipe_fingerprint()`。
- [x] 把 legacy dB migration 纳入 normalize，但保持 value-without-mode → Manual。
- [x] 为旧 JSON 补迁移，不因新字段提升版本就拒绝旧文件。
- [x] 绿测并运行 `git diff --check`。

## Task 2 — Current analysis → BatchSheet parity

**Files:**

- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_fft_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Tests: `tests/ui/test_batch_smoke.py`、`tests/ui/test_batch_method_buttons.py`、new focused parity tests

- [x] 先构造 stale `_last_batch_preset` 与当前 Inspector 不同的红测。
- [x] 为 FFT/FFT-time/Order/time 建完整 current recipe fixture，执行 `apply_preset()` + `get_preset()`，断言规范化等价。
- [x] 取消 `_last_batch_preset` 的权威地位；打开时现场构造当前 pane-local recipe。
- [x] BatchSheet 保存未映射字段；控件字段只覆盖用户实际编辑的字段，不让默认值覆盖 hidden intent。
- [x] current-single 在未扩大 scope 时保留精确 source；时域支持精确 pair 列表并兼容旧 cartesian preset。

## Task 3 — Preflight and runner validation

**Files:**

- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Tests: runner + input/output/sheet UI tests

- [x] 红测 malformed、reversed、NaN time ranges；UI 显示 invalid 而非返回 `None`。
- [x] 红测 Fs≤0、手动轴 min≥max、固定 NFFT 非法、频率超 Nyquist、Order RPM 配置缺失。
- [x] 实现纯 `validate_recipe()` 与 per-file `validate_task()`；错误携带 field/code/message。
- [x] 保留 filter Nyquist clamp message 到 `BatchItemResult.warnings/effective_params`。
- [x] 扩展 Y spin 范围以允许负 dB/线性值，不用通用 0 下限。

## Task 4 — Stable output identity and atomic writes

**Files:**

- Create: `mf4_analyzer/batch_output.py`
- Modify: `mf4_analyzer/batch.py`
- Tests: `tests/test_batch_runner.py`、new `tests/test_batch_output.py`

- [x] 红测同 basename/同 signal/不同目录和不同 group 不碰撞。
- [x] 实现 Unicode-safe slug、source/group identity、task hash 和默认 `auto_number`。
- [x] 实现同目录临时文件 + `os.replace()`；异常路径清理自己的临时文件。
- [x] `BatchItemResult` 记录 task/source/group/effective params/warnings。

## Task 5 — Remove Qt from worker rendering

**Files:**

- Create: `mf4_analyzer/batch_render.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: image assertions in `tests/test_batch_runner.py`

- [x] 先加结构红测，禁止 batch worker production path import PyQt/pyqtgraph 或创建 QApplication。
- [x] 抽取不可变 render payload/options，使用 Matplotlib Figure + Agg 输出 PNG。
- [x] 保持 Phase 1 默认尺寸 1120×630，保持线性数据导出不变。
- [x] 复用 dB formatter；零/非有限数据使用有限 floor 与 robust range。
- [x] heatmap 由 coverage edges 构造 extent；单 frame/bin 仍有非零面积。

## Task 6 — Cancellation/event invariants

**Files:**

- Modify: `mf4_analyzer/batch.py`
- Modify: `tests/test_batch_runner.py`
- Modify if needed: `tests/ui/test_batch_runner_thread.py`

- [x] 对 load/preprocess/compute/write/render 阶段逐个加 cancellation 红测。
- [x] 每阶段前后检查 token；取消后不进入下一次写入。
- [x] 断言每个 started task 恰好一个 terminal event，run 恰好一个 `run_finished`。

## Task 7 — Phase gate

- [x] 跑 Phase 1 spec 的 focused command。
- [x] 跑所有 `tests/*batch*` 与 `tests/ui/test_batch_*`。
- [x] 执行真实写盘 collision/atomic probe 和两类极端图像 probe。
- [x] `rg` 确认 GUI-free boundary；`git diff --check`。
- [x] 主 agent 对照 C1–C10 逐项给出 PASS；只有全 PASS 才进入 Phase 2。

## Execution Record

- Core/recipe/renderer/output/validation：`175 passed in 9.77s`。
- Batch UI：`110 passed in 19.60s`。
- Compute-progress integration：`25 passed in 12.96s`。
- Phase 1 总独立门禁：310 passed；所有命令 exit 0。
- C1–C10：全部 PASS；关键证据覆盖完整 recipe round-trip、实时 pane preset、严格 preflight、稳定输出身份与原子写入、无 Qt worker renderer、极端 dB/heatmap、取消事件不变量。
- 工作区纪律：未修改/删除原有 `.playwright-cli` 未跟踪文件。

## Stop Conditions

- recipe 仍有字段 round-trip 不等价：停止 Phase 2 UI 扩展。
- renderer 仍在 QThread 创建 GUI 对象：停止 Phase 3 导出格式扩展。
- 真实磁盘碰撞 probe 会覆盖文件：不得进入 manifest/resume 实施。
