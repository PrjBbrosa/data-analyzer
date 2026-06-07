# pg_canvases 解耦重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `mf4_analyzer/ui/pg_canvases.py`（5771 行）的 God 类 `TimeDomainCanvasPG`（~4500 行/~150 方法/70 字段）拆成"协调器 + 6–8 个内聚协作对象 + 4 个纯模块"的 `pg_canvas/` 包，结构清晰、可独立测试、行为零变更。

**Architecture:** 行为优先的 strangler-fig。协作对象持有 `canvas` 反向引用，方法搬出后仍通过反向引用读写那 21 个核心枢纽字段（`axes_list`/`_glw`/`_channel_lines`/`channel_data`…，它们留在协调器）；canvas 上为每个搬出的方法留**委托薄壳**，使 50+ 处 `canvas._private(...)` 的测试访问零改动继续通过。状态迁移与撤薄壳是可选的 Phase 4。

**Tech Stack:** Python 3.12 · PyQt5 · pyqtgraph · numpy · pytest（`QT_QPA_PLATFORM=offscreen`，`-m "not slow"` 默认排除 perf）

设计依据见 `docs/superpowers/specs/2026-06-07-pg-canvas-decomposition-design.md`。

---

## 约定（每个 Phase 通用）

**测试命令**
- 目标文件：`python -m pytest tests/ui/test_pg_timedomain_canvas.py -q`
- 全量默认套（排除 slow）：`python -m pytest -q`
- 7 个相关文件聚焦跑：
  `python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_overlay_grid_ticks.py tests/ui/test_xrange_debounce.py tests/ui/test_dialogs.py tests/ui/test_chart_stack.py tests/test_packaging_imports.py -q`
- perf 门禁（slow）：`python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py -q`
- 每个 Phase **收尾必须**：默认全量套 + 上面那条 perf，全绿。

**Qt/offscreen**：`tests/ui/conftest.py` 已设 `QT_QPA_PLATFORM=offscreen` 并提供 `qapp` fixture，测试无需自行设置。

**兼容硬约束**（来自现状勘察，违反即红）：测试与 chart_stack 直接 `from mf4_analyzer.ui.pg_canvases import` 了这些符号 —— 转包/搬迁后 `mf4_analyzer/ui/pg_canvases.py` 必须始终能导出它们：
`TimeDomainCanvasPG`、`_ModifierWheelViewBox`、`_pg_chart_font`、`_HIDPI_MAX_WIDTH`、`_HIDPI_COPY_SCALE`、`_snap_y_to_divisions`、`_fmt_tick`、`_frame_to_nice`、`_nice_per_div`、`positions_envelope`、`build_envelope`（后两者被 `monkeypatch.setattr(pg_canvases, ...)`，见 Phase 3 接缝处理）。

**对外契约（绝不改签名）**：`chart_stack.py` 仅用信号 `cursor_info` / `dual_cursor_info` / `dual_cursor_rows` 与方法 `full_reset()`。信号是 QWidget 上的 `pyqtSignal`，**永远留在协调器**；协作对象通过反向引用 `self._c.cursor_info.emit(...)` 触发。

**squad 分工建议**（本仓库 planner-executor split）：
- 纯模块/包结构/跨模块搬迁 → `refactor-architect`
- Qt 渲染/交互协作对象与特征化测试 → `pyqt-ui-engineer`
- Phase 3 的 painter-path 数值 parity 与 envelope 接缝 → `signal-processing-expert`

**commit 策略**：下面每个任务末尾的 `git commit` 是执行期的标准步骤。注意本仓库规则是"只在用户要求时 commit"——执行者按 Phase 推进、每任务一提交；当前 branch 与本主题无关，**执行前先开专用分支**（如 `refactor/pg-canvas-decomposition`）。

---

## 目标文件结构

```
mf4_analyzer/ui/
├── pg_canvases.py        # Phase 0–3: 仍是 TimeDomainCanvasPG 的家 + 兼容 re-export；Phase 4: 退化成 5 行 shim
└── pg_canvas/            # 新包
    ├── __init__.py       # 显式 re-export 包内公共符号
    ├── context_menu.py   # 右键菜单/i18n/网格子菜单（13 个纯函数, ~810 行）
    ├── fonts.py          # 字体（3 个纯函数, ~140 行）
    ├── ticks_math.py     # 刻度数学（6 个纯函数, ~110 行）
    ├── viewbox.py        # _ModifierWheelViewBox（~290 行）
    ├── cursor.py         # CursorController（簇 F+T）
    ├── annotations.py    # AnnotationManager（簇 H）
    ├── tick_density.py   # TickDensityController（簇 K）
    ├── overlay_axes.py   # OverlayAxisManager + OverlayInteractionController（簇 C/D/R/N）
    ├── quality.py        # QualityManager（簇 W）
    └── renderer.py       # Renderer / Exporter（簇 Q/X）← 红线, Phase 3
```

> 命名注意：包是 `pg_canvas/`（单数），旧模块是 `pg_canvases.py`（复数），两者在同目录共存合法。Phase 4 把类移入 `pg_canvas/canvas.py` 后，`pg_canvases.py` 仅剩 re-export shim。

---

## 协作对象抽取配方（Recipe R —— Phase 1–3 每个协作对象都套用）

给定协作对象 `XController`，其簇方法清单 `M`、被测/公共成员清单 `E`：

- **R1 锁定覆盖**：先确认 `M` 的行为已被现有测试覆盖（任务里列出具体测试）。无覆盖的关键行为，先在 Phase 0/本任务补特征化测试再搬。
- **R2 建协作文件**：在 `mf4_analyzer/ui/pg_canvas/<file>.py` 建 `class XController:`，`__init__(self, canvas)` 存 `self._c = canvas`。把 `M` 里的方法体**逐字搬过来**，仅做机械改写：
  - 同协作内方法互调：`self.foo()` 保持 `self.foo()`。
  - 读写 canvas 上的字段/信号/其它方法：`self.<attr>` → `self._c.<attr>`（状态此阶段**不搬**，仍住在 canvas）。
- **R3 装配**：在 `TimeDomainCanvasPG.__init__` 末尾加 `self._<x> = XController(self)`。
- **R4 委托薄壳**：把 canvas 里被搬走的每个方法替换成一行委托：
  `def _foo(self, *a, **k): return self._<x>.foo(*a, **k)`（`E` 里的每个成员都必须留壳，保证 `canvas._foo(...)` 测试访问不变）。canvas 内部对这些方法的调用保持原样（走薄壳）即可。
- **R5 验证**：先跑该簇聚焦测试，再默认全量套，再 perf。全绿。
- **R6 提交**：`git commit`。

> 为什么状态不搬：50+ 处测试直接读 `canvas._remarks`/`canvas._idle_aa_on` 等字段。让状态留在 canvas，这些访问**零改动**继续工作；只有"方法"需要薄壳。状态迁移留到可选 Phase 4。

---

## Phase 0 —— 安全网 + 纯模块抽离（极低风险）

> squad: `pyqt-ui-engineer`（0.1）+ `refactor-architect`（0.2–0.8）

### Task 0.1：补导出像素特征化测试（红线前置，TDD）

**Files:**
- Create: `tests/ui/test_pg_export_characterization.py`

- [ ] **Step 1：写新测试文件（这些断言现在就应通过——它们钉住当前正确行为，是 Phase 3 改红线时的护栏）**

```python
"""Characterization tests for the render→export chain.

Existing grab_pixmap tests only assert non-null + geometry. These pin the
PIXEL CONTENT (not blank / each curve visible), guarding the historical
"OpenGL made grab_pixmap export all-white" regression before Phase 3 touches
the renderer. See docs/superpowers/specs/2026-06-07-pg-canvas-decomposition-design.md §6.
"""
import numpy as np
import pytest

pg = pytest.importorskip("pyqtgraph")
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QColor, QImage


def _make_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    c = TimeDomainCanvasPG()
    c.resize(640, 360)
    c.show()
    QCoreApplication.processEvents()
    return c


def _rows(*specs):
    """specs: (name, color_hex). All share one 2000-pt time base."""
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    out = []
    for i, (name, color) in enumerate(specs):
        sig = 1000.0 * np.sin(2 * np.pi * (3 + i) * t)
        out.append((name, True, t, sig, color, "u", "fid-1"))
    return out


def _to_rgb(pix):
    return pix.toImage().convertToFormat(QImage.Format_RGB32)


def _nonwhite_count(pix, near_white=245, stride=2):
    img = _to_rgb(pix)
    n = 0
    for y in range(0, img.height(), stride):
        for x in range(0, img.width(), stride):
            c = img.pixelColor(x, y)
            if c.red() < near_white or c.green() < near_white or c.blue() < near_white:
                n += 1
    return n


def _color_present(pix, hex_color, tol=55, stride=1):
    tgt = QColor(hex_color)
    img = _to_rgb(pix)
    for y in range(0, img.height(), stride):
        for x in range(0, img.width(), stride):
            c = img.pixelColor(x, y)
            if (abs(c.red() - tgt.red()) <= tol
                    and abs(c.green() - tgt.green()) <= tol
                    and abs(c.blue() - tgt.blue()) <= tol):
                return True
    return False


class TestExportPixelCharacterization:
    def test_single_channel_export_is_not_blank(self, qapp):
        c = _make_canvas(qapp)
        c.plot_channels(_rows(("speed", "#1769e0")))
        QCoreApplication.processEvents()
        pix = c.grab_pixmap()
        assert not pix.isNull()
        assert _nonwhite_count(pix) > 200, "export looks blank (all-white regression)"

    def test_empty_canvas_export_is_safe(self, qapp):
        c = _make_canvas(qapp)
        pix = c.grab_pixmap()
        assert pix is not None and not pix.isNull()
        assert pix.width() >= 1 and pix.height() >= 1

    def test_overlay_each_curve_color_is_visible(self, qapp):
        c = _make_canvas(qapp)
        c.plot_channels(_rows(("a", "#1769e0"), ("b", "#ef4444")), mode="overlay")
        QCoreApplication.processEvents()
        pix = c.grab_pixmap()
        assert _color_present(pix, "#1769e0"), "blue curve missing from export"
        assert _color_present(pix, "#ef4444"), "red curve missing from export"

    def test_2x_export_is_not_blank_and_doubles_geometry(self, qapp):
        c = _make_canvas(qapp)
        c.plot_channels(_rows(("speed", "#1769e0")))
        QCoreApplication.processEvents()
        one = c.grab_pixmap(scale=1.0)
        two = c.grab_pixmap(scale=2.0)
        assert _nonwhite_count(two) > 200, "2x export looks blank"
        assert two.width() >= one.width() * 2 - 4

    def test_export_after_setxlim_is_not_blank(self, qapp):
        c = _make_canvas(qapp)
        c.plot_channels(_rows(("speed", "#1769e0")))
        c.set_xlim(0.2, 0.7)
        c._flush_pending_refresh()
        QCoreApplication.processEvents()
        pix = c.grab_pixmap()
        assert _nonwhite_count(pix) > 100, "export blank after xlim refresh"
```

- [ ] **Step 2：跑它，确认现在就全绿（钉住当前行为）**

Run: `python -m pytest tests/ui/test_pg_export_characterization.py -q`
Expected: 5 passed。若 `test_overlay_each_curve_color_is_visible` 因 AA 边缘混色偶发失败，把 `tol` 调到 70 并加 `stride=1` 全扫（已是 stride=1）；记录最终 tol 值。

- [ ] **Step 3：提交**

```bash
git add tests/ui/test_pg_export_characterization.py
git commit -m "test(pg): add export pixel-content characterization tests (redline guard)"
```

### Task 0.2：删除重复方法 `_channel_name_for_handle`

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（删除 3279–3283 那一份，保留 2224–2228）

- [ ] **Step 1：确认两份逻辑相同**（2224 与 3279，函数体仅局部变量名不同，均遍历 `self._channel_lines`）。
- [ ] **Step 2：删除第二份**（行 3279–3283 整个方法定义）。保留第一份（2224）。
- [ ] **Step 3：验证**

Run: `python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_overlay_grid_ticks.py -q`
Expected: 全绿（行为不变，第二份本就被第一份…实为被自身覆盖的死代码）。

- [ ] **Step 4：提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py
git commit -m "refactor(pg): remove duplicate _channel_name_for_handle definition"
```

### Task 0.3：建包骨架

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/__init__.py`

- [ ] **Step 1：建空包**

```python
"""pg_canvas: decomposed parts of the TimeDomainCanvasPG god class.

During Phase 0–3 this package holds the pure helper modules and the
collaborator objects; TimeDomainCanvasPG itself still lives in the legacy
mf4_analyzer/ui/pg_canvases.py and imports from here. Phase 4 moves the
class in and turns pg_canvases.py into a thin re-export shim.
"""
```

- [ ] **Step 2：验证可导入**

Run: `python -c "import mf4_analyzer.ui.pg_canvas"`
Expected: 无输出、退出码 0。

- [ ] **Step 3：提交**

```bash
git add mf4_analyzer/ui/pg_canvas/__init__.py
git commit -m "refactor(pg): scaffold pg_canvas package"
```

### Task 0.4：抽 `ticks_math.py`（最纯、最小）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/ticks_math.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`（删除这 6 个函数定义，改为从包导入并 re-export）

搬迁函数（逐字搬，含 `import math`/numpy 等所需 import）：`_snap_y_to_divisions`(1123)、`_nice_per_div`(1134)、`_adjacent_nice_step`(1155)、`_fmt_tick`(1175)、`_frame_to_nice`(1191)、`_quantize_range_key`(1232)。

- [ ] **Step 1：建新模块**，文件头放最小 import（这些是纯数学，通常只需 `import math`、可能 `import numpy as np`；按搬来的函数体实际引用补齐），文件尾加：

```python
__all__ = [
    "_snap_y_to_divisions", "_nice_per_div", "_adjacent_nice_step",
    "_fmt_tick", "_frame_to_nice", "_quantize_range_key",
]
```

- [ ] **Step 2：在 `pg_canvases.py` 删除这 6 个函数定义**，在原 import 区附近加：

```python
from mf4_analyzer.ui.pg_canvas.ticks_math import (  # noqa: F401  (re-export for tests)
    _snap_y_to_divisions, _nice_per_div, _adjacent_nice_step,
    _fmt_tick, _frame_to_nice, _quantize_range_key,
)
```

- [ ] **Step 3：验证 re-export 与行为**

Run: `python -c "from mf4_analyzer.ui.pg_canvases import _fmt_tick, _frame_to_nice, _nice_per_div; print('ok')"`
Run: `python -m pytest tests/ui/test_overlay_grid_ticks.py tests/ui/test_pg_timedomain_canvas.py -q`
Expected: `ok`；测试全绿（`test_overlay_grid_ticks.py:14` 直接 import 这三个，`test:5951` import `_snap_y_to_divisions`）。

- [ ] **Step 4：提交**

```bash
git add mf4_analyzer/ui/pg_canvas/ticks_math.py mf4_analyzer/ui/pg_canvases.py
git commit -m "refactor(pg): extract ticks_math helpers to pg_canvas.ticks_math"
```

### Task 0.5：抽 `fonts.py`

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/fonts.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

搬迁：`_pg_chart_font`(318)、`_apply_pg_axis_font`(356)、`_apply_pg_text_item_font`(372)。这些引用 PyQt5 字体类（`QFont` 等）与可能的模块级字体常量——把它们用到的常量一并带过去或从 pg_canvases 导入。

- [ ] **Step 1：建 `fonts.py`**，搬 3 个函数 + 所需 import；`__all__ = ["_pg_chart_font", "_apply_pg_axis_font", "_apply_pg_text_item_font"]`。
- [ ] **Step 2：`pg_canvases.py`** 删定义、加 `from ...pg_canvas.fonts import (_pg_chart_font, _apply_pg_axis_font, _apply_pg_text_item_font)  # noqa: F401`。
- [ ] **Step 3：验证**

Run: `python -c "from mf4_analyzer.ui.pg_canvases import _pg_chart_font; print('ok')"`
Run: `python -m pytest tests/ui/test_pg_timedomain_canvas.py -q`
Expected: `ok`；全绿（`test:1454/4547/4563` import `_pg_chart_font`）。

- [ ] **Step 4：提交**

```bash
git add mf4_analyzer/ui/pg_canvas/fonts.py mf4_analyzer/ui/pg_canvases.py
git commit -m "refactor(pg): extract font helpers to pg_canvas.fonts"
```

### Task 0.6：抽 `context_menu.py`（最大一坨纯函数）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

搬迁 13 个函数：`_clean_menu_text`(458)、`_apply_context_widget_i18n`(462)、`_style_pg_context_menu`(498)、`_localize_pg_context_actions`(523)、`_localize_pg_context_menu`(545)、`_find_top_level_action`(567)、`_route_view_all_action`(577)、`_build_grid_submenu`(596)、`_add_mouse_mode_toggle_row`(696)、`_add_y_autofit_action`(807)、`_reorder_top_level_actions`(832)、`redesign_pg_context_menu`(874)、`_strip_redundant_separators`(942)。

- [ ] **Step 1：建模块**，搬 13 个函数 + 所需 import（PyQt5 `QMenu`/`QAction`/`QWidgetAction` 等、qtawesome、以及它们引用的字体 helper —— 若引用 `_pg_chart_font` 等，从 `.fonts` 导入；若引用 i18n/翻译工具，按原引用补 import）。`__all__` 列全 13 个。
- [ ] **Step 2：`pg_canvases.py`** 删 13 个定义、加 re-export import（`redesign_pg_context_menu` 是 `TimeDomainCanvasPG._redesign_context_menu_for_viewbox` 与 `_ModifierWheelViewBox` 调用的，必须可见）。
- [ ] **Step 3：验证**（菜单逻辑被 dialogs/chart_stack 测试间接覆盖）

Run: `python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_dialogs.py tests/ui/test_chart_stack.py -q`
Expected: 全绿。

- [ ] **Step 4：提交**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py mf4_analyzer/ui/pg_canvases.py
git commit -m "refactor(pg): extract context-menu helpers to pg_canvas.context_menu"
```

### Task 0.7：抽 `viewbox.py`（`_ModifierWheelViewBox`）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/viewbox.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

`_ModifierWheelViewBox`(975) 依赖 `_localize_pg_context_menu`（现在在 `.context_menu`）。

- [ ] **Step 1：建模块**，搬整个类 + import：`import pyqtgraph as pg`、PyQt5 事件类、`from .context_menu import _localize_pg_context_menu`。`__all__ = ["_ModifierWheelViewBox"]`。
- [ ] **Step 2：`pg_canvases.py`** 删类定义、加 `from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox  # noqa: F401`。
- [ ] **Step 3：验证**

Run: `python -c "from mf4_analyzer.ui.pg_canvases import _ModifierWheelViewBox; print('ok')"`
Run: `python -m pytest tests/ui/test_pg_timedomain_canvas.py -q`
Expected: `ok`；全绿（`test:2818` import `_ModifierWheelViewBox`）。

- [ ] **Step 4：提交**

```bash
git add mf4_analyzer/ui/pg_canvas/viewbox.py mf4_analyzer/ui/pg_canvases.py
git commit -m "refactor(pg): extract _ModifierWheelViewBox to pg_canvas.viewbox"
```

### Task 0.8：Phase 0 收尾门禁

- [ ] **Step 1：默认全量套**

Run: `python -m pytest -q`
Expected: 全绿（含 `tests/test_packaging_imports.py`——它断言 `mf4_analyzer.ui.pg_canvases` 可导入）。

- [ ] **Step 2：perf 门禁**

Run: `python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py -q`
Expected: 通过。

- [ ] **Step 3：确认行数下降**

Run: `wc -l mf4_analyzer/ui/pg_canvases.py`
Expected: 比 5771 少约 1350 行（落到 ~4400）。

> Phase 0 完成判据：~1350 行纯代码出门、重复方法清除、特征化测试就位、全测+perf 绿、行为零变更。

---

## Phase 1 —— 抽独立协作对象（低–中风险，逐个）

> squad: `pyqt-ui-engineer`（主）+ `refactor-architect`（模块边界）。每个任务套用 **Recipe R**。

### Task 1.1：CursorController（簇 F + T）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/cursor.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Test（现有，应保持绿）：`tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_dialogs.py`

**M（搬这些方法）**：
`set_cursor_visible`、`set_dual_cursor_mode`、`reset_cursor_state`、`draw_idle`、`draw`、`_hide_cursor_items`、`_ensure_cursor_items`、`_remove_cursor_items`、`_set_cursor_items_pos`、`_ensure_dual_cursor_extreme_markers`、`_hide_dual_cursor_extreme_markers`、`_update_dual_cursor_extreme_markers`、`_cursor_data_x_from_viewport_pos`、`_handle_cursor_mouse_move`、`_handle_cursor_mouse_press`、`_scene_y_from_viewport_pos`、`_select_overlay_channel_from_scene_pos`、`_map_view_points_to_scene`、`_emit_single_cursor_html`、`_emit_dual_cursor_html`、`_cursor_x_to_pixmap_x`。

**E（必须留薄壳的被测/公共成员）**：上面**全部**（mechanical 起见全部留壳）。重点确保：`_handle_cursor_mouse_move`(test:5577)、`_map_view_points_to_scene`(test:2540)、`_emit_single_cursor_html`(test_dialogs:220)、`_cursor_x_to_pixmap_x`(perf)、`draw`/`draw_idle`/`set_cursor_visible`/`set_dual_cursor_mode`/`reset_cursor_state`。

**信号注意**：`_emit_single_cursor_html`/`_emit_dual_cursor_html` 内对 `self.cursor_info`/`self.dual_cursor_info`/`self.dual_cursor_rows` 的 `.emit(...)` → 改为 `self._c.cursor_info.emit(...)` 等（信号留在 canvas）。

- [ ] **Step 1（R1）**：确认覆盖——光标交互/HTML 由 `test_pg_timedomain_canvas.py`（5575–5577 等）、`test_dialogs.py`（220）覆盖。
- [ ] **Step 2（R2）**：建 `cursor.py`：

```python
class CursorController:
    """Single/dual cursor, extreme markers, hit-testing, cursor HTML emit.
    State (e.g. _cursor_*_items, _dual, _last_t, _placing) stays on the
    owner canvas during Phase 1; this object holds only a back-reference.
    """
    def __init__(self, canvas):
        self._c = canvas
    # ... 21 个方法逐字搬入，self.<canvas-attr> → self._c.<attr>；
    #     同对象内互调保持 self.<method>()
```

- [ ] **Step 3（R3）**：`TimeDomainCanvasPG.__init__` 加 `self._cursor = CursorController(self)`（放在 `_glw`/`axes_list` 等核心字段已就绪之后）。
- [ ] **Step 4（R4）**：canvas 里 21 个方法改成委托薄壳，例如：

```python
def _handle_cursor_mouse_move(self, event_or_pos):
    return self._cursor._handle_cursor_mouse_move(event_or_pos)

def set_cursor_visible(self, v):
    return self._cursor.set_cursor_visible(v)
```

- [ ] **Step 5（R5）**：验证

Run: `python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_dialogs.py -q`
然后 `python -m pytest -q` 与 perf。
Expected: 全绿。

- [ ] **Step 6（R6）**：提交 `refactor(pg): extract CursorController (clusters F+T)`。

### Task 1.2：AnnotationManager（簇 H）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/annotations.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Test：`tests/ui/test_pg_timedomain_canvas.py`（585/605/628/650/746/760…）

**M**：`set_remark_enabled`、`_clear_annotation_press_state`、`_remark_target_axis_handle`、`_nearest_data_point`、`_add_remark`、`_format_remark_label`、`_remark_item_at_viewport_pos`、`_annotation_drag_threshold`、`_handle_annotation_mouse_press`、`_handle_annotation_mouse_move`、`_handle_annotation_mouse_release`、`_update_remark_leader`、`_remove_remark_at`、`_remove_remark_by_index`、`clear_remarks`。另把模块级 helper `_annotation_pen_cursor`(134) 一并搬入 `annotations.py`（仅这里用）。

**E（留薄壳）**：全部；重点 `_add_remark`、`_nearest_data_point`、`clear_remarks`、`set_remark_enabled`。

- [ ] **Step 1–4**：套用 Recipe R（建 `class AnnotationManager: __init__(self, canvas)`；状态 `_remarks`/`_annotation_enabled`/`_annotation_press_pos`/`_annotation_press_dragged` **留在 canvas**，方法内改 `self._c._remarks` 等；canvas 加 `self._annotations = AnnotationManager(self)` + 15 个委托薄壳）。
- [ ] **Step 5**：`python -m pytest tests/ui/test_pg_timedomain_canvas.py -q` → `python -m pytest -q` → perf，全绿。
- [ ] **Step 6**：提交 `refactor(pg): extract AnnotationManager (cluster H)`。

### Task 1.3：TickDensityController（簇 K）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/tick_density.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Test：`tests/ui/test_overlay_grid_ticks.py`（578 via mock）、`tests/ui/test_pg_timedomain_canvas.py`

**M**：`set_tick_density`、`_apply_tick_density_to_all_axes`、`_apply_target_x_ticks_to_all_axes`、`_x_tick_axis_handles`、`_apply_target_x_ticks`、`_reset_x_ticks_to_adaptive`、`_compute_target_x_ticks`、`_nice_x_tick_steps`、`_x_tick_values_for_step`、`_format_x_tick_labels`、`_fit_x_tick_labels`、`_apply_axis_tick_density`。其中数学计算可调用 Phase 0 的 `from .ticks_math import _fmt_tick, _frame_to_nice, ...`。

**E（留薄壳）**：全部；重点 `set_tick_density`、`_apply_tick_density_to_all_axes`。

- [ ] **Step 1–4**：套用 Recipe R（`class TickDensityController: __init__(self, canvas)`；canvas 加 `self._tick_density = TickDensityController(self)` + 12 个薄壳）。
- [ ] **Step 5**：`python -m pytest tests/ui/test_overlay_grid_ticks.py tests/ui/test_pg_timedomain_canvas.py -q` → 全量 → perf，全绿。
- [ ] **Step 6**：提交 `refactor(pg): extract TickDensityController (cluster K)`。

> Phase 1 完成判据：cursor/annotations/tick_density 三文件就位，各自被对应测试覆盖；薄壳保旧测试全绿；全测+perf 绿。

---

## Phase 2 —— 抽 overlay 子系统（中风险）

> squad: `pyqt-ui-engineer` + `refactor-architect`。簇 C/D/R/N 较大，拆成两个任务、同一个 `overlay_axes.py` 文件内两个类，降低单步认知负荷。重点护栏：`tests/ui/test_overlay_grid_ticks.py`。

### Task 2.1：OverlayAxisManager —— 轴绑定/标签/几何（簇 C）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`（新增 `class OverlayAxisManager`）
- Modify: `mf4_analyzer/ui/pg_canvases.py`

**M**：`_bind_channel`、`_overlay_axis_label`、`_overlay_axis_label_max_chars`、`_overlay_axis_label_available_height`、`_refresh_overlay_axis_labels`、`_apply_pg_axis_style`、`_sync_pg_channel_color`、`_configure_overlay_axis_geometry`、`_initial_bind_pixel_width`、`_configure_subplot_bottom_axis`。
（`_channel_name_for_handle` **留在 canvas**：它是跨 cursor/annotation/overlay 的 `_channel_lines` 查找，作为协调器共享方法。）

**E（留薄壳）**：全部；重点 `_refresh_overlay_axis_labels`(overlay test:592 via mock)。

- [ ] Step 1–4：Recipe R（`class OverlayAxisManager: __init__(self, canvas)`；canvas 加 `self._overlay_axes = OverlayAxisManager(self)` + 薄壳）。
- [ ] Step 5：`python -m pytest tests/ui/test_overlay_grid_ticks.py tests/ui/test_pg_timedomain_canvas.py -q` → 全量 → perf，全绿。
- [ ] Step 6：提交 `refactor(pg): extract OverlayAxisManager bind/label/geometry (cluster C)`。

### Task 2.2：OverlayInteractionController —— 网格/吸附/强调/视图同步（簇 D/R/N）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`（新增 `class OverlayInteractionController`）
- Modify: `mf4_analyzer/ui/pg_canvases.py`

**M**：
- D：`_build_overlay_y_grid`、`_repin_overlay_channel_ticks`、`_snap_overlay_channel_to_grid`、`_stop_snap_anim`、`_animate_overlay_snap`、`_apply_overlay_box_zoom_y`、`_teardown_overlay_aux_viewboxes`
- R：`select_overlay_channel`、`_overlay_emphasis_for_channel`、`_apply_overlay_emphasis`、`_apply_pdi_emphasis`、`_begin_overlay_y_drag_at`、`_apply_overlay_y_drag_at`、`_selected_overlay_axes`
- N：`_sync_overlay_aux_viewboxes`、`_connect_overlay_view_sync`、`_disconnect_overlay_view_sync`

**E（留薄壳）**：全部；重点（test_overlay_grid_ticks 直接调）`_repin_overlay_channel_ticks`(142)、`_apply_overlay_box_zoom_y`(348)、`_snap_overlay_channel_to_grid`(2275 in canvas-test)、`_begin_overlay_y_drag_at`/`_apply_overlay_y_drag_at`(440–458)、`_sync_overlay_aux_viewboxes`/`_disconnect_overlay_view_sync`(579/621 via mock)、`select_overlay_channel`、`_overlay_emphasis_for_channel`(2219)。

**时序注意**：`_connect_overlay_view_sync`/`_disconnect_overlay_view_sync` 操作 pyqtgraph 信号连接，搬动后确保连接的 slot 仍指向"经薄壳的同一可调用"或直接指向控制器方法；`_animate_overlay_snap` 持 `QPropertyAnimation`，其 target/owner 的 Qt 生命周期不要改（动画对象仍由 canvas 持有 `_snap_anim`，控制器经 `self._c._snap_anim` 访问）。

- [ ] Step 1–4：Recipe R。
- [ ] Step 5：`python -m pytest tests/ui/test_overlay_grid_ticks.py -q`（这是主护栏，务必全绿）→ 全量 → perf。
- [ ] Step 6：提交 `refactor(pg): extract OverlayInteractionController (clusters D/R/N)`。

> Phase 2 完成判据：overlay 绑定/网格/吸附/强调/视图同步全部进 `overlay_axes.py` 两个类；`test_overlay_grid_ticks.py` 全绿；全测+perf 绿。

---

## Phase 3 —— 质量 + 渲染/导出（最高风险 · 红线 · 门控）

> **前置门控**：Task 0.1 的 5 个特征化测试必须已就位且稳定绿，否则不得开始本 Phase。
> squad: `pyqt-ui-engineer`（grab/Qt）+ `signal-processing-expert`（painter-path parity、envelope 接缝）。
> **红线纪律**：不改 AA/cache 预算语义、不上 OpenGL、painter-path 数值输出逐点不变。

### Task 3.1：QualityManager（簇 W）

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/quality.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Test：`tests/ui/test_pg_timedomain_canvas.py`（5349/5362/5499/5522/5620/5671/5809…，30+ 处）

**M**：`_collect_curve_items`、`_set_curves_antialias`、`_set_curves_cache_mode`、`disable_interactive_quality`、`schedule_idle_quality`、`try_enable_idle_quality`、`_idle_quality_allowed`、`_idle_aa_density_ok`、`_export_aa_affordable`、`_curves_antialiased`（contextmanager）。

**E（留薄壳）**：全部；重点 `_set_curves_antialias`、`_curves_antialiased`、`_export_aa_affordable`、`disable_interactive_quality`、`schedule_idle_quality`、`try_enable_idle_quality`、`_idle_aa_density_ok`（这些被测试直接调，且 `_curves_antialiased` 被 renderer 的 `grab_pixmap` 用）。

**注意**：`_curves_antialiased` 是 `@contextmanager`，搬入后仍用 `@contextmanager` 装饰；canvas 薄壳要保持上下文管理器语义：

```python
def _curves_antialiased(self):
    return self._quality._curves_antialiased()   # 返回 contextmanager 对象, with 可用
```

状态 `_idle_aa_on`/`_idle_aa_timer`/`_idle_aa_density_seeded`/`_idle_aa_density_allowed` **留在 canvas**（被测试直接读，且 `_idle_aa_timer` 的 `timeout` 连到 `try_enable_idle_quality` —— 连接改为指向 `self._quality.try_enable_idle_quality` 或经 canvas 薄壳，二选一且保持单次触发 150ms 配置不变）。

- [ ] Step 1–4：Recipe R。特别校验 `_idle_aa_timer.timeout` 的 connect 目标在搬迁后仍有效（test:5497/5505 验 timer 配置）。
- [ ] Step 5：`python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "aa or antialias or idle or quality or export" -q` → 该文件全量 → 默认全量 → perf。全绿。
- [ ] Step 6：提交 `refactor(pg): extract QualityManager (cluster W)`。

### Task 3.2：Renderer / Exporter（簇 Q/X）—— 含 monkeypatch 接缝处理

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Modify（接缝）：`tests/ui/test_pg_timedomain_canvas.py`（重指向 2 处 monkeypatch）
- Test 护栏：`tests/ui/test_pg_export_characterization.py`（Task 0.1）、现有 grab/path 测试、perf。

**M**：
- Q：`_current_pixel_width`、`_refresh_visible_data`、`_build_painter_path`、`_build_painter_path_loop`、`_render_path_to_pixmap`
- X：`grab_pixmap`、`_grab_widget_scaled`（`@staticmethod`，搬迁后保持 staticmethod）。把模块级 helper `_capped_hidpi_scale`(435) 与常量 `_HIDPI_MAX_WIDTH`/`_HIDPI_COPY_SCALE` 一并搬入 `renderer.py`（导出用），并在 `pg_canvases.py` re-export 这两个常量（test:4242 import `_HIDPI_MAX_WIDTH`）。

**E（留薄壳）**：全部；重点 `grab_pixmap`(公共)、`_refresh_visible_data`、`_build_painter_path`/`_build_painter_path_loop`(test:1196/T9 parity)、`_render_path_to_pixmap`(test:1201)、`_current_pixel_width`。`_flush_pending_refresh`(4447, 簇 P) **留在 canvas**（被 10+ 测试调），其内部对 `_refresh_visible_data` 的调用走薄壳。

**⚠️ monkeypatch 接缝（必处理，否则测试假绿/真断）**：
现状 `_refresh_visible_data` 调用模块级 `positions_envelope(...)` 与 `build_envelope(...)`，测试用 `monkeypatch.setattr(pg_canvases, "positions_envelope", _spy)`（test:1132–1135）、`monkeypatch.setattr(pg_canvases, "build_envelope", _spy)`（test:4581–4595）打桩。方法搬进 `renderer.py` 后，桩打在 `pg_canvases` 模块上将**不再影响** renderer 内的调用。处理：

1. `renderer.py` 顶部：`from mf4_analyzer.signal._envelope_cutils import positions_envelope` 和 `from mf4_analyzer.ui.canvases import build_envelope`（与原 pg_canvases 同源）。
2. `_refresh_visible_data` 内对这两者的调用，改为**模块级可打桩**形式：调用 `renderer.positions_envelope(...)`/`renderer.build_envelope(...)`（即引用本模块全局，便于 setattr）。
3. 更新这 2 处测试的 monkeypatch 目标到 renderer 模块：
   - test:1132 `from mf4_analyzer.ui import pg_canvases` → 增加/改为 `from mf4_analyzer.ui.pg_canvas import renderer`；`monkeypatch.setattr(renderer, "positions_envelope", _spy)`。
   - test:4581 同理把 `pg_canvases.build_envelope` 的桩改到 `renderer.build_envelope`。
   - 同时 `pg_canvases.py` 仍 `from ...renderer import positions_envelope, build_envelope  # noqa` 保留 re-export（满足"约定"里的可见性要求；但桩点以 renderer 为准）。

- [ ] **Step 1**：建 `renderer.py`，搬 Q/X 方法 + `_capped_hidpi_scale` + 常量 + envelope import；`grab_pixmap` 内对 `self._curves_antialiased()`/`self._export_aa_affordable()` 的调用 → `self._c._curves_antialiased()`/`self._c._export_aa_affordable()`（走 Phase 3.1 的 QualityManager 薄壳）。
- [ ] **Step 2**：`pg_canvases.py` 删定义、装配 `self._renderer = Renderer(self)`、加薄壳、re-export 常量与 envelope 名。
- [ ] **Step 3**：处理 monkeypatch 接缝（上面 3 小步），改 2 处测试。
- [ ] **Step 4**：先跑红线护栏

Run: `python -m pytest tests/ui/test_pg_export_characterization.py -q`
Expected: 5 passed（导出仍非全白、每曲线可见）。

- [ ] **Step 5**：跑 path parity / refresh / grab 现有测试 + envelope 桩测试

Run: `python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "path or refresh or grab or pixmap or envelope" -q`
Expected: 全绿（含 `test_refresh_visible_data_does_not_build_unused_path_or_pixmap`、T9 parity、envelope spy 桩生效）。

- [ ] **Step 6**：默认全量 + perf

Run: `python -m pytest -q` 然后 `python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py -q`
Expected: 全绿（perf 不回归）。

- [ ] **Step 7**：提交 `refactor(pg): extract Renderer/Exporter (clusters Q/X) + repoint envelope monkeypatch seam`。

> Phase 3 完成判据：质量与渲染/导出进 `quality.py`/`renderer.py`；特征化测试 + path parity + 现有 AA/grab + perf 全绿；AA/cache 语义与 painter-path 数值零变更；envelope 桩接缝已重指向。

---

## Phase 4 —— 收尾（可选，按 Phase 0–3 收益评估再决定）

> squad: `refactor-architect`。

### Task 4.1：类迁入 `pg_canvas/canvas.py`，`pg_canvases.py` 退化为 shim

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Rewrite: `mf4_analyzer/ui/pg_canvases.py` → 薄 shim

- [ ] **Step 1**：把（已大幅瘦身的）`TimeDomainCanvasPG` 类整体移入 `pg_canvas/canvas.py`，连同它现在 import 的协作对象/纯模块 import。
- [ ] **Step 2**：`pg_canvases.py` 改为兼容 shim：

```python
"""Legacy import path. Canonical home is mf4_analyzer.ui.pg_canvas."""
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG  # noqa: F401
from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox  # noqa: F401
from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font, _apply_pg_axis_font, _apply_pg_text_item_font  # noqa: F401
from mf4_analyzer.ui.pg_canvas.ticks_math import (  # noqa: F401
    _snap_y_to_divisions, _nice_per_div, _adjacent_nice_step, _fmt_tick, _frame_to_nice, _quantize_range_key,
)
from mf4_analyzer.ui.pg_canvas.renderer import (  # noqa: F401
    positions_envelope, build_envelope, _capped_hidpi_scale, _HIDPI_MAX_WIDTH, _HIDPI_COPY_SCALE,
)
```

- [ ] **Step 3**：`python -m pytest -q` + perf，全绿（`test_packaging_imports.py` 仍要求 `mf4_analyzer.ui.pg_canvases` 可导入——shim 满足）。
- [ ] **Step 4**：提交 `refactor(pg): move TimeDomainCanvasPG into pg_canvas.canvas; pg_canvases.py becomes shim`。

### Task 4.2（可选）：状态迁移 + 撤薄壳 + 迁测试

- [ ] 把单簇私有/2–3 簇共享的状态（如 `_remarks`→annotations、`_idle_aa_*`→quality）逐个迁入对应协作对象；把测试里 `canvas._remarks` 改成 `canvas._annotations.remarks` 等公开访问；删除对应委托薄壳。每迁一个对象、跑一次全量 + perf、提交一次。
- [ ] 完成判据：协调器 ≤ ~50 方法、薄壳清单收敛；公共 API（3 信号 + `full_reset`）零变更。

---

## 自检（Spec 覆盖核对）

- spec §4.1 包结构 → Task 0.3–0.7、1.1–1.3、2.1–2.2、3.1–3.2、4.1 全部建出。
- spec §4.2 协作对象与状态归属 → 各 Phase 任务的 M/E 列表逐一对应；"状态留 canvas、行为搬出"由 Recipe R 落实。
- spec §5 分期与 strangler-fig → Phase 0–4 + 委托薄壳。
- spec §6 五个特征化测试 → Task 0.1 全部写出真代码。
- spec §2.5 重复方法 → Task 0.2。
- spec §2.4 红线 + monkeypatch 接缝 → Phase 3 门控 + Task 3.2 接缝步骤。
- spec §2.3 契约冻结 → "约定"段（3 信号 + full_reset + re-export 清单）。
- 非目标（不改行为/不上 OpenGL/不改 AA 语义）→ Phase 3 红线纪律 + 每 Phase perf 门禁。

类型/命名一致性：协作对象属性名固定为 `self._cursor`/`self._annotations`/`self._tick_density`/`self._overlay_axes`/`self._overlay_interaction`/`self._quality`/`self._renderer`；信号名 `cursor_info`/`dual_cursor_info`/`dual_cursor_rows` 全程不变。

---

## 执行交接

Plan 完成并保存于 `docs/superpowers/plans/2026-06-07-pg-canvas-decomposition.md`。两种执行方式：

1. **Subagent-Driven（推荐）** —— 每个任务派新 subagent、任务间双段 review、迭代快。本仓库可对接 squad：Phase 0/4 → `refactor-architect`，Phase 1–2 → `pyqt-ui-engineer`，Phase 3 → `pyqt-ui-engineer` + `signal-processing-expert`。
2. **Inline Execution** —— 本会话内按 Phase 批量执行、检查点 review。

建议从 **Phase 0** 起步（极低风险、立竿见影），跑通再决定后续节奏。
