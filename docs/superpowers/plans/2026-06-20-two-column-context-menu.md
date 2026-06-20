# 图表右键菜单两列一级编辑优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 pyqtgraph 图表右键菜单改成左侧可操作、右侧弱说明的两列一级编辑面板，并让 X/Y 范围、查看、网格、鼠标模式都在第一层完成。

**Architecture:** 在 `mf4_analyzer/ui/pg_canvas/context_menu.py` 新增一个 reusable inline panel widget，替代旧的 mouse row + 顶层 actions + X/Y 原生 submenu + 网格 submenu 拼接。底层行为继续复用现有 handler、toolbar controller、ViewBox、`show_major_grid_left_bottom_only`，不新增状态存储。

**Tech Stack:** Python 3.12 / PyQt5 / pyqtgraph / pytest + pytest-qt；HTML prototype for visual review.

---

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-06-20-two-column-context-menu-design.md`。
- 不显示固定 `Y 自动`；X/Y 范围行都显示当前 ViewBox 数值范围。
- 所有程序化范围设置必须使用 `padding=0`。
- 鼠标模式必须继续走 toolbar controller；优先 `set_mouse_mode_broadcast(mode)`。
- 网格必须继续走 `show_major_grid_left_bottom_only(..., alpha=0.28)`，禁止点亮 top/right grid。
- 不改数值算法、不改 inspector、不改 chart toolbar。
- 当前工作树可能有无关脏项；只 stage 本计划明确列出的文件。

## File Map

- Modify: `docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html`
  - 把 mockup 更新为两列菜单布局。
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
  - 新增 inline panel widget、range/grid/mouse/view 行构建逻辑。
  - 修改 `redesign_pg_context_menu(...)` 的顶层菜单重排策略。
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
  - 更新 time-domain 菜单结构测试和 range/grid 行为测试。
- Modify: `tests/ui/test_pg_line_canvas.py`
  - 更新 FFT line 菜单结构测试。
- Modify: `tests/ui/test_pg_heatmap_canvas.py`
  - 更新 heatmap 菜单结构测试。

---

### Task 1: 更新 HTML 原型为两列左操作右说明

**Files:**
- Modify: `docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html`

- [ ] **Step 1: 改 CSS 布局 token**

把旧的 `.tool-row` / `.menu-item` / `.range-row` / `.grid-row` 思路替换为统一 row：

```css
.panel-row {
  min-height: 32px;
  display: grid;
  grid-template-columns: 204px 48px;
  align-items: center;
  column-gap: 11px;
  margin-top: 6px;
}

.panel-row:first-child { margin-top: 0; }

.control-group {
  min-width: 0;
  display: grid;
  grid-template-columns: 88px 28px 88px;
  align-items: center;
  justify-items: center;
}

.row-label {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 650;
  text-align: left;
  letter-spacing: 0;
}

.text-btn {
  height: 30px;
  width: 88px;
  padding: 0 10px;
  border: 1px solid #d6e0ec;
  border-radius: 8px;
  background: #fff;
  color: #334155;
  font-size: 14px;
  font-weight: 750;
}

.text-btn.primary,
.chip.active,
.icon-btn.active {
  border-color: var(--blue-strong);
  background: var(--blue-soft);
  color: var(--blue-strong);
}

.chip {
  width: 56px;
  height: 30px;
}

.range-input {
  width: 88px;
  height: 30px;
  border: 1px solid #d6e0ec;
  border-radius: var(--radius-control);
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  color: #111827;
  font-size: 15px;
  font-weight: 650;
  text-align: center;
}
```

- [ ] **Step 2: 改 HTML 结构**

把菜单主体改成：

```html
<section class="menu" aria-label="图表右键菜单原型">
  <div class="panel-row">
    <div class="control-group">
      <div class="icon-btn" title="框选">⌕</div>
      <div></div>
      <div class="icon-btn active" title="平移">✣</div>
    </div>
    <div class="row-label">鼠标</div>
  </div>

  <div class="panel-row">
    <div class="control-group">
      <button class="text-btn" type="button">Y适应</button>
      <div></div>
      <button class="text-btn" type="button">全图</button>
    </div>
    <div class="row-label">查看</div>
  </div>

  <div class="panel-row">
    <div class="control-group">
      <div class="range-input">0.0</div>
      <div class="dash">—</div>
      <div class="range-input">1.0</div>
    </div>
    <div class="row-label">X范围</div>
  </div>

  <div class="panel-row">
    <div class="control-group">
      <div class="range-input">-1.0</div>
      <div class="dash">—</div>
      <div class="range-input">1.0</div>
    </div>
    <div class="row-label">Y范围</div>
  </div>

  <div class="panel-row">
    <div class="control-group">
      <button class="chip active" type="button" aria-pressed="true">X</button>
      <div></div>
      <button class="chip active" type="button" aria-pressed="true">Y</button>
    </div>
    <div class="row-label">网格</div>
  </div>
</section>
```

- [ ] **Step 3: 手动打开 HTML 检查**

Open:

```bash
open docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html
```

Expected: 左侧是控件列，右侧弱标签；不再出现固定 `自动` 的 Y 范围。

---

### Task 2: 在 context_menu.py 新增两列 inline panel 基础组件

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: 写失败测试：inline panel 替代旧顶层项**

在 `tests/ui/test_pg_timedomain_canvas.py` 的 context menu 测试类中新增：

```python
def test_context_menu_uses_two_column_inline_panel(self, qapp, monkeypatch):
    from PyQt5.QtWidgets import QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box

    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)

    panel_actions = [
        action for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    ]
    assert len(panel_actions) == 1

    top = _top_level_texts(menu)
    for removed in ("Y 轴自适应", "查看全部", "X 轴范围", "Y 轴范围", "网格"):
        assert removed not in top
```

- [ ] **Step 2: Run failing test**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_context_menu_uses_two_column_inline_panel -q
```

Expected: FAIL because `pgContextInlinePanel` does not exist.

- [ ] **Step 3: 新增基础 widget class**

在 `context_menu.py` imports 中加入：

```python
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtWidgets import QGridLayout
```

新增常量和 helper：

```python
_INLINE_LABEL_COLOR = "#94a3b8"
_INLINE_CONTROL_TEXT = "#334155"
_INLINE_BLUE = "#2563eb"


def _format_range_value(value: float) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    if abs(value) >= 1000 or (0 < abs(value) < 0.01):
        return f"{value:.3g}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _view_range(view_box, axis: str) -> tuple[float, float]:
    ranges = view_box.viewRange()
    idx = 1 if axis == "y" else 0
    lo, hi = ranges[idx]
    return float(lo), float(hi)
```

新增 `_PgContextInlinePanel(QWidget)` skeleton：

```python
class _PgContextInlinePanel(QWidget):
    def __init__(
        self,
        menu,
        plot_item,
        controller,
        *,
        view_all_handler=None,
        y_autofit_handler=None,
        allow_y_grid=True,
    ):
        super().__init__(menu)
        self.setObjectName("pgContextInlinePanel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._menu = menu
        self._plot_item = plot_item
        self._view_box = plot_item.getViewBox() if plot_item is not None else None
        self._controller = controller
        self._view_all_handler = view_all_handler
        self._y_autofit_handler = y_autofit_handler
        self._allow_y_grid = bool(allow_y_grid)
        self._range_edits = {}

        layout = QGridLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setHorizontalSpacing(11)
        layout.setVerticalSpacing(6)
        layout.setColumnMinimumWidth(0, 204)
        layout.setColumnMinimumWidth(1, 48)

        row = 0
        if controller is not None:
            self._add_mouse_row(layout, row)
            row += 1
        self._add_view_row(layout, row)
        row += 1
        if self._view_box is not None:
            self._add_range_row(layout, row, "x", "X范围")
            row += 1
            self._add_range_row(layout, row, "y", "Y范围")
            row += 1
        if plot_item is not None:
            self._add_grid_row(layout, row)
```

- [ ] **Step 4: 新增 panel action factory**

```python
def _add_inline_context_panel(
    menu,
    plot_item,
    controller,
    *,
    view_all_handler=None,
    y_autofit_handler=None,
    allow_y_grid=True,
):
    panel = _PgContextInlinePanel(
        menu,
        plot_item,
        controller,
        view_all_handler=view_all_handler,
        y_autofit_handler=y_autofit_handler,
        allow_y_grid=allow_y_grid,
    )
    action = QWidgetAction(menu)
    action.setDefaultWidget(panel)
    menu.addAction(action)
    return action
```

- [ ] **Step 5: 临时接入 redesign_pg_context_menu**

在 `redesign_pg_context_menu(...)` 中，先在清理旧 action 后调用 `_add_inline_context_panel(...)`，并暂时不要删旧 `_add_mouse_mode_toggle_row` / `_add_y_autofit_action` 函数本身：

```python
    inline_action = _add_inline_context_panel(
        menu,
        plot_item,
        controller,
        view_all_handler=view_all_handler,
        y_autofit_handler=y_autofit_handler,
        allow_y_grid=allow_y_grid,
    )
```

同时移除旧的：

```python
toggle_row = _add_mouse_mode_toggle_row(...)
_add_y_autofit_action(...)
menu.addMenu(grid_menu)
_reorder_top_level_actions(...)
```

改为把 `inline_action` 放在第一位，其他保留项（例如 `keep_plot_options=True`）跟在后面。

- [ ] **Step 6: Run test**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_context_menu_uses_two_column_inline_panel -q
```

Expected: PASS.

---

### Task 3: 实现鼠标 row 和查看 row

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`, `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试：行标签和按钮文案**

Add to `tests/ui/test_pg_timedomain_canvas.py`:

```python
def test_inline_panel_labels_and_view_buttons(self, qapp, monkeypatch):
    from PyQt5.QtWidgets import QLabel, QToolButton, QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box

    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert labels[:5] == ["鼠标", "查看", "X范围", "Y范围", "网格"]

    buttons = {btn.text(): btn for btn in panel.findChildren(QToolButton)}
    assert "Y适应" in buttons
    assert "全图" in buttons
```

- [ ] **Step 2: Implement row helpers**

Add methods to `_PgContextInlinePanel`:

```python
    def _make_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("pgContextInlineLabel")
        label.setStyleSheet(
            f"color: {_INLINE_LABEL_COLOR}; font-size: 12px; font-weight: 600;"
            " background: transparent;"
        )
        return label

    def _add_row(self, layout, row: int, controls: QWidget, label_text: str) -> None:
        layout.addWidget(controls, row, 0)
        layout.addWidget(self._make_label(label_text), row, 1)

    def _control_host(self, object_name: str) -> QWidget:
        host = QWidget(self)
        host.setObjectName(object_name)
        host.setAttribute(Qt.WA_TranslucentBackground, True)
        host.setAutoFillBackground(False)
        lay = QGridLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(0)
        lay.setVerticalSpacing(0)
        lay.setColumnMinimumWidth(0, 88)
        lay.setColumnMinimumWidth(1, 28)
        lay.setColumnMinimumWidth(2, 88)
        return host

    def _place_control(self, host: QWidget, widget: QWidget, column: int) -> None:
        host.layout().addWidget(widget, 0, column, alignment=Qt.AlignCenter)

    def _make_tool_button(self, text: str, object_name: str) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName(object_name)
        btn.setText(text)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(88, 30)
        btn.setStyleSheet(
            "QToolButton { border: 1px solid #d6e0ec; border-radius: 8px;"
            " background: #ffffff; color: #334155; padding: 0 10px;"
            " font-size: 13px; font-weight: 700; }"
            "QToolButton:hover { border-color: #0b7af3; background: #f3f7ff; }"
            "QToolButton:checked { border-color: #2563eb; background: #e8efff;"
            " color: #2563eb; }"
            "QToolButton:disabled { color: #b8c2d0; border-color: #e5eaf2;"
            " background: #f8fafc; }"
        )
        return btn
```

- [ ] **Step 3: Implement mouse row**

```python
    def _add_mouse_row(self, layout, row: int) -> None:
        host = self._control_host("pgContextMouseRow")

        btn_zoom = self._make_tool_button("", "pgContextZoomButton")
        btn_pan = self._make_tool_button("", "pgContextPanButton")
        for btn, mode in ((btn_zoom, _PG_MOUSE_MODE_ZOOM), (btn_pan, _PG_MOUSE_MODE_PAN)):
            label, _tip = _PG_MOUSE_MODE_LABELS[mode]
            btn.setToolTip(label)
            btn.setIcon(qta.icon(
                _PG_MOUSE_MODE_ICONS[mode],
                color=_PG_ICON_COLOR,
                color_on=_PG_ICON_ACTIVE,
            ))
            btn.setIconSize(QSize(18, 18))
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setCheckable(True)
            btn.setFixedSize(32, 30)

        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(btn_zoom)
        group.addButton(btn_pan)

        try:
            current = self._controller.current_mouse_mode()
        except Exception:
            current = None
        _sync_mouse_mode_toggle_buttons([btn_zoom, btn_pan], current)

        btn_zoom.clicked.connect(lambda _checked=False: self._set_mouse_mode(_PG_MOUSE_MODE_ZOOM))
        btn_pan.clicked.connect(lambda _checked=False: self._set_mouse_mode(_PG_MOUSE_MODE_PAN))
        self._place_control(host, btn_zoom, 0)
        self._place_control(host, btn_pan, 2)
        self._add_row(layout, row, host, "鼠标")

    def _set_mouse_mode(self, mode: str) -> None:
        try:
            setter = getattr(self._controller, "set_mouse_mode_broadcast", None)
            if callable(setter):
                setter(mode)
            elif mode == _PG_MOUSE_MODE_ZOOM:
                self._controller.set_zoom_mode()
            else:
                self._controller.set_pan_mode()
        except Exception:
            pass
        try:
            self._menu.close()
        except Exception:
            pass
```

- [ ] **Step 4: Implement view row**

```python
    def _add_view_row(self, layout, row: int) -> None:
        host = self._control_host("pgContextViewRow")
        y_btn = self._make_tool_button("Y适应", "pgContextYAutofitButton")
        all_btn = self._make_tool_button("全图", "pgContextViewAllButton")
        y_btn.setEnabled(callable(self._y_autofit_handler))
        all_btn.setEnabled(callable(self._view_all_handler))
        y_btn.clicked.connect(lambda _checked=False: self._invoke_handler(self._y_autofit_handler))
        all_btn.clicked.connect(lambda _checked=False: self._invoke_handler(self._view_all_handler))
        self._place_control(host, y_btn, 0)
        self._place_control(host, all_btn, 2)
        self._add_row(layout, row, host, "查看")

    def _invoke_handler(self, handler) -> None:
        if callable(handler):
            try:
                handler()
            except Exception:
                pass
        try:
            self._menu.close()
        except Exception:
            pass
```

- [ ] **Step 5: Run tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_inline_panel_labels_and_view_buttons tests/ui/test_pg_line_canvas.py -k "menu_pan_button_calls_broadcast or idle_mode_leaves or pan_mode_checks or zoom_mode_checks" -q
```

Expected: PASS.

---

### Task 4: 实现 X/Y 范围行

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: 写失败测试：范围显示当前数值，不显示自动**

```python
def test_inline_range_rows_show_current_view_ranges(self, qapp, monkeypatch):
    from PyQt5.QtWidgets import QLineEdit, QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box
    vb.setXRange(0.25, 0.75, padding=0)
    vb.setYRange(-2.0, 3.0, padding=0)

    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )

    edits = {edit.objectName(): edit.text() for edit in panel.findChildren(QLineEdit)}
    assert edits["pgContextXMinEdit"] == "0.25"
    assert edits["pgContextXMaxEdit"] == "0.75"
    assert edits["pgContextYMinEdit"] == "-2"
    assert edits["pgContextYMaxEdit"] == "3"
    assert "自动" not in set(edits.values())
```

- [ ] **Step 2: 写失败测试：合法范围应用，非法范围恢复**

```python
def test_inline_range_edits_apply_valid_and_reject_invalid(self, qapp, monkeypatch):
    from PyQt5.QtWidgets import QLineEdit, QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box
    vb.setXRange(0.0, 1.0, padding=0)

    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )
    x_min = panel.findChild(QLineEdit, "pgContextXMinEdit")
    x_max = panel.findChild(QLineEdit, "pgContextXMaxEdit")

    x_min.setText("0.2")
    x_max.setText("0.8")
    x_max.returnPressed.emit()
    assert vb.viewRange()[0] == pytest.approx([0.2, 0.8])

    x_min.setText("9")
    x_max.setText("1")
    x_max.returnPressed.emit()
    assert vb.viewRange()[0] == pytest.approx([0.2, 0.8])
    assert x_min.text() == "0.2"
    assert x_max.text() == "0.8"
```

- [ ] **Step 3: Implement line edit helpers**

```python
    def _make_range_edit(self, object_name: str, value: float) -> QLineEdit:
        edit = QLineEdit(_format_range_value(value), self)
        edit.setObjectName(object_name)
        edit.setFixedSize(88, 30)
        edit.setAlignment(Qt.AlignCenter)
        edit.setValidator(QDoubleValidator(edit))
        edit.setStyleSheet(
            "QLineEdit { border: 1px solid #d6e0ec; border-radius: 7px;"
            " background: #ffffff; color: #111827; padding: 0 8px;"
            " font-size: 14px; font-weight: 650; }"
            "QLineEdit:focus { border-color: #2563eb; }"
        )
        return edit

    def _add_range_row(self, layout, row: int, axis: str, label_text: str) -> None:
        host = self._control_host(f"pgContext{axis.upper()}RangeRow")
        lo, hi = _view_range(self._view_box, axis)
        min_edit = self._make_range_edit(f"pgContext{axis.upper()}MinEdit", lo)
        max_edit = self._make_range_edit(f"pgContext{axis.upper()}MaxEdit", hi)
        self._range_edits[axis] = (min_edit, max_edit)
        dash = QLabel("—", self)
        dash.setObjectName(f"pgContext{axis.upper()}RangeDash")
        dash.setAlignment(Qt.AlignCenter)
        dash.setStyleSheet("color: #64748b; font-size: 16px; font-weight: 700; background: transparent;")
        for edit in (min_edit, max_edit):
            edit.returnPressed.connect(lambda axis=axis: self._apply_range(axis))
        self._place_control(host, min_edit, 0)
        self._place_control(host, dash, 1)
        self._place_control(host, max_edit, 2)
        self._add_row(layout, row, host, label_text)

    def _apply_range(self, axis: str) -> None:
        if self._view_box is None:
            return
        min_edit, max_edit = self._range_edits[axis]
        try:
            lo = float(min_edit.text())
            hi = float(max_edit.text())
        except ValueError:
            self._restore_range_text(axis)
            return
        if hi <= lo:
            self._restore_range_text(axis)
            return
        try:
            if axis == "x":
                self._view_box.setXRange(lo, hi, padding=0)
            else:
                self._view_box.setYRange(lo, hi, padding=0)
        except Exception:
            self._restore_range_text(axis)
            return
        self._restore_range_text(axis)

    def _restore_range_text(self, axis: str) -> None:
        if self._view_box is None or axis not in self._range_edits:
            return
        lo, hi = _view_range(self._view_box, axis)
        min_edit, max_edit = self._range_edits[axis]
        min_edit.setText(_format_range_value(lo))
        max_edit.setText(_format_range_value(hi))
```

- [ ] **Step 4: Run tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_inline_range_rows_show_current_view_ranges tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_inline_range_edits_apply_valid_and_reject_invalid -q
```

Expected: PASS.

---

### Task 5: 实现一级网格 chip

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: 写失败测试：无网格 submenu，chip 可切换**

```python
def test_inline_grid_chips_toggle_x_y_without_submenu(self, qapp, monkeypatch):
    from PyQt5.QtWidgets import QToolButton, QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box
    pi = canvas.axes_list[0].plot_item

    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    assert not any(
        a.text().replace("&", "").strip() == "网格" and a.menu() is not None
        for a in menu.actions()
    )
    panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )
    chips = {
        btn.text(): btn for btn in panel.findChildren(QToolButton)
        if btn.objectName().startswith("pgContextGrid")
    }
    assert set(chips) == {"X", "Y"}

    chips["X"].click()
    assert not pi.getAxis("bottom").grid
    assert pi.getAxis("top").grid is False
    assert pi.getAxis("right").grid is False
```

- [ ] **Step 2: 写失败测试：overlay 禁用 Y chip**

```python
def test_inline_grid_y_chip_disabled_when_y_grid_not_allowed(self, qapp, monkeypatch):
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtWidgets import QToolButton, QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
    QCoreApplication.processEvents()

    menu = _assemble_and_redesign_menu(qapp, canvas, canvas._x_master_handle.view_box, monkeypatch)
    panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )
    y_chip = next(
        btn for btn in panel.findChildren(QToolButton)
        if btn.objectName() == "pgContextGridYChip"
    )
    assert y_chip.text() == "Y"
    assert not y_chip.isEnabled()
    assert not y_chip.isChecked()
```

- [ ] **Step 3: Implement grid row**

```python
    def _grid_enabled(self, side: str) -> bool:
        try:
            axis = self._plot_item.getAxis(side)
            return bool(getattr(axis, "grid", False))
        except Exception:
            return False

    def _add_grid_row(self, layout, row: int) -> None:
        host = self._control_host("pgContextGridRow")
        x_chip = self._make_tool_button("X", "pgContextGridXChip")
        y_chip = self._make_tool_button("Y", "pgContextGridYChip")
        for chip in (x_chip, y_chip):
            chip.setCheckable(True)
            chip.setFixedSize(42, 30)
        x_chip.setChecked(self._grid_enabled("bottom"))
        y_chip.setChecked(
            self._allow_y_grid and (
                self._grid_enabled("left") or self._grid_enabled("right")
            )
        )
        y_chip.setEnabled(self._allow_y_grid)
        x_chip.clicked.connect(lambda checked=False: self._apply_grid_from_chips(x_chip, y_chip))
        y_chip.clicked.connect(lambda checked=False: self._apply_grid_from_chips(x_chip, y_chip))
        self._place_control(host, x_chip, 0)
        self._place_control(host, y_chip, 2)
        self._add_row(layout, row, host, "网格")

    def _apply_grid_from_chips(self, x_chip, y_chip) -> None:
        if self._plot_item is None:
            return
        show_major_grid_left_bottom_only(
            self._plot_item,
            x=x_chip.isChecked(),
            y=y_chip.isChecked() if self._allow_y_grid else False,
            alpha=0.28,
        )
```

- [ ] **Step 4: Run tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_inline_grid_chips_toggle_x_y_without_submenu tests/ui/test_pg_timedomain_canvas.py::TestContextMenuRedesign::test_inline_grid_y_chip_disabled_when_y_grid_not_allowed -q
```

Expected: PASS.

---

### Task 6: 更新 FFT line / heatmap 菜单测试

**Files:**
- Modify: `tests/ui/test_pg_line_canvas.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Update line canvas context menu test**

Replace assertions in `test_fft_context_menu_is_chinese_and_hides_plot_options`:

```python
from PyQt5.QtWidgets import QToolButton, QWidgetAction

panel = next(
    action.defaultWidget()
    for action in menu.actions()
    if isinstance(action, QWidgetAction)
    and action.defaultWidget() is not None
    and action.defaultWidget().objectName() == "pgContextInlinePanel"
)
assert "绘图选项" not in _menu_texts(menu)
buttons = {btn.objectName(): btn for btn in panel.findChildren(QToolButton)}
assert buttons["pgContextZoomButton"].toolTip() == "框选"
assert buttons["pgContextPanButton"].toolTip() == "平移"
buttons["pgContextZoomButton"].click()
assert controller.mode == "zoom"
```

Also update `test_fft_context_menu_includes_y_autofit` to assert `pgContextYAutofitButton` exists with text `Y适应` instead of looking for a top-level action.

- [ ] **Step 2: Update heatmap context menu test**

Replace old top-level assertions in `test_heatmap_context_menu_is_chinese_and_hides_plot_options` with the same `pgContextInlinePanel` checks as the line canvas test.

- [ ] **Step 3: Run focused tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "context_menu or menu_pan_button or idle_mode or pan_mode_checks or zoom_mode_checks" -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -k "context_menu" -q
```

Expected: PASS, except unrelated pre-existing `_time_divisions` failures if running the whole file.

---

### Task 7: Preserve shell, tooltip, and shadow contracts

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py` only if tests fail

- [ ] **Step 1: Update translucent/no-shadow tests**

Because grid no longer uses a submenu, update `test_promoted_submenus_have_translucent_background` to assert the top-level menu and inline panel are translucent:

```python
def test_inline_context_panel_has_transparent_shell(self, qapp, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QWidgetAction

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box

    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )
    assert panel.testAttribute(Qt.WA_TranslucentBackground)
```

Keep `test_context_menus_disable_native_drop_shadow` focused on the top-level menu plus any real remaining submenus from `keep_plot_options=True`.

- [ ] **Step 2: Update tooltip test**

`test_tooltips_visible_is_false_and_actions_have_no_tooltip` should still iterate actions, but also assert inline buttons have short tooltips only:

```python
for button in panel.findChildren(QToolButton):
    assert len(button.toolTip()) <= 4 or button.toolTip() in ("框选", "平移")
```

- [ ] **Step 3: Run shell tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "inline_context_panel_has_transparent_shell or native_drop_shadow or tooltips_visible" -q
```

Expected: PASS.

---

### Task 8: Final verification

**Files:**
- No new modifications expected.

- [ ] **Step 1: Run context-menu focused suite**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py -k "context_menu or inline or grid_menu or view_all" \
  tests/ui/test_pg_line_canvas.py -k "context_menu or menu_pan_button or idle_mode or pan_mode_checks or zoom_mode_checks" \
  tests/ui/test_pg_heatmap_canvas.py -k "context_menu" \
  -q
```

Expected: PASS. If `grid_menu` tests are intentionally retired, remove or rename them in the same commit after replacing their coverage with inline chip tests.

- [ ] **Step 2: Run diff check for touched files**

```bash
git diff --check -- \
  docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html \
  mf4_analyzer/ui/pg_canvas/context_menu.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py
```

Expected: no output.

- [ ] **Step 3: Live UI check**

Open TraceLab and right-click each section:

- TimeDomain subplot/overlay
- FFT line
- FFT-vs-Time heatmap
- Order heatmap

Check:

- Left column controls are nearest the cursor.
- Right column labels are weak and short.
- X/Y range rows show numeric ranges, not fixed `自动`.
- Y适应 and 全图 behave as before.
- Grid X/Y chips behave as before.
- Rounded transparent shell has no square backing.

- [ ] **Step 4: Commit**

```bash
git add \
  docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html \
  mf4_analyzer/ui/pg_canvas/context_menu.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py
git commit -m "refactor(menu): inline chart context controls"
```
