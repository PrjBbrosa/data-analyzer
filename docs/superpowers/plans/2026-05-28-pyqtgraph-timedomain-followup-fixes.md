# Pyqtgraph TimeDomain Followup Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** finish the followup pyqtgraph TimeDomain UI and interaction repairs found by `2026-05-28-pyqtgraph-timedomain-followup-verify.html`.

**Architecture:** Keep `PlotDataItem.setData()` as the visible render truth. Extend `PgAxisHandle` only where the dialog and multi-axis overlay need renderer-neutral state. Overlay multi-axis follows pyqtgraph's `MultiplePlotAxes.py` pattern: primary ViewBox plus auxiliary ViewBoxes linked on X and paired with right-side AxisItems.

**Tech Stack:** Python, PyQt5, pyqtgraph 0.14, pytest/pytest-qt, existing `mf4_analyzer.ui` modules.

---

## Files And Ownership

- Main session owns:
  - `mf4_analyzer/ui/pg_canvases.py`
  - `tests/ui/test_pg_timedomain_canvas.py`
  - `tests/perf/test_timedomain_pan_perf.py`
- Worker A owns:
  - `mf4_analyzer/ui/_axis_handle.py`
  - `mf4_analyzer/ui/dialogs.py`
  - `tests/ui/test_axis_handle.py`
  - `tests/ui/test_dialogs.py`
- Worker B owns:
  - `mf4_analyzer/ui/chart_stack.py`
  - `tests/ui/test_chart_stack.py`
- Main session integrates and runs final verification.

Workers must not revert or rewrite files outside their ownership. The worktree
already contains prior uncommitted pyqtgraph UI-gap fixes; build on them.

## Task 1: Inside Label Anchoring And Title Dedupe

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [x] **Step 1: Write RED label anchoring test**

Add this test near `TestTimeDomainCanvasPGSubplotMode`:

```python
def test_subplot_inside_label_stays_viewport_anchored_after_pan_zoom(self, qapp):
    from PyQt5.QtCore import QCoreApplication

    canvas = _pg_canvas(qapp)
    canvas.resize(1200, 800)
    rows = _five_channel_rows()[:3]
    long_rows = [
        (f"[diya luntai] {name} VeryLongChannelNameForInsideBadge", vis, t, sig, color, unit, data_id)
        for name, vis, t, sig, color, unit, data_id in rows
    ]
    canvas.plot_channels(long_rows, mode="subplot")
    QCoreApplication.processEvents()

    item = canvas._inside_label_items[0]
    vb = canvas.axes_list[0].view_box
    before = item.sceneBoundingRect().topLeft() - vb.sceneBoundingRect().topLeft()

    canvas.axes_list[0].set_xlim(0.25, 0.75)
    canvas.axes_list[0].set_ylim(-0.25, 0.25)
    canvas._flush_pending_refresh()
    QCoreApplication.processEvents()

    after = item.sceneBoundingRect().topLeft() - vb.sceneBoundingRect().topLeft()
    assert abs(after.x() - before.x()) <= 2.0
    assert abs(after.y() - before.y()) <= 2.0
```

- [x] **Step 2: Write RED title dedupe test**

Add:

```python
def test_inside_label_hides_when_custom_title_is_set(self, qapp):
    from PyQt5.QtCore import QCoreApplication

    canvas = _pg_canvas(qapp)
    canvas.resize(1200, 800)
    canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
    QCoreApplication.processEvents()
    assert canvas._inside_label_items

    handle = canvas.axes_list[0]
    handle.set_title("Custom subplot title")
    canvas._recheck_subplot_label_placement()
    QCoreApplication.processEvents()

    assert "Custom subplot title" in handle.get_title()
    assert not canvas._inside_label_items[0].isVisible()
```

- [x] **Step 3: Run RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode -q
```

Expected: the new label anchor/title tests fail while pre-existing tests pass.

- [x] **Step 4: Implement label positioning**

In `TimeDomainCanvasPG`, store inside-label specs as `(handle, item)` pairs and
add helpers with these semantics:

```python
def _position_inside_label_item(self, handle, item):
    vb = handle.view_box
    if vb is None:
        return
    x_range, y_range = vb.viewRange()
    item.setPos(float(x_range[0]), float(y_range[1]))

def _position_inside_label_items(self):
    for handle, item in self._inside_label_items:
        self._position_inside_label_item(handle, item)
```

Connect each owning `ViewBox.sigRangeChanged` to reposition labels. Hide the
inside label for an axis when `handle.get_title()` returns a non-empty title.

- [x] **Step 5: Run GREEN**

Run the same pytest command. Expected: all tests in the class pass.

## Task 2: Overlay Independent Y Axes

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- May depend on Worker A changes in `mf4_analyzer/ui/_axis_handle.py`

- [x] **Step 1: Write RED structure tests**

Add near `TestTimeDomainCanvasPGOverlayMode`:

```python
def test_overlay_builds_independent_y_viewboxes_and_axes_per_channel(self, qapp):
    canvas = _pg_canvas(qapp)
    rows = _five_channel_rows()[:4]
    canvas.plot_channels(rows, mode="overlay")

    assert len(canvas.axes_list) == len(rows)
    view_boxes = [handle.view_box for handle in canvas.axes_list]
    assert len({id(vb) for vb in view_boxes}) == len(rows)
    for handle, row in zip(canvas.axes_list, rows):
        name, _vis, _t, _sig, color, _unit, _data_id = row
        axis_handle, _line = canvas._channel_lines[name]
        assert axis_handle is handle
        y_axis = handle.y_axis_item()
        assert y_axis is not None
        assert y_axis.labelText
```

Add:

```python
def test_overlay_selected_y_drag_changes_only_selected_channel_axis(self, qapp):
    canvas = _pg_canvas(qapp)
    rows = _five_channel_rows()[:3]
    canvas.plot_channels(rows, mode="overlay")
    canvas.select_overlay_channel(rows[1][0])

    ranges_before = [handle.get_ylim() for handle in canvas.axes_list]
    canvas._begin_overlay_y_drag_at(start_y_px=100.0)
    assert canvas._apply_overlay_y_drag_at(current_y_px=140.0)
    ranges_after = [handle.get_ylim() for handle in canvas.axes_list]

    assert ranges_after[1] != pytest.approx(ranges_before[1])
    assert ranges_after[0] == pytest.approx(ranges_before[0])
    assert ranges_after[2] == pytest.approx(ranges_before[2])
```

- [x] **Step 2: Run RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGOverlayMode -q
```

Expected: overlay still reports one axis/ViewBox and selected Y drag affects the
shared axis.

- [x] **Step 3: Implement multi-axis overlay**

Replace overlay construction in `plot_channels()` with:

- create one primary `PlotItem`;
- bind channel 0 to the primary left axis;
- for channel 1, show and link the built-in right axis to a new `_ModifierWheelViewBox`;
- for channel 2+, add `pg.AxisItem("right")` to later `PlotItem.layout` columns and link each to its own `_ModifierWheelViewBox`;
- add auxiliary ViewBoxes to the scene and call `setXLink(primary.view_box)`;
- add each `PlotDataItem` directly to its owning ViewBox for auxiliary axes;
- store one `PgAxisHandle(plot_item=pi, view_box=vb, axis_item=axis_item)` per channel.

Add `_sync_overlay_aux_viewboxes()` using the same pattern as
`pyqtgraph/examples/MultiplePlotAxes.py`:

```python
rect = primary.view_box.sceneBoundingRect()
aux_vb.setGeometry(rect)
aux_vb.linkedViewChanged(primary.view_box, aux_vb.XAxis)
```

Connect primary `sigResized` to that helper.

- [x] **Step 4: Update selected overlay axis resolution**

Change `_selected_overlay_axes()` to return the axis handle stored for
`_selected_overlay_channel`, not always `_primary_xaxis_ax`.

- [x] **Step 5: Run GREEN**

Run the overlay class plus scroll tests:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGOverlayMode tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGScroll -q
```

## Task 3: Dialog Handle State And Tick Density

**Files:**
- Modify: `mf4_analyzer/ui/_axis_handle.py`
- Modify: `mf4_analyzer/ui/dialogs.py`
- Modify: `tests/ui/test_axis_handle.py`
- Modify: `tests/ui/test_dialogs.py`

- [x] **Step 1: Write RED dialog tests**

Add tests that build a `TimeDomainCanvasPG`, get `handle = canvas.axes_list[0]`,
then instantiate `ChartOptionsDialog(None, handle)`:

```python
def test_pg_chart_options_reads_grid_initial_state(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    t = np.linspace(0.0, 1.0, 50)
    canvas.plot_channels([("speed", True, t, np.sin(t), "#1769e0", "rpm")])
    dlg = ChartOptionsDialog(None, canvas.axes_list[0])
    assert dlg.chk_grid.isChecked() is True
```

Add equivalent tests for `get_yscale()` initial state, legend rebuild idempotency,
and curve color syncing the owning PG axis color.

- [x] **Step 2: Run RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_axis_handle.py -q
```

Expected: new PG-specific tests fail on grid/scale/legend/axis-color state.

- [x] **Step 3: Extend AxisHandle protocol**

Add these methods with matplotlib and PG implementations:

```python
def is_grid_enabled(self) -> bool: ...
def get_xscale(self) -> str: ...
def get_yscale(self) -> str: ...
def rebuild_legend(self) -> None: ...
def sync_line_axis_color(self, line: LineHandle, color: str) -> None: ...
```

For PG, track `_grid_enabled`, `_xscale`, and `_yscale` inside `PgAxisHandle`.
For legend, use `PlotItem.addLegend()` once and add visible line labels
idempotently. For axis color sync, color the axis item owned by the handle.

- [x] **Step 4: Move dialog off `self.ax` for shared state**

Change `_read_axes()` to prefer handle getters. Change `apply_changes()` to call
`handle.rebuild_legend()` when checked. Change `_sync_curve_axis_color()` to
call `handle.sync_line_axis_color(line, color)` first, then keep the matplotlib
escape hatch as fallback if necessary.

- [x] **Step 5: Run GREEN**

Run the same dialog/axis tests. Expected: all pass.

## Task 4: Tick Density, Readable Lines, And Dead Cache Removal

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `tests/perf/test_timedomain_pan_perf.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [x] **Step 1: Write RED tests**

Add:

```python
def test_set_tick_density_updates_pg_axis_items(self, qapp, monkeypatch):
    import pyqtgraph as pg

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
    calls = []
    original = pg.AxisItem.setTickSpacing

    def spy(axis, *args, **kwargs):
        calls.append((axis, args, kwargs))
        return original(axis, *args, **kwargs)

    monkeypatch.setattr(pg.AxisItem, "setTickSpacing", spy)
    canvas.set_tick_density(12, 7)
    assert len(calls) >= len(canvas.axes_list) * 2
    assert canvas._tick_density == (12, 7)
```

Add:

```python
def test_refresh_visible_data_does_not_build_unused_path_or_pixmap(self, qapp, monkeypatch):
    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1])
    monkeypatch.setattr(canvas, "_build_painter_path", lambda *args, **kwargs: pytest.fail("unused path built"))
    monkeypatch.setattr(canvas, "_render_path_to_pixmap", lambda *args, **kwargs: pytest.fail("unused pixmap built"))
    canvas.set_xlim(0.1, 0.8)
    canvas._flush_pending_refresh()
```

Update the existing visual-width test to expect readable PG widths:

```python
assert float(pen.widthF()) >= 1.6
```

- [x] **Step 2: Run RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
```

Expected: tick-density, dead-cache, and width tests fail.

- [x] **Step 3: Implement**

Add `_tick_density = (10, 6)` in `TimeDomainCanvasPG.__init__`. Implement
`set_tick_density()` to store ints, estimate current major spacing from each
axis range, and call `setTickSpacing(major=..., minor=...)` on bottom/left or
overlay axis items. Call the helper after every plot build.

Raise PG curve widths:

```python
self._overlay_default_lw = 1.7
self._overlay_selected_lw = 2.6
self._overlay_de_emphasised_lw = 1.35
```

Use the same default width for `_bind_channel()`.

Remove `_build_painter_path()` and `_render_path_to_pixmap()` calls from
`_refresh_visible_data()`. Keep `_last_range_key` to avoid redundant
`positions_envelope + setData` work for identical windows. Update perf tests so
they assert visible refresh and bounded timing, not pixmap-cache population.

- [x] **Step 4: Run GREEN**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py::test_timedomain_pan_refresh_pg_canvas -q -s
```

## Task 5: Cursor Drag Pass-Through

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [x] **Step 1: Write RED test**

Add near `TestTimeDomainCanvasPGCursorInteraction`:

```python
def test_cursor_mousemove_with_left_button_does_not_consume_pan_drag(self, qapp):
    from PyQt5.QtCore import QCoreApplication, QEvent, Qt
    from PyQt5.QtGui import QMouseEvent

    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:2], mode="subplot")
    QCoreApplication.processEvents()
    canvas.set_cursor_visible(True)

    point = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.5)
    event = QMouseEvent(QEvent.MouseMove, point, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    consumed = canvas.eventFilter(canvas._glw.viewport(), event)
    assert consumed is False
```

- [x] **Step 2: Run RED**

Run the cursor interaction class. Expected: new test fails because the event is
consumed.

- [x] **Step 3: Implement**

In `eventFilter()`, pass the whole event to cursor move handling and let
`_handle_cursor_mouse_move()` return `False` when `event.buttons() &
Qt.LeftButton` is true. No-button hover remains consumed.

- [x] **Step 4: Run GREEN**

Run cursor tests.

## Task 6: Toolbar Home Shared-X Policy

**Files:**
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `mf4_analyzer/ui/chart_stack.py`

- [x] **Step 1: Write RED test**

Add:

```python
def test_pg_toolbar_home_keeps_subplot_x_ranges_identical_after_auto_range(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode("time")
    t1 = np.linspace(0.0, 1.0, 50)
    t2 = np.linspace(2.0, 4.0, 50)
    cs.canvas_time.plot_channels([
        ("a", True, t1, np.sin(t1), "#1769e0", "u"),
        ("b", True, t2, np.cos(t2), "#ef4444", "u"),
    ], mode="subplot")
    for handle in cs.canvas_time.axes_list:
        handle.set_xlim(0.25, 0.75)
    cs._time_card.toolbar.home()
    ranges = [handle.get_xlim() for handle in cs.canvas_time.axes_list]
    assert ranges[0] == pytest.approx((0.0, 4.0))
    assert ranges[1] == pytest.approx(ranges[0])
```

- [x] **Step 2: Run RED**

Run `tests/ui/test_chart_stack.py -q`. Expected: new Home range test fails or
captures nondeterministic per-axis reset.

- [x] **Step 3: Implement**

Add a canvas helper, if present, call it from `PgNavigationToolbar.home()`:

```python
sync = getattr(canvas, "reset_view_to_data_extents", None)
if callable(sync):
    sync()
    return
```

If no helper exists, keep the old `autoRange()` fallback.

- [x] **Step 4: Run GREEN**

Run `tests/ui/test_chart_stack.py -q`.

## Task 7: Integrated Verification

**Files:**
- Modify only if required: `.state/lesson-candidate.md`

- [x] Run all targeted UI tests:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_dialogs.py tests/ui/test_axis_handle.py tests/ui/test_chart_stack.py -q
```

- [x] Run perf smoke:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py::test_timedomain_pan_refresh_pg_canvas -q -s
```

- [x] Render screenshots under `/tmp` for:
  - subplot inside labels after pan/zoom;
  - overlay with at least three channel axes.

- [x] Run:

```bash
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

- [x] Promote a lesson only if the lessons gate reports one is required.

