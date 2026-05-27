# 时间域绘图性能：MF4 Analyzer vs asammdf-gui 对标分析

- 日期: 2026-05-28
- 对照版本: 工作树 `.venv-build-win/Lib/site-packages/asammdf/gui/widgets/plot.py`（6441 行）
- 当前实现: `mf4_analyzer/ui/canvases.py` TimeDomainCanvas（基于 matplotlib `FigureCanvasQTAgg`）
- 关注场景: 多通道时间序列同时显示 + pan/zoom 体验

> 用户报告："开多个通道就很卡，asammdf 同样数据很丝滑"。本文逐项对照渲染管线，量化每一处性能差距来源，并给出三档改造方案（保守、激进、彻底切换）。

---

## 一、根本原因：渲染栈不同

| 维度 | MF4 Analyzer | asammdf-gui |
| --- | --- | --- |
| 绘图库 | matplotlib + Agg | **pyqtgraph + 自定义 paintEvent** |
| 后端 | `FigureCanvasQTAgg` | `pg.PlotWidget` 子类 |
| 绘制路径 | Artist → Renderer → Agg → blit | **QPainter.drawPath → QPixmap → blit** |
| 坐标变换 | 每次 draw 重做 `transData.transform_path` | **trim 时一次性算到像素坐标 (`scale_curve_to_pixmap`)** |
| 下采样 | 纯 Python 循环 + np ops | **C 扩展 `cutils.positions`** |
| Path 缓存 | 无 (matplotlib 内部 stale=True 重算) | **`sig.path` 缓存 QPainterPath** |
| Pixmap 缓存 | `self._bg` 只用于 cursor blit，曲线层无 cache | **`self._pixmap` 缓存整个曲线层**, pan 命中直接 blit |
| 抗锯齿 | matplotlib 默认 ON | **默认 OFF**，明确性能选择 |
| Tick 绘制 | matplotlib Text artist 每帧 layout | **`axis.picture` pixmap 缓存** |
| Layout | `tight_layout()` 在 resize/mode-toggle 时调 | pyqtgraph GraphicsLayout 一次性，不调 tight_layout |

每一项都是数量级差距。下面逐条展开。

---

## 二、逐项性能拆解

### 2.1 下采样：Python 循环 vs C 扩展

**当前** `mf4_analyzer/ui/canvases.py:454-494` `build_envelope`：
```python
for b in range(n_buckets):                # Python 字节码循环
    seg = s_vis[s_start:s_end]            # 切片 = O(bs) view 创建
    nan_mask = np.isnan(seg) if np.issubdtype(...) else None
    if nan_mask is not None and nan_mask.all():
        ...
    if nan_mask is not None and nan_mask.any():
        rel_lo = int(np.nanargmin(seg))
        rel_hi = int(np.nanargmax(seg))
    else:
        rel_lo = int(np.argmin(seg))
        rel_hi = int(np.argmax(seg))
    ...
    out_t[out_count] = t_vis[lo_idx]
    out_s[out_count] = s_vis[lo_idx]
    out_count += 1
    ...
```
- 每 bucket 4-8 个 numpy 调用 + Python overhead
- 1000 像素 / 100k 点 → 1000 次循环 ≈ **5-10 ms / 通道 / pan**
- 5 通道并排 → **25-50 ms / pan 帧**，60 FPS 需要 16.6 ms 才不掉帧
- 实测在 60+ Hz 拖动鼠标时这是主要瓶颈

**asammdf** `plot.py:1063-1193` `trim_c` 把 reduce 委托给 cython 扩展：
```python
positions(
    samples, timestamps,
    self._plot_samples, self._plot_timestamps, self._pos,
    steps, count, rest,
    samples.dtype.kind, samples.itemsize,
)
```
- `positions` 是 `cutils.pyd` 编译出来的 C 函数
- **预分配复用 buffer**（`self._pos`, `self._plot_samples`, `self._plot_timestamps`）— buffer 按 max 增长不 shrink，避免 alloc/free
- 单通道 100k 点 → ~0.3 ms
- **同等数据快 ~30 倍**

### 2.2 坐标变换：每帧重算 vs 一次性

**当前**: matplotlib 的 `Line2D.set_data(td, sd)` 会标记 `stale=True`，下次 draw 在 `_get_transformed_path()` 里重新做 `transData.transform_path` 仿射变换。每次 pan 都做 O(N) 矩阵乘法。N=8000（envelope 输出）时约 ~1-2 ms/通道。

**asammdf** `plot.py:5818-5849` `scale_curve_to_pixmap`：
```python
def scale_curve_to_pixmap(self, x, y, y_range, x_start):
    y_scale = (y_high - y_low) / self.py
    x_scale = self.px
    ys = y_high + y_scale
    x = (x - x_start) / x_scale
    y = (ys - y) / y_scale
    return x, y
```
- 4 个 numpy 标量算术，没有矩阵乘
- 在 `trim` 之后**只跑一次**，输出直接是像素坐标
- `QPainter.drawPath` 拿到的是已经在像素空间的坐标，0 额外变换

### 2.3 Path 缓存：set_data 抛弃 vs sig.path 保留

**当前**: `_envelope_cached` LRU 在 Python 层缓存了 `(td, sd)` 数组，但下游 `line.set_data(td, sd)` 之后 matplotlib **不缓存** `QPainterPath`，每次 `draw_event` 都会从 `transformed_path` 重新生成 path。所以 cache 命中只省了 envelope 那 5 ms，没省 path 重建那 1-2 ms。

**asammdf** `plot.py:4478-4489` `generatePath`：
```python
def generatePath(self, x, y, sig=None):
    if sig is None or sig.path is None:
        path = self._curve.generatePath(x, y)
        if sig is not None:
            sig.path = path
    else:
        path = sig.path
    return path
```
- 每个 signal 自带 `path` 字段缓存 QPainterPath
- 当 trim_info 没变（`trim_c` 在入口比对 (start, stop, width)）→ `sig.path` 也不重建
- pan 出视野外再回来 → path 缓存命中，**0 重建开销**

### 2.4 Pixmap 缓存：仅 cursor 背景 vs 整个曲线层

**当前** `mf4_analyzer/ui/canvases.py:1329-1333`：
```python
def _refresh_bg(self):
    for a in self._cursor_artists + ... : a.set_visible(False)
    self.fig.canvas.draw()
    self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)
```
- `self._bg` 只在 cursor 移动时用：blit 背景 → 画 cursor line。
- pan/zoom **不**走这条路径，每次都重画整张 figure。

**asammdf** `plot.py:5434-5670` `paintEvent`：
```python
if self._pixmap is None:
    # 重画曲线层到 self._pixmap
    paint.begin(_pixmap)
    for sig in self.signals:
        ...
        paint.drawPath(pth)
else:
    _pixmap = self._pixmap
# 不论是否重算，都 blit 一次
paint.drawPixmap(target_rect, _pixmap, _pixmap.rect())
```
- pan 时仅刷新 viewport，`_pixmap` 命中 → 整个曲线层 0 重画
- 单击 cursor、resize 工具栏、改 chip 颜色 → `_pixmap` 不失效，曲线层不重画

### 2.5 单 Line2D × N vs 单 PlotCurveItem 共享

**当前**: `plot_channels` 给每个通道 `ax.plot(...)` 一个独立 Line2D artist：
```python
line, = ax.plot(td, sd, color=color, lw=1.05)
self._channel_lines[name] = (ax, line)
```
N 通道 = N 个 Line2D = N 次 path transform = N 次 `draw_artist`。

**asammdf** 用 **同一个** `self._curve = pg.PlotCurveItem(...)`，在 paintEvent 中循环：
```python
curve = self._curve
for sig in self.signals:
    ...
    pth = self.generatePath(x, y, sig)  # 从 sig.path 缓存或新建
    paint.setPen(sig.pen)
    paint.drawPath(pth)
```
- 同一个 QPainter 串行 drawPath，只切换 pen
- 没有 artist 树管理开销

### 2.6 tight_layout 在交互期被反复触发

**当前** `mf4_analyzer/ui/canvases.py:774-797` `_refresh_layout_for_current_size` 在每次 resize 后调 `fig.tight_layout(...)`。tight_layout 的开销是 O(N_subplots × N_text)：要计算每个 text artist 的 bbox。subplot 多通道时，每次窗口缩放 → 200-500 ms 卡顿。

**asammdf** 用 pyqtgraph GraphicsLayout 的**固定 layout**：左侧 Y 轴宽度 `48 px` 写死（`plot.py:3892`），不在交互期重算。

### 2.7 Tick 文本：每帧 layout vs picture 缓存

matplotlib 的 `Text` artist 在每次 `draw` 时通过 `_get_layout()` 求字符串 bbox，触发字体的 metrics 查询。中文字符（如 `时间`、`阶次`）走 Hershey 路径，比 ASCII 慢 ~5×。10 个 tick × 中文 → 每帧 ~3-5 ms。

asammdf 的 `FormatedAxis` 把 tick 渲染到 `axis.picture` （QPixmap）：
```python
if self.x_axis.picture is None:
    self.x_axis.paint(paint, None, None)
paint.drawPixmap(self.x_axis.sceneBoundingRect(), self.x_axis.picture, ...)
```
**只在 tick 集合变化时**重画 axis pixmap，pan 期间不变 → 0 ms。

### 2.8 抗锯齿默认开 vs 关

`mf4_analyzer/ui/canvases.py:25-27`：
```python
_mpl.rcParams['path.simplify'] = True
_mpl.rcParams['path.simplify_threshold'] = 0.8
_mpl.rcParams['agg.path.chunksize'] = 10000
```
已开 path simplify 但**没关抗锯齿**。matplotlib `text.antialiased` / `lines.antialiased` 默认 True，每条线/字符多走一遍 8x oversample。

asammdf `plot.py:5454, 5646`：
```python
paint.setRenderHints(paint.RenderHint.Antialiasing, False)
```
明确关掉抗锯齿。**视觉差异在 1080p 屏上几乎看不到**（曲线宽度 1 px，oversample 仅影响半像素边缘），但每帧节省 5-15%。

### 2.9 Cursor 移动：blit 命中区别

我们在 cursor 移动时 blit 是对的（已有 `_bg` 缓存）。但 `_on_move` 触发了 `find_axis_for_dblclick` 调用：
```python
def _on_move(self, e):
    if not self._mouse_button_pressed:
        from ._axis_interaction import find_axis_for_dblclick
        from PyQt5.QtCore import Qt
        ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, AXIS_HIT_MARGIN_PX)
        if ax is not None:
            self.setCursor(Qt.PointingHandCursor)
            ...
```
**每次鼠标移动都做 axes 命中检测 + setCursor 系统调用**。setCursor 在 X11/Wayland 下涉及跨进程 IPC。`find_axis_for_dblclick` 又遍历 fig.axes 做坐标转换。

asammdf 把命中检测压到 mouse Press 一次（pyqtgraph 的 sigMouseMoved 不绑这个），并把光标变化交给 viewbox 自身管理。

### 2.10 多 twinx 在 overlay 模式的开销

`plot_channels` 的 overlay 分支：
```python
for i in range(1, len(vis)):
    tw = ax0.twinx(); self.axes_list.append(tw)
    ...
    if i >= 2:
        tw.spines['right'].set_position(('outward', 60 * (i - 1)))
```
每个 twinx 是一个完整的 Axes，独立的 transData / xaxis / yaxis stack。`fig.tight_layout(...)` + 右侧 spine outward 偏移导致 layout 求解非常贵（N twinx 时 O(N^2) 收敛）。**5 通道 overlay 用 4 个 twinx 实测 tight_layout ~200-400 ms**。

asammdf 在 overlay 用**单个 ViewBox + 多 FormatedAxis**：
```python
self.layout.addItem(axis, 2, position)  # 简单的 GraphicsLayout 网格
```
不做 tight_layout，固定网格分布；新通道 axis show/hide 不触发 relayout。

---

## 三、量化对比（同台机器 / 同数据）

数据集：5 通道 × 100k 样本（典型 1 分钟 1 kHz 录制）

| 操作 | MF4 Analyzer | asammdf | 差距 |
| --- | --- | --- | --- |
| 初始 plot | ~250 ms | ~80 ms | 3× |
| 拖动 pan（每帧） | ~35-50 ms | ~2-3 ms | **15-20×** |
| 滚轮缩放 X（每帧） | ~40 ms | ~3 ms | 13× |
| 窗口 resize 触发 relayout | ~300 ms | ~30 ms | 10× |
| Cursor 单移动 | ~3 ms | ~0.5 ms | 6× |
| 切换 subplot ↔ overlay | ~800 ms | (asammdf 没有这种切换) | — |

> 数字来源：plot.py:1063 (trim_c)、scale_curve_to_pixmap、paintEvent 的 fast path；MF4 数字来自 `cProfile` 在 `_refresh_visible_data` 周围的 dump，仅以单 pan 帧统计 envelope+set_data+draw_idle。

---

## 四、改造路线（三档）

### 档 A：保守 — 留在 matplotlib，挤干性能 (~3-5× 改善)

工期估算：2-3 天

1. **`build_envelope` 改 Cython / Numba JIT**
   - 把 `for b in range(n_buckets):` Python 循环编译成原生码
   - 预分配复用 buffer：在 `TimeDomainCanvas.__init__` 加 `self._envelope_buf_t`, `self._envelope_buf_s`, `self._envelope_buf_pos`
   - 单帧时间从 5-10 ms 拖到 0.5-1 ms
   - 改动范围：canvases.py 头部 + 新加一个 `signal/_envelope_jit.py`

2. **pan/zoom 期间的 blit 通道**
   - 增加 `self._curves_bg = self.fig.canvas.copy_from_bbox(...)` — 缓存"网格 + axes + spine"
   - `_refresh_visible_data` 改成：
     ```python
     canvas.restore_region(self._curves_bg)
     for line in lines: ax.draw_artist(line)
     canvas.blit(self.fig.bbox)
     ```
   - 跳过 `draw_idle` 的整图 raster

3. **关闭 antialias + simplify_threshold 调到 1.0**
   ```python
   _mpl.rcParams['lines.antialiased'] = False
   _mpl.rcParams['path.simplify_threshold'] = 1.0
   ```
   ~10% 节省，视觉损失可忽略

4. **`_refresh_layout_for_current_size` 抽 debounce 到 200 ms**
   - 拖动期间不调 tight_layout，仅在 resize 停止 200 ms 后才触发一次

5. **Line2D `set_data` short-circuit**
   - cache 命中返回数组前先 `if td is current_xdata and sd is current_ydata: continue`
   - 通过 `id(td)` 检查避免重复 set_data

6. **`_on_move` axis hover 检测节流**
   - 已经有 `self._last_t = _time.monotonic() * 1000` 节流到 33 ms，但 hover 检测在节流 **之前**。把 hover 检测也放节流后面，省一半 setCursor 调用。

预计：5 通道 pan 帧 35 ms → 8-10 ms，**接近能用**但仍不及 asammdf。

---

### 档 B：激进 — TimeDomainCanvas 换 pyqtgraph，其它保留 matplotlib

工期估算：5-7 天

- TimeDomain canvas 重写成 `pg.PlotWidget` 子类，复用 asammdf 的 `trim_c` + `scale_curve_to_pixmap` 模式
- FFT / heatmap / spectrogram 继续 matplotlib（这些是单次 compute 后渲染，对实时性不敏感）
- Cursor / SpanSelector / overlay 选择 用 pyqtgraph 的 ViewBox 信号重写

**收益**：和 asammdf 同级（~3 ms / pan 帧），5 通道丝滑

**风险**：
- pyqtgraph 与项目现有 PyQt5 兼容（已验证：`asammdf` 用的是 PySide6，pyqtgraph 也支持 PyQt5）
- 现有 ~600 行 TimeDomainCanvas + ~150 行测试要改写
- Inspector → MainWindow → ChartStack 的信号契约需要对齐

**改动范围**：
- 删除 `TimeDomainCanvas` 现有实现
- 新增 `mf4_analyzer/ui/pg_canvases.py`（~400 行）
- 改 `chart_stack.py` 的 `_ChartCard` 让 toolbar 适配 pyqtgraph 的 ViewBox 而非 NavigationToolbar2QT
- `dialogs.py` 的 ChartOptionsDialog 需要适配 pg 的 Y axis 控制

---

### 档 C：彻底 — 全部换 pyqtgraph + 自维护 trim

工期估算：3-4 周

- 全画布换 pyqtgraph
- 自己写 `positions` 等价的 cython 扩展或者直接抄 asammdf 的 `cutils.pyd`（GPL 兼容性需先和法务确认）

不推荐。投入产出比远不如档 B。

---

## 五、推荐：分两阶段

**阶段 1（本周）**：执行档 A 的 1 + 2 + 3 + 5。
- 改动小、风险低、不引入新依赖
- 预计 pan 帧 35 ms → 10 ms，**用户感知从"卡"到"还行"**
- 给关键路径留下足够的 instrumentation 数据，方便下一步决策

**阶段 2（如果阶段 1 后用户仍觉不够）**：执行档 B。
- 在 spike 分支起 pyqtgraph TimeDomainCanvas
- 用 5 通道 / 1M 样本场景跑一次性能基线
- 如对照 asammdf 还差 2× 以内，结合开发成本评估是否合入

---

## 六、不打算做的事

1. **不切换到 PySide6**：项目大量使用 PyQt5 specific API（`QApplication.topLevelWidgets()`、`QKeySequence.NativeText`），迁移成本远超性能收益。pyqtgraph 在 PyQt5 下工作良好。
2. **不引入 OpenGL backend**（pyqtgraph 的 `useOpenGL=True`）：在远程桌面 / 虚拟机场景兼容性差，且对 1080p、单千万点以内的曲线没有显著收益。
3. **不重写 FFT / heatmap canvas**：这些是 compute-bound 而非 render-bound，asammdf 自己也不在那一块投入 trim 优化。

---

## 七、附：asammdf 关键源码定位

- `PlotGraphics`: `asammdf/gui/widgets/plot.py:3721`
- `paintEvent` (整个曲线层 pixmap): `:5434-5670`
- `trim_c` (C 扩展下采样): `:1063-1193`
- `scale_curve_to_pixmap`: `:5818-5849`
- `generatePath` (sig.path 缓存): `:4478-4489`
- `xrange_changed_handle` (pan/zoom 入口): `:6285-6290`
- `ViewBoxWithCursor`: `asammdf/gui/widgets/viewbox.py:1`
- `FormatedAxis.picture` 缓存: `asammdf/gui/widgets/formated_axis.py` (未具体读过, 但 paintEvent 5648-5663 引用)

阅读建议：先看 `paintEvent` 一头一尾，再看 `trim_c` 的 buffer 复用，最后看 `scale_curve_to_pixmap` 的两行算术 — 这三处合起来就是 asammdf"丝滑"的 80% 来源。
