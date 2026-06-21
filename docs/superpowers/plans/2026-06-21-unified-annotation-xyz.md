# 统一标注 + 热力图 XYZ 显示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` for every behavior change and `superpowers:executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for progress tracking.

**Goal:** 按 `docs/superpowers/specs/2026-06-21-unified-annotation-xyz-design.md` 将 TimeDomain / FFT / FFT vs Time / Order 的标注视觉、label 和鼠标交互统一，并为热力图增加持续 XYZ hover 浮窗。

**Architecture:** 新增一个 pyqtgraph 标注公共层：`RemarkPoint` + `format_remark_label()` + `RemarkArtist` + `RemarkInteraction`。TimeDomain 的 `AnnotationManager` 退化为“公共交互 + TimeDomain 适配器”的装配；FFT 和热力图保留现有兼容方法（`add_remark_at` / `remove_remark_near` / `clear_remarks`），内部改用公共 artist/label，并补 viewport event filter 实现点击不拖才落点。热力图 hover 基于 `_matrix_disp/_extents/_slice_coords()`，因此 FFT vs Time 和 Order 都能发 `X=/Y=/Z=`。

**Tech Stack:** Python, PyQt5, pyqtgraph, numpy, pytest / pytest-qt.

## Current Evidence

- `TimeDomainCanvasPG` 已用 `AnnotationManager`，入口在 `mf4_analyzer/ui/pg_canvas/canvas.py` 的 viewport `eventFilter`；现有时域交互已经有拖拽阈值、右键删除、笔形 cursor。
- `PgLineCanvas` 当前在 `mf4_analyzer/ui/pg_canvas/line_canvas.py` 通过 `sigMouseClicked` 直接落点，标注只有裸 `TextItem + ScatterPlotItem`。
- `PgHeatmapCanvas` 当前在 `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` 通过 `sigMouseClicked` 直接落点，标注只有裸 `(x,y,z)` 文本 + dot。
- `PgHeatmapCanvas._on_scene_hover()` 当前要求 `self._result is not None`，所以 Order 通过 `plot_or_update_heatmap()` 渲染后有矩阵/坐标，但没有 hover readout。
- `ChartStack._connect_analysis_card_signals()` 只接 copy / annotation / tick density；分析卡 `cursor_info` 没接到 `CursorPill`。`_on_cursor_info()` / `_reposition_pill()` 仍按 `current_mode() == 'time'` 限制显示。
- 工作区基线已知有非本任务脏文件：`docs/lessons-learned/.state.yml`、未跟踪 spec、`output/`。本计划不 stage、不清理这些文件。

## Plan Adjustments From Spec

- Spec 说“Order map has no hover-readout contract”的旧注释要废弃；实现以 `_has_result + _matrix_disp + _extents` 为准，不以 `_result` 为准。FFT vs Time 的 `SpectrogramResult` 和 Order 的 COT result 都已经向 canvas 传入 `x_coords/y_coords`。
- 单位不从新建数值结构硬编码：TimeDomain 从 `channel_data` 的 unit，FFT X 固定 `Hz`、Y 从当前 amp label 推 `dB` 或空，FFT time-preview X 固定 `s`、Y 为空，热力图 X/Y 从轴 label 提取括号单位（无括号则使用 `s` / `Hz` / 空的保守默认），Z 从 `_amplitude_mode` 和 `_readout_unit()`。
- 兼容现有测试/调用：保留 `canvas._remarks` 列表、TimeDomain `canvas._annotations.remarks`、FFT/热力图的 `add_remark_at()` 和 `remove_remark_near()` 入口，但 remark dict 变为公共超集：`vb/dot/text/leader/data_x/data_y/data_z`，同时提供 legacy `label` alias 指向 `text`。

## Global Constraints

- 不改 FFT / Spectrogram / Order 数值算法；`_value_at()`、`_time_index_for()`、`_freq_index_for()` 只在需要统一 hover/remark 取值时复用。
- 不新造浮窗控件；热力图 XYZ hover 复用 `CursorPill`，避免引入新的灰底/圆角风险。
- 不重写 pyqtgraph navigation toolbar；标注 event filter 仅在 `remark_enabled` 时处理左/右键标注语义。
- 不删除用户或前序 agent 的未提交文件。
- 每个生产代码变更前先写 failing test 并跑 RED；每个 task 完成后跑对应 GREEN。

---

## Task 0: Baseline And Branch Hygiene

- [ ] Confirm branch/status:

```bash
git status --short --branch
```

- [ ] Keep unrelated dirt out of task diffs:

Expected unrelated entries may remain:

```text
 M docs/lessons-learned/.state.yml
?? docs/superpowers/specs/2026-06-21-unified-annotation-xyz-design.md
?? output/
```

---

## Task 1: RED Tests For Shared Label + Artist Shape

Purpose: lock the target label format and reusable artist contract before moving any existing canvas.

**Files:**
- Create: `tests/ui/test_pg_remarks.py`
- Create later: `mf4_analyzer/ui/pg_canvas/remarks.py`

- [ ] Add failing tests:

```python
from PyQt5.QtCore import Qt
import pyqtgraph as pg

from mf4_analyzer.ui.pg_canvas.remarks import (
    RemarkArtist,
    RemarkPoint,
    format_remark_label,
)


def test_format_remark_label_uses_xyz_with_units_and_y_color(qapp):
    point = RemarkPoint(
        vb=None,
        x=1.25,
        y=42.5,
        z=-18.75,
        color="#00b894",
        unit_x="s",
        unit_y="Hz",
        unit_z="dB",
    )

    html = format_remark_label(point).lower()

    assert "x=1.25 s" in html
    assert "y=42.5 hz" in html
    assert "z=-18.75 db" in html
    assert "#00b894" in html


def test_remark_artist_creates_dot_leader_movable_text(qapp):
    widget = pg.GraphicsLayoutWidget()
    plot = widget.addPlot()
    point = RemarkPoint(
        vb=plot.vb,
        x=1.0,
        y=2.0,
        color="#dc2626",
        unit_x="s",
        unit_y="",
    )

    remark = RemarkArtist().add(point)

    assert remark["dot"].opts["brush"].color().name() == "#dc2626"
    assert remark["leader"].opts["pen"].style() == Qt.DashLine
    assert remark["text"].flags() & remark["text"].ItemIsMovable
    assert remark["label"] is remark["text"]
    assert remark["data_x"] == 1.0
    assert remark["data_y"] == 2.0
    widget.deleteLater()
```

- [ ] Run RED:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_remarks.py -q
```

Expected: fails on missing `mf4_analyzer.ui.pg_canvas.remarks`.

- [ ] Implement minimal `remarks.py` with:
  - `@dataclass RemarkPoint`
  - `format_remark_label(point)`
  - `RemarkArtist.add(point)` / `RemarkArtist.remove(remark)` / `RemarkArtist.clear(remarks)`
  - `_annotation_pen_cursor()` moved or re-exported from existing annotations module without changing cursor bitmap.

- [ ] Run GREEN:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_remarks.py -q
```

---

## Task 2: TimeDomain Migration Without Behavior Drift

Purpose: make the old, best implementation consume the new shared pieces first.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/annotations.py`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] Add/adjust RED tests in `TestTimeDomainCanvasPGAnnotations`:
  - label text includes `X=... s`
  - label text includes `Y=... <unit>` when channel unit is present
  - created remark has `leader`, `dot`, movable `text`, and legacy `label is text`
  - existing click-release / drag-no-add / right-click-delete tests still pass

Use monkeypatch compatible with existing `_nearest_data_point` tuples:

```python
monkeypatch.setattr(
    canvas._annotations,
    "_nearest_data_point",
    lambda _pos: ("speed", 1.25, 42.5, "#00b894", "rpm"),
)
```

- [ ] Run RED:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "Annotation or remark_label"
```

- [ ] Migrate `AnnotationManager._add_remark()`:
  - convert nearest tuple to `RemarkPoint(vb, x, y, color, unit_x="s", unit_y=unit)`
  - use `RemarkArtist.add(point)`
  - preserve `self.remarks` list and `_update_remark_leader()` / delete / clear semantics via common helpers
  - preserve `_nearest_data_point()` search logic; only append unit to its tuple

- [ ] Run GREEN:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "Annotation or remark_label"
```

---

## Task 3: Shared RemarkInteraction And FFT Canvas

Purpose: FFT adopts the same cursor and click-vs-drag interaction while retaining existing direct APIs.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/remarks.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Modify: `tests/ui/test_pg_line_canvas.py`

- [ ] Add RED tests:
  - `set_remark_enabled(True)` sets the viewport cursor to `Qt.BitmapCursor`
  - direct `add_remark_at('amp', ...)` creates unified label `X=... Hz` and `Y=...`
  - direct `add_remark_at('time', ...)` creates unified label `X=... s`
  - new remarks include `leader` and movable `text`
  - left press + release in remark mode adds one remark; left drag does not add; right press/delete removes nearest

- [ ] Run RED:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q -k "remark or annotation"
```

- [ ] Implement `RemarkInteraction` in `remarks.py`:
  - owns `enabled`, `press_pos`, `press_dragged`
  - `set_enabled(enabled, viewport, menu_viewboxes=...)`
  - `handle_mouse_press(event)`, `handle_mouse_move(event)`, `handle_mouse_release(event)`
  - callbacks: `add_at_viewport_pos(viewport_pos)`, `remove_at_viewport_pos(viewport_pos)`, `remark_at_viewport_pos(viewport_pos)`

- [ ] Wire `PgLineCanvas`:
  - install viewport event filter in `__init__`
  - `set_remark_enabled()` delegates cursor/menu state to `RemarkInteraction`
  - `_remark_point_from_viewport_pos()` picks amp row or time row, using screen-space nearest for time overlay
  - keep `add_remark_at(which, x, y)` but route to shared `RemarkArtist`
  - keep `remove_remark_near(which, x)` but remove dot/text/leader through shared helper
  - remove annotation branches from `_on_click()` or guard them so scene-click does not double-add after eventFilter handles release

- [ ] Run GREEN:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q -k "remark or annotation"
```

---

## Task 4: Heatmap Canvas Unified Remarks

Purpose: FFT vs Time / Order heatmaps get the same click annotation frame and interaction.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] Add RED tests:
  - direct `add_remark_at(x, y)` label becomes three rows `X=...`, `Y=...`, `Z=...`
  - dB mode labels `Z=... dB`; linear mode labels channel unit when available
  - remark has dot + leader + movable text
  - `set_remark_enabled(True)` uses bitmap pen cursor
  - left click in remark mode adds without moving the slice; drag does not add; right click deletes nearest
  - right click in colorbar/out-of-extent region still does not delete

- [ ] Run RED:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q -k "remark or left_click_adds_remark or right_click_on_colorbar"
```

- [ ] Implement:
  - install viewport event filter for annotation mode
  - replace bare `TextItem + dot` with `RemarkArtist`
  - `HeatmapRemarkAdapter` logic uses `_value_at()`, `_time_index_for()`, `_freq_index_for()`, `_slice_coords()`
  - `remove_remark_near()` removes text/dot/leader and remains extent-gated
  - keep existing slice left-click behavior when remark mode is off

- [ ] Run GREEN:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q -k "remark or left_click_adds_remark or right_click_on_colorbar"
```

---

## Task 5: Heatmap XYZ Hover Pill For FFT vs Time And Order

Purpose: make heatmap hover visible and persistent via existing `CursorPill`.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Maybe modify: `mf4_analyzer/ui/chart_stack/cursor_pill.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`
- Modify: `tests/ui/test_chart_stack.py`

- [ ] Add RED tests:
  - FFT vs Time hover emits text containing `X=... s`, `Y=... Hz`, `Z=... dB`
  - Order-style `plot_or_update_heatmap(..., x_coords=..., y_coords=...)` hover emits `X=... s`, `Y=...` and `Z=... dB` even with `canvas._result is None`
  - `ChartStack` connects analysis card `cursor_info` to `_on_cursor_info`
  - in `fft_time` and `order` modes, emitted heatmap cursor info makes primary pill visible; in split, source canvas still routes to the correct pill
  - empty hover clears/hides according to current mode

- [ ] Run RED:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py -q -k "hover" \
  tests/ui/test_chart_stack.py -q -k "cursor_info or pill"
```

- [ ] Implement:
  - connect heatmap hover regardless of `with_slice`
  - rewrite `_on_scene_hover()` to use `_has_result`, `_matrix_disp`, `_extents`, `_slice_coords()`
  - emit the same HTML/text row style as `format_remark_label()`; no new QWidget
  - in `ChartStack._connect_analysis_card_signals()`, connect `card.canvas.cursor_info` to `_on_cursor_info`
  - replace `current_mode() == 'time'` visibility gates with helper `_cursor_pill_visible_for_mode(mode)` returning true for `time`, `fft_time`, `order`
  - keep split-pane `_pill_for_canvas()` routing unchanged

- [ ] Run GREEN:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py -q -k "hover" \
  tests/ui/test_chart_stack.py -q -k "cursor_info or pill"
```

---

## Task 6: Focused Regression Suite

- [ ] Run focused suites:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_remarks.py \
  tests/ui/test_pg_timedomain_canvas.py -q -k "Annotation or remark_label" \
  tests/ui/test_pg_line_canvas.py -q -k "remark or annotation" \
  tests/ui/test_pg_heatmap_canvas.py -q -k "remark or hover or left_click_adds_remark or right_click_on_colorbar" \
  tests/ui/test_chart_stack.py -q -k "annotation or cursor_info or pill"
```

- [ ] Run split cursor routing lesson checks if `ChartStack` pill routing changed:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_routing.py \
  tests/ui/test_split_per_pane_controls.py -q
```

- [ ] Run diff hygiene:

```bash
git diff --check
git diff --stat
```

---

## Task 7: Live UI Verification

Only after tests are green.

- [ ] Launch app:

```bash
MF4_FFT_TIME_DEBUG=1 .venv/bin/python "MF4 Data Analyzer V1.py"
```

- [ ] Manually verify:
  - TimeDomain 标注：笔形 cursor、点击落点、拖动不落点、右键删除、label `X=/Y=`
  - FFT 标注：amp row 和 time-preview row 均有红点 + 虚线 + 可拖白框
  - FFT vs Time 标注：三行 `X=/Y=/Z=`
  - Order 标注：三行 `X=/Y=/Z=`
  - FFT vs Time / Order hover：CursorPill 显示 XYZ，状态栏仍保留读数
  - split pane 中 time cursor pill 不串到另一个 pane

Record in final answer whether this live verification was run. If not run, explicitly say remaining unverified.
