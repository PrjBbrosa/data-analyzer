# 批处理输出坐标轴、数字显示与入口可用性修复报告

日期：2026-04-30

## 背景

本轮围绕批处理界面和输出链路处理了 4 个问题：

1. 配置保存内容不够明晰，需要梳理当前保存范围并判断是否需要扩展。
2. 批处理切到 `order_time` 后出现 RPM 系数输入框过宽，默认 `1.0000000000` 零太多，需要全局优化默认显示，但不限制用户输入精度。
3. 批处理最后输出需要增加 X/Y/Z 坐标轴设置，并参考 inspector 内已有布局和计算逻辑，让设置进入实际导出图片计算/渲染。
4. 批处理按钮首次进入软件时可点，但切换或点击其他内容后会因为没有文件而变灰，导致无法打开批处理。

## 配置保存现状

批处理 preset 的读写由 `mf4_analyzer/batch_preset_io.py` 负责。当前 JSON 白名单保存这些字段：

- `schema_version`：preset 文件格式版本，目前为 `1`。
- `name`：preset 名称。
- `method`：分析方法，例如 `fft`、`fft_time`、`order_time`。
- `target_signals`：自由配置模式下选中的目标信号列表。
- `rpm_channel`：阶次分析使用的 RPM 通道名。
- `params`：分析参数字典。
- `outputs`：导出内容配置，包含：
  - `export_data`
  - `export_image`
  - `data_format`

明确不会保存的内容：

- `file_ids`
- `file_paths`
- `signal`
- `rpm_signal`
- `signal_pattern`
- 输出目录 `directory`

这些字段属于运行时选择或本机环境路径，之前的设计是 recipe-only preset，因此不会写入 JSON。

本轮判断需要增加到 `params` 的内容：

- 输出图片的 X/Y/Z 坐标轴设置：
  - `x_auto`
  - `x_min`
  - `x_max`
  - `y_auto`
  - `y_min`
  - `y_max`
  - `z_auto`
  - `z_floor`
  - `z_ceiling`

原因：这些不是运行时文件选择，而是“输出图怎样画”的计算/显示配置。它们应该跟着 preset 走，否则导入配置后无法复现同一批处理输出图。

## 修改内容

### 1. 批处理 Output 增加 X/Y/Z 坐标轴设置

修改文件：

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`

新增内容：

- 在批处理 OUTPUT 区增加 `坐标轴设置` 分组。
- 增加三行轴配置：
  - `X 范围`：`自动` + 最小值 + 最大值。
  - `Y 范围`：`自动` + 最小值 + 最大值。
  - `Z 色阶`：`自动` + floor + ceiling。
- 默认全自动，保持旧行为不变。
- 手动关闭自动后，允许用户指定范围。
- 新增 `OutputPanel.axis_params()`，把轴配置打包进 preset `params`。
- 新增 `OutputPanel.apply_axis_params()`，导入 preset 时恢复轴配置。
- `BatchSheet.get_preset()` 合并 output panel 的轴参数。
- `BatchSheet.apply_preset()` 在 `current_single` 和 `free_config` 两条路径都恢复轴参数。

效果：

- 导出 preset 会包含输出轴设置。
- 导入 preset 后，批处理 Output 面板可以恢复 X/Y/Z 轴状态。
- 默认不改变老 preset 和旧用户习惯。

### 2. 批处理导出图片集成 X/Y/Z 轴设置

修改文件：

- `mf4_analyzer/batch.py`

新增内容：

- `BatchRunner._run_one()` 在调用 `_write_image()` 时传入 `preset.params`。
- `_write_image()` 新增 `params=None` 参数。
- 从 params 读取：
  - `x_auto/x_min/x_max`
  - `y_auto/y_min/y_max`
  - `z_auto/z_floor/z_ceiling`
- 对线图类输出：
  - X 手动范围应用到 `ax.set_xlim()`。
  - Y 手动范围应用到 `ax.set_ylim()`。
- 对热力图类输出，包括 `order_time` 和 `fft_time`：
  - X 手动范围应用到 `ax.set_xlim()`。
  - Y 手动范围应用到 `ax.set_ylim()`。
  - Z 手动色阶应用到 `imshow(vmin=..., vmax=...)`。

效果：

- 批处理界面中的坐标轴设置不只是保存，而是真正参与最终 PNG 输出。
- `order_time` 的时间-阶次热力图可以控制：
  - X：时间轴范围。
  - Y：阶次轴范围。
  - Z：幅值色阶。
- `fft_time` 的时间-频率热力图同样可以控制：
  - X：时间轴范围。
  - Y：频率轴范围。
  - Z：幅值色阶。

### 3. 数值输入框默认紧凑显示，仍保留输入精度

新增文件：

- `mf4_analyzer/ui/widgets/compact_spinbox.py`

修改文件：

- `mf4_analyzer/ui/drawers/batch/input_panel.py`
- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `mf4_analyzer/ui/dialogs.py`
- `mf4_analyzer/ui/drawers/rebuild_time_popover.py`
- `mf4_analyzer/ui/inspector_sections.py`

新增控件：

- `CompactDoubleSpinBox`

行为：

- 继承 `QDoubleSpinBox`。
- 保留 `setDecimals()` 决定的可输入/可存储精度。
- 仅改写 `textFromValue()`，把显示文本中的尾随 0 去掉。
- 至少保留 1 位小数，让浮点默认读起来仍是 `1.0`，不是整数 `1`。

示例：

- 原显示：`1.0000000000`
- 新显示：`1.0`
- 原显示：`20.00`
- 新显示：`20.0`
- 原显示：`0.100`
- 新显示：`0.1`
- 用户输入：`1.23456789`
- 新显示仍为：`1.23456789`

效果：

- 批处理 `order_time` 出现 RPM 系数时，左侧 INPUT 区不会因为 `1.0000000000` 变宽。
- 不是把用户限制成只能输入 1 位，而是只优化默认展示文本。
- Inspector、AxisEditDialog、重建时间轴 popover、批处理参数表单等可见 double spinbox 同步受益。

### 4. 批处理按钮保持可用

修改文件：

- `mf4_analyzer/ui/toolbar.py`
- `mf4_analyzer/ui/main_window.py`

问题根因：

- `Toolbar.set_enabled_for_mode(mode, has_file)` 里把 `btn_batch` 和 `btn_edit`、`btn_export` 一起绑定到 `has_file`。
- 软件刚启动时按钮可能还能点，但只要触发一次模式/状态刷新，`has_file=False` 就会把批处理按钮禁用。
- `MainWindow.open_batch()` 也有 `if not self.files: 请先加载文件` 的前置拦截。

修改后：

- `btn_edit` 和 `btn_export` 仍然依赖是否已有文件。
- `btn_batch` 始终保持可用。
- `open_batch()` 允许在没有已加载文件时打开批处理弹窗。

原因：

- 批处理界面本身支持从磁盘添加文件。
- 没有主窗口已加载文件时，用户仍然应该可以先进入批处理，再通过 `+ 磁盘…` 添加待处理文件。

## 测试覆盖

新增/更新测试文件：

- `tests/ui/test_batch_input_panel.py`
- `tests/test_batch_runner.py`
- `tests/ui/test_toolbar.py`
- `tests/ui/test_order_smoke.py`

新增覆盖点：

- `CompactDoubleSpinBox` 默认显示紧凑文本，同时保持高精度输入。
- `BatchSheet.get_preset()` 包含 output X/Y/Z 轴参数。
- `BatchSheet.apply_preset()` 能恢复 output X/Y/Z 轴参数。
- `BatchRunner._write_image()` 实际应用 X/Y/Z 参数到 matplotlib 轴范围和色阶。
- `Toolbar.set_enabled_for_mode(..., has_file=False)` 后批处理按钮仍可用。
- `MainWindow.open_batch()` 在空文件列表下仍会打开批处理弹窗。

验证命令：

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

验证结果：

```text
430 passed, 48 warnings in 16.22s
```

警告说明：

- 48 个 warning 是 matplotlib/DejaVu Sans 对中文 glyph 的缺字警告，和本轮功能改动无关。

## 用户可见变化

- 批处理按钮不会再因为当前没有文件而变灰。
- 可以直接打开批处理，再在批处理里选择磁盘文件。
- `order_time` 下 RPM 系数默认显示为 `1.0`，不会把左侧 INPUT 区撑宽。
- 数值框仍然能输入多位小数，例如 `1.23456789`。
- 批处理 Output 区现在能设置导出图片的 X/Y/Z 坐标轴范围。
- 导出 preset 后，坐标轴设置会随 preset 保留。
- 导入 preset 后，坐标轴设置会恢复。
- 批处理最终 PNG 输出会实际使用这些坐标轴设置。

## 主要涉及文件

- `mf4_analyzer/ui/widgets/compact_spinbox.py`
- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/batch.py`
- `mf4_analyzer/ui/drawers/batch/input_panel.py`
- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `mf4_analyzer/ui/toolbar.py`
- `mf4_analyzer/ui/main_window.py`
- `mf4_analyzer/ui/dialogs.py`
- `mf4_analyzer/ui/drawers/rebuild_time_popover.py`
- `mf4_analyzer/ui/inspector_sections.py`
- `tests/ui/test_batch_input_panel.py`
- `tests/test_batch_runner.py`
- `tests/ui/test_toolbar.py`
- `tests/ui/test_order_smoke.py`
