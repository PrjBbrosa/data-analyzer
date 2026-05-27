# UI/UX 不变前提下，内核换成 asammdf 同级的可行性评估

- 前置阅读: `docs/analyzer/reviews/2026-05-28-plot-perf-vs-asammdf.md`
- 约束: **所有用户可见的操作功能、键盘快捷键、面板布局、操作流程保持完全一致**
- 目标: 渲染内核拿到 asammdf 同级或接近的性能（pan 帧 ~3 ms / 5 通道 100k 点）

---

## 一、必须保留的"UI/UX 契约"清单

> 这些是用户看得见、点得到、能操作的。**只要这些行为不变，内部怎么改都可以**。

### 1.1 工具栏 / 快捷键
- matplotlib NavigationToolbar 的 6 个按钮：home / back / forward / **pan** / **zoom** / save，对应 Ctrl+R / Ctrl+Z / Ctrl+Shift+Z / **Ctrl+G** / **Ctrl+B** / 默认 Ctrl+S
- 时间卡专属：分屏 / 叠加 / 游标关 / 单游标 / 双游标，对应 Ctrl+1..5
- 图表选项按钮（mdi.tune-vertical）双击 axes 也能打开
- 复制为图片（mdi.content-copy）

### 1.2 鼠标 / 滚轮
- Ctrl+滚轮 缩放 X 轴
- Shift+滚轮 缩放 Y 轴
- 普通滚轮 平移 Y
- 双击 axes / axes 边缘 打开 ChartOptionsDialog
- overlay 模式：左键点击曲线选中（per-series Y 控制）+ 拖动 Y
- overlay 模式：空白区域点击取消选中
- 单/双游标点击放置

### 1.3 ChartOptionsDialog
- 坐标轴：min / max / 标签 / linear↔log / 自动
- 图形 tab：曲线颜色（同步 axis label / spine / 内嵌标签）、色图、色阶
- 图例 tab：重新生成自动图例

### 1.4 状态栏与右下游标 pill
- cursor_info / dual_cursor_info HTML 文本（含通道颜色）
- 拖动 pill 到任意位置

### 1.5 自定义 X 轴 / 范围过滤
- 可以拿任意 channel 作为 X 轴（不只是 time）
- 时间范围过滤（spin_start/end + chk_range）

### 1.6 多通道布局
- subplot：N 个垂直堆叠的子图，共享 X 轴
- overlay：N 条曲线 + N 个独立 Y 轴
- 当 subplot 的 Y label 太长时，自动改成 inside-axes 标签

### 1.7 颜色 / 单位 / 单位 chip
- 每曲线颜色由 navigator 提供
- Y 轴单位 chip 显示在 Y 轴顶部上方
- subplot 的 inside 标签带"●"前缀

---

## 二、实现细节的 matplotlib 耦合点

> 这些是当前实现的内部选择，**用户不感知**。

| 耦合点 | 当前位置 | 用户感知 |
|---|---|---|
| `Figure / Axes / Line2D` 对象 | `canvases.py` 全文 | 无 |
| `ax.transData.transform` | 颜色选择、点击命中 | 无 |
| `ax.spines / ax.xaxis.label` | 颜色同步 | 无（看到的是颜色变了） |
| `matplotlib.widgets.SpanSelector` | `canvases.py:1288` | 已禁用 |
| `NavigationToolbar2QT` | `chart_stack.py:260` | 看到的是按钮，**不感知** Toolbar 是 matplotlib 提供 |
| `fig.tight_layout()` | `canvases.py:697` 等 | 无 |
| `axvline` cursor + `copy_from_bbox` blit | `canvases.py:1313` | 无 |
| `MaxNLocator` tick 密度 | `canvases.py:753` | 看到 tick 数 |

**关键发现**：toolbar、cursor、span、layout 这些**实现路径**用户感知不到 — 它们的行为可以被 pyqtgraph 等价物替代，只要按钮还在那、快捷键还能用。

但 **ChartOptionsDialog 直接调用 matplotlib API**（`dialogs.py:537-560`）：
```python
xlo, xhi = self.ax.get_xlim()
self.ax.xaxis.get_gridlines()
self.ax.set_xscale(scale)
ax.spines[side].set_color(color)
```
这是最大的耦合点 — 要么 ChartOptionsDialog 用 facade，要么把 ax 包装成 matplotlib-like 对象。

---

## 三、三档方案，按"UI/UX 不变 + 性能改善"逐档评估

### 方案 A — 全 matplotlib，挤干所有 blit 路径（保守）

**性能目标**：~3-5×，pan 帧从 35ms → 8-10ms
**风险**：极低，纯内部优化
**工期**：5-7 天

技术清单：

1. **Cython / Numba JIT 化 `build_envelope`**
   - 把 `for b in range(n_buckets):` 编译到原生码
   - 预分配复用 `self._envelope_buf_t/_s/_pos` 三块 buffer，按 max 增长不 shrink
   - **预计 5-10 ms → 0.5 ms / 通道 / pan**

2. **Animated Line2D + blit-only 更新**
   - 把所有 Line2D 设 `animated=True`
   - 新增 `self._curves_bg = canvas.copy_from_bbox(ax.bbox)` 缓存网格+spine+tick
   - `_refresh_visible_data` 改成：
     ```python
     canvas.restore_region(self._curves_bg)
     for line in lines: ax.draw_artist(line)
     canvas.blit(ax.bbox)
     ```
   - **完全跳过 draw_idle 的整图 raster**
   - cursor 已经在 blit，二者复用同一套 bg 缓存机制

3. **Path 缓存（matplotlib 自带，但需触发）**
   - 复用 `Line2D._transformed_path` 内部缓存
   - 在 `set_data` 前比对 `id(td) == id(self._last_xdata)`，相同就 skip
   - 这样 cache 命中时 0 transform

4. **关 antialias + simplify_threshold=1.0**
   ```python
   _mpl.rcParams['lines.antialiased'] = False
   _mpl.rcParams['path.simplify_threshold'] = 1.0
   ```

5. **tight_layout debounce 到 200 ms**
   - 拖动期间不重排，仅在 resize 停止后触发一次

6. **Hover affordance 节流**
   - `_on_move` 的 axis 命中检测放节流后面

7. **subplot ↔ overlay 切换走"复用 axes" 路径**
   - 不 `fig.clear()` 重建，只 `ax.add_collection` / `set_position`

✅ **UI/UX 完全不变** — 所有改动在 canvases.py 内部
⚠️ **性能上限是 matplotlib 自身的极限**，~10ms / pan 帧是这条路的天花板

---

### 方案 B — Facade：pyqtgraph 内核 + matplotlib-like wrapper（推荐）

**性能目标**：**~10-15×**，pan 帧 35ms → 2-3ms（asammdf 同级）
**风险**：中等，需要适配层 + 测试改写
**工期**：12-15 天（含 facade 设计、迁移、测试）

**核心思路**：
- 底层换成 pyqtgraph PlotWidget
- 提供薄薄一层 facade，把 pyqtgraph 包成"matplotlib Axes 长相"
- 外部代码（main_window / dialogs / tests）几乎不动

**文件改动范围**：

```
mf4_analyzer/ui/
├── canvases.py                 ← TimeDomainCanvas 改为 pyqtgraph PlotWidget 子类
├── _mpl_facade.py              ← 新增：把 pg.ViewBox + pg.AxisItem 包装成 matplotlib-like
├── chart_stack.py              ← _ChartCard 的 toolbar 改成自实现 (home/pan/zoom/save 按钮)
├── dialogs.py                  ← ChartOptionsDialog 走 facade（不知道底层是 pg）
└── _axis_interaction.py        ← target_axes_for_event 走 facade
```

**Facade 设计**（关键，决定测试和 dialogs 是否要动）：

```python
# _mpl_facade.py
class _AxesFacade:
    """Looks like matplotlib.Axes; backed by pyqtgraph ViewBox + AxisItems."""
    def __init__(self, viewbox, axis_items):
        self._vb = viewbox
        self._left_axis = axis_items['left']
        self._bottom_axis = axis_items['bottom']
        self.spines = _SpinesFacade(self._left_axis, ...)
        self.xaxis = _AxisFacade(self._bottom_axis)
        self.yaxis = _AxisFacade(self._left_axis)
        self.title = _TextFacade(...)
        # callbacks 给 main_window 的 xlim_changed listener 用
        self.callbacks = _CallbackRegistry()

    def get_xlim(self):
        x_range, _ = self._vb.viewRange()
        return tuple(x_range)
    def set_xlim(self, lo, hi):
        self._vb.setXRange(lo, hi, padding=0)
        self.callbacks.process('xlim_changed', self)
    def get_ylim(self): ...
    def set_ylim(self, lo, hi): ...
    def set_xscale(self, scale): self._vb.setLogMode(x=(scale == 'log'))
    def set_xlabel(self, text): self._bottom_axis.setLabel(text)
    def get_xlabel(self): ...
    def autoscale(self, axis='both'): self._vb.autoRange(...)
    def grid(self, enable, **_): self._vb.showGrid(x=enable, y=enable)
    # ... 其余 matplotlib API 按需补

class _SpinesFacade:
    """ax.spines['left'].set_color(...) → pg AxisItem.setPen(...)."""
    def __getitem__(self, side):
        return _SpineProxy(self._axis_items[side])

class _SpineProxy:
    def set_color(self, color): self._axis.setPen(color)
    def set_linewidth(self, lw): ...
```

**TimeDomainCanvas 新实现骨架**：

```python
class TimeDomainCanvas(pg.PlotWidget):  # 不再继承 FigureCanvas
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    span_selected = pyqtSignal(float, float)
    overlay_channel_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent, viewBox=ViewBoxWithCursor())
        self.axes_list = []          # _AxesFacade list, matplotlib-like
        self.channel_data = {}       # 完全保留原结构
        self._channel_lines = {}     # 改成 {name: (_AxesFacade, pg.PlotCurveItem)}
        self._primary_xaxis_ax = None  # _AxesFacade
        # ... 其他状态字段全部保留

    def plot_channels(self, ch_list, mode='overlay', xlabel='Time (s)'):
        # 把现有逻辑改成调 pyqtgraph
        # asammdf 的策略：单一 PlotCurveItem 共享 + sig.path 缓存
        ...

    # 公共 API 完全不变
    def clear(self): ...
    def full_reset(self): ...
    def set_cursor_visible(self, v): ...
    def set_dual_cursor_mode(self, en): ...
    def set_tick_density(self, x, y): ...
    def select_overlay_channel(self, name): ...
    def get_statistics(self, time_range=None): ...
    def invalidate_envelope_cache(self, reason, *, data_id=None, channel=None): ...
    def open_chart_options_dialog(self, ax=None): ...

    # 关键性能路径：直接抄 asammdf 的两个核心
    def _trim(self, signals=None, force=False): ...      # asammdf trim_c 模式
    def _scale_to_pixmap(self, x, y, y_range): ...      # asammdf scale_curve_to_pixmap
    def paintEvent(self, ev): ...                         # asammdf paintEvent
```

**NavigationToolbar 适配**：

NavigationToolbar2QT 强绑 matplotlib FigureCanvas，不能直接用。改 `_ChartCard.__init__` 自实现 toolbar：

```python
class _PgNavToolbar(QToolBar):
    """Replicates NavigationToolbar2QT's home/back/forward/pan/zoom/save
    against a pyqtgraph ViewBox; preserves the same QAction names + data()
    keys so apply_chinese_toolbar_labels + Ctrl+R/Z/G/B shortcut wiring
    keeps working unchanged."""
    
    def __init__(self, canvas, parent):
        super().__init__(parent)
        self._canvas = canvas
        self._history = []  # 自己维护 viewRange 栈替代 matplotlib home/back
        # 把 act.setData(key) 用同样的 key 'home/back/forward/pan/zoom/save'
        # — 这样 chart_stack.py 的 _find_action / _install_nav_shortcuts 完全不动
        ...
    def pan(self):
        # toggle pyqtgraph viewbox's left-button drag mode
        ...
    def zoom(self):
        # toggle rubber-band zoom
        ...
    def home(self):
        # restore initial view, push current to history
        ...
```

这层适配让 `chart_stack.py` 的 _ChartCard 内部 toolbar 逻辑 **完全不变** —— 它通过 `act.data() == 'pan'` 而不是 toolbar 类型来找按钮。

**Cursor / SpanSelector 适配**：

- 单/双 cursor：用 `pg.InfiniteLine`，比 matplotlib `axvline + blit` 更快也更原生
- 拖 pill：完全在 chart_stack 层，与 canvas 无关，不动
- SpanSelector：现已禁用（用户已在 commit ae1b3a4 删了 enable_span_selector 调用），无需迁移

**ChartOptionsDialog 适配**：

如果 `_AxesFacade` 提供完整的 matplotlib API：
- `get_xlim / set_xlim / get_ylim / set_ylim` ✓
- `set_xscale('log' | 'linear')` ✓
- `get_xlabel / set_xlabel / get_ylabel / set_ylabel` ✓
- `xaxis.get_gridlines()` → 返回有 `get_visible()` 的对象
- `spines[side].set_color/set_linewidth` ✓
- `tick_params(axis='y', colors=...)` ✓
- `get_lines() / images / collections` → pyqtgraph 没有 collections 但有 PlotCurveItem，可包成 Line2D-like
- `figure.canvas.draw_idle()` → pg widget 的 update

**dialogs.py 改动**：约 80 行（主要是 mappable 那块要适配 pyqtgraph 的 ImageItem / ColorBarItem）

**测试改写**：

```bash
$ grep -rn "canvas_time\.\(axes_list\|_channel_lines\|channel_data\|_primary_xaxis_ax\|fig\)" tests/ | wc -l
~60 个断言
```

如果 facade 做得到位，**这 60 个断言绝大多数不用改** — `canvas.axes_list[0].get_xlim()` 等都仍然工作。
要改的是直接断言 matplotlib `Line2D.get_xdata()` 的部分（~15 个），换成 facade 提供的等价方法。

但有 ~10 个测试断言了 matplotlib 内部细节，例如 `canvas._cursor_artists[0]` 是 axvline 对象 — 这些必须重写为"cursor line 可见 + x 位置正确"。这类改动是测试本身的语义升级，**不算 UI 行为变化**。

✅ **UI/UX 完全不变** — 用户层面零感知（除了"速度变快了"）
✅ **性能达到 asammdf 同级**（同栈、同核心算法）
⚠️ **依赖新增 pyqtgraph** — 但项目环境里 asammdf 已经把 pyqtgraph 拖进来了，无新依赖
⚠️ **ChartOptionsDialog 的 colormap / mappable 部分需要专项适配**（fft heatmap 仍走 matplotlib，dialog 要根据 canvas 类型分支）

---

### 方案 C — Hybrid：matplotlib 当 axes 外壳，pyqtgraph 当曲线层

**性能目标**：~6-8×，pan 帧 35ms → 4-5ms
**风险**：高（两套渲染系统协调，bug 来源多）
**工期**：未估，**不推荐**

技术上可行（matplotlib axes 内嵌一个 pyqtgraph widget 当 curves layer），但混合栈维护成本高，每个 bug 都要先判定属于哪一栈。**不建议走**。

---

## 四、推荐路线

**先做方案 A（1 周内交付，零风险）**，拿到 ~10ms / pan 帧。

> 这是 80% 收益的 20% 投入。多通道场景从"卡"到"流畅"够了。

**做完 A 后，让用户实测**：
- 如果 5 通道 / 1M 样本的 pan 体验在用户标准下"够用"了 → **停在这里**，不再投入
- 如果用户对比 asammdf 后仍觉差距明显 → **再做方案 B**，~2 周拿到同级体验

---

## 五、方案 B 的具体决策点（如果决定上）

> 这些是动工前需要回答的问题。我提供推荐答案。

1. **pyqtgraph 是否启用 OpenGL backend？**
   推荐 **不启用**。OpenGL 在远程桌面 / 虚拟机 / 一些显卡驱动下会闪退；对 1M 点以内的常见场景没有显著收益。asammdf 默认也不开。

2. **是否抄 asammdf 的 `cutils.positions` C 扩展？**
   - asammdf 是 LGPLv3，我们的项目（如果是商业闭源）需法务确认引用边界。**最稳妥是自己用 Cython / Numba 重写一份同算法**，~1 天工作量。
   - 如果项目本身也是 GPL/LGPL 兼容，可直接 vendor `cutils.pyd`。

3. **FFT / Spectrogram / Heatmap 是否一起换？**
   推荐 **不换**。它们是 compute-bound（单次绘制后基本不交互），matplotlib 的渲染体验完全够。仅时间域是 interaction-heavy 的。

4. **subplot 模式怎么实现？**
   pyqtgraph 用 `GraphicsLayoutWidget` 多 `PlotItem` 组合即可。每个 PlotItem 是一个独立 ViewBox + AxisItem，与现有 subplot 一一对应。

5. **overlay 模式（N 个 twinx）怎么实现？**
   asammdf 的方式：单一 ViewBox + 多个 FormatedAxis 共享 X，每个 axis 持有独立 y_range。已验证可行。

6. **NavigationToolbar 的 home/back/forward 历史栈怎么实现？**
   自维护 `[(x_range, y_range), ...]` 列表。pyqtgraph viewbox.sigRangeChangedManually 信号可监听用户每次 pan/zoom，push 到栈。home 是 push 后 set 到 [0]，back/forward 在栈中移动。

7. **测试如何分阶段迁移？**
   - 第一阶段：facade 实现完整后，跑现有测试套件，记录红色清单
   - 第二阶段：把"直接断言 matplotlib 内部 artist"的红色 case 改写成行为断言
   - 第三阶段：补 pyqtgraph 自己的回归 case（path 缓存命中、blit 命中、tick picture 缓存）

---

## 六、决策表

| 你的实际诉求 | 推荐方案 | 投入 | 拿到的 asammdf 体验 % |
|---|---|---|---|
| "卡就行，别太卡" | A | 1 周 | ~70% |
| "希望追到 asammdf，不在乎成本" | A → B | 1 + 2 周 = 3 周 | ~95% |
| "立刻全力追 asammdf" | B | 2 周 | ~90%（少了 A 的 path simplify 等微优化） |
| "彻底重写" | C | 不推荐 | — |

---

## 七、给你一个直接可执行的下一步

如果同意推荐路线，下一个 PR 内容明确：

```
PR-1（方案 A，1 周）:
  - mf4_analyzer/signal/_envelope_jit.py  新增 Numba JIT 版 envelope
  - mf4_analyzer/ui/canvases.py            预分配 buffer、animated Line2D、blit-only refresh
  - rcParams 改 antialias / simplify
  - tests/ui/test_canvases.py              新增 blit fast-path 命中测试
  
  验收: 5 通道 / 100k 点 pan 帧 ≤ 10ms（cProfile + 实测两个口径）
```

PR-1 落地后，根据实测体验决定是否启动 PR-2 (方案 B)。

如果你直接要 B，告诉我，我可以立即开始 facade 设计和 spike 分支。
