# 设计：批处理 TimeDomain + 滤波预处理

- 日期：2026-06-26
- 状态：草案（待评审）
- 关联基线：`docs/superpowers/specs/2026-06-25-project-persistence-and-batch-parity-design.md`
- 范围：① 批处理新增 `TimeDomain` 方法；② 批处理新增滤波预处理；③ 「从当前单次填入」支持时域当前选择和当前滤波配置。

---

## 1. 背景与目标

6/25 的项目滤波持久化已经把主界面时域滤波状态写入 `.tlproj`，批处理也已经对齐 FFT / FFT-vs-Time / 阶次的计权、dB、平均等分析参数。但批处理面板仍没有两个用户可见能力：

1. **时域批量导出**：用户不能把批处理当作「多个文件 × 多个信号」的时域 CSV/Excel/PNG 导出工具。
2. **批处理滤波**：主界面的时域滤波已经能保存/恢复，但批处理没有入口选择「先滤波，再导出/分析」。

本设计按用户确认把 6/25 spec 的非目标「不把滤波接入 FFT/阶次/导出」升级为新的后续范围：**滤波进入批处理，但定位为信号预处理，不改变各分析面板自身参数语义**。

### 1.1 目标

- 批处理方法列表新增 `time`（UI 显示「时域」），与现有 `fft` / `fft_time` / `order_time` 并列。
- 批处理 INPUT 区增加「信号预处理」滤波块，默认关闭；启用后复用 `FilterSpec`、`nyquist_guard()`、`filters.apply()`。
- `time` 方法输出时域数据和时域 PNG；开启滤波时可导出/绘制原始、滤波后或两者。
- FFT / FFT-vs-Time / 阶次在滤波开启时使用滤波后的信号继续计算；RPM 通道不滤波。
- 「从当前单次填入」在时域模式下能带入当前勾选信号、时间范围、滤波类型/截止/阶数/显示开关。

### 1.2 非目标

- 不做自定义 X 轴批处理导出。批处理 `time` 的 X 轴固定为文件时间轴 `fd.time_array` 或 `np.arange(n) / fs` fallback。
- 不把主界面时域 overlay 的 axis-group、颜色、GPU、统计条、游标、标注带入批处理。
- 不滤波 RPM 通道；Order 只对目标信号做预处理，RPM 只用于转速轴/阶次计算。
- 不改项目 `.tlproj` 的滤波 schema；批处理滤波存在于 batch preset `params["filter"]` 内。
- 不支持「当前时域勾选的精确 `(fid, channel)` 配对列表」作为新 preset 数据模型；当前填入沿用批处理 free-config 语义：文件集合 × 目标信号名集合。

---

## 2. 当前代码事实

### 2.1 批处理方法

- `BatchRunner.SUPPORTED_METHODS` 当前是 `{'fft', 'order_time', 'fft_time'}`（`mf4_analyzer/batch.py`）。
- UI 方法按钮来自 `_METHODS`，参数行来自 `_METHOD_FIELDS`（`mf4_analyzer/ui/drawers/batch/method_buttons.py`）。
- OutputPanel 轴文案来自 `_AXIS_CONTEXTS`（`mf4_analyzer/ui/drawers/batch/output_panel.py`）。

### 2.2 时域与滤波

- 主界面时域数据构建在 `MainWindow._build_time_plot_data()`。
- 现有行为是：先按时间范围裁剪，再对裁剪后的 `sig` 用 `nyquist_guard(spec, fs)` + `filters.apply(sig, spec, fs)` 生成滤波 companion。
- `FilterSpec` 已有 `to_dict()/from_dict()`；滤波 UI 状态为 `enabled/spec/show_original/show_filtered`。

### 2.3 批处理导出

- `_run_one()` 负责按 method 计算数据、写 CSV/XLSX、写 PNG。
- `_write_dataframe()` 已支持 CSV/XLSX。
- `_build_export_scene()` 已支持 FFT 线图和 2D heatmap；`time` 可复用 pyqtgraph line plot 分支。

---

## 3. 参数 schema

批处理 preset 的滤波参数放在 `AnalysisPreset.params["filter"]`：

```json
"filter": {
  "enabled": true,
  "spec": {
    "kind": "low",
    "order": 4,
    "cutoff": 100.0,
    "cutoff_lo": 0.0,
    "cutoff_hi": 0.0
  },
  "show_original": true,
  "show_filtered": true
}
```

含义：

- `enabled=false` 或缺少 `filter`：批处理保持现状，不预处理。
- `spec` 使用 `FilterSpec.from_dict()` 解析，缺字段按当前默认值兜底。
- `show_original/show_filtered` 只影响 `time` 方法的数据和图片输出。
- 对 `fft` / `fft_time` / `order_time`，只读取 `enabled/spec`；show flags 被忽略。

---

## 4. 数据流设计

### 4.1 通用预处理

新增批处理内部 helper：

- `_filter_state(params) -> dict`
- `_filter_spec_from_params(params) -> FilterSpec | None`
- `_prepare_signal(sig, time, fs, params, *, apply_filter: bool = True) -> tuple[np.ndarray, np.ndarray, float, FilterSpec | None]`

顺序固定：

1. `_apply_time_range(sig, time, params)` 先裁剪。
2. 用裁剪后的 `time` 和 `fs` 解析有效采样率。
3. 如果滤波关闭，返回原始段。
4. 如果滤波开启，先 `nyquist_guard(spec, fs)`，再 `filters.apply(sig, guarded_spec, fs)`。
5. 如果 band/bandstop 下限不小于上限，当前 task blocked，错误信息包含「下限必须小于上限」。

这个顺序刻意镜像主界面 `_build_time_plot_data()`，避免同一个时间范围下屏幕和批处理边界行为不同。

### 4.2 TimeDomain 方法

新增 method key：`time`。

数据导出采用 long table，列固定为：

```text
time_s, series, value
```

规则：

- 滤波关闭：只输出 `series="original"`。
- 滤波开启 + `show_original=true`：输出原始段。
- 滤波开启 + `show_filtered=true`：输出滤波段。
- 两个 show flags 都为 false：task blocked，提示「时域导出至少需要原始或滤波后一项」。

PNG：

- `original` 使用实线。
- `filtered` 使用同色虚线或次要色虚线。
- X 轴：`Time (s)`。
- Y 轴：`Amplitude`。
- 支持 OutputPanel 的 `x_auto/x_min/x_max/y_auto/y_min/y_max`。
- `z_*` 和 `amplitude_mode` 对 `time` PNG 无效，但保留在 params 中不报错。

### 4.3 FFT / FFT-vs-Time / Order

滤波开启时：

- `_run_one()` 在进入各计算方法前把目标信号替换为滤波段。
- `fft` 用滤波后的 `sig` 调 `_compute_fft_dataframe()`。
- `fft_time` 用滤波后的 `sig/time/fs` 调 `_compute_fft_time_spectro()`。
- `order_time` 用滤波后的目标信号调 `_compute_order_time_spectro()`；`rpm` 只跟随时间范围裁剪，不做滤波。

导出文件名不额外追加 filter suffix；是否滤波由 preset 和数据列/图片内容决定。将来需要更强可追溯性时，可在 CSV/XLSX metadata 或文件名中追加短 suffix，另立小变更。

---

## 5. UI 设计

### 5.1 方法按钮

方法按钮调整为：

| method key | UI 文案 |
|---|---|
| `time` | 时域 |
| `fft` | FFT |
| `fft_time` | FFT vs Time |
| `order_time` | 阶次 |

`order_time` 的内部 key 不再直接显示给用户。

### 5.2 Analysis 面板

`time` 没有专属分析参数；选择 `time` 时显示一行轻量提示「时域导出使用 INPUT 中的目标信号、时间范围与预处理设置」。这个提示是参数区内容，不是帮助文案弹窗。

现有方法字段保持：

- FFT：`window/nfft/weighting`
- FFT vs Time：`window/nfft/overlap/remove_mean/weighting`
- 阶次：`window/nfft/max_order/order_res/time_res/weighting`

### 5.3 INPUT 预处理块

在 `InputPanel` 的「时间范围」下方新增 `BatchFilterPanel`：

- 标题：`信号预处理`
- 开关：`滤波`
- 类型：低通 / 高通 / 带通 / 带阻
- 截止：单截止或上下限，与 `FilterPanel` 行切换一致
- 阶数：2 / 4 / 6 / 8
- 时域输出：`原始`、`滤波后` 两个 checkbox，仅在 method=`time` 时显示

默认：

- 滤波关闭。
- 类型低通、截止 100 Hz、阶数 4。
- 原始=true、滤波后=true。

### 5.4 OutputPanel 轴上下文

`_AXIS_CONTEXTS` 增加 `time`：

- X：时间 (s)，summary「全时段」
- Y：幅值，summary「自动范围」
- Z：不适用，但控件可保留禁用或隐藏。推荐隐藏 Z row，避免用户以为时域线图有色阶。

若隐藏 Z row 改动过大，第一版可保留 Z row 但 disabled；验真截图必须确认它不抢视觉注意力。

### 5.5 从当前单次填入

当 `toolbar.current_mode() == "time"`：

- 从 `channel_list.get_checked_channels()` 读取当前勾选。
- `file_ids` 取勾选里出现过的 fid。
- `target_signals` 取勾选里的 channel name 去重排序。
- 读取 `inspector.top.range_enabled()/range_values()`。
- 读取 `inspector.filter_panel` 的 `enabled/spec/show_original/show_filtered`，写入 `params["filter"]`。
- 返回 `AnalysisPreset.free_config(...)` 再用 `dataclasses.replace(..., file_ids=file_ids)` 注入运行时文件集合。

这是 free-config，不是 current-single。原因：时域当前选择天然可以多文件多信号，现有 `from_current_single()` 只能表达一个 `(fid, channel)`。

---

## 6. 错误处理

- 目标信号缺失：沿用当前 per-task blocked 行为。
- 时间范围裁剪后为空：task blocked，提示「当前时间范围内无可导出数据」。
- 滤波截止越界：`nyquist_guard()` 钳制后继续；不弹窗。后续可把 message 写入 result，但第一版不扩大 `BatchItemResult` schema。
- band/bandstop 下限大于等于上限：task blocked。
- `time` 方法没有时间轴：用 `np.arange(n) / fs` fallback；若 fs 无效则 task blocked，提示「缺少有效采样率」。

---

## 7. 测试与验收

### 7.1 单元/集成测试

- `BatchRunner.SUPPORTED_METHODS` 包含 `time`。
- `time` 方法 CSV long table shape 正确。
- `time` 方法滤波开启时输出 original + filtered 两个 series。
- `time` 方法两个 show flags 都 false 时 blocked。
- `fft` / `fft_time` / `order_time` 在滤波开启时使用滤波后的目标信号。
- RPM 不被滤波。
- `BatchFilterPanel` get/apply round-trip。
- method 切换到 `time` 时 RPM row 隐藏，TimeDomain output checkboxes 显示，OutputPanel 切到 time 轴文案。
- `_build_current_batch_preset()` 在 time 模式返回 free_config preset，包含 file_ids、target_signals、time_range、filter。

### 7.2 视觉验真

离屏截图保存到 `.state/screenshots/batch-timedomain-filter/`：

- 批处理总览 method=`time`。
- method=`time` 且滤波开启，显示 original/filtered checkbox。
- method=`fft` 且滤波开启，显示滤波参数但不显示时域输出 checkbox。

### 7.3 完成判据

- Focused tests 通过：`tests/test_batch_runner.py`、`tests/test_filters.py`、`tests/ui/test_batch_input_panel.py`、`tests/ui/test_batch_method_buttons.py`、`tests/ui/test_batch_toolbar.py`、`tests/ui/test_batch_smoke.py`。
- `git diff --check` 通过。
- 至少一张 offscreen 截图确认 `time` 和滤波预处理实际渲染，不用只看单测。

---

## 8. 风险

- **当前时域多选语义**：free-config 会按 file_ids × target_signals 展开，不能精确保留「只在某文件勾某通道」的稀疏配对。这个限制与现有批处理模型一致，先不扩 schema。
- **滤波边界效应**：按当前时域行为先裁剪再滤波，短窗口可能有边界效应；这是屏幕与批处理一致性的取舍。
- **OutputPanel Z row**：线图不需要 Z。若隐藏 Z row 影响现有轴组件过大，第一版 disabled，第二版再细化。
- **运行时间**：滤波会给每个 task 增加一次 FFT-domain apply；需要保持文件级 lazy load 和 disk cache eviction 不变。
