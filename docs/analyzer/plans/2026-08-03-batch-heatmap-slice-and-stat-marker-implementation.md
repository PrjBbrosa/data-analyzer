# 批处理谱图切片导出 + 统计标记可读性 · 实施计划

- 设计：[2026-08-03-batch-heatmap-slice-and-stat-marker-design.md](../specs/2026-08-03-batch-heatmap-slice-and-stat-marker-design.md)（v3）
- 基线：`main` @ `d60cdea`
- 目标渲染效果：[2026-08-03-batch-heatmap-slice-render-target.html](../ui-prototypes/2026-08-03-batch-heatmap-slice-render-target.html)

---

## 0. 动手前

**先取测试基线。** CLAUDE.md 已记录 `main` 上 `tests/ui/test_split_*` 一批用例是红的
（`canvas_time.get_visible_xlim()` 返回 `None`）。开工前跑一次并记下失败数，
别把既有失败算到本次改动头上。

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest tests\test_batch_render_qt.py tests\test_batch_render_qt_heatmap.py tests\test_batch_render_qt_ssaa.py tests\test_batch_recipe.py tests\test_batch_validation.py tests\ui\test_batch_chart_statistics.py -q
```

全量套件约 4600 条 / 近 20 分钟，收尾再跑。

---

## 阶段 1 · 统计标记（独立可交付，先落地）

### 1.1 超采样期给散点开启 export mode

`mf4_analyzer/batch_render_qt/_export.py` · `_prepared_for_supersampling`

在既有的 `for item in graphics_scene.items():` 循环里追加：

```python
if isinstance(item, pg.ScatterPlotItem):
    restores.append(partial(item.setExportMode, False))
    item.setExportMode(True, {"antialias": False, "resolutionScale": factor})
    touched = True
```

- **保留** `opts["pen"]` 的加宽：`_style()` 只把 `resolutionScale` 乘到 `size`，
  pen 宽度仍需靠加宽维持（已核对 pg 0.14.0 源码）。两者互补，不重复。
- **只对 `ScatterPlotItem` 开**；全场景开会让 `PlotCurveItem` 读到
  `_exportOpts["antialias"]`，打翻 `_export.py` 顶部注释里那条
  「关原生抗锯齿 + 超采样兜底」的性能取舍。
- `setExportMode(False)` 必须进 `restores` —— 同一个 settled scene 会被渲染多次
  （parity guard 就这么干），残留会污染下一次。

### 1.2 标记与卡片配色

`mf4_analyzer/batch_render_qt/_builder.py` · `_add_time_statistics`（约 1250–1266 行）

```python
marker_specs = []
if "max" in metrics and item.argmax_x is not None and item.maximum is not None:
    marker_specs.append(((item.argmax_x, item.maximum), "#dc2626"))
if "min" in metrics and item.argmin_x is not None and item.minimum is not None:
    marker_specs.append(((item.argmin_x, item.minimum), "#16a34a"))
for point, color in marker_specs:
    marker = pg.ScatterPlotItem(
        symbol="o", size=11.0 * scale,
        pen=pg.mkPen("#ffffff", width=1.6 * scale),
        brush=pg.mkBrush(color),
    )
    marker.addPoints([{"pos": point}])
    marker.setZValue(1200)
    curve.getViewBox().addItem(marker)
```

同文件约 1208 行的表头配色：`#c2410c` → `#b91c1c`，`#0f766e` → `#15803d`。

### 1.3 测试

- `tests/test_batch_render_qt_ssaa.py`：断言 `_prepared_for_supersampling` 期间
  `item._exportOpts["resolutionScale"] == factor`，退出后 `item._exportOpts is False`。
- `tests/ui/test_batch_chart_statistics.py`：渲染 1920×1080 带统计的时域图，
  在 PNG 上量最大值标记的连通红色区域直径 ≥ 10 px。
  `BuiltBatchScene.plot_ink_pixel_count()`（`_builder.py:747`）可作参考实现。
- 现有断言里若写死 `#f97316` / `18.0`，一并更新。

### 1.4 阶段说明

时域批处理 PNG 的字节会变 —— **这是预期内的**，commit message 里写明。
`frozen_batch_acceptance` 的 sha256 是运行时产出，不是仓库里冻结的期望值，重跑即可。

---

## 阶段 2 · PillSwitch 卡片头（独立可交付）

### 2.1 `chart_statistics_panel.py`

1. `from ...widgets.pill_switch import PillSwitch`
2. 摘要行照 `filter_panel.py:48-67` 搭：
   `QWidget#BatchFilterSummary`（QSS 现成，不用新增样式）
   + `QLabel#BatchFilterSummaryTitle`（「图内统计」）
   + `QLabel#BatchFilterSummaryNote`（摘要）
   + `PillSwitch(object_name="batchChartStatisticsEnableSwitch", accessible_name="图内统计")`
3. `self.enabled = QCheckBox("启用")` → 上面那个 PillSwitch。
   **`_sync()` / `get_params()` / `apply_params()` 一行都不用改** —— `PillSwitch` 是 drop-in。
4. 新增 `_refresh_summary()`：
   - 关闭 → `统计关闭 · 图上不加标注`
   - 开启 → `全时段 · 最大/最小/平均` 或 `12.0–48.0 s · 最大/最小`
5. `_sync()` 里把设置区（区间行 + 项目行 + note + context）收进一个容器
   `self._settings`，`setVisible(enabled)`，与 `filter_panel._sync_enabled` 一致。

**保持 QCheckBox 的**：「自动」「最大值」「最小值」「样本平均」（设计 D25）。

### 2.2 测试

`tests/ui/test_batch_chart_statistics.py` 里若有 `isinstance(panel.enabled, QCheckBox)`
或 `panel.enabled.text() == "启用"` 这类断言，改成对 `PillSwitch` 的断言。
功能断言（`setChecked` → `get_params`）不受影响。

---

## 阶段 3 · recipe / 校验（无 UI，纯数据契约）

### 3.1 `mf4_analyzer/batch_recipe.py`

1. `METHOD_PARAM_FIELDS["fft_time"]` 与 `["order_time"]` 各加 `"slice"`。
2. 新增 `SLICE_DEFAULTS = {"enabled": False, "axis": "time", "positions": ()}`。
3. `_normalize_known_value` 加 `slice` 分支：

```python
if field == "slice" and isinstance(value, Mapping):
    raw = dict(value)
    axis = str(raw.get("axis", "time") or "time").strip().lower()
    items = raw.get("positions", ())
    if not isinstance(items, (tuple, list)):
        items = ()
    numbers = [
        float(item) for item in items
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    return {
        "enabled": bool(raw.get("enabled", False)),
        "axis": axis,
        # 排序 + 去重：fingerprint 必须对输入顺序不敏感（设计 D7）
        "positions": sorted(dict.fromkeys(numbers)),
    }
```

4. `normalize_batch_params` 里，`fft_time`/`order_time` 分支：
   `slice` 的 `enabled` 为假时 `pop("slice")`。
   **这一步决定既有预设 fingerprint 是否不变，是本阶段的核心。**

### 3.2 `mf4_analyzer/batch_validation.py`

新增谱图方法的 slice 校验，issue code 见设计 §4.4：
`invalid_slice` / `invalid_slice_axis` / `invalid_slice_positions` /
`too_many_slice_positions` / `slice_positions_required`。
超范围不在这里报（preflight 拿不到数据）。

### 3.3 测试

`tests/test_batch_recipe.py`：
- `slice` 在 `time` 方法上被剔除、在两个谱图方法上保留
- `enabled=False` → 归一化后不含 `slice`，fingerprint 与不带该字段时**相同**
- **`positions=[15, 5, 15]` 与 `[5, 15]` 归一化结果与 fingerprint 相同**
- `enabled=True` → fingerprint 变化

`tests/test_batch_validation.py`：五个 issue code 各一条。

---

## 阶段 4 · 渲染

### 4.1 `_models.py` — 切片计划

纯数据、可单测，不引 Qt：

```python
@dataclass(frozen=True)
class BatchSlicePick:
    index: int          # 矩阵索引
    value: float        # 实际落点
    requested: float    # 用户请求值
    clamped: bool

@dataclass(frozen=True)
class BatchSlicePlan:
    axis: str = "time"                      # "time" | "y"
    picks: tuple[BatchSlicePick, ...] = ()
    merged: int = 0                         # 夹取后被合并掉的位置数

    @property
    def enabled(self) -> bool:
        return bool(self.picks)
```

配套纯函数 `plan_heatmap_slice(x_values, y_values, params) -> BatchSlicePlan`：
按 `axis` 选坐标数组，每个请求值 `argmin(|coords - value|)` 吸附、越界置 `clamped`、
**夹取后再去重一次**（设计 D13），记录合并数量。

放 `_models.py` 而不是 `_builder.py`：那里已 import pyqtgraph，单测要起 Qt。
`_models.py` 目前只依赖 numpy 和 `batch_statistics`。

> **矩阵朝向**：`_extract_heatmap` 返回 row-major，**行 = Y（频率/阶次），列 = X（时间）**
> （`_builder.py:248` 的 `x_major.T`）。所以
> `axis == "time"` → 曲线 = `matrix[:, pick.index]`（横轴 = `y_values`）；
> `axis == "y"`    → 曲线 = `matrix[pick.index, :]`（横轴 = `x_values`）。
> 与单文件 `_apply_slice` 的 `m[:, idx]` / `m[idx, :]` 完全一致。

### 4.2 `_builder.py` · `build_heatmap`

1. 算 `plan`；`not plan.enabled` 时**一行代码都不多走**，`return 4` 保持原样。
2. 主图 stretch 1 → **6**；row 4 建切片图，stretch **3**；`return 6`（footer 落 row 5）。
3. 每个 pick 一条曲线，颜色取 `SLICE_WARM[k]`（`axis=="time"`）或 `SLICE_COOL[k]`。
4. 主图标记线：`axis=="time"` → `angle=90`（竖），`axis=="y"` → `angle=0`（横）；
   **先画 3.6 px 白色底衬，再画 2.0 px 彩线**，与曲线同色，`movable=False`，
   `setZValue` 高于 image item。线宽按 1920 px 导出尺度定，不照抄单文件的
   `width=1`（那是屏幕画布尺度，见设计 D17）。
5. 右侧图例栏（设计 §5.5）：复用 `_StatisticsCard`，放进 §4.3 的 colorbar 占位区，
   栏头写维度名（`固定时间` / `固定频率` / `固定阶次`），每行一个色块 + 位置值，
   被夹取的追加 `·夹取`。
6. 幅值轴 —— 三步（设计 D19/D19b/D20）：

```python
if manual_z:                       # z_auto=False 且 z_floor/z_ceiling 有效
    plot.setYRange(z_floor, z_ceiling, padding=0)   # 逐字保留，不做 nice 取整
else:
    bounds = _slice_amp_bounds(np.concatenate(all_curve_values))  # 剔 DC 死区
    if bounds is None:
        plot.enableAutoRange(axis="y", enable=True)
    else:
        lo, hi = bounds
        step = _nice_per_div((hi - lo) / self.style.tick_density_y) or (hi - lo)
        plot.setYRange(
            math.floor(lo / step) * step,
            math.ceil(hi / step) * step,
            padding=0,
        )
```

**不要用 `_frame_to_nice`。** 它强制恰好 n 等分，在默认 `tick_density_y = 10`
下实测把 `[−99.11, −34.38]` 撑成 `[−100, 0]`（浪费 35%）；
两端取整得到 `[−100, −30]`（浪费 8%），刻度一样整齐。详见设计 D19b。

来源：`_nice_per_div` 从 `mf4_analyzer/ui_kit/ticks_math.py` **直接 import**
（已在 `__all__` 里）；`_slice_amp_bounds` 要从 `heatmap_canvas.py:385`
**复制** 20 行（含 `_SLICE_MAX_SPAN_DB = 200.0`）—— `ui/` 不能被批处理渲染栈 import，
`renderer_import_policy.py` 管着这条边界。复制处的注释指回单文件出处。

`_apply_tick_density` 事后照常跑，范围已 nice，两者自洽，不需要特判。

7. `BuiltBatchScene` 增加 `slice_plan` / `slice_curves` 字段，供测试与数据导出复用。

### 4.3 X 轴对齐（建议拆成独立一步收尾）

新增 `_align_slice_to_heatmap(plot, colorbar)`，在 `layout_callbacks` 里按
colorbar 的 `sceneBoundingRect().width()` 给切片行右侧留等宽占位。
参考 `heatmap_canvas._align_slice_to_main` / `_set_slice_right_spacer`。

**这是本阶段最容易反复的一块。** 建议先做 4.1/4.2（曲线 + 标记线 + 图例），
把对齐作为独立提交收尾。图例栏依赖这块占位 —— 对齐没做完之前，
图例先临时放切片图右上角。

### 4.4 配色常量（`_palette.py`）

```python
SLICE_WARM = ("#dc2626", "#ea580c", "#c026d3", "#a16207")  # axis="time"
SLICE_COOL = ("#2563eb", "#0891b2", "#4f46e5", "#0d9488")  # axis="y"
```

长度 4 与位置上限一致，不需要取模回绕。

### 4.5 warnings

`clamped` / 合并发生时往 `warnings_out` 追加一条：

```
slice.position_clamped: 切片位置 40.000, 50.000 s 超出数据范围 [0.000, 30.000] s，
已取 30.000 s；2 个位置夹取后合并为 1 个
```

`build_heatmap` 已经收 `warnings_out`（colormap 回退在用），沿用即可。

### 4.6 测试

`tests/test_batch_render_qt_heatmap.py`：

- 切片开启 → `len(scene.plots) == 2`；关闭 → `1`
- `axis="time"` + 3 个位置 → 3 条曲线，颜色依次为 `SLICE_WARM[:3]`，
  主图 3 条 `angle==90` 的 `InfiniteLine`
- `axis="y"` → `SLICE_COOL`，主图线 `angle==0`
- 曲线 `getData()` 与 `display_matrix[:, i]` / `[i, :]` 逐点相等
- 超范围 → 落在边界 + warnings 命中 `slice.position_clamped`
- 夹取撞位 → 曲线数少于请求数，warning 说明合并
- **幅值轴端是 `tick_density_y` 步长的整数倍**；手动 z 时 `viewRange()` 等于
  `(z_floor, z_ceiling)` 逐字不变
- 造一个含 −6153 dB DC 死区的矩阵 → 幅值轴下界不被拖到死区
- `order_time` 的轴标签是阶次而非 Hz
- 关闭时渲染出的 PNG 与基线逐字节相同

`tests/test_batch_render_qt.py` 里若有「谱图页面恰好 1 个 plot」的断言，同步放宽。

---

## 阶段 5 · 数据导出

### 5.1 `mf4_analyzer/batch.py`

1. 新增 `_write_workbook(sheets: "dict[str, pd.DataFrame]", path)`，
   与 `_write_dataframe` 并列，同样走 `atomic_write`。
   切片表最多几千行，仍在写入前断言未超 `_XLSX_MAX_DATA_ROWS`。
2. `_Spectro2D` 增加 `to_slice_sheets(plan, *, render_db, reference, facts)`，
   返回 `{"切片信息": df, "<时间|频率|阶次>切片": df}`，
   列名形如 `t=5.00s` / `f=620.0Hz`。
   **切片数值必须来自与渲染同一份矩阵和同一个 plan** —— 不允许两条计算路径。
3. 约 3810 行的 `export_df` 选择处：
   - `spectro is not None` 且 slice 启用 且 `data_extension == "xlsx"` → 工作簿分支
   - `data_extension == "csv"` → 现状 long 表 + `slice.csv_fallback` warning
   - 其余 → 现状
4. `export_frame_factory` 的重试路径同步覆盖工作簿分支
   （`OutputPublishRace` → 重建 sheets）。这条别漏，是发布竞争下的正确性保证。

### 5.2 元信息来源

`切片信息` 要的字段（fs / window / nfft / overlap / weighting / dB 参考）
和页眉 facts 是同一批，`_page.effective_fact_items` 已在做同样的挑选。
**抽一个 GUI-free 的取值函数两边共用**，避免图上写 `NFFT=1024`、表里写别的。

### 5.3 测试

新建 `tests/test_batch_slice_export.py`：

- 切片开启 → 恰好两张表；表名随 `axis` 与方法变化
- 列名与设计 §6.2 一致
- 表里的数值与 `BuiltBatchScene.slice_curves` 的 `getData()` 逐点相等
- 切片关闭 → 数据文件与基线逐字节相同
- csv + 切片开启 → long 表 + warning

---

## 阶段 6 · UI

### 6.1 新文件 `mf4_analyzer/ui/drawers/batch/slice_panel.py`

骨架照阶段 2 改造后的 `chart_statistics_panel.py`（摘要行 + PillSwitch + 折叠）：

- 摘要文字：关闭 `切片关闭 · 仅导出谱图`；开启 `固定时间 · 3 处`
- 第一行 `QComboBox`：`固定时间` / `固定频率`（`order_time` 时 `固定阶次`）
- 第二行 `QLineEdit`，placeholder `5, 15, 25`，右侧单位标签随下拉变（`s` / `Hz` / 空）
- `set_context(method=...)`：切换第二个下拉项的文案与单位表
- `positions_error() -> str`：解析失败 / 超过 4 个 / 空列表，
  文案与实现照 `analysis_panel.source_time_range_error()`
- `get_params()` 返回 `{"slice": {"enabled": bool, "axis": "time"|"y", "positions": [...]}}`

### 6.2 `analysis_panel.py`

- `self._slice = SlicePanel(self)`，加在 `self._chart_statistics` 之后
- `_refresh_for_method`：`setVisible(method in {"fft_time", "order_time"})`
  + `self._slice.set_context(method=method)`
- `get_params()`：谱图方法时 merge `self._slice.get_params()`
- `apply_params()`：无条件转发（面板自己判断）
- `self._slice.changed.connect(self._on_params_changed)`
- 新增 `slice_positions_error()` 转发给 sheet

### 6.3 `sheet.py`

- `_recompute_pipeline_status` 已覆盖 params 变化，无需新接线
- 把 `slice_positions_error()` 接进既有的内联错误汇总
  （和 `source_time_range_error()` 同一处），驱动运行按钮置灰
- ~~输出摘要：切片开启时数据文件描述改成「切片结果」~~ —— **2026-08-03 撤销，前提有误**。
  写计划时假设输出摘要里有「完整矩阵」字样，实际 `output_panel._refresh_output_summary()`
  只输出 `XLSX · PNG 1920×1080 · 冲突自动编号`，讲的是格式不是内容。
  要在那里表达「切片 vs 全矩阵」需要新建「分析面板 → 输出面板」的跨面板管道，
  而切片卡自己的摘要（`固定时间 · 3 处`）就在同一张 sheet 上，已经说清楚了。
  为一个词加管道不划算，本项不做。

### 6.4 测试

新建 `tests/ui/test_batch_slice_panel.py` + 扩 `tests/ui/test_batch_smoke.py`：

- 面板只在两个谱图方法下可见
- 主开关是 `PillSwitch`；关闭时设置区 `isHidden()`
- 下拉切到「固定频率」→ 单位标签变 `Hz`；方法切到 `order_time` → 变「固定阶次」+ 无单位
- `"5, 15, 25"` → `[5.0, 15.0, 25.0]`；`"15,5,15"` → 归一化后 `[5.0, 15.0]`
- 5 个位置 / 格式错误 / 空 → `positions_error()` 非空
- `apply_params` → `get_params` 往返一致
- 切到 `time` 后 params 不再含 `slice`

---

## 阶段 7 · 提示与文档

```
/update-hints
```

- `ui/quickref.py` 「批处理」组新增 `导出切片` 一行
- `ui/hints.py` 本次不动
- `help/ffttime-guide.html`、`help/order-analysis-guide.html`、
  `help/TraceLab-使用说明.html` 三处补切片导出说明
- `docs/analyzer/README.md` 的 Current Product Baseline 段落追加一句

---

## 验证

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest tests\test_batch_render_qt_ssaa.py tests\ui\test_batch_chart_statistics.py -q
```

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest tests\test_batch_recipe.py tests\test_batch_validation.py tests\test_batch_render_qt_heatmap.py tests\test_batch_slice_export.py -q
```

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest tests\ui\test_batch_slice_panel.py tests\ui\test_batch_smoke.py -q
```

收尾全量（约 20 分钟）：

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest -q
```

**真机渲染验收（不可省）。** CLAUDE.md 明确要求视觉问题必须验真实渲染，
offscreen 只能当排版草稿。至少要：

1. 真实 MF4 跑 `fft_time` + `axis="time"` + 3 个位置，
   目视两行对齐、3 条竖线不糊、右栏图例与曲线颜色对应、**幅值轴刻度是整数**
2. 同一份数据跑 `axis="y"`，确认横线 + 横轴与主图共享
3. 跑一次 `time` + 图内统计，PNG 放大到 100% 确认红绿点清晰
4. 各存一份到 `docs/analyzer/reviews/` 作为验收证据

---

## 风险

| 风险 | 应对 |
| --- | --- |
| **切片行与主图 X 轴对不齐**（colorbar 占宽）—— 最可能反复的一块 | 照搬 `_align_slice_to_main` / `_set_slice_right_spacer`；拆成独立提交（§4.3），对齐未完成前图例临时放右上角 |
| 幅值轴 nice 取整后留白过多 | 两端取整最多各浪费一个 step（实测 8–9%）；**不要退回 `_frame_to_nice`**，那是 35–45%。若真机仍偏空，把 `tick_density_y` 上调一档得到更细的 step |
| 4 条曲线 + 4 条标记线把热力图盖住 | 位置上限卡在 4（D9）；标记线 2.0 px + 3.6 px 白底衬；真机验收第 1 项专门看这个 |
| `setExportMode` 影响其他 item | 只对 `ScatterPlotItem` 开，`restores` 必还原；`test_batch_render_qt_ssaa.py` 加断言守住 |
| `PillSwitch` 替换打断既有测试 | 阶段 2 独立提交；只改类型断言，功能断言不受影响 |
| 时域 PNG 字节变化冲掉别人的基线 | 阶段 1 独立提交，commit message 写明「时域统计图字节变化是预期」 |
| 切片幅值轴被 DC bin 压扁 | `_slice_amp_bounds` 那段必须照抄，测试里造含 −6153 dB 死区的矩阵守住 |
| 排序去重改变用户输入顺序引起困惑 | 面板不回写输入框（用户打什么留什么），只在归一化层排序 |

---

## 交付顺序

**阶段 1 + 2 可以立刻交付** —— 都是独立的既有缺陷/一致性修复，与切片零耦合。

阶段 3 → 4 → 5 → 6 → 7 按序推进，其中阶段 4 内部再拆：
先「曲线 + 标记线 + 幅值轴 nice + 图例（临时右上角）」，
再「X 轴对齐 + 图例移入右栏」。
