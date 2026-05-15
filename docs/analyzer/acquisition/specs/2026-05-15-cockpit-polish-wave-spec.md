# Acquisition Cockpit Polish Wave Spec

Date: 2026-05-15
Status: Execution-ready draft
Plan: `docs/analyzer/acquisition/plans/2026-05-15-cockpit-polish-wave-implementation.md`
Builds on: `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`

## Source Inputs

- Stage 0–5 execute report: `docs/analyzer/acquisition/reports/2026-05-15-cockpit-execute-report.md`
- Codex review reports CR1/CR2/CR3 (PASS_WITH_NOTES with optional follow-ups)
- v3 prototype: `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html`
- Design report §4.4 (right-click menu), §4.5 (threshold config), §7.1 (segment marker)

## Goal

Close every UI gap that does NOT require Windows + Vector hardware. After this
wave, a user on macOS or Windows can:

- Launch Cockpit from inside Analyzer via a menu/toolbar action.
- Edit preflight + ring-buffer + drop thresholds from a Settings dialog backed
  by a per-user override file.
- Browse all previously archived MF4s from a `历史` tab and open any of them
  in Analyzer with one click.
- Replay an existing MF4 through the Cockpit live charts via the `回放` tab
  (using `ReplayRecorderBackend` that already exists).
- Right-click measurements in the left pane to favorite / copy name / copy
  address / jump-to-A2L-source / batch-copy.
- Mark recording segments while a capture is live (segment metadata appears
  in `session_summary.json`).
- Ship a Windows package that includes the new `ui_kit / acquisition_capture
  / acquisition_ui` resources.

## Scope

In scope:

- Settings dialog v1 (threshold editing + persistence).
- `历史` tab (manifest-backed browser).
- `回放` tab (real implementation; replaces the `(待开放)` placeholder).
- Left-pane right-click context menus.
- Segment marker button while recording.
- Status-bar `state-aware` text audit.
- Analyzer-side menu/toolbar action `打开 Acquisition Cockpit`.
- PyInstaller spec + Windows build script update for the new packages.
- CR2 optional follow-up: unify the right-pane inline band classifiers into
  shared `band_*` helpers in `preflight_estimates.py`.
- CR3 optional follow-ups: tighten `test_discard_removes_mf4_and_sidecars` to
  use `do_save_only()` (no `_save_ok = True` backdoor); add explicit
  `assert not modal.isVisible()` to the real-flow open-in-analyzer test;
  switch the dropped-channel test to a writer-spy fixture.

Out of scope (separate specs / hardware gates):

- Real `VectorXcpRecorderBackend` and `IF_DATA XCP DAQ_EVENT` walking
  (Stage 8; needs Windows + Vector evidence).
- Auto-reconnect on XCP session loss.
- DBC raw-CAN capture workflow.
- Multi-A2L / multi-ECU selection.
- Bench Console full-screen mode (Approach D).
- Theme switching / i18n localisation.
- Sparkline algorithm upgrade (LTTB / antialiasing).
- Health-chip animation / pulsing during recording.

## Product Decisions

| Topic | Decision |
| --- | --- |
| Settings dialog scope | v1 covers threshold overrides only. Font scale / cache size / log level deferred to v2. |
| Settings persistence | Per-user `~/.acquisition-cockpit/settings.json`. NOT per-project. Project YAML stays measurement-selection-only. |
| Threshold override semantics | Override file values shadow `thresholds.py` constants at runtime; `acquisition_config.yaml.threshold_overrides` remains the reserved-not-implemented slot from the previous spec. |
| History tab data source | Reads existing manifest entries via `mf4_analyzer.acquisition.manifest.load_manifest`. No new manifest format. |
| History tab default sort | Most recent (entry order in manifest) descending. Filters: vehicle / scenario / issue_tag / set / path_kind. |
| Replay tab control | File picker (local MF4) + speed control (0.25× / 0.5× / 1× / 2× / 4×) + Play / Pause / Stop. The tab owns a read-only replay controller built on `ReplayRecorderBackend`; it must not create a `CaptureController` writer session unless the user explicitly starts a future save/trim flow. |
| Right-click menu | One menu instance, contextual to selection. Items: `⭐ 收藏 / 取消收藏` `复制名字` `复制地址` `跳到 A2L 源行` (single) + `批量设 raster…` `复制为列表` `取消选择` (multi). |
| Segment marker | Button visible only in `Recording` state, label `+ 段` (or icon). Click captures `(now - rec_start_s, custom_label_optional)`. Stored in `SessionSummary.segments`. |
| Analyzer launch entry | Add to Analyzer `工具` menu (or equivalent) AND a toolbar action. Single-instance Cockpit: if open, raise; else create. This is the explicit exception to the older "Analyzer does not import acquisition_ui" boundary: the import must be lazy inside the action handler, never at module load. |
| PyInstaller targets | Update `build/spec/MF4DataAnalyzer.spec` + `tools/build_windows_folder.ps1` to include `ui_kit / acquisition_capture / acquisition_ui` modules and `ui_kit/style.qss` data file. Use concrete hidden imports or `collect_submodules`; do not rely on a literal `widgets.*` wildcard. Existing single-EXE entry stays unchanged. |
| Right-pane band helpers | Move `_can_load_level / _disk_free_level / _duration_level / _ring_buffer_level / _samples_per_s_level` (and the inline DAQ band / dropped-frames band / last-rx-age band blocks) into `preflight_estimates.band_*` functions. Right-pane widget consumes the helpers only. |

## Settings Dialog Contract

### Layout

- Modal `QDialog` titled `Cockpit Settings`.
- Tabs: only `预检阈值` tab in v1 (other tabs reserved for v2).
- 预检阈值 tab is a form with one editor per threshold row from spec
  §Threshold Contract:
  - CAN bus load green-max / yellow-max (% sliders or spin boxes).
  - DAQ slot per event green-max / yellow-max.
  - Disk remaining green-min / yellow-min (in GB; converted to bytes internally).
  - Estimated record duration green-min / yellow-min (in hours).
  - Total sample events per second green-max / yellow-max (in 1000s).
  - Ring buffer green-max / yellow-low-max / red-max / red-drop-max (% spin).
  - Ring buffer auto-stop sustain seconds.
  - Dropped frames yellow-max-per-window / red-per-10s / prompt-total.
  - Disk free auto-stop bytes (in MB).
  - Health poll interval (ms).
  - REC last-rx yellow-min / red-min (seconds).
  - XCP yellow / red consecutive timeouts.
  - Connection timeout (seconds).
  - Default CAN bitrate (bps).
- Footer: `还原默认` button + `取消` + `保存` buttons.

### Persistence

- File: `~/.acquisition-cockpit/settings.json`.
- Schema:

  ```json
  {
    "version": 1,
    "thresholds": {
      "CAN_LOAD_GREEN_MAX_PCT": 60.0,
      "CAN_LOAD_YELLOW_MAX_PCT": 80.0,
      "...": "..."
    }
  }
  ```

  Key set is exactly the constants in `acquisition_capture.thresholds`; any
  unknown key on load raises `ConfigSchemaError`.

### Override semantics

- `mf4_analyzer.acquisition_capture.thresholds` gets new module functions:
  `default_user_settings_path()`, `load_user_settings(path: Path | None = None)`,
  `save_user_settings(payload, path: Path | None = None)`,
  `apply_overrides(overrides: Mapping[str, float | int])`, and
  `reset_defaults()`.
- `thresholds.py` keeps a private immutable defaults snapshot and a
  `VALID_THRESHOLD_KEYS` set derived from the editable constants. Unknown keys
  or non-numeric values raise `ConfigSchemaError`.
- Settings dialog calls `apply_overrides` on Save; the in-memory cockpit picks
  up new values immediately (band helpers and preflight estimates re-read the
  module constants per call, no caching).
- `acquisition_capture` `__init__.py` MAY auto-load the settings file once on
  package import (best effort; silent fall-back to defaults on missing/corrupt
  file).
- `还原默认` writes a "blank" settings file (`{"version": 1, "thresholds": {}}`)
  and calls `reset_defaults()`. Do not reset by re-importing the module.
- Tests MUST use a temp settings path (or monkeypatched `HOME`) and must call
  `reset_defaults()` in teardown so threshold overrides do not leak across the
  process.

### Tests

- `test_settings_schema_round_trip` — write + reload + assert key set.
- `test_settings_apply_overrides_changes_band_helpers` — call
  `apply_overrides({"CAN_LOAD_GREEN_MAX_PCT": 10})` and assert
  `band_can_load(15)` flips from green to yellow.
- `test_settings_dialog_save_persists_to_disk` (Qt offscreen).
- `test_settings_dialog_reset_to_defaults_writes_empty_overrides`.

## History Tab Contract

### Layout

- Tab body is a single `QTableView` with columns:
  - 录制时间 (manifest entry order or explicit timestamp if present).
  - vehicle / platform / scenario / sets / issue_tags / path_kind.
  - 文件大小 (computed at view time; "n/a" for non-local entries).
  - 状态: `本地` / `LFS` / `外部 (NAS)` / `缺失` (path resolves vs is unavailable).
- Filter row at top: dropdowns for vehicle, scenario, path_kind, set; chip
  toggles for issue_tags; free-text search by name/id.
- Double-click row → load via Analyzer handoff (`MainWindow.load_file`).
- Right-click row → menu: `在 Analyzer 打开` / `复制路径` / `打开所在目录`.

### Data source

- Read manifest with `mf4_analyzer.acquisition.manifest.load_manifest` from a
  configurable path. v1 default: `<project_root>/manifest.json`. If missing,
  show "未找到 manifest" empty-state with a button to point at a file.
- Resolve each row's path with
  `mf4_analyzer.acquisition.manifest.resolve_entry_path(entry, manifest_path=...)`
  so relative manifest paths are interpreted next to the manifest file, not
  against the current working directory.

### Background work

- Path resolution (existence + size) runs in a `QRunnable` (or `QtConcurrent`
  thread pool) so UI does not block when manifest contains non-local entries.
- Failed resolution → `状态` column shows `缺失` red chip, no exception
  surfaces to the user.

### Tests

- `test_history_tab_loads_manifest`.
- `test_history_tab_double_click_opens_in_analyzer`.
- `test_history_tab_filter_by_vehicle`.
- `test_history_tab_missing_path_is_not_fatal`.

## Replay Tab Contract

### Layout

- File picker (`QPushButton` → `QFileDialog`) for the source MF4.
- Speed segmented control `0.25× / 0.5× / 1× / 2× / 4×`; default `1×`.
- Transport buttons: `▶ Play / ⏸ Pause / ⏹ Stop`.
- Position slider that reflects current replay time.
- Body below the transport reuses the same widget classes as the capture path
  (`LiveCardGrid` and the recording-quality `RightPanel` variant), but the
  replay tab owns its own instances so playback does not interfere with live
  capture state.

### State machine

- Replay loads samples from an existing MF4 into `ReplayRecorderBackend`
  (`source_samples` plus a `speed_multiplier`), starts that backend, and drains
  it from a tab-local `QTimer`.
- `ReplayRecorderBackend` must support an MF4-to-samples helper that uses the
  existing loader/asammdf path and emits sorted `(channel, timestamp_s, value)`
  tuples. It must keep the existing synthetic `source_samples=None` behavior for
  tests.
- During replay, the Cockpit top-level capture state remains unchanged; replay
  has tab-local states `idle / playing / paused / stopped`.
- Replay is read-only in this wave: it does NOT create a writer, does NOT write
  `session_summary.json`, and does NOT write `manifest.json`. A future explicit
  save/trim flow can reuse Stage-5 review concepts under a separate spec.

### Tests

- `test_replay_tab_loads_existing_mf4`.
- `test_replay_speed_control_changes_emit_rate`.
- `test_replay_stop_returns_to_stopped_without_capture_state_change`.

## Right-click Context Menu Contract

### Single-row menu

| Item | Behavior |
| --- | --- |
| `⭐ 收藏` / `取消收藏` | Toggle entry in `acquisition_config.yaml.favorites`. |
| `复制名字` | Copy `measurement.name` to clipboard. |
| `复制地址` | Copy `0x{measurement.address:08X}` to clipboard. |
| `跳到 A2L 源行` | If A2L source line is available in the parsed model, focus the row in a placeholder `A2L Source` dock (deferred; v1 just opens the A2L file in the OS's default editor at the entry line if possible — best-effort). |

### Multi-row menu

| Item | Behavior |
| --- | --- |
| `批量设 raster …` | Reuses the existing batch-raster dropdown popup; only shows when `build_event_intersection(selected)` is non-empty. |
| `复制为列表` | Copy `name\tphys_unit\thex_address` lines, tab-separated. |
| `取消选择` | Deselect every row in the current selection. |

### Tests

- `test_left_pane_single_row_menu_actions` (copy clipboard assertions).
- `test_left_pane_multi_row_menu_intersection_disabled_when_empty`.
- `test_left_pane_favorite_toggle_writes_acquisition_config`.

## Segment Marker Contract

### UI

- Toolbar action visible only when `state == Recording`. Label `+ 段` /
  icon (use existing icon library). Tooltip: `标记一段 (M)`.
- Shortcut `M` while in Recording state.
- Click opens a small `QInputDialog` for optional segment label (Esc /
  empty = unlabeled).

### Data flow

- On click, `CaptureController.mark_segment(label: str | None)` closes the
  current open segment at `now - rec_start_s` and starts the next segment at the
  same timestamp with the optional label. The stop path closes the final open
  segment.
- `SessionSummary.segments` already exists; new entries land in there. The
  top-level `SessionSummary` key set is unchanged, but the inner segment dict
  may add optional `"label": str | null`.
- Spec §Persistence Contract field set is unchanged (`segments` was already
  a list of dicts; labels are an optional `label` key per entry — additive,
  not breaking).

### Tests

- `test_capture_controller_mark_segment_appends`.
- `test_segment_button_only_visible_in_recording_state` (Qt offscreen).
- `test_segment_label_dialog_records_label_in_summary`.

## Status Bar Text Audit

Verify each state's status-bar text matches spec §Status Bar:

| State | Text format |
| --- | --- |
| Disconnected | `未连接 · A2L: <name or 未加载>` |
| Connected idle | `streaming · <evt/s> · buf <ring_pct>%` |
| Recording | `RECORDING · <elapsed mm:ss> · <samples> · <file_size MB> · drop <n> · buf <ring_pct>%` |

If current implementation deviates, fix; do not introduce new fields.

## Analyzer Launch Integration

### Menu / toolbar entry

- Add `工具 → 打开 Acquisition Cockpit` to Analyzer's menu bar.
- Add a corresponding toolbar action (icon: same line-icon family as the
  existing Analyzer toolbar).

### Single-instance behavior

- Action handler scans `QApplication.topLevelWidgets()` for an existing
  `CockpitMainWindow`. If found, call `raise_()` + `activateWindow()`. If
  not, instantiate `CockpitMainWindow()` and call `show()`.
- Cockpit creation must NOT block on heavy A2L parsing — defer A2L load
  until the user actually picks one (the toolbar already gates this).
- Import `CockpitMainWindow` lazily inside the handler. Existing Analyzer
  module imports and app startup must remain free of `mf4_analyzer.acquisition_ui`
  imports until the action is invoked.
- The toolbar action uses the existing custom `mf4_analyzer.ui.toolbar.Toolbar`
  surface; do not assume Analyzer already has a native `QToolBar`.

### Bidirectional handoff

- Cockpit → Analyzer is already implemented via `MainWindow.load_file`.
- Analyzer → Cockpit is NEW: just opens / raises Cockpit; no file payload.

### Tests

- `test_analyzer_toolbar_opens_cockpit_when_none_open`.
- `test_analyzer_toolbar_raises_existing_cockpit`.
- `test_cockpit_creation_does_not_load_a2l_eagerly`.

## PyInstaller / Windows Build Contract

### Files to update

- `build/spec/MF4DataAnalyzer.spec` (or equivalent — confirm exact filename
  during Stage 0; older docs reference `build/spec/MF4DataAnalyzer.spec`).
  Add hidden imports:
  - `mf4_analyzer.ui_kit`
  - `mf4_analyzer.ui_kit.icons`
  - `mf4_analyzer.ui_kit.fonts`
  - `mf4_analyzer.ui_kit.stylesheet`
  - `mf4_analyzer.ui_kit.widgets.searchable_combo`
  - `mf4_analyzer.acquisition_capture`
  - `mf4_analyzer.acquisition_capture.thresholds`
  - `mf4_analyzer.acquisition_capture.health`
  - `mf4_analyzer.acquisition_capture.ring_buffer`
  - `mf4_analyzer.acquisition_capture.backends`
  - `mf4_analyzer.acquisition_capture.controller`
  - `mf4_analyzer.acquisition_capture.writer`
  - `mf4_analyzer.acquisition_capture.session`
  - `mf4_analyzer.acquisition_capture.search`
  - `mf4_analyzer.acquisition_capture.a2l_events`
  - `mf4_analyzer.acquisition_capture.config_store`
  - `mf4_analyzer.acquisition_capture.preflight_estimates`
  - `mf4_analyzer.acquisition_ui`
  - `mf4_analyzer.acquisition_ui.main_window`
  - `mf4_analyzer.acquisition_ui.state`
  - `mf4_analyzer.acquisition_ui.review_modal`
  - `mf4_analyzer.acquisition_ui.settings_dialog`
  - `mf4_analyzer.acquisition_ui.history_tab`
  - `mf4_analyzer.acquisition_ui.replay_tab`
  - concrete modules under `mf4_analyzer.acquisition_ui.widgets`
    (`health_strip`, `left_pane`, `live_cards`, `live_downsampler`,
    `right_panel`) or `collect_submodules("mf4_analyzer.acquisition_ui.widgets")`
  Add data files:
  - `mf4_analyzer/ui_kit/style.qss` → `mf4_analyzer/ui_kit/style.qss`
  Keep existing hidden imports / data files untouched.
- `tools/build_windows_folder.ps1` already points at
  `mf4_analyzer\ui_kit\style.qss` for `$StyleQss` (S1 updated it). Verify the
  `--hidden-import` argument list covers all new modules.

### Verification gate

- On macOS dev: `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app` still
  launches with no missing-module warnings.
- On macOS dev: `PYTHONPATH=. .venv/bin/python -c "import
  mf4_analyzer.acquisition_ui.main_window; import
  mf4_analyzer.acquisition_capture.controller"` succeeds.
- On Windows host (any time): `powershell -ExecutionPolicy Bypass -File
  tools\build_windows_folder.ps1` produces `dist\MF4DataAnalyzer\` and the
  packaged EXE opens Analyzer; clicking `工具 → 打开 Acquisition Cockpit`
  opens Cockpit.

### Tests

- `test_pyinstaller_spec_lists_new_modules` (static parse of the spec file).
- Smoke: import every module the spec mentions in a `tests/test_packaging_imports.py`.

## Band Helpers Migration (CR2 follow-up)

### Move targets

From `mf4_analyzer/acquisition_ui/widgets/right_panel.py` lines 65–94 (and
inline blocks at 267–272 / 362–367 / 380–385) into
`mf4_analyzer/acquisition_capture/preflight_estimates.py` as:

```text
band_can_load(pct: float) -> str
band_daq_slot(pct: float) -> str
band_record_duration_s(seconds: float) -> str
band_ring_buffer(pct: float) -> str
band_dropped_frames(count: int) -> str
band_rec_last_rx_age_s(age_s: float) -> str
```

Right-pane widget keeps `_format_band_value` (the HTML colour wrapper) but
imports the helpers from `preflight_estimates`. No raw threshold constants
remain in `right_panel.py`.

### Tests

- `test_band_can_load_*`, `test_band_daq_slot_*`, etc. — one green / yellow /
  red test per helper, plus boundary values. Mirrors the existing
  `band_disk_remaining` / `band_sample_events_per_s` test style.

## CR3 Optional Follow-ups (Bundled)

- `tests/acquisition_ui/test_review_handoff.py::test_discard_removes_mf4_and_sidecars`
  — replace `modal._save_ok = True` with `modal.do_save_only()` and assert the
  same post-conditions through the public API.
- `tests/acquisition_ui/test_review_handoff.py::test_cockpit_archive_then_open_in_analyzer_real_flow`
  — add `assert not modal.isVisible()` after `modal.do_open_in_analyzer()`.
- `tests/acquisition_ui/test_review_handoff.py::test_cockpit_archive_preserves_selected_names_on_dropped_channel`
  — replace the stop-result patch with a writer spy that emits only 2 of the 3
  selected channels. The assertions stay identical.

## Acceptance Gates

Existing suites stay green:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
PYTHONPATH=. .venv/bin/python scripts/acquisition_smoke.py --skip-regression
```

New suites pass:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_settings_dialog.py \
  tests/acquisition_ui/test_history_tab.py \
  tests/acquisition_ui/test_replay_tab.py \
  tests/acquisition_ui/test_right_click_menu.py \
  tests/acquisition_ui/test_segment_marker.py \
  tests/acquisition_ui/test_status_bar_text.py \
  tests/ui/test_analyzer_opens_cockpit.py \
  tests/test_acquisition_settings_overrides.py \
  tests/test_acquisition_band_helpers.py \
  tests/test_packaging_imports.py -v
```

Manual demo gate:

```bash
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app
# In Analyzer: 工具 → 打开 Acquisition Cockpit
# In Cockpit: open Settings, edit CAN load green-max from 60 to 50, Save.
# Connect to fake backend, watch CAN row turn yellow at 51%.
# Switch to 历史 tab, open a manifest, double-click an entry, see Analyzer load it.
# Switch to 回放 tab, pick /tmp/cr3_e2e.mf4, press Play, see live cards stream.
# Mark a segment during a fake capture, stop, verify session_summary.segments.
```

Windows packaging gate (run on Windows host):

```powershell
.\.venv\Scripts\python.exe -m pytest tests\acquisition_ui tests\ui\test_main_window_smoke.py -v
powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1
.\dist\MF4DataAnalyzer\MF4DataAnalyzer.exe   # then click the cockpit menu
```
