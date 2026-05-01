# Plan — Codex Review P1 Fixes (2026-05-01)

Spec: `docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md`
Source review: `docs/code-reviews/2026-05-01-recent-prs-deep-review.md`

3 个 P1 issue → 3 个 wave，每个 wave 独立 RED→GREEN→codex review gate。

---

## Wave 1 — Inspector 单位切换 reset（P7-L1 + P7-L1'）

**Expert**: `pyqt-ui-engineer`
**Files in scope**:
- `mf4_analyzer/ui/_axis_defaults.py` (新)
- `mf4_analyzer/ui/inspector_sections.py` (`OrderContextual`, `FFTTimeContextual`, 各自 `_on_amp_unit_changed`, `_apply_preset`)
- `tests/ui/test_inspector.py`

**Steps**:

1. **RED**：写两条新测试
   - `test_order_contextual_unit_toggle_resets_z_range`
   - `test_fft_time_contextual_unit_toggle_resets_z_range`
   断言 spec §1.2 不变量。运行确认失败。
2. **新文件** `_axis_defaults.py`：实现 `Z_RANGE_DEFAULTS` + `z_range_for(unit_text)`。
3. **GREEN**：改 `OrderContextual._on_amp_unit_changed` + `FFTTimeContextual._on_amp_unit_changed` 按 spec §1.4。
4. **回归保护**：`_apply_preset` 对 `combo_amp_unit.setCurrentText(...)` 用 `blockSignals(True/False)` 包裹，避免预设加载触发 reset 覆盖 preset 内的 z_floor/z_ceiling。
5. **跑全套 inspector 测试**：`pytest tests/ui/test_inspector.py -q`。
6. **W1 codex review**：派 codex 看 diff，关注 (a) blockSignals 是否覆盖所有 preset setter 路径 (b) 新测试是否真的 RED→GREEN (c) 无新回归。
7. 仅 codex 通过后 commit + 进入 W2。

**完成标志**：所有 inspector tests 绿；codex review 无 P1/P2。

---

## Wave 2 — Batch OUTPUT 单位切换对齐（P8-L1）

**Expert**: `pyqt-ui-engineer`
**Files in scope**:
- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `tests/ui/test_batch_output_panel.py` (新或扩)
- 复用 W1 的 `_axis_defaults.z_range_for`

**Steps**:

1. **RED**：新测试 `test_batch_output_panel_unit_toggle_resets_z_range`
   - 构造 OutputPanel，设 z_floor=-30/ceiling=0，关 auto
   - 切 combo_amp_unit dB→Linear
   - 断言 spec §1.2（数值变 0/1，auto 打开，spin disabled）
   - 断言 `changed` signal 只 emit 1 次（用 QSignalSpy）
2. **GREEN**：把 `combo_amp_unit.currentTextChanged.connect(lambda *_: self.changed.emit())` 替换为新 handler `_on_amp_unit_changed(text)`，handler 内：
   - `self.blockSignals(True)`（或对 spin/chk 各自 blockSignals）
   - 应用 reset（chk_z_auto + spin floor/ceiling）
   - `self._sync_axis_enabled()`
   - 解锁 signals
   - `self.changed.emit()` 一次
3. **回归**：`apply_axis_params(...)` 等已有 setter 路径不应触发 reset → 同样用 blockSignals 包裹。
4. **跑** `pytest tests/ui/test_batch_output_panel.py tests/ui/drawers -q`。
5. **W2 codex review**：派 codex，关注 (a) emit-once 是否真做到 (b) `_write_image` 调用链回归是否被覆盖 (c) preset 加载路径是否被破坏。
6. 通过后 commit + 进 W3。

**完成标志**：batch tests 全绿；codex review 无 P1/P2。

---

## Wave 3 — ChartOptionsDialog log-scale 校验（P10-L2）

**Expert**: `pyqt-ui-engineer`
**Files in scope**:
- `mf4_analyzer/ui/dialogs.py` (`ChartOptionsDialog._apply_axis`, `apply`)
- `tests/ui/test_dialogs.py`

**Steps**:

1. **RED**：三条新测试（spec §3 第 4-6 行）
   - `test_chart_options_log_axis_rejects_non_positive`
   - `test_chart_options_log_axis_warning_blocks_close`
   - `test_chart_options_log_axis_positive_range_applies`
2. **GREEN**：
   - `__init__` 加 `self._invalid_axes: list[str] = []`
   - 改 `_apply_axis` 按 spec §2.3
   - `apply()`（或 `_on_apply_clicked`）末尾：若 `self._invalid_axes` 非空，调 `QMessageBox.warning(self, "范围非法", "对数刻度下 X/Y 范围必须 > 0")`，**不**关闭 dialog；若空则 `accept()`/正常关闭路径。
3. **细节**：
   - `_invalid_axes` 在每次 `apply()` 入口先 clear
   - 不动 linear scale 路径
4. **跑** `pytest tests/ui/test_dialogs.py -q`，再跑 `pytest tests/ui -q` 确保整体绿。
5. **W3 codex review**：派 codex，关注 (a) `_invalid_axes` 复位时机 (b) MessageBox monkeypatch 是否在测试里隔离 (c) 是否破坏既有 “应用 → 关闭” 流。
6. 通过后 commit。

**完成标志**：dialogs tests 全绿；codex review 无 P1/P2。

---

## Phase 3 — 聚合 + rework 检测

按 CLAUDE.md 规则：
- 收集每个 wave specialist 的 `files_changed`
- 检查 (W_i, W_j) 文件交集 + 不同 expert：本计划三 wave 都派 `pyqt-ui-engineer`，理论上无 cross-expert rework
- 若 W2 / W3 改动了 W1 的 `_axis_defaults.py` 之外的 inspector 文件 → 写 lesson
- read-modify-write `docs/lessons-learned/.state.yml`，递增 `top_level_completions`

## Phase 4 — 终局 codex review

所有 wave 完成、Phase 3 状态写入后：

1. 派 codex 做整体 review（base = main, head = local working tree）
2. codex 指出问题 → 回 wave 修复（再走 wave 内 RED→GREEN→codex review）
3. 直到 codex verdict = `READY TO MERGE`

---

## 依赖图

```
Spec ──> W1 ──[codex pass]──> W2 ──[codex pass]──> W3 ──[codex pass]──> Phase3 ──> Phase4 codex
```

W1 必须先于 W2（W2 复用 `_axis_defaults`），W3 独立。

---

## 测试覆盖矩阵

| 不变量 | Wave | 测试 |
|---|---|---|
| Inspector dB→Linear z_auto + reset | W1 | test_order_contextual_unit_toggle_resets_z_range |
| Inspector Linear→dB z_auto + reset | W1 | （同测试参数化） |
| FFTTime dB↔Linear z_auto + reset | W1 | test_fft_time_contextual_unit_toggle_resets_z_range |
| Inspector preset 加载不触发 reset | W1 | （扩 `test_apply_preset_*`） |
| Batch OUTPUT dB↔Linear reset + emit-once | W2 | test_batch_output_panel_unit_toggle_resets_z_range |
| Log + vmin<=0 不写 set_lim | W3 | test_chart_options_log_axis_rejects_non_positive |
| Log 非正范围 warning 阻塞关闭 | W3 | test_chart_options_log_axis_warning_blocks_close |
| Log + vmin/vmax>0 正常应用 | W3 | test_chart_options_log_axis_positive_range_applies |

---

## 退出条件（计划总验收）

- [ ] W1 + W2 + W3 全部 codex verdict pass
- [ ] `pytest -q` 全绿（baseline 之外不新增 fail）
- [ ] `.state.yml` `top_level_completions` 递增 1
- [ ] 终局 codex review = READY TO MERGE
- [ ] codex review 报告路径附在 squad 最终聚合 JSON 的 `lessons_added`/notes 中（如有 rework）
