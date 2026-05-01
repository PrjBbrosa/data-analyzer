# Spec — Codex Review P2 Cleanup (2026-05-01)

源于 `docs/code-reviews/2026-05-01-recent-prs-deep-review.md` 两个 P2 issue：

- **P7-D1** `mf4_analyzer/ui/main_window.py:81` — OrderWorker / `_dispatch_order_worker` 死代码
- **P8-O1** `mf4_analyzer/ui/style.qss:146` — compact spinbox stepper 样式用全局 QSpinBox / QDoubleSpinBox selector，污染所有 spinbox

两条独立处理，分别为 W4（dead-code 清理）+ W5（QSS scope 收敛）。

---

## 1. OrderWorker 死代码删除（P7-D1, W4）

### 1.1 现状

PR #7 (W2) 把 `do_order_time` 切到同步 `COTOrderAnalyzer.compute`，从此**生产路径**不再 dispatch `OrderWorker`，但代码仍存：

| 残留 | 位置 |
|---|---|
| `OrderWorker(QThread)` 类 | `main_window.py:81` |
| `_dispatch_order_worker` | `main_window.py:1428` |
| `_on_order_progress` | `main_window.py:1471` |
| `_on_order_failed` | `main_window.py:1479` |
| `_on_order_result` | `main_window.py:1486` |
| 引用 `OrderAnalyzer.compute_time_order_result`（已 deprecated） | `main_window.py:121` (在 OrderWorker 内) |
| stale 文档注释 | `main_window.py:1345-1357`, `1410-1421` 等 |
| 测试文件 | `tests/ui/test_order_worker.py`（整个文件） |

仅 `_cancel_order_compute` 仍可达：来自 `main_window.py:291` 的 `OrderContextual.cancel_requested.connect(_cancel_order_compute)`。但该 slot 内部 `worker = getattr(self, '_order_worker', None)` 永远为 None，所以是 no-op 状态。

### 1.2 删除契约

production 删除清单：
- `OrderWorker` 类整体
- `_dispatch_order_worker(...)` 整体
- `_on_order_progress(...)`, `_on_order_failed(...)`, `_on_order_result(...)` 整体
- `_cancel_order_compute` 简化为单行 no-op，**或** 改名 `_cancel_order_compute_noop` 并加文档说明（因为信号还连着）。推荐方案：**保留 slot 但简化为 no-op + docstring 说明 "占位 for future async COT worker"**，不破坏现有 connect。
- `_order_worker`, `_order_generation` 实例属性（如有显式 init）一并清理
- stale 注释（提到 OrderWorker / dispatch / generation tokens 的段落）

production 保留：
- `OrderContextual.btn_cancel`（forward-looking，未来 async COT worker 上线时复用）
- `OrderContextual.cancel_requested` 信号
- `main_window.py:291` 的 `cancel_requested.connect(_cancel_order_compute)` 连接

测试删除：
- `tests/ui/test_order_worker.py` 整个文件

### 1.3 不变量

- `do_order_time()` 行为完全不变（仍走同步 COT 路径）
- `OrderContextual` 用户可见控件不变（`btn_cancel` 仍存在但永不 enable，与当前一致）
- 测试套件 ≥ 488 全绿（删 test_order_worker.py 后净减 4-5 个测试，但应 ≥ 488 - 5 = 483）
- 实际预期：删除前 492 passed → 删除后 ~488 passed（-test_order_worker 4 cases）+ 0 fail

### 1.4 验证

- `pytest -q` 全绿
- `grep -r "OrderWorker\|_dispatch_order_worker\|_on_order_progress\|_on_order_failed\|_on_order_result\|compute_time_order_result" mf4_analyzer/ tests/`：除 fixture/lessons 之外 **零** 命中
- 启动 app（offscreen / smoke），点 “时间-阶次谱” 按钮一次，断言 do_order_time 走 COT 同步路径正常完成（已有 test_main_window_smoke 之类应覆盖）

### 1.5 风险

- 误删 `_cancel_order_compute` 的 connect 来源：删 slot 的同时必须保留 wiring，或者一起删 wiring（会破坏 btn_cancel 的现有 `clicked.connect(cancel_requested)` 链路）。**安全选择：保留 slot + wiring，仅清空 slot 体**。
- 其他文件可能仍 import `OrderWorker`（如 batch / signal 模块）。需要全仓 grep。
- `tests/ui/test_main_window_smoke.py` 等可能间接 import OrderWorker → 需检查。

---

## 2. QSS spinbox 全局 selector 收敛（P8-O1, W5）

### 2.1 现状

`mf4_analyzer/ui/style.qss:146-164`：

```css
QSpinBox, QDoubleSpinBox {
    padding-left: 8px;
    padding-right: 8px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 0; height: 0; border: none; background: transparent;
    subcontrol-position: top right;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none; width: 0; height: 0;
}
```

`QSpinBox / QDoubleSpinBox` 全局 selector 让**任意**未来加的 spinbox 都自动隐藏 stepper。

widget 侧已有 `_no_buttons(spin)` helper（`inspector_sections.py:51-62`）调 `setButtonSymbols(NoButtons)`，QSS 是 “double protection”（注释 `style.qss:140-145` 说明）。

`mf4_analyzer/ui/drawers/batch/method_buttons.py:124-159` 直接调 `setButtonSymbols(NoButtons)`（5 处），未走 `_no_buttons`。

### 2.2 收敛策略

用 Qt 动态属性（dynamic property）作 selector，opt-in 而非全局：

**widget 侧**：
- `_no_buttons(spin)` 改为额外调 `spin.setProperty("compact", True)`
- `CompactDoubleSpinBox.__init__` 也调 `self.setProperty("compact", True)`
- `method_buttons.py` 5 处 `setButtonSymbols(NoButtons)` 改为统一通过新增的辅助 helper（或 inline 加 setProperty）。最干净：把 `_no_buttons` 提到 `widgets/compact_spinbox.py` 模块级，让 `method_buttons.py` import 并复用。

**QSS 侧**（`style.qss:146-164`）：
- selector 全部改为 `QSpinBox[compact="true"], QDoubleSpinBox[compact="true"]` 等
- 顺手清掉 `Inspector QSpinBox / QDoubleSpinBox` (line 496+) 的范围限定 selector，统一走 `[compact="true"]` 一条路

### 2.3 不变量

- 所有当前 “无按钮 spinbox”（Inspector / batch method buttons）渲染**完全不变**
- 任何普通 `QSpinBox()` / `QDoubleSpinBox()` 不设 compact 属性时，恢复 Qt 默认 stepper（显式回归测试）
- 测试套件 ≥ 之前数（W4 删除后预期 ≥ 488）+ 1-2 新测试

### 2.4 测试矩阵

| 测试 | 文件 | 断言 |
|---|---|---|
| `test_compact_double_spinbox_has_compact_property` | `tests/ui/test_compact_spinbox.py`（NEW 或扩） | `spin.property("compact") == True` |
| `test_no_buttons_helper_sets_compact_property` | 同上 | helper 返回的 spin `property("compact") == True` |
| `test_plain_spinbox_does_not_get_compact_property` | 同上 | 直接 `QSpinBox()` 没有 compact 属性 → 回归保证 |
| 现有 spinbox 渲染 / button-removal 测试 | `tests/ui/test_inspector.py:test_inspector_spinbox_buttons_hidden_*`（如存在） | 行为不变 |

### 2.5 风险

- Qt dynamic property + QSS 要求 widget 在 setProperty 之后 polish/repolish 才生效。`setProperty` 应在 widget show 之前完成；helper / constructor 调用时机已满足。
- `polish` 缓存：如果 widget 已 polish 后才 setProperty，需要 `style().unpolish(widget); style().polish(widget)` 触发 QSS 重算。在 constructor / helper 内 setProperty 不会遇到这个问题（show 前 setProperty）。
- 全局 QSS `Inspector QSpinBox` 等限定 selector 要清理，否则会与新 `[compact="true"]` selector 同时存在产生 cascade 冲突。

---

## 3. Wave 划分

- **W4 = P7-D1**：OrderWorker 死代码清理。Specialist：`refactor-architect`（跨方法删除 + 测试文件移除属于 module-level cleanup）。
- **W5 = P8-O1**：QSS scope 收敛。Specialist：`pyqt-ui-engineer`（QSS + Qt 动态属性 wiring）。

W4 / W5 文件无重叠，可平行也可串行。建议**串行**（保持 wave gate 节奏一致）：W4 → codex review → W5 → codex review → 终局 codex。

---

## 4. 非目标

- 不增加 async COT worker（spec §1.5 风险列表里说明，跨范围）
- 不重构 `_no_buttons` 与 `CompactDoubleSpinBox` 的关系（保留并列存在；只新增 setProperty）
- 不动 `Inspector QSpinBox` 之外的非 spinbox 全局 selector
