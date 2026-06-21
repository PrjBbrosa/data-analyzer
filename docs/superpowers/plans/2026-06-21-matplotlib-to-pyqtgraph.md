# matplotlib → pyqtgraph 全面替换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 matplotlib 运行时与依赖，全部出图走 pyqtgraph；实时 UI 逐像素不变，仅 batch 导出 PNG 观感变化。

**Architecture:** 先消除实时 UI 唯一的 matplotlib 依赖（热图色图），再换取色器色串工具、重写 batch 离屏出图、清死分支、删依赖。每步独立可测、低风险在前。

**Tech Stack:** pyqtgraph（已在用）、PyQt5、pytest-qt。归 pyqt-ui-engineer（UI 改动需真机渲染验证）。

## Global Constraints

- **实时 UI 逐像素不变**：色图仍 turbo、取色器行为不变、图表工具栏不变。任何实时 UI 变化都是缺陷。
- 唯一接受的可见差异：batch 导出 PNG 的渲染风格（功能/数据/坐标/colorbar/dB/色阶范围全保留）。
- 色图保真：pyqtgraph 原生 turbo/viridis 的 LUT 必须与 matplotlib 版一致，测试机械守卫。
- 绝不为出图重新引入 matplotlib（含间接 `getFromMatplotlib`）。
- UI 改动按 CLAUDE.md 验真机渲染（截图/objc），不得凭"单测过"判定。
- `signal/` 仍禁 import PyQt5/matplotlib.pyplot。

---

### Task 1: 热图色图脱离 matplotlib（最高保真优先级）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:111-120`（`_resolve_colormap`）
- Create: `tests/ui/test_colormap_parity.py`
- Create: `tests/data/colormap_golden.npz`

**Interfaces:**
- Consumes: `pg.colormap.get(name)`（pyqtgraph 原生）。
- Produces: `_resolve_colormap(name) -> pg.ColorMap`，不再调用 `getFromMatplotlib`。

- [ ] **Step 1: 写保真测试（matplotlib 仍在，证明原生==mpl）**

```python
# tests/ui/test_colormap_parity.py
import numpy as np
import pyqtgraph as pg

_NAMES = ['turbo', 'viridis']

def _lut(cm):
    return cm.getLookupTable(0.0, 1.0, 256, alpha=True)

def test_native_matches_matplotlib():
    import importlib.util
    if importlib.util.find_spec("matplotlib") is None:
        # mpl 已卸载：退化为对黄金值的守卫（见 Step 4）
        golden = np.load("tests/data/colormap_golden.npz")
        for name in _NAMES:
            np.testing.assert_array_equal(_lut(pg.colormap.get(name)), golden[name])
        return
    for name in _NAMES:
        native = _lut(pg.colormap.get(name))
        mpl = _lut(pg.colormap.getFromMatplotlib(name))
        np.testing.assert_array_equal(native, mpl)
```

- [ ] **Step 2: 跑测试确认通过（证明 pg 原生 turbo/viridis == matplotlib 版）**

Run: `pytest tests/ui/test_colormap_parity.py -q`
Expected: PASS。
> 若 FAIL（LUT 不一致）：改用内置 LUT 兜底——把 mpl 的 256×4 LUT 落盘，
> `_resolve_colormap` 用 `pg.ColorMap(pos=np.linspace(0,1,256), color=lut)` 构造。
> 本计划默认 Step 2 通过（已离线验证 `pg.colormap.get('turbo')` 存在）。

- [ ] **Step 3: 重写 `_resolve_colormap` 用原生色图**

`heatmap_canvas.py:111-120` 改为：
```python
def _resolve_colormap(name: str) -> pg.ColorMap:
    """Resolve an inspector cmap name to a pyqtgraph ColorMap, matplotlib-free.
    pyqtgraph ships 'turbo'/'viridis' natively (LUT-identical to matplotlib,
    guarded by tests/ui/test_colormap_parity.py)."""
    try:
        cm = pg.colormap.get(name)
        if cm is not None:
            return cm
    except Exception:
        pass
    return pg.colormap.get('viridis')
```

- [ ] **Step 4: 冻结黄金 LUT（matplotlib 仍在时一次性生成）**

```bash
.venv/bin/python - <<'PY'
import numpy as np, pyqtgraph as pg
names=['turbo','viridis']
out={n: pg.colormap.get(n).getLookupTable(0.0,1.0,256,alpha=True) for n in names}
# 同时确认与 mpl 一致
for n in names:
    assert np.array_equal(out[n], pg.colormap.getFromMatplotlib(n).getLookupTable(0.0,1.0,256,alpha=True))
np.savez_compressed("tests/data/colormap_golden.npz", **out)
print("wrote colormap golden")
PY
```

- [ ] **Step 5: 真机渲染验证 + 测试**

Run: `pytest tests/ui/test_colormap_parity.py tests/ui/test_pg_heatmap_canvas.py -q`
然后渲染一张谱图截图，确认色图仍是 turbo（非 viridis）。
Expected: PASS + 截图色图无变化。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_colormap_parity.py tests/data/colormap_golden.npz
git commit -m "refactor(ui): resolve heatmap colormap natively in pyqtgraph (drop getFromMatplotlib)"
```

---

### Task 2: 取色器色串工具脱离 mcolors

**Files:**
- Create: `mf4_analyzer/ui/_color_utils.py`
- Modify: `mf4_analyzer/ui/dialogs.py:30`（import）、`:921,942-943,957`（调用）
- Test: `tests/ui/test_color_utils.py`（新建）

**Interfaces:**
- Produces: `to_hex(c) -> str('#rrggbb')`、`is_color_like(c) -> bool`。
- Consumes: 被 dialogs.py 取色器使用。

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_color_utils.py
from mf4_analyzer.ui._color_utils import to_hex, is_color_like

def test_hex_string_roundtrip():
    assert to_hex('#1769e0') == '#1769e0'

def test_named_color():
    assert to_hex('red') == '#ff0000'

def test_float_tuple():
    assert to_hex((1.0, 0.0, 0.0)) == '#ff0000'

def test_is_color_like():
    assert is_color_like('#1769e0')
    assert is_color_like('red')
    assert not is_color_like('not-a-color')
    assert is_color_like((1.0, 0.0, 0.0))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_color_utils.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `_color_utils.py`**

```python
# mf4_analyzer/ui/_color_utils.py
"""Qt-native replacements for the matplotlib.colors helpers used by the
chart-options color picker. Covers exactly the inputs that occur at runtime:
hex/name strings and 0-1 float RGB(A) tuples. Output matches mcolors.to_hex
(lowercase '#rrggbb')."""
from PyQt5.QtGui import QColor


def to_hex(c):
    if isinstance(c, (tuple, list)):
        vals = list(c)
        if all(isinstance(v, float) or 0.0 <= v <= 1.0 for v in vals):
            q = QColor.fromRgbF(*[float(v) for v in vals[:4]])
        else:
            q = QColor(*[int(v) for v in vals[:4]])
    else:
        q = QColor(str(c))
    return q.name()


def is_color_like(c):
    if isinstance(c, (tuple, list)):
        return 3 <= len(c) <= 4
    return QColor(str(c)).isValid()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_color_utils.py -q`
Expected: PASS。

- [ ] **Step 5: dialogs.py 切换到新工具**

- 第 30 行 `from matplotlib import colors as mcolors` → 删除，改为
  `from ._color_utils import to_hex as _to_hex, is_color_like as _is_color_like`
- 第 921 行 `return mcolors.to_hex(line.get_color())` → `return _to_hex(line.get_color())`
- 第 942-943 行 `QColor(mcolors.to_hex(initial)) if mcolors.is_color_like(initial)` →
  `QColor(_to_hex(initial)) if _is_color_like(initial)`
- 第 957 行 `... and mcolors.is_color_like(color)` → `... and _is_color_like(color)`

- [ ] **Step 6: 跑取色器相关测试 + 真机验证**

Run: `pytest tests/ui/test_dialogs.py tests/ui/test_dialog_with_handle.py -q`
真机：打开图表选项对话框，选/改一条曲线颜色，确认行为与改前一致。
Expected: PASS + 取色器行为无变化。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/_color_utils.py tests/ui/test_color_utils.py mf4_analyzer/ui/dialogs.py
git commit -m "refactor(ui): replace matplotlib.colors with Qt-native color utils in dialogs"
```

---

### Task 3: batch 出图重写为 pyqtgraph 离屏导出

**Files:**
- Modify: `mf4_analyzer/batch.py`（`_write_image` 721-814；删 `from ._chart_kw import CHART_TIGHT_LAYOUT_KW` 第 23 行的使用）
- Modify: `tests/test_batch_runner.py`（改写 2 个 matplotlib 耦合测试）

**Interfaces:**
- Consumes: `_Spectro2D`、`SpectrogramAnalyzer.amplitude_to_db`、`_resolve_colormap`(Task1)。
- Produces: `_write_image(payload, path, params) -> Path`（签名不变）；
  `_build_export_scene(payload, params) -> (widget, info)`，`info` 含
  `{'plot_item','image_item','levels','matrix'}`（供测试断言）。

- [ ] **Step 1: 改写耦合测试为对 `_build_export_scene` 断言（先红）**

`tests/test_batch_runner.py` 中 `test_batch_heatmap_image_applies_xyz_axis_params`
与 `test_batch_heatmap_image_can_render_linear_z_scale` 改为（删 `from matplotlib...`）：
```python
def test_batch_heatmap_image_applies_xyz_axis_params(tmp_path):
    from mf4_analyzer.batch import BatchRunner
    payload = _make_heatmap_payload()  # 沿用原测试构造
    params = dict(z_auto=False, z_floor=-60.0, z_ceiling=-5.0,
                  amplitude_mode='amplitude_db')
    _w, info = BatchRunner._build_export_scene(payload, params)
    assert info['levels'] == (-60.0, -5.0)

def test_batch_heatmap_image_can_render_linear_z_scale(tmp_path):
    from mf4_analyzer.batch import BatchRunner
    payload = _make_heatmap_payload()
    params = dict(amplitude_mode='amplitude')  # linear
    _w, info = BatchRunner._build_export_scene(payload, params)
    # linear 模式矩阵未经 dB 变换
    assert float(np.nanmax(info['matrix'])) == pytest.approx(_expected_linear_max())
```
（`_make_heatmap_payload`/`_expected_linear_max` 复用原测试已有的构造数据，
保持断言语义等价：一个验 z 范围 levels、一个验 linear vs dB 矩阵。）

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_batch_runner.py -q`
Expected: FAIL（`_build_export_scene` 未定义）。

- [ ] **Step 3: 实现 pyqtgraph 离屏出图**

在 batch.py 替换 `_write_image`（721-814）为以下三函数（删除 `from matplotlib.figure import Figure` 与 `fig.tight_layout/savefig` 路径）：
```python
@staticmethod
def _ensure_qapp():
    import os
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app

@staticmethod
def _build_export_scene(payload, params=None):
    import numpy as np
    import pyqtgraph as pg
    from .ui.pg_canvas.heatmap_canvas import _resolve_colormap
    params = params or {}
    kind, data = payload
    BatchRunner._ensure_qapp()
    glw = pg.GraphicsLayoutWidget()
    glw.resize(1120, 630)
    plot = glw.addPlot()
    plot.showGrid(x=True, y=True, alpha=0.25)
    info = {'plot_item': plot, 'image_item': None, 'levels': None, 'matrix': None}

    x_auto = bool(params.get('x_auto', True)); x_min=float(params.get('x_min',0.0)); x_max=float(params.get('x_max',0.0))
    y_auto = bool(params.get('y_auto', True)); y_min=float(params.get('y_min',0.0)); y_max=float(params.get('y_max',0.0))

    if kind == 'fft':
        df = data
        plot.plot(np.asarray(df['frequency_hz'], float), np.asarray(df['amplitude'], float))
        plot.setLabel('bottom', 'Frequency (Hz)'); plot.setLabel('left', 'Amplitude')
        if not x_auto and x_max > x_min: plot.setXRange(x_min, x_max, padding=0)
        if not y_auto and y_max > y_min: plot.setYRange(y_min, y_max, padding=0)
    else:
        # 复用原 _write_image 的矩阵/extent/label 提取逻辑（_Spectro2D 与 legacy DataFrame 两路）
        matrix, x_extent, y_extent, x_label, y_label = BatchRunner._extract_matrix(data)
        amp_mode = str(params.get('amplitude_mode', 'amplitude_db' if kind=='fft_time' else 'amplitude')).lower()
        if 'db' in amp_mode:
            from .signal.spectrogram import SpectrogramAnalyzer as _SA
            ref = float(params.get('db_reference', 1.0) or 1.0); ref = ref if ref>0 else 1.0
            matrix = _SA.amplitude_to_db(matrix, reference=max(ref, 1e-12))
            cbar_label = 'Amplitude (dB)'
        else:
            cbar_label = 'Amplitude'
        img = pg.ImageItem(np.asarray(matrix, float).T)  # ImageItem 期望 (cols=x, rows=y) → 转置回 x-major
        img.setRect(pg.QtCore.QRectF(x_extent[0], y_extent[0], x_extent[1]-x_extent[0], y_extent[1]-y_extent[0]))
        cm = _resolve_colormap(params.get('cmap', 'turbo')); img.setColorMap(cm)
        levels = None
        if not bool(params.get('z_auto', True)):
            levels = (float(params['z_floor']), float(params['z_ceiling'])); img.setLevels(levels)
        plot.addItem(img)
        bar = pg.ColorBarItem(colorMap=cm, label=cbar_label); bar.setImageItem(img, insert_in=plot)
        plot.setLabel('bottom', x_label); plot.setLabel('left', y_label)
        if not x_auto and x_max > x_min: plot.setXRange(x_min, x_max, padding=0)
        if not y_auto and y_max > y_min: plot.setYRange(y_min, y_max, padding=0)
        info.update(image_item=img, levels=levels, matrix=np.asarray(matrix, float))
    return glw, info

@staticmethod
def _export_png(widget, path):
    import pyqtgraph.exporters
    exp = pyqtgraph.exporters.ImageExporter(widget.scene())
    exp.parameters()['width'] = 1120
    exp.export(str(path))
    return path

@staticmethod
def _write_image(payload, path, params=None):
    widget, _info = BatchRunner._build_export_scene(payload, params)
    return BatchRunner._export_png(widget, path)
```
并把原 `_write_image` 里 `_Spectro2D`/legacy DataFrame 的矩阵提取抽成
`BatchRunner._extract_matrix(data)`（搬运原 759-776 行逻辑，返回
`(matrix, x_extent, y_extent, x_label, y_label)`）。删除对
`CHART_TIGHT_LAYOUT_KW` 的 import 使用（batch.py:23 该 import 可删；
`_chart_kw.py` 模块保留不动，仍被 canvases.py 再导出）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_batch_runner.py -q`
Expected: PASS（含 fft 出 .png、heatmap levels、linear/dB 矩阵三项）。

- [ ] **Step 5: 真机验证导出图可读**

手动跑一次 batch 导出 fft + 谱图 PNG，肉眼确认：折线/谱图、坐标标签、
colorbar、turbo 色、dB/z 范围都在（风格变化属预期）。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "refactor(batch): render export images via pyqtgraph offscreen (drop matplotlib Figure)"
```

---

### Task 4: 清死分支 — NavigationToolbar（cards + QSS）

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/cards.py:9,98-99`
- Modify: `mf4_analyzer/ui_kit/style.qss:1272-1273`(NavigationToolbar2QT 规则块)

**Interfaces:** 无新接口；删除运行时不可达分支。

- [ ] **Step 1: 删 cards.py 的 matplotlib toolbar 分支**

- 删第 9 行 `from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar`
- 第 98-99 行 `else: self.toolbar = NavigationToolbar(canvas, self)` 改为：
```python
        else:
            raise TypeError(f"unsupported canvas type for toolbar: {type(canvas).__name__}")
```
（实时只会是 `TimeDomainCanvasPG/PgHeatmapCanvas/PgLineCanvas`，永不进此分支。）

- [ ] **Step 2: 删 QSS 中 NavigationToolbar2QT 选择器块**

`style.qss` 第 1268-1273 行附近含 `NavigationToolbar2QT#chartToolbar,
NavigationToolbar2QT { … }` 的规则整块删除（pg 工具栏用 QToolBar/object-name 选择器，已另有规则）。

- [ ] **Step 3: 跑 chart_stack/toolbar 测试 + 真机**

Run: `pytest tests/ui/test_chart_stack.py tests/ui/test_toolbar_i18n.py -q`
真机：三种画布的图表工具栏外观/交互不变。
Expected: PASS + 工具栏无变化。

- [ ] **Step 4: 提交**

```bash
git add mf4_analyzer/ui/chart_stack/cards.py mf4_analyzer/ui_kit/style.qss
git commit -m "chore(ui): remove dead matplotlib NavigationToolbar branch + QSS selector"
```

---

### Task 5: 清死分支 — MplAxisHandle / make_handle

**Files:**
- Modify: `mf4_analyzer/ui/_axis_handle.py`（删 `MplAxisHandle`、`_MplLineHandle`、`make_handle` 的 mpl 分支）
- Modify: `mf4_analyzer/ui/_axis_interaction.py`（删 mpl Axes 扫描分支）
- Modify: `tests/ui/test_axis_handle.py`、`tests/ui/test_dialog_with_handle.py`、`tests/ui/test_axis_interaction.py`（删/改 mpl 用例）

**Interfaces:**
- Produces: `make_handle(axis_or_handle)` —— 已是 `PgAxisHandle` 则透传；其它一律按 pg 处理或抛错。不再接受 matplotlib Axes。

> 实现前先 `Read` 这两个文件，按 grep 锚点逐块删除 mpl 分支。这是删代码任务，
> 以"删后全套 pg 测试仍绿"为准。

- [ ] **Step 1: 先改测试——删除针对 MplAxisHandle 的用例（先红/调整）**

在三个测试文件中删除构造 `MplAxisHandle`/matplotlib `Figure().add_subplot()`
并断言其行为的用例；保留 `PgAxisHandle` 用例。运行确认其余仍引用到的符号存在。

Run: `pytest tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py -q`
Expected: 收集阶段不报 ImportError（mpl 用例已删）。

- [ ] **Step 2: 删 `_axis_handle.py` 的 mpl 分支**

删除 `class MplAxisHandle`、`class _MplLineHandle`（及相关 `_Mpl*` 私有），
把 `make_handle` 改为：
```python
def make_handle(axis_or_handle):
    """Return a chart-axis handle. Live canvases pass a PgAxisHandle straight
    through; matplotlib Axes are no longer supported (mpl fully retired)."""
    from .pg_canvas... import PgAxisHandle  # 用文件现有的 PgAxisHandle 导入路径
    if isinstance(axis_or_handle, PgAxisHandle):
        return axis_or_handle
    raise TypeError(f"unsupported axis object: {type(axis_or_handle).__name__}")
```
（PgAxisHandle 的确切导入路径以文件现状为准。）

- [ ] **Step 3: 删 `_axis_interaction.py` 的 mpl Axes 扫描分支**

删除遍历 `figure.axes`/`MplAxisHandle` 的代码路径，仅保留 pg 路径。

- [ ] **Step 4: 跑相关测试 + 取色器真机**

Run: `pytest tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py tests/ui/test_dialogs.py -q`
真机：图表选项对话框取色/改色仍正常（它走 PgAxisHandle）。
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/_axis_handle.py mf4_analyzer/ui/_axis_interaction.py tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py
git commit -m "chore(ui): remove retired MplAxisHandle branch (pyqtgraph-only handles)"
```

---

### Task 6: 字体函数 no-op + app.py 去 matplotlib 后端

**Files:**
- Modify: `mf4_analyzer/ui_kit/fonts.py`
- Modify: `mf4_analyzer/app.py:67-69`

**Interfaces:** `setup_chinese_font()` 保留函数名与 `__all__`，变 no-op。

- [ ] **Step 1: fonts.py 改 no-op**

`setup_chinese_font` 函数体（15-49 行）替换为：
```python
def setup_chinese_font():
    """No-op since matplotlib was retired. Qt/pyqtgraph Chinese rendering is
    configured independently of matplotlib rcParams; kept as a stable entry
    point so app.py's call site is unchanged."""
    return None
```
文件顶部 docstring "for matplotlib/PyQt" 改为 "for PyQt"。`import platform` 与 `_log` 不再需要可一并删。

- [ ] **Step 2: app.py 删 matplotlib 后端设置**

`app.py:67-69` 删除：
```python
    import matplotlib
    matplotlib.use("Qt5Agg", force=True)
```

- [ ] **Step 3: 跑启动冒烟 + 真机字体**

Run: `pytest tests/ui/test_main_window_smoke.py -q`
真机：启动 GUI，确认中文标签正常显示（Qt 字体不依赖 matplotlib）。
Expected: PASS + 中文正常。

- [ ] **Step 4: 提交**

```bash
git add mf4_analyzer/ui_kit/fonts.py mf4_analyzer/app.py
git commit -m "chore: stop configuring matplotlib fonts/backend (retired)"
```

---

### Task 7: 移除 matplotlib 依赖 + 打包排除 + 全局验收

**Files:**
- Modify: `requirements.txt`（删 `matplotlib`）
- Modify: `build/spec/MF4DataAnalyzer.spec`（excludes 加 matplotlib 全链）

**Interfaces:** 无。

- [ ] **Step 1: 删 requirements 的 matplotlib**

`requirements.txt` 删除 `matplotlib` 行。

- [ ] **Step 2: PyInstaller 排除 matplotlib 全链**

`build/spec/MF4DataAnalyzer.spec` 的 `excludes`（若 Task scipy 已设为
`['scipy']`，则合并）改为：
```python
    excludes=['scipy', 'matplotlib', 'PIL', 'fontTools', 'contourpy', 'kiwisolver', 'cycler'],
```

- [ ] **Step 3: 卸载 matplotlib 全链，跑全套（关键验收）**

```bash
.venv/bin/pip uninstall -y matplotlib fonttools pillow contourpy kiwisolver cycler
pytest -q
```
Expected: 全套 PASS（含 colormap_parity 走黄金值分支、batch、axis-handle）。

- [ ] **Step 4: GUI 启动 + 真机渲染验收（CLAUDE.md 强制）**

启动 GUI，逐项截图比对改前：谱图/阶次热图色图仍是 turbo、取色器、图表工具栏、
中文显示——**不得有任何可见变化**；再跑一次 batch 导出确认出图正常。

- [ ] **Step 5: 确认无运行时 matplotlib import 残留**

Run: `grep -rn "import matplotlib\|from matplotlib\|getFromMatplotlib\|mcolors" mf4_analyzer/`
Expected: 无运行时 import（仅 docstring/注释可残留）。

- [ ] **Step 6: 提交**

```bash
git add requirements.txt build/spec/MF4DataAnalyzer.spec
git commit -m "build: drop matplotlib dependency chain, exclude from PyInstaller bundle"
```

---

## Self-Review

- **Spec coverage:** §2 色图→Task1；§4.2 色串→Task2；§4.1 batch→Task3；§3B
  NavigationToolbar→Task4、MplAxisHandle→Task5；§4.4 字体+app→Task6；§7 依赖/打包→Task7。
- **Placeholder scan:** batch `_extract_matrix` 与 axis-handle 删除以现有文件锚点为准，
  已在步骤中明确"搬运原 759-776 行""先 Read 再删"；其余步骤含完整代码。
- **Type consistency:** `_resolve_colormap(name)->pg.ColorMap`、`to_hex/is_color_like`、
  `_build_export_scene(payload,params)->(widget, info{plot_item,image_item,levels,matrix})`、
  `_write_image(payload,path,params)->Path` 全程一致。
- **依赖顺序:** Task1 Step4 / colormap 黄金值、batch 测试改写都须在 Task7 卸 matplotlib
  之前完成；计划顺序已保证（Task7 是最后一步）。
- **UI 保真:** 每个动 UI 的 Task（1/2/4/5/6/7）都含真机渲染验证步骤。
