# 标注小修 + 多通道性能 + 工具栏激活底色 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修标注画笔缩放手柄基准 + 清死代码；让多通道时域「复制图片」和「双游标悬停」不再卡；让 nav 工具栏激活按钮显示底色（不只染图标）。

**Architecture:** 三块互不依赖的子系统改动——A 在 `markup/editor.py`，B 在 `pg_canvases.py`，C 在 `chart_stack.py` + `ui_kit/style.qss`。codex 可按 A→B→C 或任意顺序执行，每组各自带离屏单测与真机验证。

**Tech Stack:** PyQt5 `QGraphicsItem` 变换 / `QPainterPathStroker`；pyqtgraph 画布抓图与 idle-AA 密度预算；matplotlib + pyqtgraph nav 工具栏 + QSS 动态属性；pytest-qt 离屏测试。

**前置阅读：** 设计 `docs/superpowers/specs/2026-05-31-polish-perf-toolbar-design.md`。

**测试命令：**

```bash
# A
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
# B
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
# C
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q
```

---

## Files

- Modify: `mf4_analyzer/ui/markup/editor.py`（A）
- Modify: `mf4_analyzer/ui/pg_canvases.py`（B）
- Modify: `mf4_analyzer/ui/chart_stack.py`、`mf4_analyzer/ui_kit/style.qss`（C）
- Test: `tests/ui/test_markup_editor.py`（A）、`tests/ui/test_pg_timedomain_canvas.py`（B）、`tests/ui/test_chart_stack.py`（C）

---

## 组 A — 标注编辑器小修

### Task A1: 画笔路径缩放手柄改为锚定 bbox 左上角

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`add_path_item` `:581-585`、`_drag_scale_handle` 非 group 分支 `:1320-1329`）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_markup_editor.py` 末尾：

```python
def test_pen_path_scale_handle_anchors_top_left(qtbot):
    from PyQt5.QtGui import QPainterPath
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    path = QPainterPath(QPointF(40, 30))
    path.lineTo(80, 60)
    item = editor.add_path_item(path)
    item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    handle = next(h for h in editor._handles if getattr(h, "_role", "") == "scale")

    before = item.mapToScene(item.boundingRect().topLeft())
    editor.drag_handle(handle, item.mapToScene(QPointF(160, 120)))
    after = item.mapToScene(item.boundingRect().topLeft())

    assert item.scale() > 1.0
    assert abs(after.x() - before.x()) < 1.0   # 左上角缩放时不漂移
    assert abs(after.y() - before.y()) < 1.0
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "anchors_top_left"
```

预期：失败——当前以场景原点 (0,0) 为基准缩放，path 左上角会随缩放漂移。

- [ ] **Step 3: 实现 — `add_path_item` 固定变换原点为 bbox 左上角**

替换 `add_path_item`（`editor.py:581-585`）：

```python
    def add_path_item(self, path: QPainterPath) -> QGraphicsPathItem:
        item = QGraphicsPathItem(path)
        item.setPen(self._pen())
        item.setTransformOriginPoint(item.boundingRect().topLeft())
        self._add_markup_item(item)
        return item
```

- [ ] **Step 4: 实现 — `_drag_scale_handle` 非 group 分支以左上角为基准**

替换 `_drag_scale_handle` 里 group 分支之后的非 group 部分（`editor.py:1320-1329`，即 `origin = item.mapToScene(QPointF(0, 0))` 到方法结尾）：

```python
        top_left = rect.topLeft()
        local = item.mapFromScene(point)
        width = rect.width()
        height = rect.height()
        candidates = []
        if width > 0.001:
            candidates.append((local.x() - top_left.x()) / width)
        if height > 0.001:
            candidates.append((local.y() - top_left.y()) / height)
        if not candidates:
            return
        item.setScale(max(max(candidates), 0.25))
```

> 文字 item 的 bbox 左上角本就是 (0,0)，故此分支对文字行为不变；画笔 path 现在锚定自身左上角，跟手缩放。group 仍走上方中心缩放分支，不动。

- [ ] **Step 5: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：新测试通过；`test_selected_text_has_resize_handle_that_scales_text` 等既有缩放测试仍绿。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "fix(markup): anchor pen-path scale handle to its bbox top-left so it tracks the cursor"
```

### Task A2: 删除死代码

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`_arrow_head(self, rect)` `:1628-1648`、`QGraphicsPolygonItem` import `:29`）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试（锁定移除）**

```python
def test_markup_editor_has_no_dead_arrow_head_method(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    assert not hasattr(MarkupEditor, "_arrow_head")
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "no_dead_arrow_head"
```

预期：失败——`MarkupEditor._arrow_head` 仍在。

- [ ] **Step 3: 实现 — 删方法 + 删未用 import**

先确认 `QGraphicsPolygonItem` 无引用：

```bash
grep -n "QGraphicsPolygonItem" mf4_analyzer/ui/markup/editor.py
```

预期：仅 import 行（`:29`）。删除 `MarkupEditor._arrow_head` 整个方法（`editor.py:1628-1648`，即文件末尾 `def _arrow_head(self, rect: QRectF) -> QPolygonF:` 到结尾），并从 `from PyQt5.QtWidgets import (...)` 删去 `QGraphicsPolygonItem`（`:29`）。`QPolygonF`（QtGui）仍被箭头 item 使用，**保留**。

- [ ] **Step 4: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：全绿（含新锁定测试）。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "chore(markup): drop dead MarkupEditor._arrow_head and unused QGraphicsPolygonItem import"
```

---

## 组 B — 多通道性能

### Task B1: 复制图片按密度自适应（AA/2× 仅在划算时强开）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（新增 `_export_aa_affordable`；改 `grab_pixmap` `:3779-3829`）
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_pg_timedomain_canvas.py` 中**含 `test_grab_pixmap_*` 的同一个测试类内**（沿用 `_pg_canvas`、`_five_channel_rows` helper；类方法签名带 `self, qapp`）：

```python
    def test_export_aa_affordable_true_when_density_small(self, qapp, monkeypatch):
        canvas = _pg_canvas(qapp)
        canvas._overlay_mode = True

        class _FakeCurve:
            def __init__(self, n):
                self._n = n
            def getData(self):
                return (np.zeros(self._n), np.zeros(self._n))
            def getViewBox(self):
                return None

        monkeypatch.setattr(canvas, "_collect_curve_items", lambda: [_FakeCurve(10)])
        assert canvas._export_aa_affordable() is True

    def test_export_aa_affordable_false_when_overlay_over_budget(self, qapp, monkeypatch):
        canvas = _pg_canvas(qapp)
        canvas._overlay_mode = True

        class _FakeCurve:
            def __init__(self, n):
                self._n = n
            def getData(self):
                return (np.zeros(self._n), np.zeros(self._n))
            def getViewBox(self):
                return None

        over = int(canvas._AA_OVERLAY_SEGMENT_OFF) + 100
        monkeypatch.setattr(canvas, "_collect_curve_items", lambda: [_FakeCurve(over)])
        assert canvas._export_aa_affordable() is False

    def test_export_aa_affordable_does_not_mutate_idle_hysteresis(self, qapp, monkeypatch):
        canvas = _pg_canvas(qapp)
        canvas._idle_aa_density_allowed = "SENTINEL_A"
        canvas._idle_aa_density_seeded = "SENTINEL_S"
        monkeypatch.setattr(canvas, "_collect_curve_items", lambda: [])
        canvas._export_aa_affordable()
        assert canvas._idle_aa_density_allowed == "SENTINEL_A"
        assert canvas._idle_aa_density_seeded == "SENTINEL_S"

    def test_grab_pixmap_skips_forced_aa_when_not_affordable(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication
        from contextlib import contextmanager

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        monkeypatch.setattr(canvas, "_export_aa_affordable", lambda: False)

        entered = []
        orig = canvas._curves_antialiased

        @contextmanager
        def _spy():
            entered.append(1)
            with orig():
                yield

        monkeypatch.setattr(canvas, "_curves_antialiased", _spy)
        pix = canvas.grab_pixmap(scale=2.0)
        assert not pix.isNull()
        assert entered == []   # 不划算时跳过强制 AA
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "export_aa_affordable or skips_forced_aa"
```

预期：失败——`_export_aa_affordable` 不存在；`grab_pixmap` 无条件进 `_curves_antialiased`。

- [ ] **Step 3: 实现 — 新增 `_export_aa_affordable`**

在 `TimeDomainCanvasPG` 内 `_idle_aa_density_ok`（`pg_canvases.py:3666`）之后新增：

```python
    def _export_aa_affordable(self) -> bool:
        """复制/导出时是否强开抗锯齿的纯密度判定。

        复用 ``_idle_aa_density_ok`` 的 metric 口径（overlay=所有曲线点数之和；
        subplot/single=各 ViewBox 行点数和的最大值），与同一个 OFF 预算比较，
        但**不触碰** ``_idle_aa_density_allowed`` / ``_idle_aa_density_seeded``
        这套 idle-AA hysteresis 状态——只读不写，避免互相干扰。
        多通道超预算时返回 False → 复制走廉价 grab（所见即所得），不再随通道数卡。
        """
        overlay = bool(getattr(self, "_overlay_mode", False))
        off_budget = (
            self._AA_OVERLAY_SEGMENT_OFF if overlay else self._AA_SUBPLOT_SEGMENT_OFF
        )
        sums: dict = {}
        total = 0
        for it in self._collect_curve_items():
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                return False
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n
        metric = total if overlay else (max(sums.values()) if sums else 0)
        return metric <= off_budget
```

- [ ] **Step 4: 实现 — `grab_pixmap` 据此分支**

替换 `grab_pixmap` 方法体（`pg_canvases.py:3802-3829`，从 `base_w = ...` 到 `return fallback`）：

```python
        # Resolve the effective (capped) factor from the OUTER widget's
        # current width — the same surface step 1 grabs. When export AA is
        # not affordable (dense multi-channel overlay), drop to 1× too: the
        # grab matches what's on screen and stays cheap.
        base_w = max(1, int(self.width()))
        affordable = self._export_aa_affordable()
        eff_scale = _capped_hidpi_scale(base_w, scale) if affordable else 1.0

        def _grab_first_good():
            for target in (self, getattr(self, "_glw", None)):
                if target is None:
                    continue
                try:
                    pix = self._grab_widget_scaled(target, eff_scale)
                except Exception:
                    pix = None
                if pix is not None and not pix.isNull() and pix.width() > 0 and pix.height() > 0:
                    return pix
            return None

        if affordable:
            # Few-channel / under-budget: keep crisp 2× + forced AA export.
            with self._curves_antialiased():
                pix = _grab_first_good()
        else:
            # Dense overlay: what-you-see-is-what-you-get, no forced AA, no 2×.
            pix = _grab_first_good()
        if pix is not None:
            return pix
        # Final fallback: a 1×1 transparent pixmap (offscreen degenerate).
        fallback = QPixmap(1, 1)
        fallback.fill(Qt.transparent)
        return fallback
```

- [ ] **Step 5: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
```

预期：新测试通过；`test_grab_pixmap_returns_non_null_pixmap_with_geometry`、`test_grab_pixmap_restores_curve_antialias`、`test_curves_antialiased_context_enables_then_restores` 仍绿（少通道场景 affordable=True，2×+AA 路径不变）。

- [ ] **Step 6: 回归既有复制契约**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q -k "copy_card_image or hidpi"
```

预期：`test_copy_card_image_renders_at_hidpi_scale`、`test_copy_card_image_composites_scaled_cursor_pill` 仍绿（测试用少通道 → affordable=True → 仍 2×）。若有断言挂在「无条件 2×」上需复核，但少通道路径未变，应通过。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "perf(pg): copy/export grab skips forced AA + 2x when curve density exceeds the AA budget"
```

### Task B2: 双游标悬停不再重算与 hover 无关的统计

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（`_handle_cursor_mouse_move` dual 分支 `:1998-2003`）
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: 写失败测试**

加到含游标测试的同一个类内（沿用 `_pg_canvas`、`_five_channel_rows`、`_viewport_point_for_data`）：

```python
    def test_dual_cursor_hover_move_does_not_recompute_stats(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtTest import QTest

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)
        canvas.set_dual_cursor_mode(True)

        viewport = canvas._glw.viewport()
        QTest.mouseClick(
            viewport, Qt.LeftButton, Qt.NoModifier,
            _viewport_point_for_data(canvas, canvas.axes_list[0], 0.25),
        )
        QCoreApplication.processEvents()
        QTest.mouseClick(
            viewport, Qt.LeftButton, Qt.NoModifier,
            _viewport_point_for_data(canvas, canvas.axes_list[2], 0.75),
        )
        QCoreApplication.processEvents()

        # Spy AFTER A/B are placed: a pure hover move must not recompute stats.
        calls = []
        monkeypatch.setattr(canvas, "_emit_dual_cursor_html", lambda *a, **k: calls.append(1))
        canvas._last_t = 0  # defeat the 33ms throttle
        move = QMouseEvent(
            QEvent.MouseMove,
            _viewport_point_for_data(canvas, canvas.axes_list[1], 0.5),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        )
        qapp.sendEvent(viewport, move)
        QCoreApplication.processEvents()

        assert calls == []  # hover 不再触发 O(通道×采样) 统计重算
        # hover guide line 仍移动可见
        assert getattr(canvas, "_cursor_line_items", [])
        assert all(it.isVisible() for it in canvas._cursor_line_items)
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "hover_move_does_not_recompute"
```

预期：失败——当前 dual 悬停每帧都调 `_emit_dual_cursor_html`。

- [ ] **Step 3: 实现 — 移除悬停里的 dual 重算**

把 `_handle_cursor_mouse_move` 的 dual 分支（`pg_canvases.py:1998-2003`）改为只移动 hover 线、不重算统计：

```python
        if self._dual:
            hover_items = self._ensure_cursor_items(
                "_cursor_line_items", color="#64748b", width=1.0, style=Qt.DotLine
            )
            self._set_cursor_items_pos(hover_items, x)
            # NOTE: _emit_dual_cursor_html depends only on _ax/_bx (not hover x)
            # and is already emitted on A/B placement (_handle_cursor_mouse_press).
            # Recomputing it per hover frame was pure O(channels×samples) waste.
        else:
```

（即删除原 `self._emit_dual_cursor_html()` 这一行，其余 single 分支与末尾 `self.draw_idle()` 不动。）

- [ ] **Step 4: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
```

预期：新测试通过；`test_dual_cursor_mouse_clicks_place_a_b_and_emit_stats`（落点仍发统计）、`test_single_cursor_mouse_move_emits_and_shows_lines`（single 分支不变）仍绿。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "perf(pg): dual-cursor hover only moves the guide line, no per-frame stat recompute"
```

---

## 组 C — 工具栏激活态底色

### Task C1: 激活的 nav 按钮显示底色（动态属性 + QSS）

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`（`_apply_mdi_icons` `:257-265`）
- Modify: `mf4_analyzer/ui_kit/style.qss`（`QToolButton:disabled` 块之后，约 `:248`）
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_chart_stack.py`（用 `qtbot` fixture）：

```python
def test_apply_mdi_icons_sets_navactive_property_on_active_button(qtbot):
    from PyQt5.QtWidgets import QToolBar, QToolButton
    from mf4_analyzer.ui.chart_stack import _apply_mdi_icons, _MDI_NAV_ICONS

    assert "pan" in _MDI_NAV_ICONS and "zoom" in _MDI_NAV_ICONS
    toolbar = QToolBar()
    qtbot.addWidget(toolbar)
    pan = toolbar.addAction("Pan")
    pan.setData("pan")
    zoom = toolbar.addAction("Zoom")
    zoom.setData("zoom")

    _apply_mdi_icons(toolbar, active_key="pan")
    pan_btn = toolbar.widgetForAction(pan)
    zoom_btn = toolbar.widgetForAction(zoom)
    assert isinstance(pan_btn, QToolButton)
    assert pan_btn.property("navActive") is True
    assert zoom_btn.property("navActive") is False

    _apply_mdi_icons(toolbar, active_key="zoom")
    assert pan_btn.property("navActive") is False
    assert zoom_btn.property("navActive") is True
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q -k "navactive"
```

预期：失败——`_apply_mdi_icons` 不设 `navActive` 属性。

- [ ] **Step 3: 实现 — `_apply_mdi_icons` 设激活属性并重抛光**

替换 `_apply_mdi_icons`（`chart_stack.py:257-265`）：

```python
def _apply_mdi_icons(toolbar, active_key=''):
    """Replace each retained action's icon with its MDI equivalent, and flag
    the active nav button via a ``navActive`` dynamic property so the QSS can
    paint a background highlight (icon recolor alone reads as 不直观)."""
    for act in toolbar.actions():
        key = act.data() if act.data() else (act.text() or '').strip().lower()
        icon_name = _MDI_NAV_ICONS.get(key)
        if icon_name is None:
            continue
        is_active = key == active_key
        color = _ICON_ACTIVE if is_active else _ICON_COLOR
        act.setIcon(qta.icon(icon_name, color=color))
        btn = toolbar.widgetForAction(act)
        if isinstance(btn, QToolButton):
            btn.setProperty("navActive", bool(is_active))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
```

> `QToolButton` 已在 `chart_stack.py:6` import；无需新增。

- [ ] **Step 4: 实现 — QSS 增激活底色规则**

在 `mf4_analyzer/ui_kit/style.qss` 的 `QPushButton:disabled, QToolButton:disabled { ... }` 块（结束于 `:248`）之后插入：

```css
/* nav 工具栏激活态底色：pan/zoom 等模式按钮激活时蓝底蓝边，
 * 不再只靠图标变色（_apply_mdi_icons 设 navActive 动态属性驱动）。 */
#chartToolbar QToolButton[navActive="true"] {
    background-color: #e8efff;
    border: 1px solid #1769e0;
}
```

- [ ] **Step 5: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q
```

预期：新测试通过；既有 chart_stack 测试全绿。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui_kit/style.qss tests/ui/test_chart_stack.py
git commit -m "feat(ui): active nav toolbar button shows a blue background, not just a colored icon"
```

---

## 全量回归 + 真机验证（本仓库铁律：只认真机渲染/截图）

- [ ] **Step 1: 三套相关单测全绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_chart_stack.py tests/ui/test_copy_thumbnail.py -q
```

- [ ] **Step 2: 真机验证**

启动 app：
1. **A**：标注编辑器画一段画笔曲线 → 选中拖右下手柄，缩放跟手、左上角不漂；undo 还原。
2. **B 复制**：时域叠加 ≥6 通道 → 点「复制为图片」**秒回不转圈**，外部粘贴出图（与屏幕一致）；切回 1-2 通道复制仍是 2× 清晰。
3. **B 游标**：多通道双游标，移动鼠标悬停**不卡**；落 A/B 后 ΔT 与各通道 min/max/mean 读数与改前一致。
4. **C**：matplotlib 卡（FFT/阶次/FFT-vs-Time）与时域卡点 pan/zoom，激活按钮**蓝底蓝边**，切换/退出底色正确跟随。

- [ ] **Step 3: lesson gate**

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

---

## Self-Review（已自检）

- **Spec 覆盖**：A1→Task A1，A2→Task A2，B1.1→Task B1，B1.2→Task B2，C→Task C1。全覆盖。
- **类型一致**：`_export_aa_affordable` 与 `_idle_aa_density_ok` 同 metric 口径但不写 hysteresis；`grab_pixmap` 的 `affordable` 分支复用 `_grab_widget_scaled`/`_curves_antialiased`/`_capped_hidpi_scale` 既有签名；`navActive` 属性名在 `_apply_mdi_icons` 与 QSS 选择器一致。
- **占位扫描**：无 TBD；每步含完整代码 + 精确行号锚点 + 红/绿命令。
- **回归保护**：少通道复制路径（affordable=True）保持 2×+AA，既有 hidpi/cursor-pill 复制契约不破；single 游标、dual 落点统计路径不动。
