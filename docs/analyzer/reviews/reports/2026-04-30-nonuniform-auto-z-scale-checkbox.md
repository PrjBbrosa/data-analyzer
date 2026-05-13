# 2026-04-30 非均匀时间轴自动处理、批处理 Z 色阶单位、复选框可见性优化报告

## 背景

本轮针对用户反馈的三个问题做了专项优化：

1. 单文件处理和批处理遇到 `non-uniform time axis` 时不应再弹阻塞提示或整批失败，应自动按计算出的采样频率继续处理。
2. 勾选项的复选框不够明显，尤其在坐标轴设置里的“自动”项上，视觉上难以判断是否已勾选。
3. 批处理 OUTPUT 的 Z 色阶只有上下限设置，缺少和 inspector 一致的 `dB / Linear` 单位选择，并且导出的图片渲染没有接入这个选项。

## 根因分析

### 1. 单文件非均匀时间轴仍然走弹窗确认

单文件 FFT/FFT vs Time 的入口会调用 `MainWindow._check_uniform_or_prompt()`。旧逻辑发现 `fd.is_time_axis_uniform()` 为 `False` 后，会：

- 用 `fd.suggested_fs_from_time_axis()` 预填 `fd.fs`；
- 弹出“重建时间轴” popover；
- 用户接受后才调用 `fd.rebuild_time_axis(new_fs)`；
- 用户取消则直接中断计算。

这导致单文件处理仍然会出现阻塞确认，和“后续自动按照计算采样频率处理”的期望不一致。

### 2. 批处理 FFT vs Time 直接把 jitter 时间轴传入 SpectrogramAnalyzer

批处理 `BatchRunner._compute_fft_time_dataframe()` 直接调用：

```python
SpectrogramAnalyzer.compute(signal=sig, time=time, params=sp, ...)
```

`SpectrogramAnalyzer` 会严格校验 `time` 与 `fs` 的一致性。只要相邻时间间隔的相对 jitter 超过 `DEFAULT_TIME_JITTER_TOLERANCE`，就会抛出：

```text
non-uniform time axis: relative_jitter=... exceeds tolerance=...
```

批处理 runner 捕获异常后把每个任务标为 blocked，因此截图中三个文件全部失败。

### 3. OUTPUT 的 Z 色阶未保存 amplitude mode

上一轮已经把 X/Y/Z 轴范围加入批处理 OUTPUT，但 `OutputPanel.axis_params()` 只包含：

- `x_auto/x_min/x_max`
- `y_auto/y_min/y_max`
- `z_auto/z_floor/z_ceiling`

没有 `amplitude_mode`，因此批处理图片无法知道用户想用 `dB` 还是 `Linear`。同时 `_write_image()` 对 `fft_time` 图片是强制 dB，用户无法切换回线性幅值。

### 4. QCheckBox 只有文本样式，没有 indicator 样式

`style.qss` 之前只设置了：

```qss
QCheckBox,
QRadioButton {
    spacing: 8px;
    color: #334155;
    background-color: transparent;
}
```

没有显式定义 `QCheckBox::indicator`。在当前 Fusion/QSS 组合下，复选框勾选状态不够突出。

## 修改内容

### 单文件：非均匀时间轴自动重建

修改文件：

- `mf4_analyzer/ui/main_window.py`

保留原方法名 `_check_uniform_or_prompt()` 以兼容现有调用，但行为改为自动处理：

1. 如果 `fd.is_time_axis_uniform()` 为 `True`，直接放行。
2. 如果为 `False`，调用 `fd.suggested_fs_from_time_axis()` 获取 median-dt 采样率估计。
3. 调用 `fd.rebuild_time_axis(new_fs)` 生成 `arange(n) / new_fs` 的均匀时间轴。
4. 清理对应文件的 FFT vs Time cache。
5. 将新 Fs 推回 `fft_ctx`、`fft_time_ctx`、`order_ctx` 中当前文件对应的上下文。
6. 更新时间范围上限并刷新主时间图。
7. 通过 status bar / info toast 告知“已自动处理”，不再弹出阻塞 popover。

手动点击 inspector 里的“重建时间轴”按钮仍然保留原 popover 逻辑，不影响用户主动调整 Fs。

### 批处理：FFT vs Time 自动生成均匀时间轴

修改文件：

- `mf4_analyzer/batch.py`

新增批处理内部辅助逻辑：

- `_suggest_fs_from_time_axis(time, fallback_fs)`
  - 和 `FileData.suggested_fs_from_time_axis()` 一致，使用正向时间间隔的 median dt 估算 Fs。
- `_uniform_time_axis_for_spectrogram(time, fs, length)`
  - 先用 `SpectrogramAnalyzer._validate_time_axis()` 做同源校验；
  - 如果校验通过，保留原时间轴；
  - 如果失败原因是 `non-uniform time axis`，使用建议 Fs 生成均匀轴；
  - 返回新的 `(time, fs)` 给 `SpectrogramParams` 和 compute 使用。

`_compute_fft_time_dataframe()` 现在会先执行上述转换，再调用 `SpectrogramAnalyzer.compute()`，因此批处理不会再因为截图里的 jitter 错误整批 blocked。

### 批处理 OUTPUT：增加 Z 色阶 dB / Linear

修改文件：

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/batch.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py` 已通过 `axis_params()` 自动合并，无需额外改动调用层

界面新增：

- `OutputPanel.combo_amp_unit`
- Z 色阶行从 `[自动][min][→][max]` 扩展为 `[自动][min][→][max][dB/Linear]`
- 默认值为 `dB`

参数保存新增：

```python
"amplitude_mode": "amplitude_db"  # dB
"amplitude_mode": "amplitude"     # Linear
```

preset 导入恢复新增：

- `amplitude_mode` 包含 `db` 时恢复为 `dB`
- 否则恢复为 `Linear`

图片渲染新增：

- `_write_image()` 读取 `params["amplitude_mode"]`
- `amplitude_db` / `Amplitude dB`：按 `20 * log10(amplitude / db_reference)` 渲染，colorbar 显示 `Amplitude (dB)`
- `amplitude` / `Amplitude`：保留线性幅值，colorbar 显示 `Amplitude`
- 旧调用没有 `amplitude_mode` 时保持兼容：`fft_time` 默认 dB，其他热力图默认 Linear

### 全局复选框可见性优化

修改文件：

- `mf4_analyzer/ui/style.qss`
- `mf4_analyzer/ui/icons.py`

新增 QSS：

- `QCheckBox::indicator`
- `QCheckBox::indicator:hover`
- `QCheckBox::indicator:checked`
- `QCheckBox::indicator:disabled`
- `QCheckBox::indicator:checked:disabled`

视觉规则：

- 未选中：16px 白底方框，灰色边框
- hover：蓝色边框，浅蓝背景
- 选中：蓝底 + 白色 check 图标
- disabled：灰色弱化状态

新增 QSS 图标缓存占位：

- `ICON_CHECKBOX_CHECKED`
- `ICON_CHECKBOX_CHECKED_DISABLED`

这些图标沿用现有 `qtawesome -> PNG -> QSS image:url(...)` 的缓存机制，和下拉框箭头的实现保持一致。

## 测试覆盖

新增/更新测试覆盖以下行为：

- 批处理 FFT vs Time 遇到 jitter 时间轴时应自动处理并输出 dataframe。
- 批处理图片导出可按 `amplitude_mode="amplitude"` 渲染 Linear Z 色阶。
- 批处理 `get_preset()` 会保存 OUTPUT 的 `amplitude_mode`。
- 批处理 `apply_preset()` 会恢复 OUTPUT 的 `dB / Linear` 下拉框。
- `style.qss` 必须包含明确的 `QCheckBox::indicator` 和 checked 图标规则。
- 单文件 FFT vs Time 遇到非均匀时间轴时不再打开 rebuild popover，而是自动重建并计算。
- 自动重建使用 `suggested_fs_from_time_axis()` 返回的 Fs。
- 手动 rebuild popover 的几何测试仍保留，保证主动点击按钮时弹窗仍在屏幕内。

## 验证结果

执行命令：

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python - <<'PY'
from PyQt5.QtWidgets import QApplication
from mf4_analyzer.ui.icons import ensure_icon_cache, render_qss_template
from pathlib import Path
app = QApplication([])
paths = ensure_icon_cache()
assert 'ICON_CHECKBOX_CHECKED' in paths
assert Path(paths['ICON_CHECKBOX_CHECKED']).exists()
qss = render_qss_template(Path('mf4_analyzer/ui/style.qss').read_text(encoding='utf-8'), paths)
assert '{{ICON_CHECKBOX_CHECKED}}' not in qss
print('checkbox icon ok')
PY
```

结果：

```text
checkbox icon ok
```

执行全量测试：

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

结果：

```text
433 passed, 48 warnings in 16.22s
```

48 个 warning 是既有 matplotlib/DejaVu Sans 中文 glyph 缺失提示，本轮未引入新的测试失败。
