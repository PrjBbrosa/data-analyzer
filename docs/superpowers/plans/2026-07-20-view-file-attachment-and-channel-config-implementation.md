# View File Attachment and Channel Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the left channel tree View-scoped, support file drag/auto-attachment, and provide reusable named channel configurations whose exact-name matches completely replace the focused TimeDomain View selection.

**Architecture:** Keep `MainWindow.files` and the upper `FileNavigator` rows global, while `ViewState.attached_file_ids` controls which already-loaded file branches the lower `MultiFileChannelWidget` projects. Put configuration persistence and exact-name resolution in a small widget-free domain module, put the compact Save/Combo/Apply UI in a dedicated widget, and route focused-View mutations through a new `ChannelScopeMixin` so View switching, split focus, project restore, and one-redraw semantics stay centralized.

**Tech Stack:** Python 3, PyQt5, `QSettings`, dataclasses/JSON, pytest, pytest-qt, existing pyqtgraph TimeDomain canvas.

## Global Constraints

- Automatic attachment affects only the focused TimeDomain View; it never populates other Views.
- `ViewManager.new_view()` always creates `attached_file_ids == []`, even while automatic attachment is enabled.
- Loading a config through the combo box has no channel-selection side effect and triggers no redraw.
- Applying a config uses exact raw `FileData.get_signal_channels()` names, not display labels, aliases, case folding, or fuzzy matching.
- A successful apply completely replaces `checked`; it never appends to the old selection.
- Zero matches preserve the entire old View state and emit no `channels_changed` signal.
- Existing hidden channels survive only when their `(fid, channel)` remains selected; newly matched channels are visible.
- Configuration overwrite, deletion, attached-file removal with checked channels, and existing dense-overlay risk flows default to Cancel.
- One attach/detach/apply transaction emits at most one semantic state-change signal and performs at most one TimeDomain redraw.
- Legacy projects missing `attached_file_ids` migrate to all successfully restored file IDs; explicit `attached_file_ids: []` remains empty.
- Do not modify FFT, FFT-vs-Time, or Order `AnalysisViewState`/`PaneState` persistence in this plan.
- Add no third-party dependencies.

## Existing Baseline (Do Not Reimplement)

- `757e71d` adds the TimeDomain eye controls.
- `2fcca1f` adds confirmed multi-row checkbox changes.
- `6a1feeb`, `e429ec1`, and `2fd964b` bridge/persist/render per-View `hidden_channels`.
- Preserve their tests and extend their invariants; do not duplicate eye state inside channel configs.

## File Structure

- Create `mf4_analyzer/ui/channel_config.py`: versioned config model/store, name validation, exact-name resolver, immutable apply result.
- Create `mf4_analyzer/ui/widgets/channel_config_bar.py`: compact Save/Combo/Apply widget and Manage sentinel behavior only.
- Create `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`: focused-TimeDomain View attachment, config dialogs, complete replacement, result feedback.
- Create `tests/ui/test_channel_config.py`: config model/store/resolver unit tests.
- Create `tests/ui/test_channel_config_bar.py`: compact widget signals/enabled-state tests.
- Create `tests/ui/test_view_channel_scope.py`: MainWindow attachment/config integration tests.
- Modify `mf4_analyzer/ui/view_state.py`: serialize `attached_file_ids`.
- Modify `mf4_analyzer/ui/view_bridge.py`: capture/project attachment before checked/hidden state.
- Modify `mf4_analyzer/ui/project_io.py`: remap explicit attachments and migrate missing fields.
- Modify `mf4_analyzer/ui/widgets/__init__.py`: project attached branches, empty state, attach drop target, parent detach hit.
- Modify `mf4_analyzer/ui/file_navigator.py`: drag-capable file rows, automatic-attachment tool button, signal bubbling, config bar mount.
- Modify `mf4_analyzer/ui/main_window/window.py`: mixin registration, store initialization, signal wiring.
- Modify `mf4_analyzer/ui/main_window/_project_io_mixin.py`: source-load transaction completion, restore guard, global-close cleanup.
- Modify `tests/ui/test_view_state.py`, `tests/ui/test_file_navigator.py`, `tests/ui/test_view_switch_integration.py`, and `tests/ui/test_project_session.py`: persistence and existing workflow updates.

---

### Task 1: Persist and Remap View File Attachments

**Files:**
- Modify: `mf4_analyzer/ui/view_state.py:35-84`
- Modify: `mf4_analyzer/ui/project_io.py:187-233`
- Test: `tests/ui/test_view_state.py`
- Test: `tests/ui/test_project_session.py`

**Interfaces:**
- Produces: `ViewState.attached_file_ids: list[str]`.
- Produces: `remap_view_fids()` output with explicit attachment remap and missing-field legacy migration.
- Consumes later: `view_bridge`, `ChannelScopeMixin`, and navigator projection.

- [x] **Step 1: Add failing ViewState serialization/default tests**

```python
def test_viewstate_new_view_has_no_attached_files():
    state = ViewState(name="View 1", tab_color="#2d7ff9")
    assert state.attached_file_ids == []


def test_viewstate_attached_file_ids_roundtrip_in_order():
    state = ViewState(
        name="View 1", tab_color="#2d7ff9",
        attached_file_ids=["f2", "f1"],
    )
    assert ViewState.from_dict(state.to_dict()).attached_file_ids == ["f2", "f1"]
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_state.py -q
```

Expected: FAIL because `ViewState` does not accept or expose `attached_file_ids`.

- [x] **Step 3: Add the field and JSON round-trip**

Add `attached_file_ids: list[str] = field(default_factory=list)` immediately before
`checked`. In `to_dict()`, add an ordered string list under
`data["attached_file_ids"]` before serializing `checked`, `hidden_channels`,
`colors`, `x_range`, `y_range`, `manual_y_ranges`, `overlay_primary`, and
`overlay_scale_mode` with their current encodings. In `from_dict()`, pass
`attached_file_ids=[str(fid) for fid in data.get("attached_file_ids", [])]` and
continue passing every currently supported constructor field unchanged.

- [x] **Step 4: Add remap tests that distinguish legacy missing from explicit empty**

```python
def test_remap_view_fids_migrates_legacy_missing_attachments():
    views = [{"name": "legacy", "checked": [], "hidden_channels": []}]
    got = remap_view_fids(views, {"old-a": "f0", "old-b": "f1"})
    assert got[0]["attached_file_ids"] == ["f0", "f1"]


def test_remap_view_fids_preserves_explicit_empty_attachments():
    views = [{"name": "empty", "attached_file_ids": [], "checked": []}]
    got = remap_view_fids(views, {"old-a": "f0"})
    assert got[0]["attached_file_ids"] == []
```

- [x] **Step 5: Implement attachment remap before channel-key remap**

```python
if "attached_file_ids" in view:
    v["attached_file_ids"] = [
        fid_map[fid]
        for fid in view.get("attached_file_ids", [])
        if fid in fid_map
    ]
else:
    # Ordered dict insertion order equals successful project restore order.
    v["attached_file_ids"] = list(fid_map.values())
```

- [x] **Step 6: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_state.py tests\ui\test_project_session.py -q
git add mf4_analyzer/ui/view_state.py mf4_analyzer/ui/project_io.py tests/ui/test_view_state.py tests/ui/test_project_session.py
git commit -m "feat(ui): persist view file attachments"
```

Expected: all focused tests PASS; explicit empty and legacy migration are both covered.

---

### Task 2: Add the Config Domain Model, Store, and Exact Resolver

**Files:**
- Create: `mf4_analyzer/ui/channel_config.py`
- Create: `tests/ui/test_channel_config.py`

**Interfaces:**
- Produces: `ChannelSelectionConfig`.
- Produces: `ChannelSelectionConfigStore.list/get/create/overwrite/rename/delete`.
- Produces: `ConfigNameConflict` carrying the conflicting config.
- Produces: `resolve_channel_config(config, attached_file_ids, files) -> ChannelConfigResolution`.

- [x] **Step 1: Write failing validation, overwrite, corruption, and resolver tests**

```python
def test_store_creates_multiple_configs_and_casefold_detects_conflict(settings):
    store = ChannelSelectionConfigStore(settings, id_factory=iter(("a", "b")).__next__)
    first = store.create("动力分析", ["Speed", "Torque", "Speed"])
    second = store.create("振动分析", ["Accel_X"])
    assert first.channel_names == ("Speed", "Torque")
    assert [c.config_id for c in store.list()] == ["a", "b"]
    with pytest.raises(ConfigNameConflict) as exc:
        store.create(" 动力分析 ", ["Temp"])
    assert exc.value.existing.config_id == "a"


def test_resolver_matches_every_attached_file_by_exact_raw_name():
    config = ChannelSelectionConfig.create("cfg", "动力", ["Speed", "Torque"])
    files = {
        "f0": FakeFd(["Speed", "Torque", "speed"]),
        "f1": FakeFd(["Speed", "Temp"]),
        "f2": FakeFd(["Torque"]),
    }
    result = resolve_channel_config(config, ["f0", "f1"], files)
    assert result.matched == (
        ("f0", "Speed"), ("f0", "Torque"), ("f1", "Speed")
    )
    assert result.missing_names == ()
    assert result.target_file_count == 2
```

- [x] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config.py -q
```

Expected: collection FAIL because `mf4_analyzer.ui.channel_config` does not exist.

- [x] **Step 3: Implement immutable records and ordered-name normalization**

```python
SCHEMA_VERSION = 1


def normalize_channel_names(values: Iterable[str]) -> tuple[str, ...]:
    out, seen = [], set()
    for value in values:
        name = str(value)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


@dataclass(frozen=True)
class ChannelSelectionConfig:
    schema_version: int
    config_id: str
    name: str
    channel_names: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChannelConfigResolution:
    matched: tuple[tuple[str, str], ...]
    missing_names: tuple[str, ...]
    target_file_count: int
```

- [x] **Step 4: Implement the versioned QSettings store with injected clocks/IDs**

Create `ChannelSelectionConfigStore.SETTINGS_KEY =
"channel_selection/configs_v1"`. Its constructor accepts `settings` plus optional
`now` and `id_factory` callables, defaulting to UTC ISO timestamps and UUID hex
IDs. Implement all six operations with these exact contracts:

- `create(name, channel_names)` trims and validates the name, rejects an empty
  normalized channel-name tuple, raises `ConfigNameConflict(existing)` for a
  casefold-equivalent name, appends a new record, persists once, and returns it.
- `overwrite(config_id, channel_names)` preserves ID/name/created time, replaces
  the ordered de-duplicated names, updates the timestamp, persists once, and
  returns the replacement record.
- `rename(config_id, name)` applies the same trim/casefold rules while excluding
  the record itself from conflict checks, updates the timestamp, persists once,
  and returns the replacement record.
- `delete(config_id)` removes and persists the matching record and returns it.
- `get(config_id)` returns the matching record or `None`.
- `list()` returns valid records in persisted order.

Decode the JSON array entry-by-entry: ignore malformed entries, set a public
read-only `had_corruption` flag when any entry or root payload is invalid, and
preserve every valid record. Missing records in `overwrite`, `rename`, or
`delete` raise `KeyError`. Flush with `settings.sync()` after each mutation.

- [x] **Step 5: Implement exact resolution and zero-match data without UI side effects**

```python
def resolve_channel_config(config, attached_file_ids, files):
    wanted = set(config.channel_names)
    matched = []
    seen_names = set()
    target_count = 0
    for fid in attached_file_ids:
        fd = files.get(fid)
        if fd is None:
            continue
        target_count += 1
        for channel in fd.get_signal_channels():
            if channel in wanted:
                matched.append((str(fid), str(channel)))
                seen_names.add(str(channel))
    return ChannelConfigResolution(
        matched=tuple(matched),
        missing_names=tuple(n for n in config.channel_names if n not in seen_names),
        target_file_count=target_count,
    )
```

- [x] **Step 6: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config.py -q
git add mf4_analyzer/ui/channel_config.py tests/ui/test_channel_config.py
git commit -m "feat(ui): add named channel config store"
```

Expected: PASS for create/list, casefold collision, explicit overwrite, rename/delete, corrupt-entry isolation, exact-match resolution, duplicate-name expansion, missing names, and unattached-file exclusion.

---

### Task 3: Build the Compact Save / Config Combo / Apply Bar

**Files:**
- Create: `mf4_analyzer/ui/widgets/channel_config_bar.py`
- Create: `tests/ui/test_channel_config_bar.py`
- Modify: `mf4_analyzer/ui/widgets/__init__.py:269-343`

**Interfaces:**
- Produces: `ChannelConfigBar.save_requested`.
- Produces: `ChannelConfigBar.apply_requested(str)` with selected `config_id`.
- Produces: `ChannelConfigBar.manage_requested(str | None)`.
- Produces: `set_configs(configs, selected_id=None)`, `set_context(has_checked, has_attached)`, `selected_config_id()`.

- [x] **Step 1: Write failing compact-layout and no-side-effect selection tests**

```python
def test_config_bar_has_save_combo_apply_order(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    assert [bar.layout().itemAt(i).widget().objectName() for i in range(3)] == [
        "channelConfigSave", "channelConfigCombo", "channelConfigApply"
    ]


def test_selecting_config_does_not_emit_apply(qtbot):
    bar = ChannelConfigBar()
    bar.set_configs([fake_config("a", "动力分析", 4)])
    with qtbot.assertNotEmitted(bar.apply_requested):
        bar.combo.setCurrentIndex(1)
    assert bar.selected_config_id() == "a"
```

- [x] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config_bar.py -q
```

Expected: import FAIL because `ChannelConfigBar` does not exist.

- [x] **Step 3: Implement the bar and Manage sentinel**

```python
class ChannelConfigBar(QWidget):
    save_requested = pyqtSignal()
    apply_requested = pyqtSignal(str)
    manage_requested = pyqtSignal(object)
    MANAGE_SENTINEL = "__manage_configs__"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.btn_save = QPushButton("保存", self)
        self.btn_save.setObjectName("channelConfigSave")
        self.combo = QComboBox(self)
        self.combo.setObjectName("channelConfigCombo")
        self.btn_apply = QPushButton("应用", self)
        self.btn_apply.setObjectName("channelConfigApply")
        self.btn_apply.setProperty("role", "primary")
        for widget in (self.btn_save, self.combo, self.btn_apply):
            layout.addWidget(widget)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
```

Populate index 0 with `选择配置…`, append configs with `config_id` data, append `管理配置…` with the sentinel, and restore the prior index when Manage is chosen.

- [x] **Step 4: Mount the bar below the channel tree without changing its domain behavior**

```python
self.config_bar = ChannelConfigBar(self)
layout.addWidget(self.config_bar)
```

Do not wire persistence inside `MultiFileChannelWidget`; bubble the bar signals later through `FileNavigator`.

- [x] **Step 5: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config_bar.py tests\ui\test_file_navigator.py -q
git add mf4_analyzer/ui/widgets/channel_config_bar.py mf4_analyzer/ui/widgets/__init__.py tests/ui/test_channel_config_bar.py
git commit -m "feat(ui): add channel config action bar"
```

Expected: PASS; combo selection emits no apply, Apply emits the selected ID, and disabled states follow `has_checked`/`has_attached`.

---

### Task 4: Project Only Attached File Branches in the Channel Tree

**Files:**
- Modify: `mf4_analyzer/ui/widgets/__init__.py:256-1084`
- Modify: `mf4_analyzer/ui/file_navigator.py:157-365`
- Test: `tests/ui/test_file_navigator.py`

**Interfaces:**
- Produces: `get_attached_file_ids() -> list[str]`.
- Produces: `set_attached_file_ids(fids: Iterable[str]) -> None` with no `channels_changed` emission.
- Produces: `files_attach_requested(tuple[str, ...])` and `files_detach_requested(tuple[str, ...], str)`.

- [x] **Step 1: Add failing flat/grouped projection and empty-state tests**

```python
def test_channel_tree_projects_only_attached_files(qapp):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd(short_name="one"))
    nav.add_file("f1", FakeFd(short_name="two"))
    nav.set_attached_file_ids(["f1"])
    assert nav.get_attached_file_ids() == ["f1"]
    assert nav.channel_list._file_items["f0"].isHidden()
    assert not nav.channel_list._file_items["f1"].isHidden()


def test_explicit_empty_attachment_shows_empty_state_and_disables_bulk_actions(qapp):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    nav.set_attached_file_ids([])
    assert nav.channel_list.empty_state.isVisible()
    assert not nav.channel_list.search.isEnabled()
    assert not nav.channel_list.btn_selected_only.isEnabled()
```

- [x] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_file_navigator.py -q
```

Expected: FAIL because attachment APIs and empty state do not exist.

- [x] **Step 3: Add attachment projection helpers**

```python
def set_attached_file_ids(self, fids):
    known = self._files
    self._attached_file_ids = [
        str(fid) for fid in dict.fromkeys(fids or ()) if str(fid) in known
    ]
    attached = set(self._attached_file_ids)
    for fid, item in self._file_items.items():
        item.setHidden(str(fid) not in attached)
    for source in self._source_items.values():
        source.setHidden(not any(
            not source.child(i).isHidden() for i in range(source.childCount())
        ))
    self._sync_empty_state()
    self._apply_filters()
```

Update `_apply_filters`, `_all`, `_none`, `get_checked_channels`, and parent aggregation so detached branches cannot reappear or contribute.

- [x] **Step 4: Add a real empty widget rather than a fake tree node**

Wrap `tree` and a centered `QLabel` in a `QStackedLayout`. Use:

```text
当前 View 尚未加入文件
从上方拖入文件，或开启自动加入
```

No placeholder `QTreeWidgetItem` is allowed.

- [x] **Step 5: Add parent detach hit routing and signal bubbling**

Use the existing third column: channel leaves keep eye icons; file/source parents show a close icon on hover. Resolve descendant fids with one helper and emit exactly once:

```python
files_detach_requested = pyqtSignal(object, str)

def _fids_for_node(self, item):
    data = item.data(0, Qt.UserRole)
    if data[0] in ("file", "raster"):
        return (str(data[1]),)
    if data[0] == "source":
        return tuple(
            str(item.child(i).data(0, Qt.UserRole)[1])
            for i in range(item.childCount())
        )
    return ()
```

- [x] **Step 6: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_file_navigator.py tests\ui\test_view_bridge.py -q
git add mf4_analyzer/ui/widgets/__init__.py mf4_analyzer/ui/file_navigator.py tests/ui/test_file_navigator.py
git commit -m "feat(ui): scope channel tree files per view"
```

Expected: PASS for flat/grouped projection, detached search exclusion, empty state, duplicate projection idempotency, and detach signal payload.

---

### Task 5: Add Internal File Drag and the Automatic-Attachment Toggle

**Files:**
- Modify: `mf4_analyzer/ui/file_navigator.py:50-411`
- Modify: `mf4_analyzer/ui/widgets/__init__.py:256-343`
- Test: `tests/ui/test_file_navigator.py`

**Interfaces:**
- Produces: `_FileRow.MIME_TYPE = "application/x-tracelab-file-fids"`.
- Produces: `FileNavigator.auto_attach_changed(bool)` and `set_auto_attach_enabled(bool)`.
- Produces: `FileNavigator.files_attach_requested(tuple[str, ...])`.

- [x] **Step 1: Write failing MIME, grouped-row, toggle, and drop tests**

```python
def test_file_row_drag_payload_contains_every_group_fid(qapp):
    row = _FileRow("f0", FakeFd())
    row.add_fid("f1", FakeFd())
    mime = row._build_drag_mime()
    assert json.loads(bytes(mime.data(row.MIME_TYPE))) == ["f0", "f1"]


def test_auto_attach_toggle_is_compact_and_emits(qtbot):
    nav = FileNavigator()
    assert nav.btn_auto_attach.maximumWidth() <= 24
    with qtbot.waitSignal(nav.auto_attach_changed, timeout=200) as signal:
        nav.btn_auto_attach.click()
    assert signal.args == [nav.btn_auto_attach.isChecked()]
```

- [x] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_file_navigator.py -q
```

Expected: FAIL for missing drag/toggle APIs.

- [x] **Step 3: Implement drag threshold and JSON MIME without affecting click activation**

```python
def mousePressEvent(self, event):
    if event.button() == Qt.LeftButton:
        self._drag_start = event.pos()
        self.activated.emit(self.fid)
    super().mousePressEvent(event)

def mouseMoveEvent(self, event):
    if not (event.buttons() & Qt.LeftButton) or self._drag_start is None:
        return super().mouseMoveEvent(event)
    if (event.pos() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
        return
    drag = QDrag(self)
    drag.setMimeData(self._build_drag_mime())
    drag.exec_(Qt.CopyAction)
```

- [x] **Step 4: Add the compact header toggle next to count/kebab**

Use `Icons.cloud_download()` until/unless a dedicated existing icon is semantically clearer. Set `checkable=True`, `24x24`, and update tooltip/property for on/off state.

- [x] **Step 5: Accept only the internal MIME in the lower channel card**

Parse/validate the payload on drop, ignore malformed/empty payloads, emit one `files_attach_requested(tuple(fids))`, and leave existing external URL drop handling to `DropImportMixin`.

- [x] **Step 6: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_file_navigator.py -q
git add mf4_analyzer/ui/file_navigator.py mf4_analyzer/ui/widgets/__init__.py tests/ui/test_file_navigator.py
git commit -m "feat(ui): drag files into focused view"
```

Expected: PASS; clicks still activate, group drags include all fids, malformed payloads do not emit, and internal drops emit once.

---

### Task 6: Route Attachments Through the Focused Time View

**Files:**
- Create: `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py:30-75, 220-260, 630-665`
- Modify: `mf4_analyzer/ui/view_bridge.py:44-140`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py:136-335, 590-625, 687-740`
- Create: `tests/ui/test_view_channel_scope.py`
- Modify: `tests/ui/test_view_switch_integration.py`

**Interfaces:**
- Produces: `_focused_time_view_state() -> tuple[int, ViewState] | None`.
- Produces: `_attach_files_to_focused_view(fids) -> tuple[str, ...]`.
- Produces: `_detach_files_from_focused_view(fids, label) -> bool`.
- Produces: `_on_source_load_finished(new_fids)` and `_restoring_project` guard.

- [x] **Step 1: Write failing focused/new/split attachment tests**

```python
def test_normal_load_auto_attaches_only_current_view(window_with_csv):
    w, fid = window_with_csv
    assert w.view_manager.get(0).attached_file_ids == [fid]
    w._on_view_new()
    assert w.view_manager.get(1).attached_file_ids == []
    assert w.navigator.get_attached_file_ids() == []


def test_attach_targets_secondary_focused_view(split_window):
    w, fid = split_window
    w._on_chart_focus_changed(True)
    w._attach_files_to_focused_view([fid])
    assert w.view_manager.get(w._secondary_view_idx).attached_file_ids == [fid]
    assert w.view_manager.get(w._primary_view_idx).attached_file_ids == []
```

- [x] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_channel_scope.py -q
```

Expected: FAIL for missing mixin/attachment APIs.

- [x] **Step 3: Capture/project attachments before checked and hidden state**

```python
def capture_view(window) -> ViewState:
    navigator = window.navigator
    return ViewState(
        name="",
        tab_color="",
        attached_file_ids=list(navigator.get_attached_file_ids()),
        checked=[_channel_key(row) for row in navigator.get_checked_channels()],
        hidden_channels=[_channel_key(row) for row in navigator.get_hidden_channels()],
        # existing fields unchanged
    )

def apply_controls_from_state(state, window, canvas=None):
    navigator = window.navigator
    with _signals_blocked(navigator):
        navigator.set_attached_file_ids(state.attached_file_ids)
        navigator.set_checked_channels(state.checked)
        navigator.set_hidden_channels(state.hidden_channels)
        # existing control restoration unchanged
```

- [x] **Step 4: Implement focused attachment/detachment as atomic state mutations**

```python
class ChannelScopeMixin:
    def _attach_files_to_focused_view(self, fids):
        resolved = self._focused_time_view_state()
        if resolved is None:
            return ()
        idx, state = resolved
        added = [fid for fid in fids if fid in self.files and fid not in state.attached_file_ids]
        if not added:
            return ()
        state.attached_file_ids.extend(added)
        self._project_view_controls(idx)
        return tuple(added)
```

Detachment snapshots checked count, prompts only when nonzero, filters attached/checked/hidden/colors, clears `overlay_primary` if needed, projects once, and replots once only when selected curves changed.

- [x] **Step 5: Add auto-attach load transaction and restore suppression**

At `_load_one()` entry, snapshot `before_fids`. In `finally`, compute ordered new fids and call `_on_source_load_finished(new_fids)`. The helper attaches only when:

```python
not self._restoring_project and self.navigator.auto_attach_enabled()
```

Wrap the project file-loading loop in `self._restoring_project = True` / `finally: False`.

- [x] **Step 6: Clean attachments from every View on global file close**

Before deleting `self.files[fid]`, filter the fid from every `view_manager.views` attachment/checked/hidden/color/primary field. Then remove the global navigator row and reproject the focused View.

- [x] **Step 7: Update existing View-switch tests for the new empty-View contract**

After every `_on_view_new()` that subsequently selects channels, explicitly attach the test fid first:

```python
w._on_view_new()
w._attach_files_to_focused_view([fid])
_set_checked(w, "torque")
```

Do not weaken assertions about independent checked/hidden/range state.

- [x] **Step 8: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_channel_scope.py tests\ui\test_view_switch_integration.py tests\ui\test_view_bridge.py -q
git add mf4_analyzer/ui/main_window/_channel_scope_mixin.py mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/view_bridge.py mf4_analyzer/ui/main_window/_project_io_mixin.py tests/ui/test_view_channel_scope.py tests/ui/test_view_switch_integration.py
git commit -m "feat(ui): attach files to focused time views"
```

Expected: PASS for auto-on/off, new View empty, split focus, idempotent attach, confirmed detach, close cleanup, and one semantic update.

---

### Task 7: Wire Named Config Save, Manage, and Complete Replacement

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Test: `tests/ui/test_view_channel_scope.py`
- Test: `tests/ui/test_channel_config_bar.py`

**Interfaces:**
- Consumes: store/resolver from Task 2 and UI bar from Task 3.
- Produces: `_save_current_channel_config()`, `_manage_channel_config(config_id)`, `_apply_selected_channel_config(config_id)`.

- [x] **Step 1: Write failing save/overwrite/no-side-effect/replace/zero-match tests**

```python
def test_config_combo_selection_does_not_change_checked_or_replot(window, monkeypatch):
    before = _checked_pairs(window)
    replots = []
    monkeypatch.setattr(window, "_replot_canvas_for_view", lambda *a: replots.append(1))
    window.navigator.channel_list.config_bar.select_config("cfg-a")
    assert _checked_pairs(window) == before
    assert replots == []


def test_apply_config_completely_replaces_focused_selection(window):
    window._apply_selected_channel_config("cfg-a")
    assert _checked_pairs(window) == [
        ("f0", "Speed"), ("f1", "Speed"), ("f1", "Torque")
    ]


def test_zero_match_preserves_state_and_emits_nothing(window, qtbot):
    before = _checked_pairs(window)
    with qtbot.assertNotEmitted(window.navigator.channels_changed):
        window._apply_selected_channel_config("missing")
    assert _checked_pairs(window) == before
```

- [x] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_channel_scope.py -q
```

Expected: FAIL for missing config handlers.

- [x] **Step 3: Initialize one shared isolated store and populate the bar**

Use the existing `_preset_settings()` factory so `tests/ui/conftest.py` isolates settings. In `MainWindow.__init__` after `_init_ui()`:

```python
self.channel_config_store = ChannelSelectionConfigStore(self._channel_scope_settings())
self._reload_channel_config_bar()
```

- [x] **Step 4: Implement Save and explicit overwrite confirmation**

Freeze current checked raw names before opening dialogs. On conflict, show exactly:

```text
配置“动力分析”已存在
原 N 个通道 → 新 M 个通道
覆盖后无法从应用内撤销
```

Create `覆盖配置` and `取消` buttons, set Cancel as default, and call `store.overwrite(existing.config_id, frozen_names)` only after confirmation. Overwrite must not call Apply or replot.

- [x] **Step 5: Implement manage rename/delete with Cancel defaults**

The combo Manage sentinel opens actions for the selected config. Rename uses the same trim/casefold validation. Delete asks confirmation, removes the config, clears the combo selection if it was selected, and disables Apply.

- [x] **Step 6: Implement complete replacement with preflight and hidden intersection**

```python
resolution = resolve_channel_config(config, state.attached_file_ids, self.files)
if not resolution.matched:
    self.toast("配置在当前 View 的已加入文件中没有匹配通道", "warning")
    return False

next_checked = list(resolution.matched)
next_set = set(next_checked)
state.checked = next_checked
state.hidden_channels = [key for key in state.hidden_channels if key in next_set]
state.colors = {key: value for key, value in state.colors.items() if key in next_set}
if state.overlay_primary not in next_set:
    state.overlay_primary = None
self._project_view_controls(idx)
self.navigator.channels_changed.emit()
```

Before mutation, build color-bearing rows and reuse `_estimate_current_time_overlay_risk()` / `_confirm_overlay_risk()` for a dangerous overlay. Cancellation leaves state unchanged.

- [x] **Step 7: Add success/partial feedback and dirty marker**

Use bounded counts in toast/status text. Do not join unbounded missing names. Re-resolve the selected config after manual checkbox changes; set the bar dirty when `set(current_checked) != set(resolution.matched)`.

- [x] **Step 8: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config.py tests\ui\test_channel_config_bar.py tests\ui\test_view_channel_scope.py -q
git add mf4_analyzer/ui/main_window/_channel_scope_mixin.py mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/file_navigator.py tests/ui/test_view_channel_scope.py tests/ui/test_channel_config_bar.py
git commit -m "feat(ui): apply reusable channel configs"
```

Expected: PASS for create, overwrite confirm/cancel, combo no-op, rename/delete, exact complete replace, partial missing, zero-match no-op, hidden preservation, risk cancel, and one redraw.

---

### Task 8: Project Round-Trip, Grouped Loads, and Full Regression

**Files:**
- Modify: `tests/ui/test_project_session.py`
- Modify: `tests/ui/test_view_switch_integration.py`
- Modify: `tests/ui/test_file_navigator.py`
- Modify: `docs/superpowers/plans/2026-07-20-view-file-attachment-and-channel-config-implementation.md` (checkbox progress only)

**Interfaces:**
- Verifies all tasks together; produces no new production API.

- [x] **Step 1: Add project round-trip tests for explicit subsets and explicit empty Views**

Add `test_project_roundtrip_restores_timedomain_attached_file_subset`: load two
CSV fixtures through the normal window path, replace the first View's attachment
list with only the second file ID, save the project, open it in a fresh window,
and assert that the restored View contains exactly the remapped ID for the second
file and that only that file branch is visible in the channel tree.

Add `test_project_roundtrip_preserves_explicit_empty_view`: load one CSV, set the
first View's attachment list to an explicit empty list, save, open in a fresh
window, and assert both `attached_file_ids == []` and the real lower-card empty
state is visible. These tests must use the existing project save/open helpers and
must assert by restored source path rather than assuming generated IDs are stable.

- [x] **Step 2: Add a legacy fixture with no attachment field**

Write/save a normal project, remove `attached_file_ids` from each View JSON payload, reopen, and assert all successfully restored fids are attached. This test must coexist with the explicit-empty test.

- [x] **Step 3: Extend the existing multi-group HDF test**

With automatic attachment enabled, loading one two-group HDF must append both generated fids in one transaction and preserve them after project restore without duplication.

- [x] **Step 4: Run the complete focused suite**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config.py tests\ui\test_channel_config_bar.py tests\ui\test_file_navigator.py tests\ui\test_view_state.py tests\ui\test_view_bridge.py tests\ui\test_view_channel_scope.py tests\ui\test_view_switch_integration.py tests\ui\test_project_session.py -q
```

Expected: all tests PASS.

- [x] **Step 5: Run TimeDomain visibility and canvas regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ui\test_pg_timedomain_canvas.py tests\ui\test_overlay_grid_ticks.py tests\ui\test_time_filter_overlay.py -q
```

Expected: all tests PASS; the prior eye/hidden/range behavior remains intact.

- [x] **Step 6: Run repository integrity checks**

```powershell
git diff --check
rg -n -S "TODO|TBD|implement later|选择即应用|追加匹配" mf4_analyzer tests
```

Expected: `git diff --check` returns no output; grep returns no new placeholder/stale behavior in changed files.

- [x] **Step 7: Render the real navigator at minimum width**

Use an isolated `QSettings` path and `QT_QPA_PLATFORM=offscreen`; capture a screenshot showing:

- automatic-attachment icon on/off;
- empty View drop state;
- one attached file with eye column;
- Save / config combo / Apply without truncation;
- parent detach hover icon.

Compare geometry against the approved V3 prototype; no production file is changed by the probe.

- [x] **Step 8: Commit the integration coverage**

```powershell
git add tests/ui/test_project_session.py tests/ui/test_view_switch_integration.py tests/ui/test_file_navigator.py docs/superpowers/plans/2026-07-20-view-file-attachment-and-channel-config-implementation.md
git commit -m "test(ui): cover view channel configuration workflow"
```

Expected: clean working tree and all focused/integration suites green.

---

## Final Verification Checklist

- [x] Every View attachment write targets `_focused_view_idx`; no loop populates other Views.
- [x] New View creation is empty under both auto-attach states.
- [x] Combo selection changes only pending `config_id` and emits no selection/replot signal.
- [x] Existing-name Save shows old/new counts and defaults to Cancel.
- [x] Apply fully replaces `checked`, preserves only intersecting hidden keys, and does not append.
- [x] Zero matches leave `checked`, hidden state, colors, primary axis, canvas, and signal count untouched.
- [x] Global file close cleans every TimeDomain View; View detach cleans only the focused View.
- [x] Legacy missing field and explicit empty field have separate tests and opposite expected outcomes.
- [x] Grouped source drag/auto-load carries every generated fid exactly once.
- [x] Existing eye, batch-confirmation, Y-fit, X-range, overlay risk, and project restore tests pass.
