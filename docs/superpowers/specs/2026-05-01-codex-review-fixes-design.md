# Spec — Codex Review P1 Fixes (2026-05-01)

源于 `docs/code-reviews/2026-05-01-recent-prs-deep-review.md` 三个 P1 issue：

- **P7-L1** `inspector_sections.py:2132` `OrderContextual._on_amp_unit_changed`
- **P7-L1'** `inspector_sections.py:2667` `FFTTimeContextual._on_amp_unit_changed`
- **P8-L1** `drawers/batch/output_panel.py:128` Batch OUTPUT `combo_amp_unit.currentTextChanged`
- **P10-L2** `dialogs.py:638` `ChartOptionsDialog._apply_axis` log scale + 非正 limit

> P7-L1 与 P7-L1' 同源，统一处理；与 P8-L1 共用同一行为契约。

---

## 1. 单位切换不变量（P7-L1 / P7-L1' / P8-L1）

### 1.1 问题陈述

用户在 Z 范围已锁定的状态下切换 dB↔Linear，旧单位的数值会被沿用到新单位。最小复现：

```
chk_z_auto = False
spin_z_floor = -30, spin_z_ceiling = 0   # dB 数值
combo_amp_unit: dB → Linear
chk_z_auto = False                        # 用户再关闭自动
→ 实际写入: amplitude_mode=amplitude, z_floor=-30, z_ceiling=0
→ 渲染: Linear 色阶用 [-30, 0]，几乎全 black 或全 saturated
```

### 1.2 不变量（写在测试里）

切换 `combo_amp_unit` 后立即满足：

```
chk_z_auto.isChecked()   == True
spin_z_floor.value()     == DEFAULT_FLOOR[new_unit]
spin_z_ceiling.value()   == DEFAULT_CEILING[new_unit]
spin_z_floor.isEnabled() == False    # 因 auto 打开，sync 后 disable
spin_z_ceiling.isEnabled() == False
```

### 1.3 unit-defaults 常量

放 `mf4_analyzer/ui/_axis_defaults.py`（新文件）：

```python
Z_RANGE_DEFAULTS = {
    'dB':     (-30.0, 0.0),
    'Linear': (0.0, 1.0),
}

def z_range_for(unit_text: str) -> tuple[float, float]:
    return Z_RANGE_DEFAULTS.get(unit_text, (0.0, 1.0))
```

dB 的 -30..0 与既有 batch 旧 `dynamic='30 dB'` 迁移路径对齐。
Linear 的 0..1 是占位，用户会在 re-disable auto 时重新填值。

### 1.4 行为契约

三处实现统一为：

```python
def _on_amp_unit_changed(self, text):
    floor, ceiling = z_range_for(text)
    self.chk_z_auto.setChecked(True)        # 必须先 set，让 sync 生效
    self.spin_z_floor.setValue(floor)
    self.spin_z_ceiling.setValue(ceiling)
    self._sync_axis_enabled()
```

OutputPanel 当前 `combo_amp_unit.currentTextChanged.connect(lambda *_: self.changed.emit())` 替换为相同 handler，并在末尾 `self.changed.emit()`。

### 1.5 边界

- 重复触发同单位（`dB→dB`）：handler 仍执行 reset，幂等
- `set_amplitude_mode_from_preset` 等已存在的 setter：**不**触发 reset（用 `blockSignals` 或在 setter 内显式恢复值）
- `combo_amp_unit` 初始化：constructor 中调用一次 `_on_amp_unit_changed` 不应覆盖 preset。处理：constructor 设置默认值后**不**手动 emit；signal 仅响应用户交互

---

## 2. ChartOptionsDialog log-scale 校验（P10-L2）

### 2.1 问题陈述

`_apply_axis(scale_text='对数', auto=False, vmin=-1, vmax=10)` 顺序：

1. `set_yscale('log')` ✓
2. `set_ylim(-1, 10)` → Matplotlib 仅 warning，下限被静默替换为自动正值

UI 显示 “应用” 成功，但实际范围与输入不符。

### 2.2 不变量

```
log + (vmin <= 0 or vmax <= 0)
  → 不调用 set_xlim / set_ylim
  → return False（“此轴未应用”），由 caller 汇总用户提示
  → 该 axis 的 scale 仍切换成功（log 是合法的）

log + vmin > 0 + vmax > 0 + vmin < vmax
  → set_xlim/set_ylim 正常应用

linear + 任意 vmin/vmax（合法浮点）
  → 行为不变
```

### 2.3 行为契约

```python
def _apply_axis(self, *, axis, auto, vmin, vmax, label, scale_text):
    scale = self.TEXT_TO_SCALE.get(scale_text, "linear")
    setter_scale = self.ax.set_xscale if axis == 'x' else self.ax.set_yscale
    setter_lim   = self.ax.set_xlim   if axis == 'x' else self.ax.set_ylim
    setter_label = self.ax.set_xlabel if axis == 'x' else self.ax.set_ylabel

    setter_scale(scale)
    if auto:
        self.ax.autoscale(axis=axis)
    else:
        if scale == 'log' and (float(vmin) <= 0 or float(vmax) <= 0):
            self._invalid_axes.append(axis)   # 由 apply() 收集
            self.ax.autoscale(axis=axis)      # 退回自动，避免静默错误
        else:
            setter_lim(float(vmin), float(vmax))
    setter_label(label)
```

`apply()` 在 dialog 关闭前若 `self._invalid_axes` 非空，弹一个 `QMessageBox.warning`，列出 “X 轴 / Y 轴 对数模式下范围必须为正”，dialog 不关闭，让用户改。

### 2.4 字段校验时机

只在 “应用” 按钮（`self._apply_clicked`）触发；spinbox `valueChanged` 不做提示，避免输入过程中弹框打断。

---

## 3. 测试矩阵（RED 前置）

| Test | File | Asserts |
|---|---|---|
| `test_order_contextual_unit_toggle_resets_z_range` | `tests/ui/test_inspector.py` | 切 dB→Linear 后 spin_z_floor=0, spin_z_ceiling=1, chk_z_auto=True |
| `test_fft_time_contextual_unit_toggle_resets_z_range` | `tests/ui/test_inspector.py` | 同上，FFTTimeContextual |
| `test_batch_output_panel_unit_toggle_resets_z_range` | `tests/ui/test_batch_output_panel.py` (新) | 切 Linear→dB 后 spin_z_floor=-30, spin_z_ceiling=0, chk_z_auto=True，emit changed 一次 |
| `test_chart_options_log_axis_rejects_non_positive` | `tests/ui/test_dialogs.py` | log + vmin=-1 时 `_apply_axis` 不写 set_ylim，invalid_axes 记录 'y' |
| `test_chart_options_log_axis_warning_blocks_close` | `tests/ui/test_dialogs.py` | 带非正范围点击应用：QMessageBox.warning 被调用，dialog 未关闭 |
| `test_chart_options_log_axis_positive_range_applies` | `tests/ui/test_dialogs.py` | log + vmin=0.1, vmax=10 时 set_ylim(0.1, 10) |

---

## 4. 非目标

- 不重构 `_axis_settings_group` 共用工厂；现在的三处仅做 handler 行为改造
- 不动 `batch_preset_io._migrate_axis_keys`（codex 已确认幂等）
- 不清理 `OrderWorker` / `_dispatch_order_worker` 死代码（PR #7 follow-up，单独 issue）
- 不动 `style.qss` 全局 spinbox selector（PR #8 P2，单独 issue）

---

## 5. 风险

- **Inspector 旧调用方**：`_apply_preset` 调用 `combo_amp_unit.setCurrentText(...)` 会触发 `currentTextChanged`，进而 reset 用户已存的范围。Mitigation：`_apply_preset` 用 `blockSignals(True/False)` 包裹，或在 reset handler 内对 `programmatic` 来源做 guard。
- **OutputPanel emits**：现在 handler 会调 setValue 三次（floor/ceiling/auto），各自 emit `changed`，导致 batch preset 多次 dirty。Mitigation：用 `blockSignals` 在 handler 内统一 emit 一次。
