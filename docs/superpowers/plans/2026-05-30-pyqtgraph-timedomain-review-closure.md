# Pyqtgraph TimeDomain Review Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining pyqtgraph TimeDomain interaction gaps after Claude's recent UI polish pass.

**Architecture:** Keep the current `TimeDomainCanvasPG` + `PgAxisHandle` adapter structure. Route context-menu actions through canvas-owned handlers, add an overlay-aware grid policy to the adapter, and make PG ChartOptions color sync call back into the owning canvas.

**Tech Stack:** Python, PyQt5, pyqtgraph, pytest with offscreen Qt.

---

## File Map

- Modify: `mf4_analyzer/ui/pg_canvases.py`
  - context-menu View All reroute
  - overlay-aware grid submenu
  - PG channel color sync helper
  - cursor hover throttling
  - subplot first-frame X-grid geometry alignment
- Modify: `mf4_analyzer/ui/_axis_handle.py`
  - `PgAxisHandle(owner_canvas=..., allow_y_grid=...)`
  - dynamic grid read/write policy
  - owner callback from `sync_line_axis_color`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
  - context-menu View All regression
  - overlay grid menu regression
  - cursor throttle regression
  - subplot X-grid first-frame alignment regression
- Modify: `tests/ui/test_dialogs.py`
  - ChartOptions overlay grid regression
  - ChartOptions PG color-source regression
- Modify: `tests/ui/test_axis_handle.py`
  - adapter-level grid policy regression

## Task 1: Context Menu View All And Overlay Grid Tests

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Add failing tests**

Add tests under `TestTimeDomainCanvasPGContextMenuRedesign`:

```python
    def test_overlay_grid_menu_x_toggle_does_not_enable_y_grid(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()

        pi = canvas._x_master_handle.plot_item
        vb = canvas._x_master_handle.view_box
        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        grid_menu = next(
            a.menu() for a in menu.actions()
            if a.text().replace("&", "").strip() == "网格"
        )
        act_x, act_y = grid_menu.actions()

        assert act_x.isChecked()
        assert not act_y.isChecked()
        assert not act_y.isEnabled()

        act_x.trigger()
        QCoreApplication.processEvents()

        assert not pi.getAxis("bottom").grid
        assert not pi.getAxis("left").grid
        assert not pi.getAxis("right").grid
        for ax_item in canvas._overlay_aux_axes:
            assert not ax_item.grid

    def test_context_menu_view_all_resets_overlay_raw_x_and_per_channel_y(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        rows = _five_channel_rows()[:2]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        left = canvas.axes_list[0]
        right = canvas.axes_list[1]
        left.set_xlim(0.2, 0.4)
        left.set_ylim(-1.0, 1.0)
        right.set_ylim(45.0, 55.0)
        QCoreApplication.processEvents()

        menu = _assemble_and_redesign_menu(
            qapp, canvas, canvas._x_master_handle.view_box, monkeypatch
        )
        view_all = next(
            a for a in menu.actions()
            if a.text().replace("&", "").strip() == "查看全部"
        )
        view_all.trigger()
        QCoreApplication.processEvents()

        t0 = rows[0][2]
        sig0 = rows[0][3]
        sig1 = rows[1][3]
        assert left.get_xlim() == pytest.approx((float(t0.min()), float(t0.max())), abs=1e-6)
        assert left.get_ylim() == pytest.approx((float(sig0.min()), float(sig0.max())), rel=0.08)
        assert right.get_ylim() == pytest.approx((float(sig1.min()), float(sig1.max())), rel=0.08)
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGContextMenuRedesign::test_overlay_grid_menu_x_toggle_does_not_enable_y_grid \
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGContextMenuRedesign::test_context_menu_view_all_resets_overlay_raw_x_and_per_channel_y -q
```

Expected: both fail on current HEAD. The grid test sees Y grid enabled; the View All test sees overlay Y ranges remain zoomed.

## Task 2: Implement Context Menu Routing And Grid Policy

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: Route View All**

Add helper:

```python
def _route_view_all_action(menu, handler):
    action = _find_top_level_action(menu, "查看全部", "View All")
    if action is None or handler is None:
        return
    try:
        action.triggered.disconnect()
    except (TypeError, RuntimeError):
        pass

    def _trigger(_checked=False):
        try:
            handler()
        except Exception:
            pass

    action.triggered.connect(_trigger)
```

Update `redesign_pg_context_menu` signature:

```python
def redesign_pg_context_menu(
    menu, plot_item, controller, *, view_all_handler=None, allow_y_grid=True
):
```

Call `_route_view_all_action(menu, view_all_handler)` immediately after localization.

- [ ] **Step 2: Make grid submenu overlay-aware**

Update `_build_grid_submenu` signature:

```python
def _build_grid_submenu(menu, plot_item, *, allow_y_grid=True):
```

Initialize state from current AxisItem grid values:

```python
def _axis_grid_enabled(side):
    try:
        axis = plot_item.getAxis(side)
        return bool(getattr(axis, "grid", False))
    except Exception:
        return False

state = {
    "x": _axis_grid_enabled("bottom"),
    "y": _axis_grid_enabled("left") or _axis_grid_enabled("right"),
}
if not allow_y_grid:
    state["y"] = False
```

Set `act_y.setEnabled(False)` when `allow_y_grid` is false, and make `_apply_grid()` pass `y=False` in that mode.

- [ ] **Step 3: Pass policy from canvas**

Update `_redesign_context_menu_for_viewbox`:

```python
allow_y_grid = not self._overlay_mode
redesign_pg_context_menu(
    menu,
    plot_item,
    self._mouse_mode_controller,
    view_all_handler=self.reset_view_to_data_extents,
    allow_y_grid=allow_y_grid,
)
```

- [ ] **Step 4: Verify Task 1 tests pass**

Run the same command from Task 1. Expected: `2 passed`.

## Task 3: ChartOptions Overlay Grid Tests And Implementation

**Files:**
- Modify: `tests/ui/test_dialogs.py`
- Modify: `tests/ui/test_axis_handle.py`
- Modify: `mf4_analyzer/ui/_axis_handle.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: Add failing tests**

In `tests/ui/test_dialogs.py` add:

```python
def test_pg_chart_options_overlay_apply_preserves_x_only_grid(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(900, 480)
    canvas.show()
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, 50.0 + np.cos(t), "#ef4444", "Nm"),
    ], mode="overlay")
    QCoreApplication.processEvents()

    pi = canvas._x_master_handle.plot_item
    dlg = ChartOptionsDialog(None, canvas.axes_list[0])
    assert dlg.chk_grid.isChecked()
    dlg.apply_changes()
    QCoreApplication.processEvents()

    assert bool(pi.getAxis("bottom").grid)
    assert not pi.getAxis("left").grid
    assert not pi.getAxis("right").grid
```

In `tests/ui/test_axis_handle.py` add an adapter-level test:

```python
def test_pg_axis_handle_grid_can_disallow_y_grid(qapp):
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    plot = pg.PlotItem()
    handle = PgAxisHandle(plot_item=plot, allow_y_grid=False)

    handle.grid(True)

    assert bool(plot.getAxis("bottom").grid)
    assert not plot.getAxis("left").grid
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_dialogs.py::test_pg_chart_options_overlay_apply_preserves_x_only_grid \
  tests/ui/test_axis_handle.py::test_pg_axis_handle_grid_can_disallow_y_grid -q
```

Expected: first test fails with Y grid enabled; second fails because constructor has no `allow_y_grid`.

- [ ] **Step 3: Implement adapter policy**

Update `PgAxisHandle.__init__`:

```python
def __init__(
    self,
    plot_item=None,
    *,
    view_box=None,
    axis_item=None,
    owner_canvas=None,
    allow_y_grid=True,
):
    self._owner_canvas = owner_canvas
    self._allow_y_grid = bool(allow_y_grid)
```

Update `grid()`:

```python
self._grid_enabled = bool(enabled)
pi.showGrid(
    x=self._grid_enabled,
    y=self._grid_enabled if self._allow_y_grid else False,
)
```

Update `is_grid_enabled()`:

```python
try:
    bottom = self._ax("bottom")
    if bottom is not None:
        return bool(getattr(bottom, "grid", False))
except Exception:
    pass
return bool(self._grid_enabled)
```

Update PG canvas constructors:

```python
PgAxisHandle(plot_item=pi, owner_canvas=self)
PgAxisHandle(plot_item=pi, owner_canvas=self, allow_y_grid=False)
PgAxisHandle(
    plot_item=primary_plot,
    view_box=aux_vb,
    axis_item=axis_item,
    owner_canvas=self,
    allow_y_grid=False,
)
```

- [ ] **Step 4: Verify Task 3 tests pass**

Run the Task 3 command. Expected: `2 passed`.

## Task 4: PG ChartOptions Color Sync

**Files:**
- Modify: `tests/ui/test_dialogs.py`
- Modify: `mf4_analyzer/ui/_axis_handle.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: Add failing test**

Extend the existing `test_pg_chart_options_curve_color_syncs_owning_axis_color`:

```python
    seen = []
    canvas.cursor_info.connect(seen.append)
    canvas._emit_single_cursor_html(0.5)

    assert canvas.channel_data["speed"][2].lower() == "#123456"
    assert "#123456" in seen[-1]
    assert "#1769e0" not in seen[-1]
```

Add an inside-label regression:

```python
def test_pg_chart_options_curve_color_updates_inside_label_badge(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 800)
    canvas.show()
    t = np.linspace(0.0, 1.0, 200)
    name = "[diya luntai] Rte_ActRetPlausi_mActiveReturnMotorTorq4C VeryLongChannelName"
    canvas.plot_channels([
        (name, True, t, np.sin(t * 12.0), "#1769e0", "Nm"),
        ("other", True, t, np.cos(t * 10.0), "#ef4444", "Nm"),
    ], mode="subplot")
    QCoreApplication.processEvents()

    assert canvas._inside_label_items
    dlg = ChartOptionsDialog(None, canvas.axes_list[0])
    dlg.edit_curve_color.setText("#123456")
    dlg.apply_changes()
    QCoreApplication.processEvents()

    assert canvas.channel_data[name][2].lower() == "#123456"
    assert canvas._inside_label_items[0].color.name().lower() == "#123456"
    assert canvas._inside_label_items[0].border.color().name().lower() == "#123456"
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_dialogs.py::test_pg_chart_options_curve_color_syncs_owning_axis_color \
  tests/ui/test_dialogs.py::test_pg_chart_options_curve_color_updates_inside_label_badge -q
```

Expected: failures on stale `channel_data` / inside label color.

- [ ] **Step 3: Implement owner color callback**

In `PgAxisHandle.sync_line_axis_color()`:

```python
owner = getattr(self, "_owner_canvas", None)
label = line.get_label() if hasattr(line, "get_label") else ""
sync = getattr(owner, "_sync_pg_channel_color", None)
if label and callable(sync):
    sync(label, color)
```

In `TimeDomainCanvasPG`:

```python
def _sync_pg_channel_color(self, channel_name, color):
    row = self.channel_data.get(channel_name)
    if row is not None:
        self.channel_data[channel_name] = (row[0], row[1], color, row[3])
    for handle, item in zip(self._inside_label_handles, self._inside_label_items):
        if self._channel_name_for_handle(handle) != channel_name:
            continue
        try:
            item.setColor(pg.mkColor(color))
            item.border = pg.mkPen(color=color, width=0.8)
            item.update()
        except Exception:
            pass
    self.draw_idle()
```

Add `_channel_name_for_handle()` by scanning `self._channel_lines`.

- [ ] **Step 4: Verify Task 4 tests pass**

Run the Task 4 command. Expected: `2 passed`.

## Task 5: Cursor Hover Throttle

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: Add failing test**

Under `TestTimeDomainCanvasPGCursorInteraction` add:

```python
    def test_single_cursor_mousemove_is_throttled_to_one_emit_per_33ms(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)

        seen = []
        canvas.cursor_info.connect(seen.append)
        point = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.5)

        for _ in range(5):
            assert canvas._handle_cursor_mouse_move(point) is True

        assert len(seen) == 1

        canvas._last_t -= 40
        assert canvas._handle_cursor_mouse_move(point) is True
        assert len(seen) == 2
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGCursorInteraction::test_single_cursor_mousemove_is_throttled_to_one_emit_per_33ms -q
```

Expected: fails because five immediate moves emit five times.

- [ ] **Step 3: Implement throttle**

Add import:

```python
import time as _time
```

In `_handle_cursor_mouse_move()` replace `self._last_t = 0` with:

```python
now = _time.monotonic() * 1000
if now - self._last_t < 33:
    return True
self._last_t = now
```

- [ ] **Step 4: Verify Task 5 test passes**

Run the Task 5 command. Expected: `1 passed`.

## Task 6: Subplot X Grid First-Frame Alignment

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: Add failing test**

Under `TestTimeDomainCanvasPGSubplotMode` add a test that builds four subplot
rows with very different Y tick text widths, calls `plot_channels(...,
mode="subplot")`, and does not process another Qt event before measuring
`ViewBox.mapViewToScene(QPointF(x, 0.0)).x()` for `x in (0.0, 0.5, 1.0)`.

Expected failure on the pre-fix code: the row with narrow tick labels maps
`x=0.0` about 22px left of the other rows, so vertical X grid lines render
misaligned on the first frame.

- [ ] **Step 2: Verify test fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode::test_subplot_x_grid_geometry_is_aligned_before_first_frame -q
```

Expected: fails with different scene-X positions across subplot rows.

- [ ] **Step 3: Implement final geometry settle**

After `plot_channels()` applies tick density, call `_unify_subplot_left_axis_widths()`
again so late AxisItem geometry changes are covered.

At the end of `_unify_subplot_left_axis_widths()`, after setting every left
AxisItem width to the measured maximum, settle the graphics layout immediately:

```python
layout = self._glw.ci.layout
layout.invalidate()
layout.activate()
```

- [ ] **Step 4: Verify Task 6 test passes**

Run the Task 6 command. Expected: `1 passed`.

## Task 7: Full Regression

**Files:**
- No new files.

- [ ] **Step 1: Run target UI regression**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_dialogs.py \
  tests/ui/test_axis_handle.py \
  tests/ui/test_chart_stack.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lessons completion gate**

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

Expected: `lesson_required: False`, unless implementation exposed a durable new workflow failure.

## Self-Review

- Spec coverage: Tasks 1-6 cover spec sections A-F.
- Placeholder scan: no placeholder tokens or unspecified edge-case steps.
- Type consistency: `allow_y_grid`, `_sync_pg_channel_color`, `_channel_name_for_handle`, `view_all_handler`, and `_unify_subplot_left_axis_widths` names are consistent across tasks.
