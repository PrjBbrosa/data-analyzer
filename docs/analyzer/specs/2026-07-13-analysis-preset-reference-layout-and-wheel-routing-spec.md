# 分析预设、dB 参考布局与滚轮缩放修复 — Product / Design Spec

日期：2026-07-13
状态：已批准并直接实施
相关基线：[dB Reference 默认值、自动解析与结果标识](2026-07-12-db-reference-defaults-and-labeling-spec.md)

## 1. Outcome

修复 FFT、FFT-vs-Time 和 Order 中三项已确认的回归，同时不改变任何分析算法或 compute cache key：

1. FFT-vs-Time 内置预设不再改写当前 View 的 dB reference 值或 Auto/Manual 模式，也不因预设应用而启动计算。
2. 三个分析 Inspector 的 dB 参考控件移入“坐标轴设置”组，放在“自动 / 最小 / 最大”表头之前；不再显示在“谱参数”表单的频率加权之后。
3. Ctrl+滚轮继续只缩放 X，Shift+滚轮继续只缩放鼠标所在图的 Y；FFT、FFT-vs-Time 和 Order 的真实 Qt 滚轮事件都必须生效。

## 2. Evidence and Root Cause

| 症状 | 已确认原因 | 代码锚点 |
| --- | --- | --- |
| FFT-vs-Time 点击任一内置预设后 dB reference 跳为 `1` 且可能直接计算 | `_builtin_preset_full_params()` 写入 `db_reference=1.0` 但未写 mode；旧预设迁移把它解释为 Manual。编辑器的 `valueChanged` 随后调度 `do_fft_time()`，新谱参数导致 cache miss 时便启动 worker。 | `contextual_fft_time.py`、`_helpers.py`、`window.py` |
| Order 不复现 | Order 内置预设没有 dB reference 字段。 | `contextual_order.py` |
| Ctrl/Shift 滚轮无效 | 共享 `_ModifierWheelViewBox` 调用时传入 `scene_pos` 和 `axis`，而 FFT 线图和热图的 `_handle_wheel_dispatch` 签名不接收这两个关键字。Qt 事件处理期间抛出 `TypeError`，没有进入默认回退。 | `viewbox.py`、`line_canvas.py`、`heatmap_canvas.py` |
| 现有缩放测试仍绿 | 测试直接调用 `_handle_wheel_dispatch`，绕开了 ViewBox → GraphicsLayoutWidget viewport 的真实 Qt 事件边界。 | `test_pg_line_canvas.py`、`test_pg_heatmap_canvas.py` |

## 3. Requirements

### R1 — dB reference 是 View 显示状态

- 内置预设只能改变其声明的分析/坐标轴参数；不得包含 `db_reference` 或 `db_reference_mode`。
- 点击 FFT-vs-Time 三个内置预设时，当前 `DbReferenceControl.mode()` 与 editor 值保持不变，且 editor 不发出新的 `valueChanged`。
- 历史或用户保存的预设若显式携带 dB reference，仍按既有兼容迁移规则处理：缺 mode 的历史值迁移为 Manual。
- 为避免任何预设 blob 的同步控件写入触发昂贵路径，`_on_db_reference_value_edited()` 在对应 contextual 的 `_applying_preset` 为真时不得调度 re-render/compute。

### R2 — 坐标轴布局

每个分析页的目标顺序如下：

```text
坐标轴设置
  dB 参考: [科学计数 editor | Auto/Manual badge | 管理]
            自动             最小                 最大
  频率/时间 (X) ...
  幅值/频率/阶次 (Y) ...
  色阶 (Z) ...                 # 仅 FFT-vs-Time 与 Order
```

- FFT、FFT-vs-Time、Order 都使用同一坐标轴组构造路径；仅把已有 `db_reference_control` 作为组内头部行插入，不创建第二个控件，不改变 `ctx.spin_db_ref` alias。
- dB 行的文字起点与 X/Y/Z 行对齐；复合 editor 填充字段列、管理按钮贴右。标签必须与 editor 本身垂直居中，不得按包含来源文字和 badge 的整个复合控件居中；既有最大宽度、管理按钮方形尺寸、badge 不裁切等窄 Inspector 契约继续成立。
- “谱参数”表单内不再包含 `dB 参考:` 行。

### R3 — 统一滚轮分发契约

- 共享 ViewBox 的 owner 回调契约为：

```python
def _handle_wheel_dispatch(
    self, *, delta, modifiers, x_pos, y_pos,
    view_box=None, scene_pos=None, axis=None,
) -> bool: ...
```

- 不使用 `scene_pos`/`axis` 的 line/heatmap canvas 显式接受并忽略它们；TimeDomain 的 overlay 实现继续实际使用它们。
- 有 Ctrl 或 Shift 时，事件由自定义逻辑 consume；没有修饰键时维持 pyqtgraph 原生行为。

## 4. Non-goals

- 不改变 FFT、Spectrogram、COT 的算法、worker 调度规则或 compute cache key 内容。
- 不改变手动编辑 dB reference 时的现有 cache-hit 渲染行为。
- 不改变历史保存预设的 dB reference 迁移语义。
- 不调整 dB reference catalog、标签格式、Batch 输出或 QSettings schema。
- 不改变时间域 overlay 的单通道 Y 轴滚轮行为。

## 5. Design

### 5.1 内置预设与重渲染边界

FFT-vs-Time 内置预设的完整参数字典删除 `db_reference`。缺少 reference key 时，现有 `apply_db_reference_preset()` 已保证控制器保持当前状态。主窗口的 dB editor 回调先检查 `ctx._applying_preset`；这是防止未来任何预设写入控件后意外调度计算的防线，不改变普通用户提交与项目状态恢复。

### 5.2 可复用的轴组头部行

`_make_axis_settings_group()` 接收可选的头部行（label + widget），在 `_build_axis_header()` 之前创建对齐行。三个 contextual 仍在构造自己的一个 `DbReferenceControl`，但移除原先 QFormLayout 的 `addRow`，再将同一实例交给轴组。这样状态、信号、object name 和兼容 alias 均不变。

### 5.3 事件端到端验证

测试从 GraphicsLayoutWidget viewport 发送带 `Qt.ControlModifier` 或 `Qt.ShiftModifier` 的 `QWheelEvent`。断言真实 ViewBox 的范围按单轴变化；这会在签名不兼容时保持范围不变，从而稳定捕获本次回归。

## 6. Acceptance Criteria

- 三个 FFT-vs-Time 内置预设在 Auto 与 Manual 两种状态下均保持 dB reference 值/mode，且不触发计算入口。
- 三个 contextual 的 `dbReferenceControl` 位于 `axisSettingsGroup` 内，并严格位于自动/最小/最大表头之前；窄至 288 px 时 editor 填充字段列、不溢出、不裁切，标签与 editor 垂直居中。
- 从真实 viewport 投递 Ctrl-wheel 时 FFT line 与 heatmap 的 X 范围收缩且 Y 不变；投递 Shift-wheel 时相应 Y 范围收缩且 X 不变。
- 原有的 reference 兼容迁移、所有 focused UI 测试和新增事件路由测试通过。

## 7. Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\ui\test_inspector.py `
  tests\ui\test_main_window_smoke.py `
  tests\ui\test_pg_line_canvas.py `
  tests\ui\test_pg_heatmap_canvas.py `
  --basetemp D:\tmp\pytest-analysis-reference-wheel
```

视觉探针若需要实例化 Inspector，必须沿用 `tests/ui/conftest.py` 的 QSettings 隔离；不得对真实用户设置调用持久化 setter。
