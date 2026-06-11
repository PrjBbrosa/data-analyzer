# 分析画布 pyqtgraph 迁移（P1–P3）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本仓库另有 CLAUDE.md squad 约定：** 执行时由 main Claude 按任务性质 dispatch
> `pyqt-ui-engineer`（画布/接线任务）；涉及 dB 数学校验的步骤引用
> `signal-processing-expert` 复核。`.py` 改动不得由 main Claude 直接编写。

**Goal:** 把 Order、FFT-vs-Time、FFT 三个分析的绘图画布从 matplotlib 换为 pyqtgraph，单视图行为完全对等（功能一项不删），并把 Order 计算移出 GUI 线程。

**Architecture:** 新建两个可复用画布 `PgHeatmapCanvas`（Order 与 FFT-vs-Time 共用，构造开关 `with_slice` 控制切片行）与 `PgLineCanvas`（FFT 双行谱线）。`MainWindow` 的 `_render_order_time` / `_render_fft_time` / `do_fft` 调用面保持同名同参，最小化接线 diff。计算层 `signal/` 与离线导出 `batch.py` 零改动。

**Tech Stack:** PyQt5、pyqtgraph ≥ 0.13.3（`ImageItem` / `ColorBarItem` / `GraphicsLayoutWidget`）、pytest + pytest-qt（`tests/ui/conftest.py` 的 `qapp` fixture，offscreen）。

**对应 spec：** `docs/superpowers/specs/2026-06-10-analysis-multiview-pyqtgraph-design.md` §5、§7、§8、§9、§10（P1–P3）、§11。

**关键既有事实（执行前读一遍）：**

- dB 转换语义以 `mf4_analyzer/ui/canvases.py:2221-2244` 为准（本 plan 已复刻成代码）。
- `SpectrogramResult` 字段：`times / frequencies / amplitude(freq_bins, frames) / params / channel_name / unit / metadata`（`signal/spectrogram.py:73-105`）。
- `_ChartCard` 按 canvas 类型分流 toolbar：`chart_stack.py:970` `isinstance(canvas, TimeDomainCanvasPG)` → `PgNavigationToolbar`，否则 matplotlib `NavigationToolbar`。
- card→canvas 注释契约：`canvas.set_remark_enabled(bool)`（`chart_stack.py:1314`）、`canvas.clear_remarks()`（`chart_stack.py:1330-1332`，hasattr 守卫）。
- 导出优先链 `_grab_pixmap_hidpi`（`chart_stack.py:30-60`）：实现 `grab_pixmap(scale=…)` 即自动接入。
- 时域画布**不开 OpenGL**（`pg_canvas/canvas.py:195` 普通 `GraphicsLayoutWidget`）；新画布同样不开——OpenGL 会破坏 `grab_pixmap` 导出（历史实测全白）。
- app 入口：`mf4_analyzer/app.py`；视觉验收脚本先例：`tools/_screenshot_inspector_after_spinbox_button_removal.py`。

---

## Task 1: `AnalysisComputeWorker` 泛化 worker

**Files:**
- Create: `mf4_analyzer/ui/analysis_worker.py`
- Test: `tests/ui/test_analysis_worker.py`

- [ ] **Step 1: 写失败测试**

```python
"""AnalysisComputeWorker: generic QObject worker contract tests."""
import pytest

from mf4_analyzer.ui.analysis_worker import AnalysisComputeWorker


def test_job_result_emitted_via_finished(qapp):
    got = []
    worker = AnalysisComputeWorker(lambda w: 42)
    worker.finished.connect(got.append)
    worker.run()
    assert got == [42]


def test_job_exception_emitted_via_failed(qapp):
    errs, oks = [], []

    def job(w):
        raise ValueError("boom")

    worker = AnalysisComputeWorker(job)
    worker.failed.connect(errs.append)
    worker.finished.connect(oks.append)
    worker.run()
    assert errs == ["boom"] and oks == []


def test_cancel_flag_visible_to_job(qapp):
    seen = []
    worker = AnalysisComputeWorker(lambda w: seen.append(w.cancelled()) or 1)
    worker.cancel()
    worker.run()
    assert seen == [True]


def test_progress_relay(qapp):
    ticks = []

    def job(w):
        w.progress.emit(1, 4)
        return None

    worker = AnalysisComputeWorker(job)
    worker.progress.connect(lambda c, t: ticks.append((c, t)))
    worker.run()
    assert ticks == [(1, 4)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_analysis_worker.py -v`
Expected: FAIL，`ModuleNotFoundError: mf4_analyzer.ui.analysis_worker`

- [ ] **Step 3: 实现**

```python
"""Generic analysis compute worker (QObject; move-to-QThread pattern).

Mirrors the proven ``FFTTimeWorker`` contract (main_window.py:29-78) but
takes an opaque ``job`` callable so Order / FFT-vs-Time / future analyses
share one worker class. The job receives the worker itself, so it can
emit ``progress`` and poll ``cancelled()`` as its cancel token.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class AnalysisComputeWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job):
        """``job(worker) -> result``; raise to land in ``failed``."""
        super().__init__()
        self._job = job
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            result = self._job(self)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_analysis_worker.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/analysis_worker.py tests/ui/test_analysis_worker.py
git commit -m "feat(analysis): add generic AnalysisComputeWorker"
```

---

## Task 2: `PgHeatmapCanvas` 骨架（ImageItem + ColorBar + 范围/levels 数学）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: 写失败测试**

```python
"""PgHeatmapCanvas: levels/extent math + API-parity tests (offscreen)."""
import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas


@pytest.fixture
def canvas(qapp):
    c = PgHeatmapCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _mat():
    # 4 rows (Y) x 5 cols (X), peak = 100 at [2, 3]
    m = np.ones((4, 5))
    m[2, 3] = 100.0
    return m


def test_linear_mode_levels_auto(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    lo, hi = canvas._img.getLevels()
    assert lo == pytest.approx(1.0) and hi == pytest.approx(100.0)


def test_db_mode_manual_levels_clip(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude_db', z_auto=False,
        z_floor=-30.0, z_ceiling=0.0,
    )
    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (-30.0, 0.0)
    # ref = peak → peak cell is 0 dB; ones are 20log10(1/100) = -40 → clipped to -30
    img = canvas._img.image
    assert img.max() == pytest.approx(0.0)
    assert img.min() == pytest.approx(-30.0)


def test_image_rect_matches_extents(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(2.0, 12.0), y_extent=(1.0, 9.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    r = canvas._img.boundingRect()
    mapped = canvas._img.mapRectToParent(r)
    assert mapped.left() == pytest.approx(2.0)
    assert mapped.right() == pytest.approx(12.0)
    assert mapped.top() == pytest.approx(1.0)
    assert mapped.bottom() == pytest.approx(9.0)


def test_has_result_lifecycle(canvas):
    assert not canvas.has_result()
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 1.0), y_extent=(0.0, 1.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas.has_result()


def test_manual_axis_ranges(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        x_auto=False, x_min=1.0, x_max=5.0,
        y_auto=False, y_min=2.0, y_max=6.0,
    )
    (x0, x1), (y0, y1) = canvas._plot.vb.viewRange()
    assert (x0, x1) == (pytest.approx(1.0), pytest.approx(5.0))
    assert (y0, y1) == (pytest.approx(2.0), pytest.approx(6.0))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v`
Expected: FAIL，`ModuleNotFoundError ... heatmap_canvas`

- [ ] **Step 3: 实现骨架**

```python
"""PgHeatmapCanvas: pyqtgraph heatmap canvas for the Order and
FFT-vs-Time sections.

Replaces ``PlotCanvas.plot_or_update_heatmap`` (canvases.py:2178) and —
with ``with_slice=True`` — ``SpectrogramCanvas`` (canvases.py:1602).
API names/kwargs mirror the matplotlib originals so MainWindow render
paths keep their call sites.

dB semantics are a line-for-line port of canvases.py:2221-2244.
NO OpenGL anywhere here: OpenGL breaks grab_pixmap exports (all-white,
verified on the time-domain canvas history).
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget


def _resolve_colormap(name: str) -> pg.ColorMap:
    """Map the inspector's matplotlib cmap names to pg ColorMaps.

    matplotlib stays a dependency (batch.py), so getFromMatplotlib gives
    exact color parity with the old canvases.
    """
    try:
        return pg.colormap.getFromMatplotlib(name)
    except Exception:
        return pg.colormap.get('viridis')


class _DensityAxis(pg.AxisItem):
    """AxisItem whose tick density scales with the global chart option.

    pg has no MaxNLocator equivalent; scaling the *size* argument that
    tickSpacing sees makes pg believe there is more/less room, which
    yields proportionally more/fewer major ticks.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._density = 1.0

    def set_density(self, density: float) -> None:
        self._density = max(0.2, min(5.0, float(density)))
        self.picture = None
        self.update()

    def tickSpacing(self, minVal, maxVal, size):
        return super().tickSpacing(minVal, maxVal, size * self._density)


class PgHeatmapCanvas(QWidget):
    cursor_info = pyqtSignal(str)
    # Emitted when the user drags the interactive colorbar (lo, hi).
    levels_changed = pyqtSignal(float, float)

    def __init__(self, parent=None, with_slice: bool = False):
        super().__init__(parent)
        self._with_slice = bool(with_slice)
        self._glw = pg.GraphicsLayoutWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._axis_bottom = _DensityAxis('bottom')
        self._axis_left = _DensityAxis('left')
        self._plot = self._glw.addPlot(
            row=0, col=0,
            axisItems={'bottom': self._axis_bottom, 'left': self._axis_left},
        )
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._img = pg.ImageItem()
        # row-major: matrix[row, col] -> row = Y (origin at rect bottom,
        # matching imshow origin='lower'), col = X.
        self._img.setOpts(axisOrder='row-major')
        self._plot.addItem(self._img)

        self._cbar: pg.ColorBarItem | None = None
        self._has_result = False
        self._matrix_disp: np.ndarray | None = None  # display-space matrix
        self._extents: tuple | None = None           # (x0, x1, y0, y1)
        self._remarks: list = []
        self._remark_enabled = False

    # ------------------------------------------------------------------
    # main API (signature mirrors canvases.PlotCanvas.plot_or_update_heatmap)
    # ------------------------------------------------------------------
    def plot_or_update_heatmap(
        self, matrix, x_extent, y_extent, *,
        x_label='', y_label='', title='', cmap='turbo', interp=None,
        cbar_label='Amplitude', amplitude_mode='amplitude',
        z_auto=False, z_floor=-30.0, z_ceiling=0.0,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        vmin=None, vmax=None,
    ):
        # ``interp`` accepted for call-site parity; pg ImageItem rendering
        # is already smooth-scaled, no per-call interpolation knob.
        m = np.asarray(matrix, dtype=float)

        # -- dB conversion: line-for-line port of canvases.py:2221-2244 --
        if amplitude_mode == 'amplitude_db':
            ref = float(np.nanmax(m))
            if ref <= 0:
                m_disp = np.full_like(m, fill_value=-100.0)
            else:
                with np.errstate(divide='ignore'):
                    m_disp = 20.0 * np.log10(np.clip(m, 1e-12, None) / ref)
            if not z_auto:
                m_disp = np.clip(m_disp, float(z_floor), float(z_ceiling))
            m = m_disp
            if vmin is None:
                vmin = float(z_floor) if not z_auto else float(np.nanmin(m))
            if vmax is None:
                vmax = float(z_ceiling) if not z_auto else 0.0
            if 'dB' not in cbar_label:
                cbar_label = f"{cbar_label} (dB)"
        else:
            if vmin is None:
                vmin = float(np.nanmin(m))
            if vmax is None:
                vmax = float(np.nanmax(m))

        x0, x1 = float(x_extent[0]), float(x_extent[1])
        y0, y1 = float(y_extent[0]), float(y_extent[1])

        cm = _resolve_colormap(cmap)
        self._img.setImage(m, autoLevels=False)
        self._img.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self._img.setColorMap(cm)
        self._img.setLevels((vmin, vmax))

        if self._cbar is None:
            self._cbar = pg.ColorBarItem(
                colorMap=cm, interactive=True, label=cbar_label,
            )
            self._cbar.setImageItem(self._img, insert_in=self._plot)
            self._cbar.sigLevelsChanged.connect(self._on_cbar_levels)
        else:
            self._cbar.setColorMap(cm)
            self._cbar.getAxis('right').setLabel(cbar_label)
        # setLevels emits sigLevelsChanged; block so programmatic updates
        # don't masquerade as user drags.
        self._cbar.blockSignals(True)
        self._cbar.setLevels((vmin, vmax))
        self._cbar.blockSignals(False)

        self._plot.setLabel('bottom', x_label)
        self._plot.setLabel('left', y_label)
        self._plot.setTitle(title)

        if x_auto:
            self._plot.setXRange(x0, x1, padding=0)
        elif x_max > x_min:
            self._plot.setXRange(float(x_min), float(x_max), padding=0)
        if y_auto:
            self._plot.setYRange(y0, y1, padding=0)
        elif y_max > y_min:
            self._plot.setYRange(float(y_min), float(y_max), padding=0)

        self._matrix_disp = m
        self._extents = (x0, x1, y0, y1)
        self._has_result = True

    def has_result(self) -> bool:
        return self._has_result

    def set_tick_density(self, x_density, y_density) -> None:
        self._axis_bottom.set_density(float(x_density))
        self._axis_left.set_density(float(y_density))

    # ------------------------------------------------------------------
    def _on_cbar_levels(self, bar) -> None:
        lo, hi = bar.levels()
        self.levels_changed.emit(float(lo), float(hi))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v`
Expected: 5 passed

注意：若 `test_image_rect_matches_extents` 中 `mapRectToParent` 的 top/bottom 与
预期相反，说明 row-major 的行方向与 `origin='lower'` 不一致——此时**改实现不改测试**：
在 `setRect` 前对矩阵 `m = m[::-1]` 翻转或设置 `self._plot.vb.invertY(False)`，
并以 Task 6 的视觉验收（与 matplotlib 旧图对比方向）为最终裁决。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(canvas): PgHeatmapCanvas skeleton with mpl-parity dB/levels math"
```

---

## Task 3: `PgHeatmapCanvas` 标注（remarks）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（类内追加）
- Test: `tests/ui/test_pg_heatmap_canvas.py`（追加）

- [ ] **Step 1: 写失败测试（追加到测试文件）**

```python
def test_remark_add_and_clear(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1
    # Label text carries (x, y, value)
    assert '5' in canvas._remarks[0]['label'].toPlainText()
    canvas.clear_remarks()
    assert canvas._remarks == []


def test_remark_disabled_noop(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(False)
    canvas.add_remark_at(5.0, 4.0)
    assert canvas._remarks == []


def test_value_at_maps_extent_to_cell(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # peak cell [row 2, col 3]: col 3 of 5 → x ∈ [6,8); row 2 of 4 → y ∈ [4,6)
    assert canvas._value_at(7.0, 5.0) == pytest.approx(100.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v -k remark` 与 `-k value_at`
Expected: FAIL，`AttributeError: set_remark_enabled`

- [ ] **Step 3: 实现（类内追加方法 + 在 `__init__` 末尾接鼠标事件）**

`__init__` 末尾追加：

```python
        # remarks: card contract is set_remark_enabled / clear_remarks
        # (chart_stack.py:1314, 1330-1332).
        self._plot.scene().sigMouseClicked.connect(self._on_scene_click)
```

类内追加：

```python
    # ------------------------------------------------------------------
    # remarks (annotation parity with the matplotlib canvases)
    # ------------------------------------------------------------------
    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)

    def clear_remarks(self) -> None:
        for r in self._remarks:
            self._plot.removeItem(r['label'])
            self._plot.removeItem(r['dot'])
        self._remarks = []

    def add_remark_at(self, x: float, y: float) -> None:
        if not self._remark_enabled or not self._has_result:
            return
        val = self._value_at(x, y)
        if val is None:
            return
        label = pg.TextItem(
            f"({x:.3g}, {y:.3g}, {val:.3g})", color='#111827',
            fill=pg.mkBrush(255, 255, 255, 200), anchor=(0, 1),
        )
        label.setPos(x, y)
        dot = pg.ScatterPlotItem(
            [x], [y], size=7, brush=pg.mkBrush('#e03131'),
            pen=pg.mkPen('w', width=1),
        )
        self._plot.addItem(label)
        self._plot.addItem(dot)
        self._remarks.append({'label': label, 'dot': dot})

    def remove_remark_near(self, x: float, y: float) -> None:
        if not self._remarks:
            return
        (x0, x1, y0, y1) = self._extents
        sx = max(x1 - x0, 1e-12)
        sy = max(y1 - y0, 1e-12)

        def dist(r):
            p = r['dot'].getData()
            return ((p[0][0] - x) / sx) ** 2 + ((p[1][0] - y) / sy) ** 2

        nearest = min(self._remarks, key=dist)
        self._plot.removeItem(nearest['label'])
        self._plot.removeItem(nearest['dot'])
        self._remarks.remove(nearest)

    def _value_at(self, x: float, y: float):
        if self._matrix_disp is None or self._extents is None:
            return None
        x0, x1, y0, y1 = self._extents
        rows, cols = self._matrix_disp.shape
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return None
        col = min(int((x - x0) / max(x1 - x0, 1e-12) * cols), cols - 1)
        row = min(int((y - y0) / max(y1 - y0, 1e-12) * rows), rows - 1)
        return float(self._matrix_disp[row, col])

    def _on_scene_click(self, ev) -> None:
        if not self._plot.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = self._plot.vb.mapSceneToView(ev.scenePos())
        if ev.button() == Qt.LeftButton:
            self.add_remark_at(p.x(), p.y())
        elif ev.button() == Qt.RightButton and self._remark_enabled:
            self.remove_remark_near(p.x(), p.y())
            ev.accept()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(canvas): heatmap remarks parity (add/remove/clear, card contract)"
```

---

## Task 4: `PgHeatmapCanvas` 导出（grab_pixmap）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（类内追加）
- Test: `tests/ui/test_pg_heatmap_canvas.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_grab_pixmap_scaled_nonnull(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None and not pix.isNull()
    assert pix.width() >= canvas.width() * 2 - 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v -k grab`
Expected: FAIL，`AttributeError: grab_pixmap`

- [ ] **Step 3: 实现（类内追加）**

```python
    # ------------------------------------------------------------------
    # export — plugs into chart_stack._grab_pixmap_hidpi's first branch
    # ------------------------------------------------------------------
    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
        w = max(1, int(self._glw.width() * scale))
        h = max(1, int(self._glw.height() * scale))
        target = QPixmap(w, h)
        target.fill(Qt.white)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(scale, scale)
        self._glw.render(painter)
        painter.end()
        return target
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(canvas): heatmap grab_pixmap(scale) HiDPI export"
```

---

## Task 5: Order 接线换芯 + worker 化

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py:1652`（canvas_order 实例化）、`:970`（toolbar 分流）
- Modify: `mf4_analyzer/ui/main_window.py:2379-2428`（do_order_time）、`closeEvent`（约 2493-2520）
- Test: 现有套件回归

- [ ] **Step 1: ChartStack 换 canvas 类型**

`chart_stack.py:1652`：

```python
# 旧
        self.canvas_order = PlotCanvas(self)
# 新
        self.canvas_order = PgHeatmapCanvas(self)
```

文件顶部 import 区追加：

```python
from .pg_canvas.heatmap_canvas import PgHeatmapCanvas
```

`chart_stack.py:970` toolbar 分流改为按"pg 系画布"判断：

```python
# 旧
        if isinstance(canvas, TimeDomainCanvasPG):
# 新
        if isinstance(canvas, (TimeDomainCanvasPG, PgHeatmapCanvas)):
```

注意 `PgNavigationToolbar(canvas, self)` 对非时域画布的可选接口
（`register_replot_callback` / `register_mouse_mode_controller`）已有
`callable()` 守卫（`chart_stack.py:975-989`），新画布不提供它们也安全。
若 `PgNavigationToolbar.__init__` 还要求其他 canvas 属性，跑
`python -m pytest tests/ui -k "card or toolbar" -x` 按报错补齐
（预期需要的只有 `_glw`，Task 2 已提供）。

- [ ] **Step 2: do_order_time 移入 worker**

`main_window.py` do_order_time 中 `try: ... result = COTOrderAnalyzer.compute(sig, rpm, t_arr, p)` 同步段（2409-2427）替换为：

```python
        if getattr(self, '_order_thread', None) is not None and self._order_thread.isRunning():
            self.statusBar.showMessage("正在计算…")
            return
        try:
            p = COTParams(
                samples_per_rev=int(order_params.get('samples_per_rev', 256)),
                nfft=int(op['nfft']),
                window=op.get('window', 'hanning'),
                max_order=float(op['max_order']),
                order_res=float(op['order_res']),
                time_res=float(op['time_res']),
                fs=fs,
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            return
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")

        from .analysis_worker import AnalysisComputeWorker

        def job(worker, _sig=sig, _rpm=rpm, _t=t_arr, _p=p):
            return COTOrderAnalyzer.compute(_sig, _rpm, _t, _p)

        worker = AnalysisComputeWorker(job)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_order_finished)
        worker.failed.connect(self._on_order_failed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_order_thread_done)
        self._order_thread = thread
        self._order_worker = worker
        thread.start()
        return
```

新增三个回调（紧随 `_render_order_time` 之后）：

```python
    def _on_order_finished(self, result):
        self.inspector.order_ctx.set_progress("")
        self._render_order_time(result)

    def _on_order_failed(self, message):
        self.inspector.order_ctx.set_progress("")
        QMessageBox.critical(self, "错误", str(message))

    def _on_order_thread_done(self):
        self._order_thread = None
        self._order_worker = None
```

`__init__` 中 `self._fft_time_thread = None` 处（main_window.py:107）追加：

```python
        self._order_thread = None
        self._order_worker = None
```

`closeEvent`（main_window.py:2493 起）在 fft_time 清理后追加同款 Order 清理：

```python
        order_thread = getattr(self, '_order_thread', None)
        order_worker = getattr(self, '_order_worker', None)
        if order_thread is not None and order_thread.isRunning():
            if order_worker is not None:
                order_worker.cancel()
            order_thread.quit()
            order_thread.wait(2000)
```

`_render_order_time` 本体**不改**——`plot_or_update_heatmap` / `set_tick_density`
调用面已由新画布同名提供。

- [ ] **Step 3: 跑回归**

Run: `python -m pytest tests/ui -x -q`
Expected: 全绿（若有针对 `canvas_order` 是 matplotlib 类型的断言失败，逐个改为
断言新接口 `has_result/plot_or_update_heatmap`，不放宽行为语义）

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/main_window.py
git commit -m "feat(order): swap heatmap canvas to pyqtgraph; move COT compute off GUI thread"
```

---

## Task 6: P1 视觉验收（Order）

**Files:**
- Create: `tools/_screenshot_order_pg_migration.py`（仿 `tools/_screenshot_inspector_after_spinbox_button_removal.py` 的启动方式）

- [ ] **Step 1: 截图脚本**

脚本职责：启动 app（入口 `mf4_analyzer/app.py`）、加载 `tests/fixtures` 或
`testdoc/` 样例数据、切 Order、触发计算、等 worker 完成、
`canvas_order.grab_pixmap(scale=2)` 存 `docs/superpowers/verify/p1-order-pg.png`。

- [ ] **Step 2: 真实渲染逐项核对（人工，不可省）**

对照旧版（git stash 或上一 commit 运行一次存参照图）核对：
热力图方向（时间→右、阶次→上）；colorbar 标签含 `(dB)`；z 手动范围生效；
x/y 手动范围生效；标注添加/右键删除/清除；复制为图片非全白且含 colorbar；
计算期间 UI 不冻结（拖动窗口验证）。
**红线：仅"属性已设置"+单测通过不算通过；必须以渲染结果为准。**

- [ ] **Step 3: 移除 matplotlib 热力图死代码**

确认无引用后删 `canvases.py` 的 `plot_or_update_heatmap` 路径：

```bash
grep -rn "plot_or_update_heatmap" mf4_analyzer --include="*.py"
# 预期仅剩 canvases.py 定义处 → 删除该方法及 _heatmap_ax/_heatmap_im/_heatmap_cbar 簇
python -m pytest tests/ -x -q
```

注意 `PlotCanvas` 类本身保留（FFT 在 P3 前仍用它的线图+标注路径）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(order): visual parity verified; drop matplotlib heatmap path"
```

---

## Task 7: 切片行 + 点击选帧（FFT-vs-Time 形态）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult


def _spec_result():
    freqs = np.linspace(0, 500, 64)
    times = np.linspace(0, 2.0, 10)
    amp = np.random.RandomState(7).rand(64, 10).astype(np.float32) + 0.01
    return SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=128),
        channel_name='vib', unit='g', metadata={'frames': 10},
    )


def test_slice_updates_on_select(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0, y_auto=True, y_min=0.0, y_max=0.0,
    )
    c.select_time_index(3)
    xs, ys = c._slice_curve.getData()
    assert len(xs) == 64
    # slice shows the SAME display-space (dB) values as column 3
    expected = c._matrix_disp[:, 3]
    np.testing.assert_allclose(ys, expected, rtol=1e-6)
    c.deleteLater()


def test_plot_result_without_slice_flag_has_no_slice_row(qapp):
    c = PgHeatmapCanvas(with_slice=False)
    assert not hasattr(c, '_slice_curve') or c._slice_curve is None
    c.deleteLater()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v -k slice`
Expected: FAIL，`AttributeError: plot_result`

- [ ] **Step 3: 实现**

`__init__` 中 `self._remark_enabled = False` 之后追加：

```python
        self._slice_curve = None
        self._slice_plot = None
        self._slice_marker = None
        self._result = None  # SpectrogramResult / COTResult-like payload
        self._db_cache = None  # (cache_key, ndarray) — keyed (id(result), db_ref)
        if self._with_slice:
            self._slice_plot = self._glw.addPlot(row=1, col=0)
            self._slice_plot.setMaximumHeight(140)
            self._slice_plot.showGrid(x=True, y=True, alpha=0.25)
            self._slice_plot.setLabel('bottom', 'Frequency (Hz)')
            self._slice_curve = self._slice_plot.plot(pen=pg.mkPen('#2563eb', width=1.2))
            self._slice_plot.setXLink(None)  # frequency axis independent of time axis
            self._slice_marker = pg.InfiniteLine(
                angle=90, movable=False, pen=pg.mkPen('#e03131', width=1))
            self._plot.addItem(self._slice_marker)
            self._slice_marker.setVisible(False)
```

类内追加（plot_result 签名对齐 `_render_fft_time` 调用面，main_window.py:2767-2781）：

```python
    # ------------------------------------------------------------------
    # SpectrogramCanvas-parity API (FFT vs Time)
    # ------------------------------------------------------------------
    def plot_result(
        self, result, *, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
    ):
        self._result = result
        unit = f" ({result.unit})" if result.unit else ""
        # dB via the analyzer helper + memoized cache, parity with the old
        # SpectrogramCanvas db cache (keyed (id(result), db_reference)).
        db_ref = float(result.params.db_reference)
        if amplitude_mode == 'amplitude_db':
            key = (id(result), db_ref)
            if self._db_cache is None or self._db_cache[0] != key:
                from ...signal.spectrogram import SpectrogramAnalyzer
                self._db_cache = (key, SpectrogramAnalyzer.amplitude_to_db(
                    result.amplitude, db_ref))
            m = self._db_cache[1]
            if not z_auto:
                m = np.clip(m, float(z_floor), float(z_ceiling))
            vmin = float(z_floor) if not z_auto else float(np.nanmin(m))
            vmax = float(z_ceiling) if not z_auto else float(np.nanmax(m))
            cbar = f"Amplitude{unit} (dB re {db_ref:g})"
        else:
            m = result.amplitude
            vmin, vmax = float(np.nanmin(m)), float(np.nanmax(m))
            cbar = f"Amplitude{unit}"

        y_lo = float(result.frequencies[0])
        y_hi = float(result.frequencies[-1])
        if freq_range is not None:
            y_auto, y_min, y_max = False, float(freq_range[0]), float(freq_range[1])

        # amplitude is (freq_bins, frames) → rows=freq(Y), cols=time(X):
        # already row-major-correct for our ImageItem orientation.
        self.plot_or_update_heatmap(
            matrix=m,
            x_extent=(float(result.times[0]), float(result.times[-1])),
            y_extent=(y_lo, y_hi),
            x_label='Time (s)', y_label='Frequency (Hz)',
            title=f'FFT vs Time - {result.channel_name}',
            cmap=cmap, cbar_label=cbar,
            amplitude_mode='amplitude',  # conversion already done above
            z_auto=True, vmin=vmin, vmax=vmax,
            x_auto=x_auto, x_min=x_min, x_max=x_max,
            y_auto=y_auto, y_min=y_min, y_max=y_max,
        )
        # display-space matrix for slice/value readouts
        self._matrix_disp = m
        if self._slice_curve is not None and len(result.times):
            self.select_time_index(0)

    def select_time_index(self, idx: int) -> None:
        if self._result is None or self._slice_curve is None:
            return
        idx = int(np.clip(idx, 0, len(self._result.times) - 1))
        self._slice_curve.setData(
            self._result.frequencies, self._matrix_disp[:, idx])
        t = float(self._result.times[idx])
        self._slice_plot.setTitle(f"t = {t:.3f} s")
        self._slice_marker.setPos(t)
        self._slice_marker.setVisible(True)

    def _time_index_for(self, x: float) -> int:
        return int(np.argmin(np.abs(np.asarray(self._result.times) - x)))
```

`_on_scene_click` 中 LeftButton 分支改为「标注开启→标注；否则有切片→选帧」：

```python
        if ev.button() == Qt.LeftButton:
            if self._remark_enabled:
                self.add_remark_at(p.x(), p.y())
            elif self._slice_curve is not None and self._result is not None:
                self.select_time_index(self._time_index_for(p.x()))
```

并在 `__init__` 接 hover 读数（对等 `cursor_info`）：

```python
        self._plot.scene().sigMouseMoved.connect(self._on_scene_hover)
```

```python
    def _on_scene_hover(self, pos) -> None:
        if not self._has_result or not self._plot.sceneBoundingRect().contains(pos):
            self.cursor_info.emit("")
            return
        p = self._plot.vb.mapSceneToView(pos)
        val = self._value_at(p.x(), p.y())
        if val is None:
            self.cursor_info.emit("")
        else:
            self.cursor_info.emit(f"t={p.x():.3f}s  y={p.y():.2f}  值={val:.3f}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v`
Expected: 全部通过（含 Task 2-4 的既有用例——回归确认 slice 行不破坏无切片模式）

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(canvas): slice row + click-to-select-frame + hover readout"
```

---

## Task 8: 导出 full/main 两模式

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_grab_full_vs_main(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.plot_result(
        _spec_result(), amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0, y_auto=True, y_min=0.0, y_max=0.0,
    )
    full = c.grab_full_view()
    main = c.grab_main_chart()
    assert not full.isNull() and not main.isNull()
    # main excludes the slice row → strictly shorter
    assert main.height() < full.height()
    c.deleteLater()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v -k "full_vs_main"`
Expected: FAIL，`AttributeError: grab_full_view`

- [ ] **Step 3: 实现（类内追加）**

```python
    def grab_full_view(self) -> QPixmap:
        return self.grab_pixmap(scale=2.0)

    def grab_main_chart(self) -> QPixmap:
        """Heatmap + colorbar only (no slice row).

        Renders the scene region covering row 0 of the layout. Falls back
        to the full grab when geometry is degenerate (headless parity with
        SpectrogramCanvas.grab_main_chart's documented fallback).
        """
        scale = 2.0
        scene = self._glw.scene()
        rect = self._plot.sceneBoundingRect()
        if self._cbar is not None:
            rect = rect.united(self._cbar.sceneBoundingRect())
        if rect.width() < 2 or rect.height() < 2:
            return self.grab_full_view()
        target = QPixmap(int(rect.width() * scale), int(rect.height() * scale))
        target.fill(Qt.white)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        scene.render(
            painter,
            QRectF(0, 0, rect.width() * scale, rect.height() * scale),
            rect,
        )
        painter.end()
        return target
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(canvas): grab_full_view / grab_main_chart export parity"
```

---

## Task 9: FFT-vs-Time 接线换芯 + 删 SpectrogramCanvas

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py:1651`、`:1694-1696`（SpectrogramChartCard）
- Modify: `mf4_analyzer/ui/main_window.py`（FFTTimeWorker → AnalysisComputeWorker；cursor_info 接线处，grep `cursor_info.connect`）
- Delete: `mf4_analyzer/ui/canvases.py` 的 `SpectrogramCanvas`（1602-2050）
- Test: 现有套件回归

- [ ] **Step 1: ChartStack 换 canvas**

```python
# chart_stack.py:1651 旧
        self.canvas_fft_time = SpectrogramCanvas(self)
# 新
        self.canvas_fft_time = PgHeatmapCanvas(self, with_slice=True)
```

`isinstance` 分流（Task 5 已含 PgHeatmapCanvas）覆盖本卡。
`SpectrogramChartCard`（chart_stack.py:1694）若仅为 mpl 特有微调而存在，先跑
`grep -n "class SpectrogramChartCard" -A 30 mf4_analyzer/ui/chart_stack.py`
评估：其 mpl 专有逻辑随画布失效的，改用基类 `_ChartCard(self.canvas_fft_time,
annotations=True, chart_mode='fft_time')`；与画布无关的（如额外按钮）保留并适配。

- [ ] **Step 2: worker 收敛**

`do_fft_time`（main_window.py:2726）`FFTTimeWorker(...)` 替换为：

```python
        from .analysis_worker import AnalysisComputeWorker

        def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
            from ..signal import SpectrogramAnalyzer
            return SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        worker = AnalysisComputeWorker(job)
```

随后删除 `FFTTimeWorker` 类（main_window.py:29-78）；`closeEvent` 中对
`_fft_time_worker.cancel()` 的调用不变（接口同名）。

- [ ] **Step 3: 删除 SpectrogramCanvas + 回归**

```bash
grep -rn "SpectrogramCanvas" mf4_analyzer tests --include="*.py"
# 逐个改引用到 PgHeatmapCanvas 后删除类定义（canvases.py:1602-2050）
python -m pytest tests/ -x -q
```

涉及 `cursor_info` / `time_index_selected` 的旧接线（grep
`canvas_fft_time` in main_window.py）逐条核对：`cursor_info` 信号新画布同名，
`_on_fft_time_cursor_info`（main_window.py:2783）无需改。

- [ ] **Step 4: P2 视觉验收（同 Task 6 模式）**

截图脚本 `tools/_screenshot_ffttime_pg_migration.py` 存
`docs/superpowers/verify/p2-ffttime-pg.png`。人工核对：方向、colorbar、
dB↔Linear 切换、点击热力图切片更新且红线 marker 跟随、hover 读数、
presets 三件套应用后渲染、复制 full/main 两模式像素内容（main 无切片行）、
计算中 UI 不冻、缓存命中秒渲染。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(ffttime): migrate spectrogram canvas to pyqtgraph; retire FFTTimeWorker + SpectrogramCanvas"
```

---

## Task 10: `PgLineCanvas`（FFT 双行谱线）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

```python
"""PgLineCanvas: dual-row spectrum canvas tests (offscreen)."""
import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


@pytest.fixture
def canvas(qapp):
    c = PgLineCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _entry(label='f1 · vib', color='#2563eb'):
    freq = np.linspace(0, 500, 256)
    amp = np.exp(-((freq - 120) / 15.0) ** 2)
    return {'label': label, 'color': color, 'freq': freq,
            'amp': amp, 'psd': amp ** 2}


def test_plot_spectra_single_entry(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0),
        amp_label='Amplitude', psd_label='PSD (dB)',
        title='FFT - vib', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1
    assert len(canvas._psd_curves) == 1
    xs, ys = canvas._amp_curves[0].getData()
    assert len(xs) == 256
    (x0, x1), _ = canvas._plot_amp.vb.viewRange()
    assert (x0, x1) == (pytest.approx(0.0), pytest.approx(500.0))


def test_plot_spectra_overlay_n(canvas):
    canvas.plot_spectra(
        [_entry('a', '#2563eb'), _entry('b', '#dc2626'), _entry('c', '#16a34a')],
        xlim=(0.0, 500.0), amp_label='Amplitude', psd_label='PSD',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 3
    # replot replaces, never accumulates
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='A', psd_label='P',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1


def test_cursor_readout_values(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        psd_label='PSD', title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    rows = canvas.readout_at(120.0)
    assert len(rows) == 1
    label, freq, amp_val = rows[0][:3]
    assert label == 'f1 · vib'
    assert amp_val == pytest.approx(1.0, abs=0.01)


def test_remark_snaps_to_curve(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        psd_label='PSD', title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at('amp', 119.0, 0.5)   # off-curve y → snaps to nearest sample
    assert len(canvas._remarks) == 1
    assert '1' in canvas._remarks[0]['label'].toPlainText()  # snapped peak ≈1
    canvas.clear_remarks()
    assert canvas._remarks == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -v`
Expected: FAIL，`ModuleNotFoundError ... line_canvas`

- [ ] **Step 3: 实现**

```python
"""PgLineCanvas: dual-row (amplitude + PSD) spectrum canvas.

Replaces the inline matplotlib plotting in MainWindow.do_fft
(main_window.py:2293-2354). One canvas, N overlay curves per row;
legend names follow "file · channel". Cursor + snap-remark parity with
PlotCanvas.store_line_data/_add_remark.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from .heatmap_canvas import _DensityAxis


class PgLineCanvas(QWidget):
    cursor_info = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glw = pg.GraphicsLayoutWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        def make_plot(row):
            p = self._glw.addPlot(
                row=row, col=0,
                axisItems={'bottom': _DensityAxis('bottom'),
                           'left': _DensityAxis('left')},
            )
            p.showGrid(x=True, y=True, alpha=0.25)
            p.addLegend(offset=(8, 8))
            return p

        self._plot_amp = make_plot(0)
        self._plot_psd = make_plot(1)
        self._plot_psd.setXLink(self._plot_amp)

        self._amp_curves: list = []
        self._psd_curves: list = []
        self._entries: list = []      # plotted data for readout/snap
        self._remarks: list = []
        self._remark_enabled = False

        self._cursor_amp = pg.InfiniteLine(angle=90, movable=False,
                                           pen=pg.mkPen('#94a3b8', width=1))
        self._cursor_psd = pg.InfiniteLine(angle=90, movable=False,
                                           pen=pg.mkPen('#94a3b8', width=1))
        for line in (self._cursor_amp, self._cursor_psd):
            line.setVisible(False)
        self._plot_amp.addItem(self._cursor_amp)
        self._plot_psd.addItem(self._cursor_psd)

        self._glw.scene().sigMouseMoved.connect(self._on_hover)
        self._glw.scene().sigMouseClicked.connect(self._on_click)

    # ------------------------------------------------------------------
    def plot_spectra(self, entries, *, xlim, amp_label, psd_label, title,
                     y_auto=True, y_min=0.0, y_max=0.0):
        """entries: [{label, color, freq, amp, psd}] — display-space values."""
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_psd, self._psd_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        self._entries = list(entries)

        for e in self._entries:
            pen = pg.mkPen(e['color'], width=1.2)
            self._amp_curves.append(
                self._plot_amp.plot(e['freq'], e['amp'], pen=pen, name=e['label']))
            self._psd_curves.append(
                self._plot_psd.plot(e['freq'], e['psd'], pen=pen, name=e['label']))

        self._plot_amp.setTitle(title)
        self._plot_amp.setLabel('left', amp_label)
        self._plot_psd.setLabel('left', psd_label)
        self._plot_psd.setLabel('bottom', 'Frequency (Hz)')
        for p in (self._plot_amp, self._plot_psd):
            p.setXRange(float(xlim[0]), float(xlim[1]), padding=0)
            if not y_auto and y_max > y_min:
                p.setYRange(float(y_min), float(y_max), padding=0)
            else:
                p.enableAutoRange(axis='y')

    def has_result(self) -> bool:
        return bool(self._entries)

    def set_tick_density(self, x_density, y_density) -> None:
        for p in (self._plot_amp, self._plot_psd):
            p.getAxis('bottom').set_density(float(x_density))
            p.getAxis('left').set_density(float(y_density))

    # ------------------------------------------------------------------
    def readout_at(self, freq: float):
        """[(label, snapped_freq, amp_value, psd_value)] per curve at ``freq``."""
        rows = []
        for e in self._entries:
            idx = int(np.argmin(np.abs(np.asarray(e['freq']) - freq)))
            rows.append((e['label'], float(e['freq'][idx]),
                         float(e['amp'][idx]), float(e['psd'][idx])))
        return rows

    def _on_hover(self, pos) -> None:
        target = None
        for p in (self._plot_amp, self._plot_psd):
            if p.sceneBoundingRect().contains(pos):
                target = p
                break
        if target is None or not self._entries:
            for line in (self._cursor_amp, self._cursor_psd):
                line.setVisible(False)
            self.cursor_info.emit("")
            return
        x = target.vb.mapSceneToView(pos).x()
        for line in (self._cursor_amp, self._cursor_psd):
            line.setPos(x)
            line.setVisible(True)
        rows = self.readout_at(x)
        text = "  |  ".join(
            f"{label}: {amp:.4g} / {psd:.4g}" for label, _f, amp, psd in rows)
        self.cursor_info.emit(f"f={rows[0][1]:.2f} Hz  {text}")

    # ------------------------------------------------------------------
    # remarks: snap to nearest sample on nearest curve (PlotCanvas parity)
    # ------------------------------------------------------------------
    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)

    def clear_remarks(self) -> None:
        for r in self._remarks:
            r['plot'].removeItem(r['label'])
            r['plot'].removeItem(r['dot'])
        self._remarks = []

    def add_remark_at(self, which: str, x: float, y: float) -> None:
        if not self._remark_enabled or not self._entries:
            return
        plot = self._plot_amp if which == 'amp' else self._plot_psd
        key = 'amp' if which == 'amp' else 'psd'
        best = None  # (dy, snapped_x, snapped_y)
        for e in self._entries:
            idx = int(np.argmin(np.abs(np.asarray(e['freq']) - x)))
            sx, sy = float(e['freq'][idx]), float(e[key][idx])
            dy = abs(sy - y)
            if best is None or dy < best[0]:
                best = (dy, sx, sy)
        _dy, sx, sy = best
        label = pg.TextItem(f"({sx:.2f}, {sy:.4g})", color='#111827',
                            fill=pg.mkBrush(255, 255, 255, 200), anchor=(0, 1))
        label.setPos(sx, sy)
        dot = pg.ScatterPlotItem([sx], [sy], size=7,
                                 brush=pg.mkBrush('#e03131'),
                                 pen=pg.mkPen('w', width=1))
        plot.addItem(label)
        plot.addItem(dot)
        self._remarks.append({'label': label, 'dot': dot, 'plot': plot})

    def remove_remark_near(self, which: str, x: float) -> None:
        plot = self._plot_amp if which == 'amp' else self._plot_psd
        cands = [r for r in self._remarks if r['plot'] is plot]
        if not cands:
            return
        nearest = min(cands, key=lambda r: abs(r['dot'].getData()[0][0] - x))
        plot.removeItem(nearest['label'])
        plot.removeItem(nearest['dot'])
        self._remarks.remove(nearest)

    def _on_click(self, ev) -> None:
        for which, p in (('amp', self._plot_amp), ('psd', self._plot_psd)):
            if p.sceneBoundingRect().contains(ev.scenePos()):
                v = p.vb.mapSceneToView(ev.scenePos())
                if ev.button() == Qt.LeftButton:
                    self.add_remark_at(which, v.x(), v.y())
                elif ev.button() == Qt.RightButton and self._remark_enabled:
                    self.remove_remark_near(which, v.x())
                    ev.accept()
                return

    # ------------------------------------------------------------------
    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
        w = max(1, int(self._glw.width() * scale))
        h = max(1, int(self._glw.height() * scale))
        target = QPixmap(w, h)
        target.fill(Qt.white)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(scale, scale)
        self._glw.render(painter)
        painter.end()
        return target
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(canvas): PgLineCanvas dual-row spectrum with overlay/cursor/remarks"
```

---

## Task 11: FFT 接线换芯

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py:1650`、`:970`（isinstance 加 PgLineCanvas）
- Modify: `mf4_analyzer/ui/main_window.py:2293-2354`（do_fft 绘图段）
- Test: 回归 + 视觉验收

- [ ] **Step 1: ChartStack 换 canvas**

```python
# chart_stack.py:1650 旧
        self.canvas_fft = PlotCanvas(self)
# 新
        self.canvas_fft = PgLineCanvas(self)
```

import 区追加 `from .pg_canvas.line_canvas import PgLineCanvas`；
`:970` isinstance 元组加 `PgLineCanvas`。

- [ ] **Step 2: do_fft 绘图段替换**

main_window.py:2293-2354（`self.canvas_fft.clear()` 起到 `self.canvas_fft.draw()` 止）
整段替换为（计算与 xlim/dB 逻辑 2295-2320 原样保留在前）：

```python
            sig_label = self.inspector.fft_ctx.combo_sig.currentText()
            entry = {
                'label': sig_label,
                'color': '#2563eb',
                'freq': freq,
                'amp': amp_disp,
                'psd': psd_disp,
            }
            self.canvas_fft.plot_spectra(
                [entry],
                xlim=xlim,
                amp_label='Amplitude (dB)' if amp_y == 'dB' else 'Amplitude',
                psd_label='PSD (dB)' if psd_y == 'dB' else 'PSD',
                title=f'FFT - {sig_label} (窗:{win}, NFFT:{nfft or "auto"})',
                y_auto=y_auto, y_min=y_min, y_max=y_max,
            )
            xt, yt = self.inspector.top.tick_density()
            self.canvas_fft.set_tick_density(xt, yt)
```

（`store_line_data` / `tight_layout` / `draw` 调用随段删除——吸附数据
已由 canvas 的 `_entries` 承担。）

- [ ] **Step 3: 回归 + 视觉验收**

```bash
grep -rn "canvas_fft\b" mf4_analyzer --include="*.py" | grep -v fft_time
# 逐个核对残留调用面（clear/draw/store_line_data 等 mpl 专有调用须已全部移除）
python -m pytest tests/ -x -q
```

视觉验收（`tools/_screenshot_fft_pg_migration.py` →
`docs/superpowers/verify/p3-fft-pg.png`）：双行布局、dB 切换、x/y 手动范围、
游标读数、标注吸附、复制图片、平均/峰值保持模式结果与旧版数值一致
（峰值频率与幅值打印对比）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(fft): migrate FFT spectrum rendering to PgLineCanvas"
```

---

## Self-review 记录

- spec §5/§7/§8 覆盖：Task 1-4（heatmap 核心）、5（Order+worker）、7-9（切片/导出/FFT-time）、10-11（FFT）。§9 对等清单中 presets / Contextual 参数面板不在本 plan 改动面（零接触即对等）。
- 类型一致性：`AnalysisComputeWorker(job)`、`PgHeatmapCanvas.plot_or_update_heatmap(同 mpl 签名)`、`plot_result(同 SpectrogramCanvas 签名)`、`PgLineCanvas.plot_spectra(entries,…)` 在各任务间引用一致。
- 已知不确定点（执行时按指令收敛，不是 TBD）：row-major 方向（Task 2 Step 4 给了裁决程序）、`SpectrogramChartCard` 去留（Task 9 Step 1 给了评估程序）、`PgNavigationToolbar` 对 canvas 的最小接口（Task 5 Step 1 给了验证命令）。
