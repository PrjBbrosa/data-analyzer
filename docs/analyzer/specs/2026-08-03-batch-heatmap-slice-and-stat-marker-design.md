# 批处理谱图切片导出 + 统计标记可读性 · 设计

- 日期：2026-08-03（v3：单一切片维度 + nice-step 幅值轴 + PillSwitch 卡片头）
- 基线：`main` @ `d60cdea`，TraceLab v7.9.2
- 涉及方法：`fft_time`（FFT-vs-Time）、`order_time`（Order-vs-Time）；`time` 受第 3、7.4 节影响
- 不涉及：`fft`（现状数据导出已确认有意义，保持不变）

---

## 1. 目标

1. **谱图的数据文件从「摊平的长表」改成「切片结果」** —— 长表对人和 Excel 都不可用。
2. **导出图上补一条切片曲线图**，同一维度上可切多个位置叠加对比。
3. **修复时域图内统计的极值标记看不清** —— 根因不是配色，是超采样把标记缩小了 3 倍。
4. **卡片主开关统一成 PillSwitch**，对齐「预处理」那张卡的范式。

---

## 2. 现状事实

| 事实 | 位置 |
| --- | --- |
| 谱图数据导出 = `spectro.to_long_dataframe()`，long 三列 | [batch.py:3818](../../../mf4_analyzer/batch.py#L3818)、[batch.py:4935](../../../mf4_analyzer/batch.py#L4935) |
| 超过 1,048,575 行时切成 `数据1 / 数据2` 多 sheet | [batch.py:4858](../../../mf4_analyzer/batch.py#L4858) |
| UI 的 `data_format` 硬编码 `"xlsx"` | [output_panel.py:904](../../../mf4_analyzer/ui/drawers/batch/output_panel.py#L904) |
| 谱图渲染只有热力图 + colorbar，全包无 slice 代码 | [_builder.py:1464](../../../mf4_analyzer/batch_render_qt/_builder.py#L1464) |
| 页面行布局：0/1/2 页眉，3 图，4 页脚 | `finish(footer_row=...)` |
| `_extract_heatmap` 返回 row-major，行=Y（频率/阶次），列=X（时间） | [_builder.py:248](../../../mf4_analyzer/batch_render_qt/_builder.py#L248) |
| 图内统计只属于 `time` 方法 | [analysis_panel.py:258](../../../mf4_analyzer/ui/drawers/batch/analysis_panel.py#L258)、[batch_recipe.py:75](../../../mf4_analyzer/batch_recipe.py#L75) |
| 统计极值标记：空心圈，`size=18*scale`，近白填充 | [_builder.py:1250](../../../mf4_analyzer/batch_render_qt/_builder.py#L1250) |
| 导出走 3× 超采样再缩回 | [_export.py:21](../../../mf4_analyzer/batch_render_qt/_export.py#L21) |
| `PillSwitch` 是 `QCheckBox` 的 drop-in（同 `toggled/isChecked/setChecked`） | [pill_switch.py:14](../../../mf4_analyzer/ui/widgets/pill_switch.py#L14) |
| 「预处理」卡范式：标题 + 摘要 + 开关，关闭即折叠设置区 | [filter_panel.py:48](../../../mf4_analyzer/ui/drawers/batch/filter_panel.py#L48)、[filter_panel.py:147](../../../mf4_analyzer/ui/drawers/batch/filter_panel.py#L147) |
| 逗号分隔数值输入已有先例（源数据区间 `0.0, 120.0 s`） | [analysis_panel.py:198](../../../mf4_analyzer/ui/drawers/batch/analysis_panel.py#L198) |
| `_nice_per_div(v)` 把步长向上取到 1/2/2.5/5/10 系列 | [ticks_math.py:29](../../../mf4_analyzer/ui_kit/ticks_math.py#L29) |
| `_frame_to_nice(lo, hi, n)` 强制**恰好 n 等分**（示波器格线语义）—— 见 D19b，本特性**不用**它 | [ticks_math.py:119](../../../mf4_analyzer/ui_kit/ticks_math.py#L119) |
| `nice_ticks_within` 永不加宽区间（手动范围必须逐字保留） | [ticks_math.py:149](../../../mf4_analyzer/ui_kit/ticks_math.py#L149) |
| `DEFAULT_TICK_DENSITY_Y = 10` | [batch_render_style.py:23](../../../mf4_analyzer/batch_render_style.py#L23) |
| `_apply_tick_density` 已对每个值轴统一钉刻度数 | [_builder.py:616](../../../mf4_analyzer/batch_render_qt/_builder.py#L616) |

**长表规模实测量级**（默认参数）：

| 场景 | 行数 |
| --- | --- |
| FFT-vs-Time，fs=10 kHz、60 s、nfft=1024、overlap=0.5 | 513 bin × ≈1170 帧 ≈ **60 万行** |
| Order，max_order=20、order_res=0.05、time_res=0.1、60 s | 400 阶 × ≈600 帧 ≈ **24 万行** |

---

## 3. 统计标记：根因与修法

### 3.1 根因（已在 pyqtgraph 0.14.0 源码中确认）

`ScatterPlotItem.paint()` 在 `pxMode=True` 时执行 `p.resetTransform()`，符号按**设备像素**尺寸绘制，painter 的世界变换被丢弃。pyqtgraph 用 `self._exportOpts['resolutionScale']` 补偿：

- `ScatterPlotItem.py:949` 读 `scale = self._exportOpts.get('resolutionScale', 1.0)`
- `_style(..., scale=scale)` 里 `if opt == 'size' and scale is not None: col *= scale`
- `_exportOpts` 非 `False` 时还会跳过 atlas 缓存路径，走逐符号绘制
- 官方 `ImageExporter` 正是这样调 `setExportMode(True, {'resolutionScale': ...})`

批处理的 `_prepared_for_supersampling()` 只处理了 cosmetic pen 和
`ItemIgnoresTransformations`，**从未设置 `_exportOpts`**。于是：

> 标记以 18 px 画进 3× 画布 → 缩回 1× 后只剩 **≈6 px**。

只改颜色不改这条，点依然是个 6 px 的小圈。

### 3.2 修法

**D1 · 超采样期给散点开启 export mode。**
在 `_prepared_for_supersampling` 的遍历里，对 `pg.ScatterPlotItem` 实例调用
`item.setExportMode(True, {"antialias": False, "resolutionScale": factor})`，
`finally` 阶段 `setExportMode(False)` 还原。

- `antialias=False` 与全页「关原生抗锯齿 + 超采样兜底」的既定策略一致。
- 现有的 `opts["pen"]` 加宽**保留**：`_style` 只把 `resolutionScale` 乘到 `size`，
  pen 宽度仍需靠加宽维持。两者互补。
- **只对散点开** —— `PlotCurveItem` 也读 `_exportOpts["antialias"]`，全场景开会打翻
  `_export.py` 顶部注释里那条性能取舍。

**D2 · 标记改成 cursor 的实心红绿点。**
对齐 [cursor.py:329](../../../mf4_analyzer/ui/pg_canvas/cursor.py#L329)：

| | 现状 | 目标 |
| --- | --- | --- |
| 最大值 | pen `#f97316` 2.7 / brush `#fff7ed` | brush `#dc2626` 实心 |
| 最小值 | pen `#0f766e` 2.7 / brush `#ecfdf5` | brush `#16a34a` 实心 |
| 描边 | 主色 2.7 | 白色 `#ffffff`，1.6 × scale |
| 尺寸 | 18 × scale（实际出图 ≈6 px） | 11 × scale（实际出图 ≈11 px） |

**D3 · 统计卡片表头配色跟着改。**
`最大值` 列头 `#c2410c` → `#b91c1c`，`最小值` 列头 `#0f766e` → `#15803d`，
`样本平均` 保持 `#64748b`。否则卡片和图上的点对不上。

---

## 4. 切片：参数模型

### 4.1 一次只切一个维度

**D4 · 切片维度二选一，不允许同时切两个方向。**

| 维度 | 固定什么 | 曲线 | 主图标记线 |
| --- | --- | --- | --- |
| `time` | 时间位置 (s) | 幅值 vs **频率 / 阶次** | 竖线 |
| `y` | 频率 (Hz) / 阶次 | 幅值 vs **时间** | 横线 |

理由：**没有工况需要在同一张报告图上同时对比这两个维度**。
「t=15 s 的频谱」和「6 阶随时间的走势」是两个独立的问题，
硬塞进一页只会让读者先花时间分辨哪条线属于哪个维度。
真要两个都看，跑两次批处理（或建两个任务）即可 —— 得到两张各自干净的图。

这条同时消掉了 v2 里三处复杂度：动态行数、冷暖双色系的辨认负担、
以及主图上最多 8 条方向混杂的标记线。

### 4.2 recipe schema

新增方法级字段 `slice`，加入
`METHOD_PARAM_FIELDS["fft_time"]` 与 `METHOD_PARAM_FIELDS["order_time"]`：

```json
"slice": {
  "enabled": true,
  "axis": "time",
  "positions": [5.0, 15.0, 25.0]
}
```

- `axis`：`"time"`（固定时间）或 `"y"`（固定频率 / 阶次）。
  `y` 与既有的 `y_auto / y_min / y_max`（同样指这条轴）保持同一套命名。
- `positions`：该维度上的位置列表，单位随 `axis` 与方法决定
  （s / Hz / 阶）。
- 默认 `{"enabled": false, "axis": "time", "positions": []}`

**D5 · 默认关闭。** 打开会改变每个既有谱图预设的产出字节，连带作废 fingerprint 与
resume 状态。让用户显式打开，一次打开后由「记住导出偏好」带到下次。

**D6 · 归一化时丢弃未启用的 slice。**
仿照 `chart_statistics`（[batch_recipe.py:369](../../../mf4_analyzer/batch_recipe.py#L369)）：
`enabled` 为假时 `pop("slice")`。**既有预设的 fingerprint 一字节不变。**

**D7 · 归一化时排序 + 去重。**
`[15, 5, 15]` → `[5.0, 15.0]`。两条理由：

1. **fingerprint 稳定性** —— `5,15` 和 `15,5` 必须产生同一个指纹，否则 resume 会误判过期。
2. 颜色按列表顺序分配，排序后图例读起来是递增的，不会出现「第三色=5 s、第一色=25 s」。

**D8 · 取消「自动峰值」。**
批量跑多个文件时每个文件的峰值落在不同位置，产出的图互相不可比 ——
而多位置切片的**唯一目的就是对比**。固定位置才有对比意义。

**D9 · 最多 4 个位置。**
约束来自主图：4 条标记线已经是热力图不被盖住的上限。
右侧图例栏（§5.5）纵向能放下 6 条，但主图先饱和。
超过 4 个 → 面板内联错误，运行按钮置灰。

**D10 · `positions` 为空 → 校验错误。**
「切片已启用，请填写至少一个位置」。属于面板内联错误，
和既有的 `source_time_range_error()` 同一类，不是运行时失败。

### 4.3 落点与越界

**D11 · 吸附到最近的网格中心。**
与单文件一致（`_seed_slice` 用 `argmin(|coords - value|)`）。
数据文件同时记录「请求值」和「实际落点」，避免用户以为导出的是 620.0 Hz
而实际是 615.2 Hz 那一格。

**D12 · 超范围 → 夹到最近的数据边界 + warning，绝不失败。**
批处理跨异构文件是常态（一个 30 s 的文件配 `t=45 s`）。硬失败会让整批任务红一片。
warning code `slice.position_clamped`，一条 warning 列出所有被夹的位置。
经 `warnings_out` 汇入任务 warnings 与 manifest，与现有 colormap 回退同一条路。

**D12b · 发这条 warning 的责任按「本次有没有出图」划分。**（2026-08-03 实施期补）
初版把它交给 `build_heatmap` 单独负责，漏了一种配置：
**只导数据、不导图**时 `build_heatmap` 根本不跑，夹取就只剩 `切片信息` 表里的一行备注，
进不了 manifest —— 而那恰恰是最需要 warning 的场景（没有图可看，
批量跑几十个文件时不可能逐个打开 xlsx 去查）。
规则改为：出图时由图那边发；不出图时由 `_slice_workbook_factory` 发。
两条路径互斥，同一次夹取不会被报两遍。

**D13 · 夹取后可能撞位。**
`[40, 50]` 在一个 30 s 的文件上会同时夹到 30 s，得到两条重合曲线。
夹取后再去重一次，图例只留一条，warning 里说明「2 个位置夹取后合并为 1 个」。

### 4.4 校验（`batch_validation.py`）

`slice` 存在且 `enabled` 为真时：

| 条件 | code |
| --- | --- |
| 不是 mapping | `invalid_slice` |
| `axis` 不是 `time` / `y` | `invalid_slice_axis` |
| `positions` 不是列表，或含非有限数 | `invalid_slice_positions` |
| `axis == "y"` 且含负值（频率/阶次不可为负） | `invalid_slice_positions` |
| 超过 4 个 | `too_many_slice_positions` |
| 空列表 | `slice_positions_required` |

超范围**不在这里校验** —— preflight 拿不到数据，且按 D12 不构成错误。

---

## 5. 渲染布局

### 5.1 固定两行

| 状态 | 行结构 | stretch |
| --- | --- | --- |
| 切片关闭 | 主图（现状，**字节不变**） | — |
| 切片开启 | 主图 + 一条切片图 | **6 : 3** |

1920×1080：页眉 ≈90 px、页脚 ≈24 px，剩 ≈966 px 按 6:3 分 →
主图 ≈644 px、切片 ≈322 px。切片行拿到比 v2（193 px）更宽裕的高度，
因为它现在要承载最多 4 条叠加曲线。

**D14 · `axis == "y"` 时切片放主图正下方并与主图共享横轴。**
该维度的曲线横轴就是时间，与主图横轴同物理量，紧贴主图能竖着直接读。
`axis == "time"` 时曲线横轴是频率/阶次，与主图无对齐关系，但仍占同一行位置 ——
布局不因维度改变，只有轴标签和曲线内容变。

### 5.2 X 轴对齐

主图那行右侧被 colorbar 占掉一段宽度，切片行没有 colorbar，
不处理则绘图区左右边界对不齐。

单文件已经解决过：`_align_slice_to_main`
（[heatmap_canvas.py:2205](../../../mf4_analyzer/ui/pg_canvas/heatmap_canvas.py#L2205)）
与 `_set_slice_right_spacer`（同文件 2522）。批处理照搬：
在切片行右侧插一个宽度等于 colorbar 总宽（含坐标轴与标签）的占位项，
在 `layout_callbacks` 里随 `sigResized` 复算。

`axis == "time"` 时横轴虽不对齐主图，也套同一个占位，让两行的绘图区边界一致。

### 5.3 配色

**D15 · 保留冷 / 暖两套色，用色系标识切片维度。**

| `axis` | 色系 | 顺序 |
| --- | --- | --- |
| `time`（固定时间 → 幅值 vs 频率/阶次） | **暖** | `#dc2626` `#ea580c` `#c026d3` `#a16207` |
| `y`（固定频率/阶次 → 幅值 vs 时间） | **冷** | `#2563eb` `#0891b2` `#4f46e5` `#0d9488` |

一页只用其中一套。保留两套的价值在**跨图**：用户会同时翻多张不同任务的导出图，
色系让他一眼知道这张是「某时刻的频谱」还是「某频率的历程」，不用去读轴标签。
成本为零。

沿用单文件的两个基色（切片曲线 `#2563eb`、标记线 `#e03131`
—— [heatmap_canvas.py:1042](../../../mf4_analyzer/ui/pg_canvas/heatmap_canvas.py#L1042)）
作为两套的首色。

### 5.4 标记线

| 元素 | 样式 |
| --- | --- |
| 主图标记线（每个位置一条） | `pg.InfiniteLine`，`axis=="time"` 时 `angle=90`（竖），`axis=="y"` 时 `angle=0`（横）；对应色 **2.0 px**，`movable=False` |
| 底衬 | 每条线先画 **3.6 px** 白线打底 |
| 切片曲线 | 与它的标记线**同色**，宽度 = `options.line_width`，`antialias=False` |

**D16 · 白色底衬是必需的。** turbo 配色下纯红/纯蓝在局部区域会完全消失。

**D17 · 线宽按导出尺度定，不照抄单文件。**
单文件的 `_slice_marker` 用 `width=1`，但那是 ~800 px 宽的屏幕画布；
批处理导出是 1920 px，同样的 1 px 视觉上细一倍以上。
2.0 px 彩线 + 3.6 px 白衬按 1920 px 宽定；`image_size` 改大时**不随之缩放**
（与 `theme.axis` 的 1.0 px 同一套固定像素规则）。

### 5.5 图例放在右侧 colorbar 占位栏

**D18 · 把对齐用的空占位变成图例栏。**

§5.2 的右侧占位本来就是空的，宽度 ≈100 px，正好放图例：

```
固定时间            ← 栏头（维度名）
── 5.00 s
── 15.00 s
── 25.00 s
```

与单文件一致 —— 那边的 `_slice_panel` 就是
「sits in the colorbar column, below the colorbar, beside the slice」
（[heatmap_canvas.py:1057](../../../mf4_analyzer/ui/pg_canvas/heatmap_canvas.py#L1057) 注释）。

代价是**零数据面积**，这也是「不需要自适应加宽」的直接理由。
单个位置时退化成一行；被夹取的位置追加 `·夹取`。

实现复用 `_StatisticsCard`
（[_builder.py:362](../../../mf4_analyzer/batch_render_qt/_builder.py#L362)）：
已经是 GraphicsObject + `sigResized` 定位、非 pxMode，不受 §3.1 的缩放坑影响。

### 5.6 幅值轴：nice step

**D19 · 自动范围先剔死区，再把两端按 nice step 向外取整。**

三步：

1. **剔死区**：复刻 `_slice_amp_bounds`
   （[heatmap_canvas.py:385](../../../mf4_analyzer/ui/pg_canvas/heatmap_canvas.py#L385)），
   按 `_SLICE_MAX_SPAN_DB = 200` 丢掉被去均值 / A 计权压到 ≈−6153 dB 的 0 Hz DC bin。
   不做这步，真实信号会被压成顶部一条细带。**必须照抄，不能省。**
   多曲线时取所有曲线的并集。
2. **两端向外取整**：

```python
step = _nice_per_div((hi - lo) / self.style.tick_density_y) or (hi - lo)
bottom = math.floor(lo / step) * step
top    = math.ceil(hi / step) * step
plot.setYRange(bottom, top, padding=0)
```

   轴端落在 nice 步长的整数倍上，读出来是 `−100 / −90 / … / −30`，
   而不是 `−99.12 / −93.4 / … / −34.38`。
   `_nice_per_div` 已在 `ticks_math.__all__` 里，直接 import。

3. **刻度**：`_apply_tick_density` 事后照常跑。范围已经 nice，
   它的 `nice_ticks_within` 算出的 per_div 正好落在轴端上，两者自洽。

**D19b · 不要用 `_frame_to_nice`。**
那个 helper 强制 `top = bottom + n * per_div`（示波器格线语义，恰好 n 等分），
而 `_nice_per_div` 是向上取整的 —— 两者叠加会把轴撑出大片空白。
在本仓库默认的 `tick_density_y = 10`（[batch_render_style.py:23](../../../mf4_analyzer/batch_render_style.py#L23)）下实测：

| 原始范围 | `_frame_to_nice` | 两端取整 |
| --- | --- | --- |
| `[−99.11, −34.38]` | `[−100, 0]` · 浪费 **35%** | `[−100, −30]` · 浪费 **8%** |
| `[−99.16, −44.51]` | `[−100, 0]` · 浪费 **45%** | `[−100, −40]` · 浪费 **9%** |

两者的刻度值同样整齐，但 `_frame_to_nice` 把曲线压到了轴的下半部。

**D20 · 手动 z 时范围逐字保留。**
`z_auto=False` 且 `z_floor/z_ceiling` 有效时，直接钳到色标同一窗口，
**不做 nice 外扩** —— 用户填的边界必须原样出现，这与 `nice_ticks_within`
「manually entered axis range must survive verbatim」的既有约定一致。

**横轴**：跟随主图对应轴的最终范围（含手动 `x_min/x_max`、`y_min/y_max`），
曲线只画可见段。横轴的 nice 由 `_apply_tick_density` 既有逻辑负责，不额外处理
（它要么与主图共享范围，要么继承主图轴的手动设定，两种情况下都不该被本特性改写）。

### 5.7 dB 与线性

切片取自 `display_matrix` —— 主图那一份，`render_db` 为真时是 dB。
切片的幅值轴标签直接复用 colorbar 的标签，保证图上两处同一口径。

---

## 6. 数据文件

### 6.1 规则

| 条件 | 数据文件内容 |
| --- | --- |
| `slice.enabled = false` | **保持现状**（完整 long 表），字节不变 |
| `slice.enabled = true` 且 `data_format = xlsx` | 切片工作簿（2 张表） |
| `slice.enabled = true` 且 `data_format = csv` | 退回 long 表 + warning `slice.csv_fallback` |

**D21 · 数据导出跟随切片开关，不引入第二个开关。**
「图上画了什么，文件里就是什么」是最容易解释的契约，也保证既有预设的数据产出一字节不变。

**D22 · CSV 不支持多表 → 降级而非报错。**
`reserve_output_paths` 按扩展名预留一个路径，一次原子发布一个文件；
拆成多个 csv 会破坏 write-set 的原子性契约。UI 现在只发 `xlsx`，
csv 只可能来自手写 recipe，降级 + warning 是代价最低的诚实做法。

### 6.2 工作簿结构

**D23 · 一张切片宽表，位置是列。**

sheet 名随 `axis` 与方法：`时间切片` / `频率切片` / `阶次切片`。

`axis = "time"`（fft_time）：

| `frequency_hz` | `t=5.00s` | `t=15.00s` | `t=25.00s` |
| --- | --- | --- | --- |

`axis = "y"`（fft_time）：

| `time_s` | `f=620.0Hz` | `f=1240.0Hz` |
| --- | --- | --- |

宽表让用户在 Excel 里框选几列就能直接出对比图 —— 这正是多位置切片的使用场景。

sheet **`切片信息`** —— 两列键值，让文件自解释（现状 xlsx 完全没有元信息）：

```
来源文件           EPS_MotorSweep_2026-07-19_run03.mf4
通道               MotorSpeed
单位               rpm
方法               FFT vs Time
采样率 Fs (Hz)     10000
窗 / NFFT / 重叠   hanning / 1024 / 50%
计权               None
幅值口径           dB (ref 1 rpm, auto)
切片维度           固定时间
切片位置 请求      5.0, 15.0, 25.0 s
切片位置 落点      4.9920, 14.9760, 24.9600 s
切片位置 备注      —
```

**D24 · 表里只写图上口径，不并列线性与 dB。**
多位置下并列两套列会让列数翻倍。`切片信息` 写明口径与 dB 参考值，
线性↔dB 是确定的可逆换算。
（`fft` 方法的既有线性导出不受影响，两者口径不同的原因记在 `切片信息` 里。）

### 6.3 规模

513 行 × 最多 5 列 ≈ **513 行**，对比现状的 60 万行。
写入从几十秒降到毫秒级，文件从几十 MB 降到几十 KB。

### 6.4 可选增量（本次不做，先标出来）

- sheet **`峰值轨迹`**：`time_s | peak_frequency_hz | peak_amplitude`，即每帧 argmax。
  成本是一次 `np.argmax(axis=0)`，是阶次/扫频分析里真正常用的输出。
- sheet **`完整矩阵`**（宽表，首行=频率、首列=时间）：给确实要原始数据的场景留后路，
  需要新增输出开关。

---

## 7. UI

### 7.1 卡片主开关统一成 PillSwitch

**D25 · 卡片级主开关用 `PillSwitch`，行内的多选/二选保留 `QCheckBox`。**

界线清楚：一张卡「开不开」是 PillSwitch；卡内部的「统计哪几项」「区间自不自动」
是并列多选，pill 的 44×24 尺寸放进行里也不合适。

`PillSwitch` 是 `QCheckBox` 的 drop-in（同样的 `toggled/isChecked/setChecked`），
两处替换都不用动 enable/sync 逻辑。

### 7.2 「预处理」卡范式

三处组件照 [filter_panel.py:48](../../../mf4_analyzer/ui/drawers/batch/filter_panel.py#L48) 复用：

1. 摘要行 `QWidget#BatchFilterSummary`（现成 QSS：圆角 + `#fafbfd` 底 + `#dbe4ef` 边）
2. `标题 + 摘要文字 + PillSwitch` 三件套
3. `_refresh_summary()` 随状态改摘要文字；**关闭时把设置区整个折叠**

### 7.3 切片面板

新增 `mf4_analyzer/ui/drawers/batch/slice_panel.py`：

```
┌────────────────────────────────────────────────┐
│ 切片   固定时间 · 3 处                  [====] │  ← 关闭：「切片关闭 · 仅导出谱图」
├────────────────────────────────────────────────┤
│ 切片维度  [ 固定时间          ▾ ]              │
│ 位置      [ 5, 15, 25            ]  s          │
│ ⓘ 逗号分隔，最多 4 个；一次只切一个维度        │
└────────────────────────────────────────────────┘
```

**D26 · 维度用 `QComboBox` 二选一。**
和面板里既有的「源数据区间」（全时段 / 指定区间）同一个控件范式。
两项：`固定时间` / `固定频率`（`order_time` 时为 `固定阶次`）。
选中项驱动位置行的单位标签：`s` / `Hz` /（无单位）。

**D27 · 位置用逗号分隔的文本框。**
和「源数据区间」（placeholder `0.0, 120.0 s`）完全同一个输入范式，
一行搞定不占高度。批处理面板本来就窄，可增删的行列表（+/− 按钮）会把它撑爆。

内联错误参照 `source_time_range_error()`
（[analysis_panel.py:425](../../../mf4_analyzer/ui/drawers/batch/analysis_panel.py#L425)）：
解析失败 / 超过 4 个 / 列表为空 → 面板下方红字 + 运行按钮置灰。

### 7.4 图内统计面板改造

`chart_statistics_panel.py` 的 `self.enabled = QCheckBox("启用")` → PillSwitch，
并补上摘要行：

- 关闭：`统计关闭 · 图上不加标注`
- 开启：`全时段 · 最大/最小/平均` 或 `12.0–48.0 s · 最大/最小`

卡内的「自动」「最大值」「最小值」「样本平均」保持 QCheckBox（D25）。
`_sync()` 里把设置区折叠行为一并加上，与「预处理」一致。

### 7.5 联动

- 方法切换离开谱图 → 切片面板隐藏，`normalize_batch_params` 把 `slice` 从 params 剔除
- 方法在 `fft_time` ↔ `order_time` 之间切换 → 维度下拉的第二项文案与位置单位同步更新；
  **`positions` 的数值不清空**（用户可能只是换了方法，数值仍可能有意义），
  但越界会在运行时按 D12 夹取
- `sheet.py` 的 `_recompute_pipeline_status` 已覆盖 params 变化，
  `SlicePanel.changed` 接到 `_on_params_changed` 即可
- 输出摘要：切片开启时把数据文件描述从「完整矩阵」改成「切片结果」

### 7.6 提示与文档（走 `/update-hints`）

| 面 | 内容 |
| --- | --- |
| `ui/quickref.py` 「批处理」组 | 新增 `导出切片` 一行：「选一个维度，逗号分隔可切多个位置叠加对比，数据文件同步改成切片结果」 |
| `ui/hints.py` | 批处理侧目前无 hint 条目，本次不新增；发现性由面板 ⓘ 承担 |
| `help/ffttime-guide.html`、`help/order-analysis-guide.html` | 批处理段落补切片导出说明 |
| `help/TraceLab-使用说明.html` | 批处理数据文件的描述从长表改成切片 |

---

## 8. 兼容性

| 面 | 结论 |
| --- | --- |
| 既有预设 fingerprint | **不变**（D6：未启用即不写入 params） |
| 既有数据产出 | **不变**（D21：切片关闭时仍写 long 表） |
| 既有 PNG 字节 | 谱图不变；**时域图会变**（§3 的标记修复） |
| `to_long_dataframe` | 保留，仍是切片关闭时的导出路径与 `_compute_*_dataframe` 包装的实现 |
| `export_frame_factory` 重试路径 | 必须保留 —— `OutputPublishRace` 时要能重建帧（[batch.py:3952](../../../mf4_analyzer/batch.py#L3952)）。切片工作簿体积极小，`export_frame_holder` 那套内存优化对切片路径不再必要，但**结构要保持一致** |
| `PillSwitch` 替换 | 现有测试若用 `QCheckBox` 类型断言或 `.text()` 取「启用」，需同步更新 |

---

## 9. 明确不做

- **不支持一次切两个维度**（D4）—— 要两个就跑两次
- 不做「自适应加宽」（D18 已使加宽无必要）
- 不做自动峰值（D8）
- 不给谱图加「图内统计」卡片（谱图全局极值意义不大；要标应该标在切片曲线上，另议）
- 不给 FFT 加峰值标注（有价值，但属于另一个特性）
- 不改 `fft` 的数据导出
- 不加「完整矩阵」宽表开关（§6.4）
- 不做交互式切片位置拾取（批处理是无人值守链路）
- 不改 `data_format` 的 UI（仍只有 xlsx）

---

## 10. 验收

**渲染**
1. 切片开启 → PNG 恰好两行（6:3）；关闭 → 一行且与改动前**逐字节相同**
2. 两行绘图区的左右边界像素级对齐（colorbar 占位生效）
3. `axis="time"` + 3 个位置 → 切片图 3 条暖色曲线 + 主图 3 条同色**竖**线 + 右栏 3 条图例
4. `axis="y"` → 曲线冷色、主图**横**线、切片横轴与主图共享
5. `order_time` 的轴标签/图例为「阶次」，不出现 Hz
6. 位置超范围 → 夹到边界、图例带「夹取」、warnings 含 `slice.position_clamped`
7. 夹取后撞位 → 去重合并，warning 说明合并数量
8. **幅值轴端落在 nice 步长整数倍上**（如 `−120 / −100 / −80 / −60`）；
   手动 z 时范围逐字保留、不被 nice 外扩
9. 含 −6153 dB DC 死区的矩阵 → 真实信号不被压成顶部细带

**数据**
10. 切片开启 + xlsx → `切片信息` + 一张切片表；列名形如 `t=5.00s` / `f=620.0Hz`
11. 表里的数值与切片曲线逐点相等（同一份 `display_matrix` 与同一个 plan，不允许两条计算路径）
12. 切片关闭 → 数据文件与改动前逐字节相同
13. csv + 切片开启 → long 表 + `slice.csv_fallback` warning

**UI**
14. 切片、图内统计两张卡的主开关是 PillSwitch；关闭时设置区折叠、不占高度
15. 维度下拉切换 → 位置行单位标签跟着变；方法在两个谱图方法间切换 → 第二项文案跟着变
16. 位置超过 4 个 / 列表为空 / 解析失败 → 内联红字 + 运行按钮置灰
17. `[15, 5, 15]` 与 `[5, 15]` 归一化后 fingerprint 相同

**统计标记**
18. 1920×1080 导出的 PNG 中，最大值标记的实测直径 ≥ 10 px（当前实现约 6 px）
19. 标记为实心红/绿 + 白描边；卡片列头配色同步
20. 曲线本身的渲染不因 export mode 改变（抗锯齿策略未被打翻）
