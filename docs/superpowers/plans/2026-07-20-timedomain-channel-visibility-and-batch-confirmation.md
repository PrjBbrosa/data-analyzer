# TimeDomain Channel Visibility And Batch Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate TimeDomain channel membership from per-View chart visibility with an eye control, and require explicit confirmation before a multi-selected checkbox click changes every selected channel.

**Architecture:** `MultiFileChannelWidget` owns the live channel-tree visibility projection and exposes checked, hidden, and visible-checked APIs. `ViewState` persists `hidden_channels`, `view_bridge` moves that state between the focused View and navigator, and `MainWindow` replots only visible checked channels while retaining checked channels as analysis inputs. The existing View replot pipeline remains responsible for per-pane routing and X/Y restoration.

**Tech Stack:** Python 3, PyQt5 `QTreeWidget`/`QMessageBox`, pyqtgraph TimeDomain canvas, pytest/pytest-qt.

## Global Constraints

- The eye affects only the TimeDomain chart; checked membership remains the input contract for FFT, FFT-vs-Time, and Order.
- Hidden state is stored per TimeDomain View as `hidden_channels`, with missing legacy data defaulting to no hidden channels.
- In subplot mode a hidden channel removes its row; in overlay mode it removes the channel curve bundle and axis.
- Replots must preserve the focused pane's X range and restore saved Y ranges; a re-shown channel without a saved Y range fits the visible X window once.
- Multi-selected checkbox changes are atomic, emit once, redraw once, and default the confirmation dialog to cancellation.
- Do not add parent-node eye controls or implicit multi-row eye propagation.
- Preserve existing pyqtgraph dense-subplot spacing, overlay grid, shared-axis, filter-companion, and custom-X contracts.

---

## File Structure

- `mf4_analyzer/ui/view_state.py`: serialize the per-View hidden channel set.
- `mf4_analyzer/ui/project_io.py`: remap hidden channel file IDs when projects reopen.
- `mf4_analyzer/ui/view_bridge.py`: capture/apply hidden channels with existing View controls.
- `mf4_analyzer/ui_kit/icons.py`: programmatic open-eye and closed-eye icons.
- `mf4_analyzer/ui/widgets/__init__.py`: channel-tree eye column, live hidden set, batch confirmation, and public APIs.
- `mf4_analyzer/ui/file_navigator.py`: bubble visibility signal and delegate visibility APIs.
- `mf4_analyzer/ui/main_window/window.py`: mode-column routing, focused-pane visibility replot, visible-channel plotting, counts, and stats preservation.
- `mf4_analyzer/ui/pg_canvas/canvas.py`: centered empty-chart hint when every checked channel is hidden.
- `tests/ui/test_view_state.py`, `tests/test_project_io.py`, `tests/ui/test_view_bridge.py`: persistence and bridge contracts.
- `tests/ui/test_channel_widget.py`, `tests/ui/test_channel_widget_setters.py`: eye and batch-confirmation widget contracts.
- `tests/ui/test_split_focus_routing.py`, `tests/ui/test_main_window_smoke.py`: focused View routing and plotted-channel integration.
- `tests/ui/test_pg_timedomain_canvas.py`: TimeDomain empty-hint lifecycle.

---

### Task 1: Persist And Remap Hidden Channels

**Files:**
- Modify: `mf4_analyzer/ui/view_state.py`
- Modify: `mf4_analyzer/ui/project_io.py`
- Test: `tests/ui/test_view_state.py`
- Test: `tests/test_project_io.py`

**Interfaces:**
- Produces: `ViewState.hidden_channels: list[ChannelKey]`.
- Produces: `ViewState.to_dict()["hidden_channels"]` and legacy-safe `ViewState.from_dict()`.
- Produces: `project_io.remap_view_fids()` remapping/dropping hidden channel references.

- [ ] **Step 1: Write failing state and remap tests**

```python
def test_viewstate_hidden_channels_roundtrip_and_legacy_default():
    state = ViewState(
        name="V", tab_color="#2d7ff9",
        checked=[("f1", "rpm"), ("f1", "speed")],
        hidden_channels=[("f1", "speed")],
    )
    assert ViewState.from_dict(state.to_dict()).hidden_channels == [("f1", "speed")]
    assert ViewState.from_dict({"name": "Old", "tab_color": "#fff"}).hidden_channels == []

def test_remap_rewrites_and_drops_hidden_channels():
    view = {
        "name": "V", "tab_color": "#fff",
        "checked": [["f0", "rpm"], ["f1", "speed"]],
        "hidden_channels": [["f0", "rpm"], ["f1", "speed"]],
    }
    out = pio.remap_view_fids([view], {"f0": "f3"})[0]
    assert out["hidden_channels"] == [["f3", "rpm"]]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_state.py tests/test_project_io.py -q`

Expected: FAIL because `ViewState` has no `hidden_channels` field and remapping leaves the old file ID.

- [ ] **Step 3: Add the data field and serialization**

```python
@dataclass
class ViewState:
    name: str
    tab_color: str
    checked: list[ChannelKey] = field(default_factory=list)
    hidden_channels: list[ChannelKey] = field(default_factory=list)

def to_dict(self):
    data = asdict(self)
    data["checked"] = [list(key) for key in self.checked]
    data["hidden_channels"] = [list(key) for key in self.hidden_channels]
    return data

# inside from_dict
hidden_channels=[
    _coerce_channel_key(key) for key in data.get("hidden_channels", [])
],
```

In `remap_view_fids`, apply the same checked-list remap to `hidden_channels`:

```python
v["hidden_channels"] = [
    [fid_map[fid], ch]
    for fid, ch in (tuple(x) for x in view.get("hidden_channels", []))
    if fid in fid_map
]
```

- [ ] **Step 4: Run the focused persistence tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_state.py tests/test_project_io.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mf4_analyzer/ui/view_state.py mf4_analyzer/ui/project_io.py tests/ui/test_view_state.py tests/test_project_io.py
git commit -m "feat: persist timedomain channel visibility"
```

### Task 2: Add Eye Icons And Channel-Tree Visibility State

**Files:**
- Modify: `mf4_analyzer/ui_kit/icons.py`
- Modify: `mf4_analyzer/ui/widgets/__init__.py`
- Test: `tests/ui/test_channel_widget.py`
- Test: `tests/ui/test_channel_widget_setters.py`

**Interfaces:**
- Produces: `Icons.eye_open()` and `Icons.eye_closed()`.
- Produces: `MultiFileChannelWidget.visibility_changed(str fid, str channel, bool visible)`.
- Produces: `get_hidden_channels()`, `set_hidden_channels(hidden)`, `get_visible_checked_channels()`, and `set_time_visibility_available(available)`.
- Produces: `set_channel_visible(fid, channel, visible, *, emit=True) -> bool`.

- [ ] **Step 1: Write failing icon and single-row visibility tests**

```python
def test_checked_channel_eye_toggles_visibility_without_unchecking(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("file-a", _MultiChannelFileData())
    item = widget._file_items["file-a"].child(0)
    item.setCheckState(0, Qt.Checked)
    assert not item.icon(2).isNull()

    fired = []
    widget.visibility_changed.connect(lambda *_: fired.append(1))
    widget._on_item_clicked(item, 2)

    assert item.checkState(0) == Qt.Checked
    assert widget.get_hidden_channels() == [("file-a", "speed")]
    assert widget.get_visible_checked_channels() == []
    assert fired == [1]

def test_visibility_icons_are_distinct(qapp):
    assert not Icons.eye_open().isNull()
    assert not Icons.eye_closed().isNull()
    assert Icons.eye_open().cacheKey() != Icons.eye_closed().cacheKey()
```

Also add tests that unchecking clears hidden state, `set_hidden_channels` drops unchecked/unknown keys, eye clicks affect only the clicked row, and column 2 hides outside TimeDomain.

- [ ] **Step 2: Run the widget tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_channel_widget.py tests/ui/test_channel_widget_setters.py -q`

Expected: FAIL because the eye icons, column, signal, and visibility APIs do not exist.

- [ ] **Step 3: Draw open and closed eye icons**

Add two programmatic icon factories following the existing `_painting` and `_pen` pattern:

```python
@classmethod
def eye_open(cls):
    with _painting() as (pix, p):
        p.setPen(_pen(GRAY, 1.45))
        p.setBrush(Qt.NoBrush)
        eye = QPainterPath()
        eye.moveTo(3, 10)
        eye.cubicTo(6, 5, 14, 5, 17, 10)
        eye.cubicTo(14, 15, 6, 15, 3, 10)
        eye.closeSubpath()
        p.drawPath(eye)
        p.setBrush(QBrush(GRAY))
        p.drawEllipse(QRectF(8, 8, 4, 4))
    return QIcon(pix)

@classmethod
def eye_closed(cls):
    with _painting() as (pix, p):
        p.setPen(_pen(MUTED, 1.45))
        p.drawArc(QRectF(4, 5, 12, 10), 200 * 16, 140 * 16)
        p.drawLine(QPointF(4, 4), QPointF(16, 16))
    return QIcon(pix)
```

- [ ] **Step 4: Add the visibility column and state APIs**

Initialize a third fixed-width centered `显示` column, connect `itemClicked`, and keep a compact hidden-key set:

```python
self.tree.setHeaderLabels(["Channel", "Pts", "显示"])
header.setSectionResizeMode(2, QHeaderView.Fixed)
header.resizeSection(2, 42)
self.tree.itemClicked.connect(self._on_item_clicked)
self._hidden_channels = set()

def get_hidden_channels(self):
    return [
        (fid, ch) for fid, ch, _color in self.get_checked_channels()
        if (fid, ch) in self._hidden_channels
    ]

def get_visible_checked_channels(self):
    return [
        row for row in self.get_checked_channels()
        if (row[0], row[1]) not in self._hidden_channels
    ]
```

`set_channel_visible` must refuse unchecked/unknown rows, update only column 2 behind the `_updating` guard, set the exact tooltip copy from the design, and emit `visibility_changed` once only when state changed. Checkbox, parent cascade, `全选`, `全不`, programmatic restore, and file removal must enforce `hidden_channels ⊆ checked`.

- [ ] **Step 5: Run the focused widget tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_channel_widget.py tests/ui/test_channel_widget_setters.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add mf4_analyzer/ui_kit/icons.py mf4_analyzer/ui/widgets/__init__.py tests/ui/test_channel_widget.py tests/ui/test_channel_widget_setters.py
git commit -m "feat: add timedomain channel eye controls"
```

### Task 3: Confirm Multi-Selected Checkbox Changes

**Files:**
- Modify: `mf4_analyzer/ui/widgets/__init__.py`
- Test: `tests/ui/test_channel_widget.py`

**Interfaces:**
- Produces: `_confirm_selected_channel_checks(count: int, state: Qt.CheckState) -> bool`.
- Changes: `_set_selected_channel_checks(clicked_item, state)` returns `True` for both confirmed and cancelled batch gestures so the tree always consumes the original click.

- [ ] **Step 1: Replace the old immediate-batch test with confirmation tests**

```python
def test_batch_checkbox_cancel_keeps_every_state_and_emits_nothing(..., monkeypatch):
    first, second = _select_first_two_rows(widget)
    monkeypatch.setattr(widget, "_confirm_selected_channel_checks", lambda *_: False)
    fired = []
    widget.channels_changed.connect(lambda: fired.append(1))
    _click_checkbox(first)
    assert first.checkState(0) == Qt.Unchecked
    assert second.checkState(0) == Qt.Unchecked
    assert fired == []

def test_batch_checkbox_confirm_checks_and_shows_once(..., monkeypatch):
    first, second = _select_first_two_rows(widget)
    widget.set_channel_visible(second_fid, second_name, False, emit=False)
    monkeypatch.setattr(widget, "_confirm_selected_channel_checks", lambda *_: True)
    _click_checkbox(first)
    assert first.checkState(0) == Qt.Checked
    assert second.checkState(0) == Qt.Checked
    assert widget.get_hidden_channels() == []
    assert fired == [1]
```

Add an inspection test that captures the `QMessageBox`, asserts the exact check/uncheck copy and action labels, and verifies `取消操作` is the default button.

- [ ] **Step 2: Run confirmation tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_channel_widget.py -q`

Expected: FAIL because the batch mutation still happens before confirmation.

- [ ] **Step 3: Implement the explicit confirmation**

```python
def _confirm_selected_channel_checks(self, count, state):
    checking = state == Qt.Checked
    box = QMessageBox(self.tree)
    box.setWindowTitle("批量操作确认")
    box.setIcon(QMessageBox.Question)
    box.setText(
        f"当前选中了 {count} 个通道，是否将它们全部勾选并显示？"
        if checking else
        f"当前选中了 {count} 个通道，是否将它们全部取消勾选并从当前视图移除？"
    )
    confirm = box.addButton(
        "全部勾选并显示" if checking else "全部取消勾选",
        QMessageBox.AcceptRole,
    )
    cancel = box.addButton("取消操作", QMessageBox.RejectRole)
    box.setDefaultButton(cancel)
    box.exec_()
    return box.clickedButton() is confirm
```

Call this before setting `_updating` or mutating an item. On cancellation return `True` without `_apply_filters`, signal emission, or icon changes. On confirmation mutate the selection snapshot, clear all affected hidden keys, refresh icons, apply filters, and emit once.

- [ ] **Step 4: Run the focused confirmation tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_channel_widget.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mf4_analyzer/ui/widgets/__init__.py tests/ui/test_channel_widget.py
git commit -m "feat: confirm batch channel checkbox changes"
```

### Task 4: Bridge Visibility Through Views And Navigator

**Files:**
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `mf4_analyzer/ui/view_bridge.py`
- Test: `tests/ui/test_view_bridge.py`
- Test: `tests/ui/test_file_navigator.py`

**Interfaces:**
- `FileNavigator` bubbles `visibility_changed` and delegates the four visibility APIs from Task 2.
- `view_bridge.capture_view()` reads `navigator.get_hidden_channels()`.
- `view_bridge.capture_controls_into()` copies `hidden_channels`.
- `view_bridge.apply_controls_from_state()` calls `navigator.set_hidden_channels()` after checked channels are restored.

- [ ] **Step 1: Write failing bridge tests**

Extend `_Nav` with `_hidden`, `get_hidden_channels`, and `set_hidden_channels`. Assert:

```python
state = view_bridge.capture_view(win)
assert state.hidden_channels == [("f1", "rpm")]

view_bridge.apply_view(
    ViewState(
        name="v", tab_color="#000000",
        checked=[("f1", "rpm")],
        hidden_channels=[("f1", "rpm")],
    ),
    win,
)
assert win.navigator.set_hidden == [("f1", "rpm")]
```

Add a `FileNavigator` test proving its signal fires once when the child signal fires and its delegates return the child values.

- [ ] **Step 2: Run bridge tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_bridge.py tests/ui/test_file_navigator.py -q`

Expected: FAIL because the bridge and navigator do not know hidden channels.

- [ ] **Step 3: Implement navigator delegation and bridge capture/apply**

```python
class FileNavigator(QWidget):
    visibility_changed = pyqtSignal(str, str, bool)

# __init__
self.channel_list.visibility_changed.connect(self.visibility_changed)

def get_hidden_channels(self):
    return self.channel_list.get_hidden_channels()

def set_hidden_channels(self, hidden):
    self.channel_list.set_hidden_channels(hidden)
```

Add equivalent delegates for visible checked rows, `set_channel_visible`, and TimeDomain-column availability. In `view_bridge` copy the new list alongside `checked`, and apply it immediately after `set_checked_channels` while navigator signals are blocked.

- [ ] **Step 4: Run bridge tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_view_bridge.py tests/ui/test_file_navigator.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mf4_analyzer/ui/file_navigator.py mf4_analyzer/ui/view_bridge.py tests/ui/test_view_bridge.py tests/ui/test_file_navigator.py
git commit -m "feat: bridge timedomain visibility through views"
```

### Task 5: Render Only Visible Channels In The Focused Time View

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Test: `tests/ui/test_main_window_smoke.py`
- Test: `tests/ui/test_split_focus_routing.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Consumes: `navigator.visibility_changed`, `get_visible_checked_channels()`, and per-View `hidden_channels`.
- Produces: `_on_time_channel_visibility_changed(fid: str, channel: str, visible: bool)`.
- Produces: `_build_time_statistics(checked, range_enabled, range_lo, range_hi)` so eye state does not change checked-channel statistics.
- Produces: `TimeDomainCanvasPG.show_empty_hint(text: str)` and `clear_empty_hint()`.

- [ ] **Step 1: Write failing focused-canvas and rendering tests**

Add integration coverage that loads speed and torque, checks both, hides torque, then asserts:

```python
assert set(_checked_pairs(w)) == {(fid, "speed"), (fid, "torque")}
assert _has_channel(w.canvas_time, "speed")
assert not _has_channel(w.canvas_time, "torque")
assert len(w.canvas_time.axes_list) == 1
```

For subplot mode, assert hiding one of two channels reduces `axes_list` from two rows to one and the visible X range remains unchanged. For split mode, focus the secondary, hide its channel, and assert the primary canvas remains untouched while the secondary becomes empty; switch focus back and verify each View's hidden set projects independently.

- [ ] **Step 2: Run the integration tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_split_focus_routing.py -q`

Expected: FAIL because eye changes are not routed and plotting still consumes all checked rows.

- [ ] **Step 3: Wire mode and visibility signals**

```python
self.navigator.visibility_changed.connect(self._on_time_channel_visibility_changed)
self.navigator.set_time_visibility_available(
    self.chart_stack.current_mode() == "time"
)

def _on_time_channel_visibility_changed(self, fid, channel, visible):
    canvas = self.chart_stack.focused_canvas()
    idx = self._view_index_for_canvas(canvas)
    if idx is None:
        return
    state = self.view_manager.get(idx)
    self._view_bridge.capture_canvas_ranges_into(state, canvas)
    self._view_bridge.capture_controls_into(state, self, canvas)
    invalidate = getattr(canvas, "invalidate_envelope_cache", None)
    if callable(invalidate):
        invalidate("channel visibility changed")
    rendered = self._replot_canvas_for_view(idx, canvas)
    if rendered is False and visible:
        self.navigator.set_channel_visible(fid, channel, False, emit=False)
        self._view_bridge.capture_controls_into(state, self, canvas)
        self._replot_canvas_for_view(idx, canvas)
```

Set visibility-column availability after every mode change, with `True` only for `mode == "time"`.

- [ ] **Step 4: Split checked membership from plotted membership**

At `_plot_time_on_canvas` entry retain `all_checked`, derive `checked = get_visible_checked_channels()`, and use only visible rows for risk estimation, overlay-left-axis ordering, `_build_time_plot_data`, and `canvas.plot_channels`. Clear `_overlay_primary` only when absent from `all_checked`; a hidden preferred primary remains stored and temporarily falls back to the first visible plotted channel.

Before a structural visibility replot, capture current Y ranges as shown above. The existing `_render_view_to_canvas` restore sequence then restores saved X/Y; the existing missing-Y fallback fits a newly shown channel in the visible X window.

Make `_plot_time_on_canvas` return `False` only when the existing high-risk overlay confirmation is cancelled and `True` after every accepted/empty render. Propagate that result through `_render_view_to_canvas` and `_replot_canvas_for_view`. This lets the visibility handler roll a rejected eye-open action back to closed without leaving the tree and canvas inconsistent; the rollback replot uses the prior low-risk hidden set.

- [ ] **Step 5: Preserve checked-channel statistics and show both counts**

Extract the existing original-sample statistics loop into:

```python
def _build_time_statistics(self, checked, range_enabled, range_lo, range_hi):
    stats = {}
    for fid, ch, _color in checked:
        fd = self.channel_list.get_file_data(fid)
        if fd is None or ch not in fd.data.columns:
            continue
        signal = fd.data[ch].to_numpy(copy=False)
        if range_enabled:
            time_axis = fd.time_array
            signal = signal[(time_axis >= range_lo) & (time_axis <= range_hi)]
        if len(signal) == 0:
            continue
        stats[fd.get_prefixed_channel(ch)] = {
            "min": np.min(signal), "max": np.max(signal),
            "mean": np.mean(signal), "rms": np.sqrt(np.mean(signal ** 2)),
            "std": np.std(signal), "p2p": np.ptp(signal),
            "unit": fd.channel_units.get(ch, ""),
        }
    return stats
```

When all checked channels are hidden, clear the focused canvas without treating it as “no channels selected”, retain statistics, call `canvas.show_empty_hint(f"已选择 {len(all_checked)} 个通道，当前均已隐藏")`, and show the same status message. Otherwise clear the empty hint and show `绘制: M/N 通道，F 文件` using the actual visible/checked/file counts.

Implement `show_empty_hint` with a centered `pg.LabelItem` added to the empty `GraphicsLayoutWidget`; `clear()` must reset its reference, and the next `plot_channels()` rebuild must remove it. Add a canvas-level test that shows the hint, verifies its text/reference, calls `plot_channels`, and verifies the hint no longer remains.

- [ ] **Step 6: Run focused integration tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_main_window_smoke.py::test_timedomain_eye_hides_channel_without_unchecking tests/ui/test_main_window_smoke.py::test_subplot_eye_collapses_row_and_preserves_ranges tests/ui/test_split_focus_routing.py::test_channel_visibility_routes_to_focused_secondary -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_main_window_smoke.py tests/ui/test_split_focus_routing.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat: route timedomain channel visibility"
```

### Task 6: Project Roundtrip And Full Regression Verification

**Files:**
- Modify: `tests/ui/test_project_session.py`

**Interfaces:**
- Verifies the complete feature; produces no new production API.

- [ ] **Step 1: Add a project roundtrip regression**

```python
def test_project_roundtrip_restores_timedomain_hidden_channels(qapp, tmp_path):
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    proj = tmp_path / "visibility.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    fid = next(iter(mw.files))
    mw.navigator.set_checked_channels([(fid, "rpm")])
    mw.navigator.set_hidden_channels([(fid, "rpm")])
    mw._capture_current_view()
    mw.save_project(proj)

    restored = MainWindow()
    restored.open_project(proj)
    assert restored.view_manager.get(0).hidden_channels
    assert restored.navigator.get_hidden_channels()
    assert not restored.canvas_time.axes_list
```

- [ ] **Step 2: Run the new roundtrip regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_project_session.py::test_project_roundtrip_restores_timedomain_hidden_channels -q`

Expected: PASS.

- [ ] **Step 3: Run the focused feature suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_channel_widget.py tests/ui/test_channel_widget_setters.py tests/ui/test_view_state.py tests/ui/test_view_bridge.py tests/ui/test_file_navigator.py tests/test_project_io.py tests/ui/test_project_session.py tests/ui/test_split_focus_routing.py -q`

Expected: PASS.

- [ ] **Step 4: Run the TimeDomain fragile-area regressions**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_overlay_grid_ticks.py tests/ui/test_subplot_shared_axis.py tests/ui/test_main_window_smoke.py -q`

Expected: PASS.

- [ ] **Step 5: Run repository hygiene checks**

Run: `git diff --check`

Expected: no output and exit code 0.

Run: `.\.venv\Scripts\python.exe scripts\lessons\check.py`

Expected: no unmet lesson requirement. If implementation reveals a durable recurring failure, follow the repository lesson promotion workflow before clearing it.

- [ ] **Step 6: Commit the integration regression or final fixes**

```powershell
git add tests/ui/test_project_session.py
git commit -m "test: cover timedomain visibility project restore"
```
