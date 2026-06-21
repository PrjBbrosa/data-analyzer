# matplotlib -> pyqtgraph 全面替换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 matplotlib 运行时与必需依赖，所有运行时出图走 pyqtgraph；实时 UI、
按钮接口、工具栏接口保持现状，只有 batch PNG 渲染风格允许变化。

**Architecture:** 先移除屏幕热图色图的 matplotlib 依赖并冻结 LUT，再替换取色器、
batch 离屏导出、toolbar/axis 退役分支、字体/backend 配置，最后删除依赖和打包残留。
所有步骤 TDD-first；每个 UI 相关步骤都必须验证按钮/action key/tooltip/QSS contract 未漂移。

**Tech Stack:** PyQt5, pyqtgraph, pytest, pytest-qt, PyInstaller spec.

---

## Global Constraints

- 不要修改实时 UI 布局、按钮文案、按钮顺序、tooltip、快捷键、objectName 或右键菜单行为。
- `PgNavigationToolbar` 必须继续提供 action data keys:
  `home`, `back`, `forward`, `pan`, `zoom`, `save`。
- `_ChartCard` 自定义按钮（图表选项、复制、标注、清空标注、定位/密度）只能保持，不得重排。
- `ChartOptionsDialog` 面向用户行为保持：tab/中文标签/颜色输入/Apply/Reset/Close 语义不变。
- Batch 热图色图保持当前语义：固定 turbo，不读取历史 preset 的 `cmap` 参数。
- 所有命令用项目 venv：
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest ...`
- 当前 worktree 可能有其他未提交改动。Agent 不得 revert/clean 与自己任务无关的文件。

## Agent Assignment

- **Task 1, 2, 4, 5, 6:** `pyqt-ui-engineer`
- **Task 3:** `worker` or `refactor-architect`（batch isolated rewrite）
- **Task 7:** `worker`
- 每个 task 完成后先做 spec-compliance review，再做 code-quality review。
- 不并行写同一文件；若要并行，只能选择完全 disjoint write set。

---

### Task 1: 热图色图脱离 matplotlib 并冻结 LUT

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Create: `tests/ui/test_colormap_parity.py`
- Create: `tests/data/colormap_golden.npz`

**Invariant:** 屏幕 FFT-vs-Time / Order 色图仍是 turbo；`viridis` fallback 仍可用；不得出现
`getFromMatplotlib` runtime call。

- [ ] **Step 1: 写色图 parity 测试**

Create `tests/ui/test_colormap_parity.py`:

```python
from pathlib import Path

import numpy as np
import pyqtgraph as pg


NAMES = ("turbo", "viridis")
GOLDEN = Path(__file__).resolve().parents[1] / "data" / "colormap_golden.npz"


def _lut(cm):
    return cm.getLookupTable(0.0, 1.0, 256, alpha=True)


def test_native_colormaps_match_golden_lut():
    golden = np.load(GOLDEN)
    for name in NAMES:
        native = pg.colormap.get(name)
        assert native is not None
        np.testing.assert_array_equal(_lut(native), golden[name])


def test_resolve_colormap_uses_native_and_falls_back():
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _resolve_colormap

    np.testing.assert_array_equal(_lut(_resolve_colormap("turbo")), _lut(pg.colormap.get("turbo")))
    np.testing.assert_array_equal(_lut(_resolve_colormap("viridis")), _lut(pg.colormap.get("viridis")))
    np.testing.assert_array_equal(_lut(_resolve_colormap("not-a-real-map")), _lut(pg.colormap.get("viridis")))


def test_resolve_colormap_does_not_call_matplotlib():
    import inspect
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _resolve_colormap

    assert "getFromMatplotlib" not in inspect.getsource(_resolve_colormap)
```

- [ ] **Step 2: 生成黄金 LUT（matplotlib 仍在时）**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python - <<'PY'
from pathlib import Path
import numpy as np
import pyqtgraph as pg

out = {}
for name in ("turbo", "viridis"):
    native = pg.colormap.get(name).getLookupTable(0.0, 1.0, 256, alpha=True)
    mpl = pg.colormap.getFromMatplotlib(name).getLookupTable(0.0, 1.0, 256, alpha=True)
    np.testing.assert_array_equal(native, mpl)
    out[name] = native
Path("tests/data").mkdir(exist_ok=True)
np.savez_compressed("tests/data/colormap_golden.npz", **out)
print("wrote tests/data/colormap_golden.npz")
PY
```

Expected: prints `wrote tests/data/colormap_golden.npz`.

- [ ] **Step 3: 确认测试先红或缺 resolver 行为**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_colormap_parity.py -q
```

Expected before implementation: `test_resolve_colormap_does_not_call_matplotlib` fails while the resolver still
contains `getFromMatplotlib`.

- [ ] **Step 4: 改 `_resolve_colormap`**

Replace `heatmap_canvas.py` resolver with:

```python
def _resolve_colormap(name: str) -> pg.ColorMap:
    """Resolve heatmap colormap names without matplotlib.

    Runtime uses turbo, with viridis as the legacy/fallback map. Their 256-step
    LUTs are pinned by tests/ui/test_colormap_parity.py.
    """
    requested = str(name or "turbo")
    try:
        cm = pg.colormap.get(requested)
        if cm is not None:
            return cm
    except Exception:
        pass
    return pg.colormap.get("viridis")
```

- [ ] **Step 5: 跑 focused tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_colormap_parity.py tests/ui/test_pg_heatmap_canvas.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_colormap_parity.py tests/data/colormap_golden.npz
git commit -m "refactor(ui): resolve heatmap colormaps without matplotlib"
```

---

### Task 2: 取色器色串工具脱离 `matplotlib.colors`

**Files:**
- Create: `mf4_analyzer/ui/_color_utils.py`
- Create: `tests/ui/test_color_utils.py`
- Modify: `mf4_analyzer/ui/dialogs.py`
- Modify as needed: `tests/ui/test_dialogs.py`

**Invariant:** 图表选项里的曲线颜色读取、输入、选择器初始色、Apply 行为不变。

- [ ] **Step 1: 写 `_color_utils` 测试**

Create `tests/ui/test_color_utils.py`:

```python
from mf4_analyzer.ui._color_utils import is_color_like, to_hex


def test_hex_string_roundtrip():
    assert to_hex("#1769e0") == "#1769e0"


def test_named_color():
    assert to_hex("red") == "#ff0000"


def test_float_tuple():
    assert to_hex((1.0, 0.0, 0.0)) == "#ff0000"


def test_int_tuple():
    assert to_hex((18, 52, 86)) == "#123456"


def test_is_color_like():
    assert is_color_like("#1769e0")
    assert is_color_like("red")
    assert is_color_like((1.0, 0.0, 0.0))
    assert is_color_like((18, 52, 86))
    assert not is_color_like("not-a-color")
    assert not is_color_like((1.0, 0.0))
```

- [ ] **Step 2: 跑测试确认模块缺失**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_color_utils.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现 `_color_utils.py`**

```python
"""Qt-native replacements for the matplotlib.colors helpers used by dialogs."""

from PyQt5.QtGui import QColor


def _sequence_is_0_to_1(vals) -> bool:
    return all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in vals)


def to_hex(c) -> str:
    if isinstance(c, (tuple, list)):
        vals = list(c)
        if not 3 <= len(vals) <= 4:
            raise ValueError(f"invalid color tuple length: {len(vals)}")
        if _sequence_is_0_to_1(vals):
            q = QColor.fromRgbF(*[float(v) for v in vals])
        else:
            q = QColor(*[int(v) for v in vals])
    else:
        q = QColor(str(c))
    if not q.isValid():
        raise ValueError(f"invalid color: {c!r}")
    return q.name()


def is_color_like(c) -> bool:
    try:
        to_hex(c)
    except Exception:
        return False
    return True
```

- [ ] **Step 4: 切换 dialogs.py**

Replace:

```python
from matplotlib import colors as mcolors
```

with:

```python
from ._color_utils import is_color_like as _is_color_like
from ._color_utils import to_hex as _to_hex
```

Then replace:

- `mcolors.to_hex(...)` -> `_to_hex(...)`
- `mcolors.is_color_like(...)` -> `_is_color_like(...)`

- [ ] **Step 5: 修 tests/ui/test_dialogs.py 的 mcolors import**

Remove `from matplotlib import colors as mcolors` from `tests/ui/test_dialogs.py` if any assertion still uses it.
Do not migrate the raw `Figure` fixture in this task; Task 5 owns raw-Axes removal. If a color-only assertion
remains here, use `_color_utils.to_hex` instead of `mcolors`.

- [ ] **Step 6: 跑 focused tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_color_utils.py tests/ui/test_dialogs.py::test_pg_chart_options_curve_color_syncs_owning_axis_color tests/ui/test_dialogs.py::test_pg_chart_options_curve_color_updates_inside_label_badge -q
```

Expected: PASS. Do not weaken user-facing dialog assertions.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/_color_utils.py mf4_analyzer/ui/dialogs.py tests/ui/test_color_utils.py tests/ui/test_dialogs.py
git commit -m "refactor(ui): replace matplotlib color helpers with Qt utilities"
```

---

### Task 3: Batch PNG 导出改为 pyqtgraph 离屏渲染

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Modify: `tests/test_batch_runner.py`
- Modify: `tests/test_db_conversion_convergence.py` only if helper assertions need info-path updates

**Invariant:** `_write_image(payload, path, params)` 签名不变；batch 热图仍固定 turbo；dB 转换仍
调用 `SpectrogramAnalyzer.amplitude_to_db`；exported data 不因 display mode 改变。

- [ ] **Step 1: 改写 batch tests 先红**

Update `tests/test_batch_runner.py`:

```python
def test_batch_heatmap_image_applies_xyz_axis_params(tmp_path):
    from mf4_analyzer.batch import BatchRunner

    df = pd.DataFrame({
        "time_s": [0.0, 1.0, 0.0, 1.0],
        "order": [1.0, 1.0, 2.0, 2.0],
        "amplitude": [0.1, 0.2, 0.3, 0.4],
    })
    _widget, info = BatchRunner._build_export_scene(
        ("order_time", df),
        {
            "x_auto": False, "x_min": 0.25, "x_max": 0.75,
            "y_auto": False, "y_min": 1.25, "y_max": 1.75,
            "z_auto": False, "z_floor": -40.0, "z_ceiling": -5.0,
        },
    )

    assert info["x_range"] == (0.25, 0.75)
    assert info["y_range"] == (1.25, 1.75)
    assert info["levels"] == (-40.0, -5.0)
    assert info["colormap_name"] == "turbo"
```

```python
def test_batch_heatmap_image_can_render_linear_z_scale(tmp_path):
    from mf4_analyzer.batch import BatchRunner

    df = pd.DataFrame({
        "time_s": [0.0, 1.0, 0.0, 1.0],
        "frequency_hz": [10.0, 10.0, 20.0, 20.0],
        "amplitude": [0.25, 0.5, 1.0, 2.0],
    })
    _widget, info = BatchRunner._build_export_scene(
        ("fft_time", df),
        {"amplitude_mode": "amplitude", "z_auto": True},
    )

    assert float(np.asarray(info["matrix"]).max()) == pytest.approx(2.0)
    assert info["colorbar_label"] == "Amplitude"
```

Add a PNG smoke:

```python
def test_write_image_exports_nonempty_png_with_fixed_size(tmp_path):
    from PyQt5.QtGui import QImage
    from mf4_analyzer.batch import BatchRunner

    df = pd.DataFrame({"frequency_hz": [0.0, 1.0], "amplitude": [0.0, 1.0]})
    out = BatchRunner._write_image(("fft", df), tmp_path / "fft.png")
    image = QImage(str(out))

    assert out.exists()
    assert out.stat().st_size > 0
    assert not image.isNull()
    assert (image.width(), image.height()) == (1120, 630)
```

- [ ] **Step 2: Run red tests**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_batch_runner.py::test_batch_heatmap_image_applies_xyz_axis_params tests/test_batch_runner.py::test_batch_heatmap_image_can_render_linear_z_scale -q
```

Expected: FAIL because `_build_export_scene` does not exist.

- [ ] **Step 3: Implement helpers in batch.py**

Add static/class helpers near `_write_image`:

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
    def _extract_matrix(data):
        if isinstance(data, _Spectro2D):
            spectro = data
            matrix = np.asarray(spectro.matrix, dtype=float).T
            return (
                matrix,
                (float(spectro.x.min()), float(spectro.x.max())),
                (float(spectro.y.min()), float(spectro.y.max())),
                spectro.x_name,
                spectro.y_name,
            )
        df = data
        pivot = df.pivot(index=df.columns[1], columns=df.columns[0], values="amplitude")
        return (
            pivot.to_numpy(dtype=float),
            (float(pivot.columns.min()), float(pivot.columns.max())),
            (float(pivot.index.min()), float(pivot.index.max())),
            df.columns[0],
            df.columns[1],
        )
```

Replace `_write_image` with `_build_export_scene`, `_export_png`, and thin `_write_image`.
Implementation requirements:

- FFT path uses `plot.plot(frequency_hz, amplitude)`.
- Heatmap path uses `pg.ImageItem(render_matrix)`.
- Heatmap colormap is always `_resolve_colormap("turbo")`.
- `levels = (z_floor, z_ceiling)` only when `z_auto` is false.
- `info["matrix"]` is the render matrix actually passed to `ImageItem`.
- `info["x_range"]` / `info["y_range"]` are set only to the manual ranges when applied; otherwise `None`.
- `_export_png` uses `pyqtgraph.exporters.ImageExporter(widget.scene())`, width `1120`, and returns `Path(path)`.

- [ ] **Step 4: Remove matplotlib imports from batch.py**

Delete:

```python
from ._chart_kw import CHART_TIGHT_LAYOUT_KW
from matplotlib.figure import Figure
```

`mf4_analyzer/_chart_kw.py` can remain for `ui.canvases` compatibility.

- [ ] **Step 5: Run batch tests**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_batch_runner.py tests/test_db_conversion_convergence.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py tests/test_db_conversion_convergence.py
git commit -m "refactor(batch): export PNGs with pyqtgraph offscreen"
```

---

### Task 4: 删除 matplotlib toolbar fallback，保持按钮接口

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/cards.py`
- Modify: `mf4_analyzer/ui/_toolbar_i18n.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `tests/ui/test_toolbar_i18n.py`
- Modify: `tests/ui/test_surface_layering.py`

**Invariant:** `PgNavigationToolbar` action keys、中文 tooltip、`chartToolbar` QSS 透明/无边框不变。

- [ ] **Step 1: 改 `test_toolbar_i18n.py` 使用 PgNavigationToolbar**

Replace the matplotlib toolbar fixture with:

```python
def _build_toolbar(qtbot):
    from mf4_analyzer.ui.chart_stack.toolbar import PgNavigationToolbar
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    toolbar = PgNavigationToolbar(canvas)
    qtbot.addWidget(toolbar)
    return toolbar
```

Keep existing assertions for `pan`, `zoom`, `save`, `home`, `back`, `forward`.

- [ ] **Step 2: 改 surface QSS test**

In `tests/ui/test_surface_layering.py`, replace the regex with:

```python
match = re.search(
    r"QToolBar#chartToolbar,\s*"
    r"QWidget#chartToolbar\s*\{(?P<body>[^}]*)\}",
    qss,
    flags=re.S,
)
```

Keep assertions for transparent background, no border, no border-radius.

- [ ] **Step 3: Delete cards.py matplotlib import and fallback**

Remove:

```python
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
```

Change fallback branch to:

```python
        else:
            raise TypeError(f"unsupported canvas type for toolbar: {type(canvas).__name__}")
```

Do not change toolbar construction for `TimeDomainCanvasPG`, `PgHeatmapCanvas`, or `PgLineCanvas`.

- [ ] **Step 4: Update QSS selector**

Change the chart toolbar selector block to:

```css
/* Chart toolbar - compact spacing & padding for the pyqtgraph toolbar. */
QToolBar#chartToolbar,
QWidget#chartToolbar {
    background-color: transparent;
    border: none;
    spacing: 1px;
    padding: 1px;
}
```

- [ ] **Step 5: Update `_toolbar_i18n.py` docstring only**

Docstring should say it applies Chinese labels to the chart navigation toolbar. Do not change
`apply_chinese_toolbar_labels()` behavior unless tests require it.

- [ ] **Step 6: Run toolbar/surface tests**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar_i18n.py tests/ui/test_surface_layering.py tests/ui/test_chart_stack.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/chart_stack/cards.py mf4_analyzer/ui/_toolbar_i18n.py mf4_analyzer/ui_kit/style.qss tests/ui/test_toolbar_i18n.py tests/ui/test_surface_layering.py
git commit -m "chore(ui): remove retired matplotlib toolbar fallback"
```

---

### Task 5: 删除 `MplAxisHandle`，迁移 dialog/axis tests 到 pyqtgraph handles

**Files:**
- Modify: `mf4_analyzer/ui/_axis_handle.py`
- Modify: `mf4_analyzer/ui/_axis_interaction.py`
- Modify: `tests/ui/test_axis_handle.py`
- Modify: `tests/ui/test_dialog_with_handle.py`
- Modify: `tests/ui/test_axis_interaction.py`
- Modify: `tests/ui/test_dialogs.py`

**Invariant:** 用户打开图表选项、改标题/轴范围/曲线颜色/grid/log 防护的行为不变；只是测试和
dispatch 不再接受 raw matplotlib Axes。

- [ ] **Step 1: Add pyqtgraph handle fixtures in tests**

Use `TimeDomainCanvasPG` for line tests:

```python
def _pg_time_handle(qapp):
    import numpy as np
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    t = np.linspace(0.0, 1.0, 50)
    canvas.plot_channels([("speed", True, t, np.sin(t), "#1769e0", "rpm")])
    return canvas.axes_list[0], canvas
```

Use `PgHeatmapCanvas` for mappable tests:

```python
def _pg_heatmap_handle(qapp):
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    canvas = PgHeatmapCanvas(with_slice=False)
    matrix = np.arange(9, dtype=float).reshape(3, 3)
    canvas.plot_or_update_heatmap(
        matrix,
        (0.0, 2.0),
        (10.0, 30.0),
        x_label="time_s",
        y_label="frequency_hz",
        cmap="viridis",
        z_auto=False,
        z_floor=0.0,
        z_ceiling=8.0,
    )
    return canvas.axes_list[0], canvas
```

- [ ] **Step 2: Rewrite tests instead of deleting behavior**

Replace raw matplotlib Axes assertions with pyqtgraph handle assertions:

- `get_xlim` / `set_xlim`
- `get_ylim` / `set_ylim`
- title/xlabel/ylabel read/write
- grid enabled/disabled
- `get_lines()` visible line label/color
- `sync_line_axis_color(...)`
- `get_mappables()` and heatmap clim behavior
- `ChartOptionsDialog(None, handle)` reads and applies fields
- log-axis invalid range warning still blocks close

- [ ] **Step 3: Run tests before production delete**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py tests/ui/test_dialogs.py -q
```

Expected: tests either pass with old Mpl code still present or fail only where production still accepts raw Axes.

- [ ] **Step 4: Delete matplotlib wrappers**

In `mf4_analyzer/ui/_axis_handle.py`:

- Delete `_MplLineHandle`.
- Delete `MplAxisHandle`.
- Update module docstring to say the runtime handle layer is pyqtgraph-only.
- Keep `LineHandle`, `AxisHandle`, `PgLineHandle`, `PgAxisHandle`.
- Change `make_handle` to:

```python
def make_handle(axis_or_handle) -> AxisHandle:
    """Return an existing pyqtgraph chart-axis handle.

    Matplotlib Axes are retired; callers must pass PgAxisHandle-compatible handles.
    """
    if isinstance(axis_or_handle, AxisHandle):
        return axis_or_handle
    raise TypeError(f"unsupported axis object: {type(axis_or_handle).__name__}")
```

If `isinstance(..., AxisHandle)` is too broad/slow for Protocol at runtime, use structural checks already
required by `ChartOptionsDialog`: `get_xlim`, `set_xlim`, `get_lines`, `request_redraw`, and no `figure`.

- [ ] **Step 5: Simplify `_axis_interaction.py`**

- Remove `find_axis_for_dblclick(fig, ...)` and `target_axes_for_event(...)` if no runtime caller remains.
- Keep `edit_chart_options_dialog(parent_widget, handle)` and make it pass `handle` through `make_handle`.
- Update docstring to say raw matplotlib event hit-testing is retired.

- [ ] **Step 6: Run dialog/axis focused tests**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py tests/ui/test_dialogs.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/_axis_handle.py mf4_analyzer/ui/_axis_interaction.py tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py tests/ui/test_dialogs.py
git commit -m "chore(ui): retire matplotlib axis handles"
```

---

### Task 6: 清理字体/backend 与 matplotlib-only test helpers

**Files:**
- Modify: `mf4_analyzer/ui_kit/fonts.py`
- Modify: `mf4_analyzer/ui_kit/__init__.py`
- Modify: `mf4_analyzer/app.py`
- Modify: `tests/ui/test_plot_helpers.py`
- Modify: `tests/perf/test_timedomain_pan_perf.py`

**Invariant:** GUI 中文仍由 Qt/pyqtgraph 字体路径保证；TimeDomain pan perf benchmark 仍能独立运行。

- [ ] **Step 1: Make `setup_chinese_font()` no-op**

Replace `mf4_analyzer/ui_kit/fonts.py` with:

```python
"""Font setup helpers for Qt/PyQt entry points."""


def setup_chinese_font():
    """Stable no-op after matplotlib retirement.

    Qt/pyqtgraph chart fonts are configured through the QApplication path.
    """
    return None


__all__ = ["setup_chinese_font"]
```

Update `mf4_analyzer/ui_kit/__init__.py` docstring line for `setup_chinese_font` to remove matplotlib wording.

- [ ] **Step 2: Remove app.py matplotlib backend setup**

Delete:

```python
    import matplotlib

    matplotlib.use("Qt5Agg", force=True)
```

Keep `_configure_high_dpi()`, `QApplication`, stylesheet, icon, and `apply_global_chart_font(app)` order intact.

- [ ] **Step 3: Remove matplotlib tests from `test_plot_helpers.py`**

If `_set_series_ylabel` is no longer used by runtime pyqtgraph code, delete only the `TestSetSeriesYlabel`
class that creates `matplotlib.figure.Figure`. Keep tests for pure helpers such as `_middle_ellipsis`,
`_format_dual_html`, and cursor formatting.

- [ ] **Step 4: Remove perf warmup dependency**

In `tests/perf/test_timedomain_pan_perf.py`, delete the matplotlib `FigureCanvasQTAgg` warmup block. If the
PG benchmark still aborts in isolation, replace with a native Qt warmup:

```python
from PyQt5.QtWidgets import QWidget

_warmup = QWidget()
_warmup.resize(1, 1)
_warmup.show()
QCoreApplication.processEvents()
_warmup.hide()
```

- [ ] **Step 5: Run focused tests**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_plot_helpers.py tests/perf/test_timedomain_pan_perf.py -q
```

Expected: command exits 0. It may run the perf case or deselect slow-marked tests according to current pytest
marker config, but it must not import matplotlib.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui_kit/fonts.py mf4_analyzer/ui_kit/__init__.py mf4_analyzer/app.py tests/ui/test_plot_helpers.py tests/perf/test_timedomain_pan_perf.py
git commit -m "chore: remove matplotlib font and backend setup"
```

---

### Task 7: 删除依赖、打包排除、全局验收

**Files:**
- Modify: `requirements.txt`
- Modify: `build/spec/MF4DataAnalyzer.spec`
- Modify tests only if grep finds remaining test-only matplotlib imports

**Invariant:** 不删除仍被 tools/dev workflow 需要的依赖，除非确认该 workflow out of scope 且不影响运行时。

- [ ] **Step 1: Remove requirements dependency**

Delete `matplotlib` from `requirements.txt`. Do not delete `pyqtgraph>=0.13.3`.

- [ ] **Step 2: Update PyInstaller excludes**

In `build/spec/MF4DataAnalyzer.spec`, update excludes to:

```python
    excludes=[
        'scipy',
        'matplotlib',
        'PIL',
        'fontTools',
        'contourpy',
        'kiwisolver',
        'cycler',
    ],
```

Only add `pyparsing` if dependency inspection proves no runtime/tool path in this repo still needs it.

- [ ] **Step 3: Run grep gate**

```bash
rg -n "^\s*(from matplotlib|import matplotlib)|getFromMatplotlib|mcolors|NavigationToolbar2QT|MplAxisHandle|_MplLineHandle" mf4_analyzer tests | rg -v "tests/test_signal_no_gui_import.py|tests/ui/test_colormap_parity.py"
```

Expected: no matches. The unfiltered grep may still show only:

- `tests/test_signal_no_gui_import.py` poison `matplotlib.pyplot` guard.
- `tests/ui/test_colormap_parity.py` negative `getFromMatplotlib` assertion.

Historical docs/tools can remain out of runtime scope, but list them in the final report.

- [ ] **Step 4: Run focused aggregate**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_colormap_parity.py tests/ui/test_color_utils.py tests/ui/test_toolbar_i18n.py tests/ui/test_surface_layering.py tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py tests/ui/test_dialogs.py tests/ui/test_main_window_smoke.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_batch_runner.py tests/test_db_conversion_convergence.py -q
```

Expected: PASS. Keep the UI targets in one `tests/ui/...` invocation so `tests/ui/conftest.py`
loads fixtures such as `loaded_csv`; mixing non-UI files into this command can make pytest miss
the UI-local conftest in this repo.

- [ ] **Step 5: Run full suite**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Isolated no-matplotlib validation**

Do not destructively uninstall from the user's active venv until explicitly accepted. Preferred validation:
create a temporary venv or use a copied environment, install project requirements after removing matplotlib,
and run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. /path/to/no-mpl-venv/bin/python -m pytest tests/ui/test_colormap_parity.py tests/test_batch_runner.py tests/ui/test_main_window_smoke.py -q
```

Expected: PASS; `test_colormap_parity` uses golden LUT.

- [ ] **Step 7: Manual/live GUI acceptance**

Launch with the project venv:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"
```

Verify:

- TimeDomain toolbar action buttons and custom buttons still appear/order correctly.
- FFT toolbar and chart options work.
- FFT-vs-Time heatmap still turbo, not viridis.
- Order heatmap still turbo.
- ChartOptionsDialog color edit/choose/apply unchanged.
- Batch FFT and heatmap PNGs export and are readable.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt build/spec/MF4DataAnalyzer.spec
git commit -m "build: drop matplotlib runtime dependency"
```

---

## Self-Review Checklist

- Spec coverage:
  - 色图 runtime dependency -> Task 1
  - dialogs color helpers -> Task 2
  - batch export -> Task 3
  - toolbar/buttons/QSS -> Task 4
  - axis handle/dialog raw-Axes retirement -> Task 5
  - fonts/app/test helpers -> Task 6
  - requirements/spec/final gates -> Task 7
- UI/button protection:
  - Task 4 explicitly protects `PgNavigationToolbar` action data and `chartToolbar`.
  - Task 5 explicitly protects `ChartOptionsDialog` behavior.
  - Task 7 requires live GUI acceptance.
- Previously missed tests now included:
  - `tests/ui/test_dialogs.py`
  - `tests/ui/test_toolbar_i18n.py`
  - `tests/ui/test_surface_layering.py`
  - `tests/ui/test_plot_helpers.py`
  - `tests/perf/test_timedomain_pan_perf.py`
  - `tests/test_db_conversion_convergence.py`
- Command hygiene:
  - All pytest commands use `.venv/bin/python -m pytest`.
  - Qt commands set `QT_QPA_PLATFORM=offscreen`; Matplotlib transition commands set `MPLCONFIGDIR=/tmp`.
- Stale identifier scan before final:
  - `rg -n "^\s*(from matplotlib|import matplotlib)|getFromMatplotlib|mcolors|NavigationToolbar2QT|MplAxisHandle|_MplLineHandle" mf4_analyzer tests | rg -v "tests/test_signal_no_gui_import.py|tests/ui/test_colormap_parity.py"`
  - Expected no output; the unfiltered matches are limited to the intentional poison/negative tests listed in Task 7.
