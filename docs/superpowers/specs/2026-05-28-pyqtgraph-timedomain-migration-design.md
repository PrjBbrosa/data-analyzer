# TimeDomainCanvas → pyqtgraph 迁移 Design Spec

**Date:** 2026-05-28
**Branch:** `plan/pyqtgraph-timedomain-migration`
**Status:** ready to execute
**Related prior review:** `docs/analyzer/reviews/2026-05-28-plot-perf-vs-asammdf.md`
**Plan tier:** 档 B（仅替换 TimeDomainCanvas，FFT/Heatmap/Spectrogram 保留 matplotlib）

---

## 1. Goal

把 TimeDomainCanvas 的渲染栈从 `matplotlib + FigureCanvasQTAgg` 切到 **`pyqtgraph + 自维护 paintEvent / pixmap cache`**，达到与 asammdf-gui 同档的 pan/zoom 流畅度（≤ 5 ms / 帧 @ 5 通道 × 100k 样本）。

**非目标：**
- 不迁移 FFTCanvas / HeatmapCanvas / SpectrogramCanvas / PlotCanvas (order)。这些是 compute-bound + 单次渲染，matplotlib 表现足够。
- 不切 PySide6。pyqtgraph 在 PyQt5 下工作正常，只需控制 import 顺序。
- 不开 OpenGL backend（`useOpenGL=True`）。对单千万点以内场景没有显著收益，且远程桌面 / VM 兼容性差。
- 不引入自维护的 C 扩展。直接复用 `asammdf.blocks.cutils.positions`（asammdf 已是依赖）。
- 不重做 ChartOptionsDialog 的 UI（保留 PyQt5 dialog，只换底层 axis 访问接口）。

---

## 2. Scope

### 2.1 Included

**新增模块：**

- `mf4_analyzer/ui/pg_canvases.py`（新）：`TimeDomainCanvasPG`、`PgAxisAdapter`、`PgToolbar` 三个类
- `mf4_analyzer/ui/_axis_handle.py`（新）：`AxisHandle` 抽象基类 + matplotlib / pyqtgraph 两个实现
- `mf4_analyzer/signal/_envelope_cutils.py`（新）：`positions` 包装层 + numpy 回退

**修改模块：**

- `mf4_analyzer/ui/canvases.py`：保留旧 TimeDomainCanvas 在分支期间，最终阶段删除
- `mf4_analyzer/ui/chart_stack.py`：`_ChartCard` / `TimeChartCard` 切换到新画布、新 toolbar
- `mf4_analyzer/ui/dialogs.py`：`ChartOptionsDialog` 改成接受 `AxisHandle` 而非 matplotlib `Axes`
- `mf4_analyzer/ui/_axis_interaction.py`：`find_axis_for_dblclick` / `_open_chart_options_for_event` 兼容 pyqtgraph 命中检测
- `mf4_analyzer/ui/main_window.py`：保持 `set_cursor_visible / set_dual_cursor_mode / invalidate_envelope_cache / invalidate_monotonicity_cache` 签名不变，让 main_window 无感
- `requirements.txt`：新增 `pyqtgraph>=0.13.3`

**功能必须 1:1 兑现（survey §1-§15 全量）：**

15 个公开方法 + 4 个 Qt signal + 单/双游标 + SpanSelector + 子图/叠图两模式 + 双击轴 → 编辑对话框 + 视口下采样 + 统计 + 模态期 toolbar 禁用 + Y 轴 hover PointingHandCursor + inside label + monotonicity cache。

### 2.2 Excluded

- 性能基线、性能回归测试（独立 spec，不在本次合入）
- asammdf 的 region / Y axis Y-link / channel chip 切换 / value list 等本应用不需要的特性
- 颜色主题切换（保留现有 matplotlib 风格的暗色 + 浅灰网格）
- 中文字体特殊处理（pyqtgraph 用 Qt 字体栈，原生支持，无 Hershey 路径瓶颈）
- 性能比对 demo（已在 review 文档完成，不再独立开 spike）

---

## 3. Architecture

### 3.1 类关系

```
┌────────────────────────────────────────────────────────┐
│ TimeChartCard (chart_stack.py)                          │
│ ┌────────────────────────────────────────────────────┐ │
│ │ PgToolbar (新)                                      │ │
│ │   pan / zoom toggle, home, save, mode dispatch     │ │
│ └─────────────────┬──────────────────────────────────┘ │
│ ┌────────────────▼──────────────────────────────────┐ │
│ │ TimeDomainCanvasPG (pg.GraphicsLayoutWidget)       │ │
│ │  ├─ self._lw: GraphicsLayoutWidget                │ │
│ │  ├─ self._plots: list[pg.PlotItem]   (subplot)    │ │
│ │  │   或                                             │ │
│ │  │  self._primary_plot + self._overlay_vbs         │ │
│ │  │  list[pg.ViewBox]                  (overlay)    │ │
│ │  ├─ self._curves: dict[name, pg.PlotDataItem]      │ │
│ │  ├─ self._cursor_a / self._cursor_b: InfiniteLine  │ │
│ │  ├─ self._span: LinearRegionItem (lazy)            │ │
│ │  └─ self._channel_data: dict[name, (t,s,c,u)]      │ │
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
       │
       │ uses
       ▼
┌────────────────────────────────────────────────────────┐
│ AxisHandle (新, _axis_handle.py)                        │
│   抽象：get_xlim/set_xlim/get_ylim/set_ylim/             │
│         autoscale/set_scale/set_label/get_label         │
│   实现：MplAxisHandle, PgAxisHandle                      │
└────────────────────────────────────────────────────────┘
       ▲
       │ consumes
┌──────┴─────────────────────────────────────────────────┐
│ ChartOptionsDialog (dialogs.py)                         │
│   原本 ax: matplotlib.Axes                              │
│   迁移后 handle: AxisHandle                              │
└────────────────────────────────────────────────────────┘
```

### 3.2 关键设计决策

#### D1. 用 `AxisHandle` 抽象，**不**改 ChartOptionsDialog 的 UI
ChartOptionsDialog 现状直接调用 `ax.get_xlim() / set_xlim() / autoscale()`，跟 matplotlib Axes 强耦合。
**做法**：新增 `_axis_handle.py`，提供以下接口：

```python
class AxisHandle(Protocol):
    def get_xlim(self) -> tuple[float, float]: ...
    def set_xlim(self, lo: float, hi: float) -> None: ...
    def get_ylim(self) -> tuple[float, float]: ...
    def set_ylim(self, lo: float, hi: float) -> None: ...
    def autoscale(self, axis: str = 'both') -> None: ...
    def set_xscale(self, scale: str) -> None: ...  # 'linear'/'log'
    def set_yscale(self, scale: str) -> None: ...
    def get_xlabel(self) -> str: ...
    def get_ylabel(self) -> str: ...
    def set_xlabel(self, label: str) -> None: ...
    def set_ylabel(self, label: str) -> None: ...
    def get_lines(self) -> list[LineHandle]: ...  # 用于 Appearance tab
    def request_redraw(self) -> None: ...
```

`MplAxisHandle(ax)` 直通 matplotlib；`PgAxisHandle(plot_item)` 把 `plot_item.getViewBox().viewRange()` 这些映射过去。ChartOptionsDialog **只改一个口子**：构造时接 `AxisHandle` 而不是 `Axes`。

剩余画布（FFT / Heatmap / Spectrogram / Order）外层包一层 `MplAxisHandle` 即可，**0 行业务改动**。

#### D2. 下采样：先 `build_envelope` 复用，再切 `cutils.positions`
- **阶段 1** 直接调用现有的 `build_envelope(t, sig, xlim, pixel_width, is_monotonic)`，输出 `(td, sd)` numpy 数组，喂给 `pg.PlotDataItem.setData`。已知 5-10 ms / 通道 / pan 帧，**先保证功能正确**。
- **阶段 2** 替换为 `signal/_envelope_cutils.py::positions_envelope(t, sig, xlim, pixel_width)`：

```python
try:
    from asammdf.blocks.cutils import positions as _c_positions
    _HAS_C_POSITIONS = True
except ImportError:
    _HAS_C_POSITIONS = False

def positions_envelope(t, sig, xlim, pixel_width):
    if not _HAS_C_POSITIONS or pixel_width < 4 or len(sig) < pixel_width * 4:
        return build_envelope(t, sig, xlim, pixel_width, is_monotonic=True)
    # 预分配（按 max 增长不 shrink，sticky buffer）
    ...
    _c_positions(samples, timestamps, plot_samples, plot_timestamps, pos, steps, count, rest, dtype_kind, itemsize)
    return plot_timestamps[:N], plot_samples[:N]
```

预期单通道 100k 点：5 ms → 0.3 ms（~15×）。

> **许可证检查项**：asammdf 是 LGPL v3+。本项目目前以 pip 依赖形式分发 asammdf，调用其公开 API 不构成衍生作品；本次新增的"通过 Python 调用 asammdf 中的 `cutils.positions`" 与既有调用 `asammdf.MDF(...)` 同性质。**Phase 0 验收前需让人复核一次**，记录在 spec 末尾的 risk register。

#### D3. 主结构：`pg.GraphicsLayoutWidget` + 模式分支
- **subplot 模式** (`len(vis) > 1`)：垂直堆叠 `PlotItem`，第 2 个起 `setXLink(plots[0])`；底部那个显示 xlabel + xticks，其余 hide bottom axis label。
- **overlay 模式** (`len(vis) >= 2` 且 inspector 选了 overlay)：单 `PlotItem`，第 1 通道挂在 `primary_vb`，第 2-N 通道每个挂一个 `pg.ViewBox`，X 轴跟 primary `setXLink`；每个 ViewBox 配一个右侧 `pg.AxisItem`，通过 `axis.linkToView(vb)` 关联。
- **单通道**：和 subplot 模式同代码路径，`len(plots) == 1`。

参考实现：`asammdf/gui/widgets/plot.py` 的 `Plot._setup_layout` 系列。

#### D4. 模态期 toolbar 禁用：在 PgToolbar 内封装
现有 `_toolbar_mode_key()` 检查 `toolbar.mode in ('pan', 'zoom')` 用于模态对话框前禁用 nav。pyqtgraph 没有原生 toolbar mode 状态。
**做法**：`PgToolbar` 自己维护 `self._mode: Literal['idle', 'pan', 'zoom']`，对外暴露 `def mode(self) -> str` 与现 NavToolbar2QT 同名同义；`deactivate_modal_nav() / restore_nav()` 封装为方法。`_axis_interaction.py` 改两行调用即可。

#### D5. 单/双游标：`InfiniteLine` 而非自维护 blit
pyqtgraph 的 `pg.InfiniteLine(angle=90, movable=False)` 自带高效渲染（pixmap 内合成），不需要 `_bg` / `_refresh_bg`。
- `set_cursor_visible(v)` → `cursor.setVisible(v)`
- `_update_single(x)` → `cursor.setPos(x)` + 计算并 emit `cursor_info`
- `_update_dual(...)` → `cursor_a.setPos(...) + cursor_b.setPos(...)` + 计算并 emit `dual_cursor_info`
- `_a_artists / _b_artists` 等内部状态删掉
- `_bg / _refresh_bg / _flush_pending_refresh` 全删

`cursor_info` / `dual_cursor_info` 的 HTML 文本格式与 `_interp_cursor_value / _format_dual_html` **复用现有 module-level 函数**，零改动。

#### D6. SpanSelector → `LinearRegionItem`
- `enable_span_selector(cb)` 内部 lazy 创建 `pg.LinearRegionItem(values=[lo, hi], orientation='vertical', movable=True)`
- 连接 `region.sigRegionChangeFinished` → emit `span_selected(lo, hi)` + 调用户 cb
- 模态期通过 `region.setMovable(False) / setVisible(False)` 控制
- 注：matplotlib SpanSelector 的鼠标右键拖创建语义在 pg 下走双击进入 span 模式（或 inspector 上的按钮），具体由 chart_stack 现有 UI 决定 — **不在本 spec 改 UX**

#### D7. Inside label：`pg.TextItem`
matplotlib 现状用 `ax.text(...)` 在 axes 坐标系画一个带 box 的标签（survey 提到 `_apply_inside_channel_labels`）。
对应 pg：

```python
label = pg.TextItem(text, anchor=(0, 0), color=(r, g, b), fill=fill_color)
plot_item.addItem(label, ignoreBounds=True)
label.setParentItem(plot_item.vb)
label.setPos(8, 8)  # viewbox 坐标
```

`_subplot_ylabels_need_inside_labels` 的渲染器 bbox 检测在 pg 下做不到（无 renderer），**简化为 fixed-rule**：当 Y label 字符串长度 > 14 或 unit 字符串非空时，自动启用 inside label。和 matplotlib 现状行为有 5-10% 差异，**接受**。

#### D8. Y 轴 hover PointingHandCursor
matplotlib 走 `_on_move` + `find_axis_for_dblclick`。pyqtgraph 路径：
- 给每个 `pg.AxisItem` 绑 `axis.hoverEvent = self._on_axis_hover`
- hover 时 `QApplication.setOverrideCursor(Qt.PointingHandCursor)`，leave 时 `restoreOverrideCursor()`
- 双击事件挂 `axis.mouseDoubleClickEvent`

不再需要每帧 hit-test，节省 setCursor IPC 调用（survey §2.9 提到的瓶颈）。

#### D9. 模拟"`find_axis_for_dblclick`"语义供外部使用
`_axis_interaction.py:18` 的 `find_axis_for_dblclick(fig, x_px, y_px, margin)` 被多个外部点引用。改成 dispatch：
- 对 matplotlib canvas 走旧逻辑
- 对 `TimeDomainCanvasPG` 走 `canvas._axis_at_qpoint(QPoint(x_px, y_px))`，内部遍历 `_plots + _overlay_vbs` 的 sceneBoundingRect

返回 `(plot_item_or_None, axis_kind: 'x'/'y'/None)`。`_open_chart_options_for_event` 接收后构造 `PgAxisHandle(plot_item)` 喂给 dialog。

#### D10. 直接访问 `canvas._channel_lines / canvas.channel_data / canvas.fig` 的外部点
survey §14 列出的所有访问点：

- `canvas.fig` 被 `chart_stack.image_copy / ChartOptionsDialog / _axis_interaction` 使用
  - 替换：新画布暴露 `canvas.grab_image() -> QImage`（截图导出），dialog / interaction 走 `AxisHandle`
- `canvas.axes_list` → 新画布暴露 `canvas.plot_items() -> list[pg.PlotItem]`
- `canvas._channel_lines` → 新画布暴露 `canvas.curve_for(name) -> pg.PlotDataItem`
- `canvas.channel_data` → 保持同名 dict 同 schema（迁移容易）
- `canvas._inside_channel_label_artists` → 新画布暴露 `canvas.inside_label_for(name) -> pg.TextItem | None`
- main_window 直接 mutate `canvas._ax / _bx / _placing / _refresh` → 全部封装成 `canvas.reset_cursor_state()` 方法

**原则**：底层 artist 不向外暴露，全部走 getter / setter 方法。

#### D11. 旧 TimeDomainCanvas 何时删
**分阶段保留**：
- Phase 0-4 期间，旧 canvas 留在 `canvases.py`，新 canvas 在 `pg_canvases.py`
- Phase 5（最后）切 chart_stack 的 import，跑全 UI 测试 + 手动 dogfood 1 周
- 如稳定，Phase 6 删旧 canvas + 旧 `_bg` / `_refresh_bg` / `build_envelope` LRU cache 相关测试（envelope 模块本身保留）
- 不引入运行期 feature flag（项目偏好「不留 backwards-compat hack」）

---

## 4. 执行 phases

### Phase 0 — Spike / 依赖验证（0.5 day）

**目标**：证明 pyqtgraph 在本项目 Python / Qt 版本下能 import + 显示一根曲线 + 不破坏现有打包。

**任务**：
1. `pip install pyqtgraph>=0.13.3` 在 `.venv-build-win`，验证 import 成功 + 与 PyQt5 共存
2. 写 `tests/spike/test_pg_smoke.py`：`pytest-qt` 跑一个 GraphicsLayoutWidget 显示 1000 点曲线，pytest 退出 code 0
3. 把 `pyqtgraph` 加入 `requirements.txt`
4. 跑一次本地 PyInstaller 打包（如果 build skill 已有 hook），确认 .exe 启动不报缺包
   - 如果 PyInstaller 报缺 `pyqtgraph.opengl` 等 hidden import，加 hook 文件 `packaging/hooks/hook-pyqtgraph.py`
5. **确认 `from asammdf.blocks.cutils import positions` 在 `.venv-build-win` 可用**，写一个 micro-bench：`positions` 处理 100k 点 vs `build_envelope`，记录倍率

**验收**：
- spike 测试通过
- 打包产物启动正常
- `cutils.positions` micro-bench 给出具体数字
- LGPL 复核结论写进本 spec 末尾 risk register

**回退**：如 pyqtgraph + PyInstaller 兼容性炸了，停在这里，重评估档 A。

---

### Phase 1 — `TimeDomainCanvasPG` 骨架 + 单通道 + 游标 + ChartOptionsDialog（1.5 day）

**目标**：能 plot 单通道、显示单/双游标、双击 Y 轴打开 dialog 改限值，**不**接 chart_stack（独立 demo）。

**新增文件**：

```
mf4_analyzer/ui/pg_canvases.py
mf4_analyzer/ui/_axis_handle.py
mf4_analyzer/signal/_envelope_cutils.py    # 占位，先 fallback 到 build_envelope
tests/ui/test_pg_canvas_basic.py           # 单通道 + 游标 + dialog 烟雾测试
```

**任务**：
1. 写 `AxisHandle` Protocol + `MplAxisHandle` + `PgAxisHandle`
2. 写 `TimeDomainCanvasPG.__init__`：`GraphicsLayoutWidget`，主 `PlotItem`，背景色和 axis pen 与现网格风格一致
3. 实现 `plot_channels(ch_list, mode='subplot', xlabel='Time [s]')` 单通道分支：
   - 存 `channel_data[name] = (t, sig, color, unit)`
   - 创建 `pg.PlotDataItem`（默认 `antialias=False`），喂 envelope 输出
   - 监听 `plot_item.getViewBox().sigXRangeChanged` 触发 envelope 重算
   - 设 X label / Y label / unit chip（unit chip 用 `pg.LabelItem`，addItem 到 layout 顶部）
4. 实现 `set_cursor_visible(v)` / `set_dual_cursor_mode(en)` / `_update_single` / `_update_dual` 用 InfiniteLine
5. 改 `ChartOptionsDialog`：构造函数接 `AxisHandle` 而非 `Axes`；用 `replace_all` 替换 `self.ax.get_xlim()` → `self.handle.get_xlim()` 等等
   - 同步改 `_axis_interaction.py` 两个 helper 函数构造 dialog 处传入 `MplAxisHandle(ax)`（旧画布走这里）或 `PgAxisHandle(plot_item)`（新画布走这里）
6. 实现 `canvas._axis_at_qpoint` 命中检测，挂 `axis.mouseDoubleClickEvent`
7. 实现 `open_chart_options_dialog(plot_item)` 入口
8. 把 `cursor_info` / `dual_cursor_info` 两个 signal 接通，`_interp_cursor_value / _format_dual_html` 直接复用

**验收**：
- demo 程序（`scripts/dev/pg_demo.py`，不入正式分发）显示单通道、双击 Y 轴改限值、单/双游标移动正确
- `tests/ui/test_pg_canvas_basic.py` 3 个测试全过：
  - `test_plot_single_channel_emits_curve`
  - `test_cursor_visible_toggle`
  - `test_double_click_y_axis_opens_dialog`
- `pytest tests/` 全套不退化（旧画布全部测试照过）

**风险**：
- ChartOptionsDialog 改动可能影响其他画布 — 用 `MplAxisHandle` 包一层后理论 0 行为变化，必须跑现有 dialog 测试验证
- Qt 的 mouseDoubleClickEvent 与 pyqtgraph 默认行为可能冲突，需要 `axis.installEventFilter` 兜底

---

### Phase 2 — 多通道 subplot + overlay 模式 + 视口下采样（1.5 day）

**目标**：5 通道场景，subplot / overlay 两模式都能跑，pan/zoom 触发 envelope 重算，性能达预期（pan 帧 < 10 ms，cutils 路径下）。

**任务**：
1. `plot_channels` 加 `mode='subplot' | 'overlay'` 分支
   - subplot：垂直堆 `PlotItem`，`setXLink` 链接，底部 plot 显示 xlabel
   - overlay：单 `PlotItem` + 多 `ViewBox` + 多 `AxisItem`，参考 `asammdf/gui/widgets/plot.py` 的 layout 代码（不抄袭，自己写）
2. 实现 `selected_overlay_channel` / `select_overlay_channel` / `overlay_channel_selected` signal
   - 复用现有 `_select_overlay_channel_from_event` 逻辑但用 pg 坐标
3. 接入 envelope cache：保留现 `_envelope_cached` LRU + monotonicity cache（这些是 pure 函数，无需改）
4. 在 `sigXRangeChanged` handler 里：
   - 拿到 viewport 像素宽（`plot_item.getViewBox().width()`）
   - 对每个可见通道调 `_envelope_cached(...)` 或 `positions_envelope(...)`
   - `curve.setData(td, sd)`（不分配新 array，pg 内部会复用）
5. 切 envelope 后端到 `positions_envelope`（已经在 _envelope_cutils.py 准备好的回退路径）
6. 实现 `set_tick_density(x, y)` / `invalidate_envelope_cache` / `invalidate_monotonicity_cache` 等公开方法
7. 实现 `clear` / `full_reset`，确保 plot items / view boxes / cursor lines 全清理，无 leak

**验收**：
- `tests/ui/test_pg_canvas_multi.py`：
  - 5 通道 subplot 模式 plot 成功
  - 5 通道 overlay 模式 plot 成功
  - 视口 setXRange → curve 数据点数变化（envelope 工作）
  - `select_overlay_channel('signal2')` 后 `overlay_channel_selected` signal emit 正确
- 微基准 `tests/perf/test_pg_pan_perf.py`（marked `@pytest.mark.slow`，不强制 CI）：5 通道 100k 样本 pan 帧时间分布 P50 < 8 ms，P95 < 15 ms

**风险**：
- overlay 模式的 ViewBox 多层堆叠 layout 调参反复，可能要 1 天单独打磨
- envelope cache key 现在用 matplotlib `xlim` quantized，pg 也要给一致的 key（用 viewbox.viewRange()[0] 同样 quantize）

---

### Phase 3 — Span selector + 统计 + 模态 toolbar（1 day）

**目标**：完成剩余的 4 个公开方法和工具栏交互。

**任务**：
1. `enable_span_selector(cb)` + `span_selected` signal + `LinearRegionItem`
2. `get_statistics(time_range) -> dict` — 直接复用旧实现（操作 `channel_data` 全量数据，无关画布）
3. `PgToolbar` 类：
   - 给 chart_stack `_ChartCard` 当 toolbar 用
   - 按钮：pan 切换 / zoom 切换 / home（reset view）/ save image（导 png）
   - `mode` 属性返回 `'pan' / 'zoom' / ''`，与 NavToolbar2QT 同义
   - `deactivate_modal_nav` / `restore_nav` 方法
4. 改 `chart_stack.py::TimeChartCard`：
   - import `TimeDomainCanvasPG` + `PgToolbar`
   - **不在本 phase 切换**，先在一个 feature 分支 `--with-pg-time` 命令行开关下打开（仅 dev 用，不暴露给最终用户）
5. 把 main_window 里所有 `canvas._ax / _bx / _placing / _refresh` 的直接 mutate 收编：
   - 新画布提供 `canvas.reset_cursor_state()`
   - main_window 旧画布路径不变（暂时 if-isinstance 二分支）

**验收**：
- `tests/ui/test_pg_canvas_span.py`：span 选择触发 `span_selected` signal，数值对得上
- `tests/ui/test_pg_canvas_stats.py`：5 通道 + 子区间 → stats 字典与旧画布同输入同输出位级一致
- 手动跑 chart_stack 在 dev flag 下能完整加载一个 MF4 文件并交互

---

### Phase 4 — Inside label + 模态 hover + 最后打磨（0.5 day）

**目标**：把视觉细节和小交互补齐。

**任务**：
1. Inside label 用 TextItem，规则简化为 "ylabel 长 > 14 或 unit 非空则启用"（D7）
2. Y 轴 hover PointingHandCursor（D8）
3. resize / DPI 切换 layout 重算（pyqtgraph 自动处理，验证一遍即可）
4. 颜色 / 字体 / 网格风格对齐旧画布
5. 双击 X 轴打开 dialog（现有逻辑应该一并打通）

**验收**：
- 视觉对照旧画布，pixel-imperfect 但 "看起来一致"，1080p 屏目测过关
- 跑 chart_stack 在 dev flag 下不出现样式回退（无白底，无错字号）

---

### Phase 5 — 切生产（0.5 day）+ 试用期

**目标**：默认走新画布。

**任务**：
1. `chart_stack.py::TimeChartCard` 默认走 `TimeDomainCanvasPG`，删 dev flag
2. 跑 `pytest tests/`，确认全过（含旧 envelope cache 测试 — 后端仍叫 build_envelope，路径还在）
3. 跑一次完整 batch 流程 + 一次完整交互流程 dogfood，特别确认：
   - 多文件加载切换
   - inspector 改通道颜色 → 画布同步
   - inspector 改 Y 限值 → 画布同步
   - export 截图
   - 模态对话框前后 toolbar 状态恢复
4. 合 PR，**保留旧 TimeDomainCanvas 类不删**（merge 后 1 周观察期）

**验收**：
- 全测试套绿
- 手动 5 通道 × 100k 样本 pan 流畅度对照 asammdf，主观无差距
- 无 console error / Qt warning 喷涌

---

### Phase 6 — 清理（0.5 day，merge 后 1 周）

**目标**：删旧代码。

**任务**：
1. 删 `canvases.py` 里的 `TimeDomainCanvas` 类 + `_bg` / `_refresh_bg` / `_flush_pending_refresh` 等相关私有方法
2. 删 `MplAxisHandle` 的 TimeDomain 专用路径（保留给 FFT / Heatmap / Spectrogram / Order 用）
3. 删 `scripts/dev/pg_demo.py`（如有）
4. 收尾 doc：在 `docs/superpowers/reports/` 写一份 retrospective，记录实际 vs 估时、坑、新性能基线

---

## 5. Signal / API 对照表

| 旧 (matplotlib) | 新 (pg) | 备注 |
| --- | --- | --- |
| `cursor_info: pyqtSignal(str)` | 同名同签名 | 文本生成函数复用 |
| `dual_cursor_info: pyqtSignal(str)` | 同名同签名 | 同上 |
| `span_selected: pyqtSignal(float, float)` | 同名同签名 | LinearRegionItem 驱动 |
| `overlay_channel_selected: pyqtSignal(object)` | 同名同签名 | hit-test 由 ViewBox scene 提供 |
| `plot_channels(...)` | 同名同签名 | |
| `set_cursor_visible(v)` | 同名同签名 | |
| `set_dual_cursor_mode(en)` | 同名同签名 | |
| `clear()` | 同名同签名 | |
| `full_reset()` | 同名同签名 | |
| `open_chart_options_dialog(ax)` | `open_chart_options_dialog(plot_item)` | 参数类型变了，但调用方都在 _axis_interaction.py，内部 dispatch |
| `selected_overlay_channel()` | 同名同签名 | |
| `select_overlay_channel(name)` | 同名同签名 | |
| `get_statistics(time_range)` | 同名同签名 | |
| `set_tick_density(x, y)` | 同名同签名 | |
| `enable_span_selector(cb)` | 同名同签名 | |
| `invalidate_envelope_cache(...)` | 同名同签名 | 内部 cache 是 pure 函数，签名 0 改 |
| `invalidate_monotonicity_cache(...)` | 同名同签名 | 同上 |
| `draw_idle()` | 同名 | 新画布 noop（pg 自动 schedule repaint）|
| `canvas.fig` | `canvas.grab_image() -> QImage` | 截图用 |
| `canvas.axes_list` | `canvas.plot_items() -> list[PlotItem]` | |
| `canvas._channel_lines` | `canvas.curve_for(name) -> PlotDataItem` | |
| `canvas.channel_data` | 同名同 schema | |
| `canvas._inside_channel_label_artists` | `canvas.inside_label_for(name)` | |
| `canvas._ax / _bx / _placing / _refresh` | `canvas.reset_cursor_state()` | 封装 |

---

## 6. 测试策略

### 6.1 保留不动

- `tests/test_canvases_envelope.py` — `build_envelope` 是 pure function，签名不变
- `tests/test_envelope.py` — 同上
- `tests/test_axis_interaction.py` — 增补 pg 命中分支测试

### 6.2 新增

| 文件 | 测试覆盖 |
| --- | --- |
| `tests/ui/test_pg_canvas_basic.py` | 单通道 plot + 游标 + dialog |
| `tests/ui/test_pg_canvas_multi.py` | subplot / overlay 多通道 + envelope 触发 |
| `tests/ui/test_pg_canvas_span.py` | span selector |
| `tests/ui/test_pg_canvas_stats.py` | 与旧画布 bit-level 同输入同输出 |
| `tests/ui/test_axis_handle.py` | `MplAxisHandle` / `PgAxisHandle` 参数化 |
| `tests/ui/test_dialog_with_handle.py` | ChartOptionsDialog 在两种 handle 下行为一致 |
| `tests/perf/test_pg_pan_perf.py` (`@slow`) | 5 通道 pan 帧 P50/P95（不阻塞 CI）|
| `tests/spike/test_pg_smoke.py` (Phase 0) | 装包正确性 |

### 6.3 回归保护

- Phase 1-4 期间，**旧画布所有测试持续运行**，不允许任何一个绿变红
- 新增的 ui/ 测试用 `pytest-qt` 的 `qtbot.waitSignal`，避免依赖固定 sleep

### 6.4 手动 smoke

每个 phase 结束跑：
1. 单文件 1 通道
2. 单文件 5 通道 subplot
3. 单文件 5 通道 overlay
4. 多文件叠图
5. 改通道颜色 / 限值 / 单位 → 画布同步
6. 双游标 + span selector → 数值正确

---

## 7. Risk register

| ID | 风险 | 影响 | Mitigation |
| --- | --- | --- | --- |
| R1 | `asammdf.blocks.cutils.positions` LGPL 合规性未确认 | 法务问题 | Phase 0 即让人复核；如不通过，**降级为纯 numpy `build_envelope`**（性能仍优于现状 8-10×，因为省了 matplotlib draw 开销）|
| R2 | PyInstaller 打包漏 pyqtgraph hidden import | .exe 启动崩 | Phase 0 跑一次打包；如缺包写 `packaging/hooks/hook-pyqtgraph.py` |
| R3 | pyqtgraph 与 PyQt5 import 顺序导致绑定错乱（pyqtgraph 默认探测 PySide6 first） | 启动崩 | 在 `mf4_analyzer/__init__.py` 顶部强制 `import PyQt5` 在 `import pyqtgraph` 之前；在 `pg_canvases.py` 头部 `import os; os.environ['PYQTGRAPH_QT_LIB'] = 'PyQt5'` |
| R4 | ChartOptionsDialog 改造影响 FFT / Heatmap / Spectrogram / Order 画布 | 范围炸 | `MplAxisHandle` 包一层，dialog 调用面收口；所有现有 dialog 测试 must pass |
| R5 | Overlay 模式 ViewBox 多层 layout 调参超预算 | Phase 2 延期 | 直接参考 asammdf `plot.py:3892` 之后的写法，不创新；超 1 天弹回求助 |
| R6 | `canvas._ax / _bx` 等私有属性被 main_window / chart_stack 隐式依赖路径多于 survey 所列 | 切换后 crash | Phase 5 切换前用 `grep -rn "canvas\._" mf4_analyzer/` 全文扫描 |
| R7 | `find_axis_for_dblclick` 既要兼容 matplotlib 又要兼容 pg，可能成"双头函数" | 维护负担 | 直接 dispatch on canvas type，**不**抽象统一接口（小一点的代码量更易维护，参考项目"不要过度抽象"偏好）|
| R8 | 中文 Y 轴 label 在 pg AxisItem 下字体回退到方块 | 视觉退化 | 在 `pg_canvases.py` 顶部 `QFont` 设置 `Microsoft YaHei` fallback，参考现有 matplotlib 中文字体配置 |
| R9 | dual cursor / span / overlay-select 三种交互在同一时刻只能一种激活，状态机散落在 main_window | 行为退化 | Phase 3 跑前先在 main_window 找到所有 set 这些状态的点，列清单；切换时严格按列表对照测试 |
| R10 | 性能没有达到 asammdf 同档（如阶段 2 测出 pan 帧 > 15 ms）| 投入产出比劣化 | Phase 2 验收时若 P50 > 12 ms，停下来 profile；优先排查 envelope 输出是否真的从 cutils 走 |

---

## 8. Rollback plan

**Phase 0 失败**：直接放弃，切回 main，删 branch。

**Phase 1-4 中任何 phase 失败**：
- 留 branch 在那里不合，回到 main 上做档 A 的 blit 优化
- 已写的 `AxisHandle` 抽象可以 cherry-pick 回来给 dialog 解耦，本身不绑定 pyqtgraph

**Phase 5 切生产后回退**：
- Phase 5 PR 只改 chart_stack 一个文件 import，1 行 revert 即可
- 旧 TimeDomainCanvas 类此时仍在 canvases.py（Phase 6 才删）

**Phase 6 清理后回退**：
- 通过 git revert 双 PR（Phase 6 + Phase 5），恢复旧画布

---

## 9. Acceptance criteria（最终）

- [ ] `pytest tests/` 全套绿
- [ ] 5 通道 × 100k 样本 pan 帧 P50 ≤ 8 ms（cutils 路径）或 ≤ 15 ms（numpy 回退路径）
- [ ] 旧 TimeDomainCanvas 的 15 个公开方法 + 4 个 signal 在新画布上 1:1 兑现（survey §1-§2 全量勾选）
- [ ] ChartOptionsDialog 在 matplotlib / pyqtgraph 两类轴上行为一致（双向参数化测试通过）
- [ ] PyInstaller 打包产物启动正常，pyqtgraph 不缺包
- [ ] 中文 Y 轴 label / unit chip 显示正常
- [ ] 模态对话框前 toolbar pan/zoom 被禁用，对话框关闭后恢复
- [ ] 视觉对照旧画布无明显回退（颜色、网格、字体、inside label 可接受 5-10% 像素差）
- [ ] LGPL 合规复核留底（risk R1）

---

## 10. Timeline 估算

| Phase | 估时 | 累计 |
| --- | --- | --- |
| 0 — Spike | 0.5 d | 0.5 |
| 1 — 骨架 + 单通道 + dialog | 1.5 d | 2.0 |
| 2 — 多通道 + envelope | 1.5 d | 3.5 |
| 3 — Span + stats + toolbar | 1.0 d | 4.5 |
| 4 — Inside label + 打磨 | 0.5 d | 5.0 |
| 5 — 切生产 | 0.5 d | 5.5 |
| Buffer (R5 / R9 风险吸收) | 1.5 d | 7.0 |
| 6 — 清理（合入后 1 周）| 0.5 d | — |

**总：5-7 人日，预留 buffer**。

文档评审 review 估 0.5 d（如走 codex / ultrareview），不计入。

---

## 11. Open questions

1. **LGPL 复核谁来做？** 建议在 Phase 0 验收前由用户拍板，否则 R1 直接锁回到 numpy 回退路径。
2. **打包产物是否纳入本次回归测试？** 当前 CI 不打 .exe，如要打包验证需要单独触发 build job。建议 Phase 0 手动一次即可，不纳入 CI。
3. **`scripts/dev/pg_demo.py` 是否保留？** 我倾向 Phase 6 删，但如果团队想留作未来维护参考也可以。
4. **Inside label 的 5-10% 视觉差异是否需要 designer 签字？** 当前没有 designer 角色，估计用户主观接受即可。

---

## 附录 A — 参考资源

- asammdf 源码（已经在 .venv-build-win 中）：
  - `asammdf/gui/widgets/plot.py` — `PlotGraphics.paintEvent` (line 5434-5670) / `trim_c` (1063-1193) / `scale_curve_to_pixmap` (5818-5849)
  - `asammdf/gui/widgets/viewbox.py` — `ViewBoxWithCursor` 整体
  - `asammdf/gui/widgets/formated_axis.py` — `FormatedAxis` picture cache
  - `asammdf/blocks/cutils.pyi` — `positions(...)` 函数签名
- pyqtgraph 官方文档：`docs.pyqtgraph.org` — 重点看 `PlotItem`、`ViewBox`、`AxisItem`、`InfiniteLine`、`LinearRegionItem`、`TextItem`
- 上游 review 文档：`docs/analyzer/reviews/2026-05-28-plot-perf-vs-asammdf.md`
- TimeDomainCanvas survey（本 spec 编写时的输入）：`docs/superpowers/reports/2026-05-28-timedomain-surface-survey.md`（待 Phase 0 落盘留底）

---

## 附录 B — 决策日志

| 日期 | 决策 | 理由 |
| --- | --- | --- |
| 2026-05-28 | 选档 B（仅 TimeDomain），不选档 C | 投入产出比 + 单点风险隔离 |
| 2026-05-28 | 直接用 `asammdf.blocks.cutils.positions` 而非自造 C 扩展 | asammdf 已是依赖，零新工具链；许可证待复核 |
| 2026-05-28 | 引入 `AxisHandle` 抽象 | 避免 ChartOptionsDialog 改大；可复用于其他画布 |
| 2026-05-28 | 不上 feature flag，phase-by-phase 切换 | 项目偏好「不留 backwards-compat hack」 |
| 2026-05-28 | 旧 canvas 在 Phase 5 后保留 1 周才删 | 给生产观察期，但不无限拖延 |
