# 分析参数一致性与 dB 参考布局设计

状态：草案
日期：2026-06-21
对应 plan：`docs/superpowers/plans/2026-06-21-analysis-weighting-levels-db-reference.md`

## 背景

当前 FFT / FFT-vs-Time / Order 三个分析 section 已经有 A 计权入口，但
近期使用音视频音轨时暴露了三类问题：

1. 拖动 FFT-vs-Time / Order 色阶后，`频率加权` 会从 `A` 被改成 `None`。
2. 拖动到某个色阶显示状态后，用同样的色阶范围重新计算，画面可能完全不同。
3. `dB 参考` 只存在于 FFT-vs-Time，而且被单独放在「幅值」标题组里；FFT
   和 Order 没有同等入口。

这三类问题都发生在右侧 inspector 参数与渲染/计算之间的边界：部分 UI
回写不应该覆盖未携带的参数，显示参数应该能稳定复现当前画面，dB 参考值
应该在三个频域分析里有一致位置和一致语义。

## 当前证据

- 色阶拖动入口是
  `mf4_analyzer/ui/main_window/_analysis_mixin.py::_on_analysis_levels_dragged`，
  它只向 `ctx.apply_params(...)` 传入 `z_auto/z_floor/z_ceiling`。
- `FFTContextual.apply_params`、`FFTTimeContextual.apply_params`、
  `OrderContextual.apply_params` 当前都使用
  `d.get('weighting', 'None')`，所以任何不带 `weighting` 的局部 dict 都会
  把当前计权重置为 `None`。
- FFT-vs-Time 的 `spin_db_ref` 已存在并进入 `SpectrogramParams.db_reference`；
  但 UI 结构是单独的「幅值」组。
- FFT 线图 dB 显示当前使用 `20log10(amp / amp.max())`，不是
  `20log10(amp / db_reference)`。
- Order 热图 dB 显示当前走 `PgHeatmapCanvas.plot_or_update_heatmap` 的
  `amplitude_db` 分支，该分支也用当前矩阵最大值作为参考。

## 目标

1. **局部参数回写安全**：
   - `apply_params(partial_dict)` 只修改 dict 中显式存在的字段。
   - 缺失 `weighting` 不再等价于 `weighting='None'`。
   - 旧 preset / 旧项目缺 `weighting` 的兼容语义仍保持在 preset/load 边界：
     旧数据缺键默认 `None`，但普通局部 UI 回写必须保留当前值。

2. **色阶拖动与重算一致**：
   - 拖 colorbar 只把 Z 范围回写到 inspector，不改变计算参数。
   - 若计算前为 `A` 计权，拖色阶后再次计算仍然使用 `A`。
   - FFT-vs-Time / Order 的锁定色阶、分屏色阶传播仍由
     `AnalysisSectionPage` 负责；MainWindow 只做聚焦 pane 的 inspector echo。

3. **dB 参考布局与语义统一**：
   - FFT-vs-Time 去掉独立「幅值」标题组。
   - `dB 参考` 直接放在 `频率加权` 下方。
   - FFT / FFT-vs-Time / Order 三段都显示 `频率加权` 和 `dB 参考`，顺序一致。
   - FFT 和 Order 的 dB 显示改为 `dB re <db_reference>`，不再隐式使用
     当前结果最大值作为参考。

4. **全局横展 / 查看全部不引入同类污染**：
   - `Home` / 右键 `查看全部` / 联动缩放只改变 ViewBox 可见范围。
   - 这些操作不调用 inspector `apply_params()`，不得改变 `weighting` 或
     `db_reference`。
   - 交互缩放仍是临时视野状态；重算或查看全部回到 inspector 设定范围，
     本轮只增加回归证明，不改变该交互契约。

## 非目标

- 不引入 SPL 标定、麦克风灵敏度、声压级总量或声级积分。
- 不改变 A 计权算法。
- 不改变 FFT-vs-Time 的时间覆盖 extents、slice 逻辑或热图插值方式。
- 不把热图交互缩放持久化为 inspector X/Y 手动范围。
- 不重构 inspector section 的整体布局组件。

## 详细设计

### 1. `apply_params` 与 preset load 分离

三类 contextual 都保留两个不同语义：

- `apply_params(d)`：普通状态恢复、view switch、colorbar echo、局部 UI 回写。
  它只应用显式 key。`weighting` 缺失时保留现值。
- `_apply_preset_values(d)`：preset / legacy payload 入口。为兼容旧 preset，
  缺失 `weighting` 仍按 `None` 处理。

实现规则：

```python
if 'weighting' in d:
    self._apply_weighting_value(d['weighting'])
```

只用于 `apply_params`。

`_apply_preset_values` 可继续使用：

```python
self._apply_weighting_value(d.get('weighting', 'None'))
```

这样旧 preset 行为不变，但拖色阶这类局部 dict 不再污染计权。

### 2. 色阶拖动一致性

`_on_analysis_levels_dragged(section, pane_idx, lo, hi)` 当前只需要继续传：

```python
{
    'z_auto': False,
    'z_floor': float(lo),
    'z_ceiling': float(hi),
}
```

修复点在 contextual 的 `apply_params`。不在 MainWindow 里补传
`weighting`，因为那会把一个局部 echo 路径变成“需要知道所有字段”的全量
同步，后续仍会漏别的字段。

验收行为：

- `FFTTimeContextual.set_weighting_default('A')` 后调用
  `apply_params({'z_auto': False, 'z_floor': -39.03, 'z_ceiling': -9.03})`，
  `get_params()['weighting']` 仍为 `A`。
- `OrderContextual` 同样成立。
- `FFTContextual.apply_params({'nfft': 4096})` 也不改变当前 weighting。
- `MainWindow._on_analysis_levels_dragged('fft_time', 0, ...)` 与
  `MainWindow._on_analysis_levels_dragged('order', 0, ...)` 保留 weighting。

### 3. dB 参考 UI 布局

三个 section 的主参数表单都采用同一顺序：

```text
...
频率加权: [None/A]
dB 参考:  [1.0]
...
```

FFT-vs-Time：

- 移除单独的 `QGroupBox("幅值")`。
- 复用已有 `self.spin_db_ref`，创建位置从「幅值」组移动到时频参数 form 中，
  紧跟 `combo_weighting`。
- 保留 tooltip：`0 dB 对应的线性幅值，仅平移 dB 刻度、不改波形。`
- `get_params` / `_collect_preset` / `apply_params` / `_apply_preset_values`
  的 `db_reference` 语义不变。

FFT：

- 新增 `self.spin_db_ref = CompactDoubleSpinBox()`，范围、精度、默认值与
  FFT-vs-Time 一致：`1e-9..1e9`，`decimals=6`，默认 `1.0`。
- 在 `get_params()` / `current_params()` / `_collect_preset()` 中包含
  `db_reference`。
- 在 `apply_params()` / `_apply_preset_values()` 中应用显式 `db_reference`。
- `db_reference` 是显示参数，不进入 FFT compute cache key。

Order：

- 新增 `self.spin_db_ref`，布局紧跟 `combo_weighting`。
- 在 `current_params()` / `_collect_preset()` / `apply_params()` /
  `_apply_preset_values()` 中包含并恢复 `db_reference`。
- `get_params()` 可以包含 `db_reference` 以便 view state / preset round-trip
  一致；但 Order compute cache key不应因为 dB 参考变化而失效。

### 4. dB 参考渲染语义

FFT：

- 抽出一个小 helper，例如 `_amplitude_to_db(amp, reference)`，语义为：
  `20 * log10(max(abs(amp), eps) / reference)`。
- `_do_fft_single()` 和 `_fft_entry_from_cache()` 都使用同一 helper。
- `amp_for_xlim` 继续保留线性 amplitude，自动 X 范围不受 dB 参考影响。
- `_fft_render_signature()` 需要把 display-only `db_reference` 纳入签名，
  否则离开再回到 FFT 页可能跳过重渲染。

FFT-vs-Time：

- 保持现有 `SpectrogramAnalyzer.amplitude_to_db(result.amplitude, db_ref)`。
- 只移动控件位置，不改变计算和 cache 行为。

Order：

- 不把 `db_reference` 加入 `COTParams`，因为 COT 结果矩阵仍是线性幅值，
  dB 参考只影响显示。
- `_render_order_on()` 在 `amplitude_mode == 'Amplitude dB'` 时，把
  `result.amplitude.T` 转成 `20log10(matrix / db_reference)` 后以
  `amplitude_mode='amplitude'` 传给 `plot_or_update_heatmap`，避免 canvas
  再次按矩阵最大值归一化。
- dB 色标 label 应显示 `Amplitude (dB re <db_reference>)` 或保持现有英文
  标签风格中的等价表述。
- Linear 模式仍传线性矩阵，不使用 `db_reference`。

### 5. 全局横展 / 查看全部回归边界

增加只读回归证明：

- `PgHeatmapCanvas.reset_view_to_data_extents()` 不触发 `levels_changed`。
- `AnalysisSectionPage.set_linked(True/False)` 不触发 inspector
  `apply_params`。
- `MainWindow._on_analysis_levels_dragged` 是唯一从 heatmap colorbar 直接
  回写 Z 参数到 contextual 的路径。

这保证“全局横展”类操作不会产生和色阶拖动类似的 `weighting=None` 污染。

## 测试策略

重点测试放在现有文件中，避免新建分散测试：

- `tests/ui/test_weighting_ui.py`
  - 修改旧的 `ctx.apply_params({}) -> None` 预期，改为保留当前 weighting。
  - 新增三类 contextual 的 partial apply regression。
  - 新增 MainWindow 色阶拖动保留 weighting regression。

- `tests/ui/test_inspector.py`
  - FFT / FFT-vs-Time / Order 标签顺序测试：`频率加权:` 后紧跟 `dB 参考:`。
  - FFT-vs-Time 不再出现独立「幅值」group 标题。
  - FFT / Order 都暴露 `spin_db_ref` 且 tooltip 含 `dB`。

- `tests/ui/test_main_window_smoke.py`
  - FFT dB 显示使用 `db_reference`，不是 `amp.max()`。
  - `_fft_entry_from_cache()` 与 `_do_fft_single()` 使用同一转换。
  - Order `_render_order_on()` 在 dB 模式用 `db_reference` 生成显示矩阵。

- `tests/ui/test_pg_heatmap_canvas.py` 或 `tests/ui/test_analysis_section_page.py`
  - `Home` / `查看全部` / `set_linked` 不触发 `levels_changed` 或
    `apply_params` 污染的边界测试。

## 验收标准

- 音视频导入后三个 section 的推荐 preset 默认 `A`，拖色阶后仍为 `A`。
- 拖到 `-39.03 -> -9.03` 一类手动色阶后再次计算，`weighting` 不变；
  画面差异不再来自 A/None 参数切换。
- FFT-vs-Time 的「幅值」标题消失，`dB 参考` 出现在 `频率加权` 下方。
- FFT 和 Order 同样有 `dB 参考` 输入。
- FFT / Order 的 dB 模式以 `db_reference` 为参考值，Linear 模式不受影响。
- Home / 查看全部 / 联动缩放不改变 `weighting` 或 `db_reference`。
