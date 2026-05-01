# Plan — Codex Review P2 Cleanup (2026-05-01)

Spec: `docs/superpowers/specs/2026-05-01-codex-p2-cleanup-design.md`
Source review: `docs/code-reviews/2026-05-01-recent-prs-deep-review.md`

2 个 P2 → 2 个 wave，独立 RED→GREEN→codex review gate。

---

## Wave 4 — OrderWorker 死代码清理（P7-D1）

**Expert**: `refactor-architect`（跨方法删除 + 测试文件移除）
**Files in scope**:
- `mf4_analyzer/ui/main_window.py`（删类 + 删方法 + 改注释）
- `tests/ui/test_order_worker.py`（删整个文件）
- 全仓 grep 验证（read-only）

**Steps**:

1. **Audit**：先 `grep -r "OrderWorker\|_dispatch_order_worker\|_on_order_progress\|_on_order_failed\|_on_order_result\|compute_time_order_result" mf4_analyzer/ tests/ docs/`，列出所有命中。docs/lessons-learned 内的引用属历史记录可保留；production / tests 必须清零（除 `_cancel_order_compute` 自身保留）。
2. **删除 production 残留**（`main_window.py`）：
   - `OrderWorker(QThread)` 类整体（约 :81-:160 范围）
   - `_dispatch_order_worker(...)`
   - `_on_order_progress(...)`, `_on_order_failed(...)`, `_on_order_result(...)`
   - 同步清理 stale 注释（:1345-:1357 / :1410-:1421 等提到 OrderWorker / generation tokens 的段落）
3. **简化 `_cancel_order_compute`**：保留 slot signature，body 改为 docstring + `pass`（说明 “forward-looking placeholder for future async COT worker”）。**不**删除该 slot 与 :291 的 connect 链路。
4. **删 test_order_worker.py 整文件**。
5. **再次全仓 grep 验证**：除 docs/lessons-learned 之外**零**命中 deprecated 符号。
6. **跑 `pytest -q`**：预期 488 ± passed（删除 4-5 个 worker 测试），无新 fail。
7. **W4 codex review**：派 codex 看 diff，关注：
   - `OrderContextual.btn_cancel` 的 wire/clicked.connect 是否完整保留
   - `_cancel_order_compute` slot 是否真的还在并正确接到 `cancel_requested` 信号
   - 注释清理彻底
   - 没有 import 残留（`from .main_window import OrderWorker` 等）
8. 通过后进 W5。

**完成标志**：grep 无 deprecated 符号；pytest 全绿；codex VERDICT READY。

---

## Wave 5 — QSS spinbox scope 收敛（P8-O1）

**Expert**: `pyqt-ui-engineer`
**Files in scope**:
- `mf4_analyzer/ui/widgets/compact_spinbox.py`（构造器加 setProperty）
- `mf4_analyzer/ui/inspector_sections.py`（仅 `_no_buttons` helper）
- `mf4_analyzer/ui/drawers/batch/method_buttons.py`（5 处 setButtonSymbols 同步加 setProperty 或改用 helper）
- `mf4_analyzer/ui/style.qss`（selector 改 `[compact="true"]`，清理 Inspector 限定 selector）
- `tests/ui/test_compact_spinbox.py`（NEW，3-4 个测试）
- 现有 inspector spinbox 测试（read-only 验证不破坏）

**Steps**:

1. **RED**：先在 `tests/ui/test_compact_spinbox.py` 写新测试（应当 FAIL）：
   - `test_compact_double_spinbox_sets_compact_property`：构造 CompactDoubleSpinBox，断言 `spin.property("compact") == True`
   - `test_no_buttons_helper_sets_compact_property`：用 `_no_buttons(QSpinBox())`，断言 `property("compact") == True`
   - `test_plain_qspinbox_has_no_compact_property`：直接 `QSpinBox()`，断言 `property("compact")` 为 None / falsy。这条不 FAIL（无前置代码即满足），但作为回归保证留下。
   - `test_method_button_spinboxes_have_compact_property`：构造 `method_buttons` 中的某个 `_w_nfft`（或等价构造），断言 `property("compact") == True`。
2. **GREEN — widget 侧**：
   - `CompactDoubleSpinBox.__init__`：在 `super().__init__(parent)` 之后加 `self.setProperty("compact", True)`
   - `inspector_sections._no_buttons(spin)`：在 `setButtonSymbols(...)` 之后加 `spin.setProperty("compact", True)`
   - `method_buttons.py` 5 处 `setButtonSymbols(QAbstractSpinBox.NoButtons)`：在每处之后追加 `setProperty("compact", True)`，或重构成 import `_no_buttons` 后通过 helper 设置（更优；但要避免 inspector_sections → method_buttons 反向 import 风险，可以把 helper 提到 `widgets/compact_spinbox.py` 作为模块函数，让两边都 import）
3. **GREEN — QSS 侧**（`style.qss:146-164`）：
   - 全部 `QSpinBox` / `QDoubleSpinBox` selector 改为 `QSpinBox[compact="true"], QDoubleSpinBox[compact="true"]` 等
   - subcontrol selector：`QSpinBox[compact="true"]::up-button, ...`
4. **GREEN — Inspector 限定 selector 清理**（`style.qss:496-516`）：
   - 该段如果是 stepper / padding 相关，改为统一的 `[compact="true"]` 路径
   - 如果是其他 Inspector-only 样式（颜色、字体等非 stepper），保留不动
5. **跑** `pytest tests/ui/test_compact_spinbox.py tests/ui/test_inspector.py tests/ui/test_batch_method_buttons.py -q`，确保全绿且新测试 PASS。
6. **回归视觉**：
   - `pytest tests/ui -q`（不应有视觉相关测试 fail）
   - 启动 app（offscreen smoke），inspector / batch / chart options dialog 的 spinbox 渲染依然无 stepper；通过 `tests/ui/test_canvases.py` / `test_inspector.py:test_*spinbox_buttons_hidden*`（如存在）保持绿
7. **W5 codex review**：派 codex，关注：
   - 所有 `[compact="true"]` selector 与对应 widget setProperty 一一对应
   - 没有遗漏的 `setButtonSymbols(NoButtons)` 调用未配对 setProperty
   - QSS Inspector 限定 selector 的清理不破坏其他样式
   - test_compact_spinbox.py 新测试为 strong RED：临时去掉 setProperty 调用时测试 FAIL
8. 通过后进 Phase 4 终局 review。

**完成标志**：所有 `[compact="true"]` selector 与 widget property 配对；pytest 全绿；codex VERDICT READY。

---

## Phase 3 — rework 检测

W4 expert = `refactor-architect`，W5 expert = `pyqt-ui-engineer`。两 wave 文件无重叠（W4 改 main_window.py + 删 test_order_worker.py；W5 改 widgets / style.qss / method_buttons / inspector_sections._no_buttons + tests/ui/test_compact_spinbox.py）。

但 W5 触及 `mf4_analyzer/ui/inspector_sections.py`（仅改 `_no_buttons` helper），W1 也曾改过 inspector_sections 的两个 `_on_amp_unit_changed`。这是同一文件不同方法，**不算 rework**（rework 标准是 “更早 wave 改了同方法”）。但要在 aggregate 时报告 `symbols_touched` 精确到方法。

`top_level_completions` 35 → 36（W4+W5 合在同一个 top-level 任务里，只 +1）。

## Phase 4 — 终局 codex review

两 wave 完成后，派 codex 整体看 P2-D1 + P8-O1 是否真被消化，回归 `pytest -q` 全绿。

---

## 依赖图

```
Spec/Plan ──> W4 ──[codex pass]──> W5 ──[codex pass]──> Phase4 codex
```

W4 与 W5 文件无重叠，理论上可并行。但保持 wave-gate 节奏一致 → 串行。

---

## 退出条件

- [ ] W4 + W5 都 codex VERDICT READY
- [ ] `pytest -q` 全绿（≥ 488 - 5 + 4 = ~487）
- [ ] grep 全仓零命中 OrderWorker / `_dispatch_order_worker` / `compute_time_order_result`（除 docs/lessons-learned）
- [ ] grep 全仓 spinbox 全局 QSS selector 仅余 `[compact="true"]` 形式
- [ ] `.state.yml` `top_level_completions` 36
- [ ] 终局 codex review = READY TO MERGE
