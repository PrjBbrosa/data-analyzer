# Acquisition Cockpit Polish Wave Implementation Plan

> Stage-scoped execution path. Each stage owns a disjoint file set; later
> stages depend on earlier-stage symbols but do not edit them.

Date: 2026-05-15
Status: Execution-ready draft
Spec: `docs/analyzer/acquisition/specs/2026-05-15-cockpit-polish-wave-spec.md`

## Goal

Turn the post-Stage-5 cockpit into a ship-ready product on macOS dev + Windows
packaged build, by closing every non-Vector UI gap in one wave: Settings
dialog, 历史 tab, 回放 tab, right-click menus, segment marker, status-bar
audit, Analyzer launch entry, PyInstaller packaging, plus the CR2 + CR3
optional follow-ups bundled in.

## Non-Negotiable Constraints

- Keep all new analyzer-facing docs under `docs/analyzer/acquisition/`.
- Use `.venv/bin/python` or `PYTHONPATH=. .venv/bin/python` in executable doc
  commands.
- Do not modify `_load_one(fp)` in `mf4_analyzer/ui/main_window.py`; only the
  Stage-7 launch action is allowed to add new public methods.
- Analyzer may import `mf4_analyzer.acquisition_ui.main_window.CockpitMainWindow`
  only lazily inside `open_acquisition_cockpit()`. No module-load import from
  `mf4_analyzer.ui` to `mf4_analyzer.acquisition_ui`.
- Do not import Vector / python-can / pyxcp at module load time.
- Do not edit `mf4_analyzer/acquisition/` source files (validation program —
  consume via existing public functions only).
- Do not change spec field-sets that the previous wave pinned exact (e.g.
  `SessionSummary` 12-key set — segment label is an inner-list optional key,
  not a new top-level key).
- `tests/acquisition_ui` and `tests/test_acquisition_capture_*` suites must
  stay green through every stage exit gate.

## Branch Strategy

Recommended sequence on a fresh branch off `feat/acquisition` (or off the
merged `main` once PR #11 lands):

```bash
git switch -c feat/acquisition-cockpit-polish
```

Each stage commits separately; merging happens at the end.

## Parallel Dispatch Notes

To keep multi-agent work conflict-free, workers should first land standalone
surfaces and tests. `mf4_analyzer/acquisition_ui/main_window.py` is the main
integration hotspot; if more than one worker needs it, prefer adding new
module-level APIs in owned files and leave final main-window wiring to the
coordinator.

Suggested independent slices:

- Worker A: Stage 1 band helpers (`preflight_estimates.py`, `right_panel.py`,
  focused tests).
- Worker B: Stage 2 Settings core/dialog (`thresholds.py`,
  `settings_dialog.py`, settings tests). Avoid unrelated tab wiring.
- Worker C: Stage 3 History tab (`history_tab.py`, standalone tests).
- Worker D: Stage 4 Replay backend/tab (`backends.py`, `replay_tab.py`,
  replay tests).
- Worker E: Stage 5 polish core (`left_pane.py`, `config_store.py`,
  `controller.py`, related tests). Keep `main_window.py` changes minimal and
  clearly marked for coordinator review.
- Worker F: Stage 6/7 Analyzer launch + packaging (`mf4_analyzer/ui/*`,
  `build/spec/*`, `tools/build_windows_folder.ps1`, packaging tests).

## Stage 0 — Preflight & Baseline

**Goal:** Confirm previous-wave state is green and pin baselines.

**Files:** read-only.

**Tasks:**

- [ ] Read CR1/CR2/CR3 reports under `docs/analyzer/acquisition/reports/` for
  the optional follow-ups list; cross-check against this plan's Stage 6.
- [ ] Confirm `mf4_analyzer/acquisition_capture/thresholds.py` exposes every
  constant the Settings dialog will edit (per spec §Settings Dialog Contract
  field list). If any is missing (unlikely; CR1 already inventoried them),
  flag and stop — do NOT add to `thresholds.py` in Stage 0.
- [ ] Confirm `mf4_analyzer/acquisition/manifest.py` exposes
  `load_manifest(path)` and `Mf4DatasetEntry` (the 历史 tab consumes these).
- [ ] Confirm `mf4_analyzer/acquisition_capture/backends.py` has a working
  `ReplayRecorderBackend`. If MF4-path replay is still absent, record it as
  the expected Stage 4 implementation gap rather than blocking Stage 0.
- [ ] Locate the real PyInstaller spec filename (S1 / S5 reports reference
  `build/spec/MF4DataAnalyzer.spec` — verify it exists). Record the path in
  the Stage 0 note.
- [ ] Re-run the full pre-existing suite to pin a green baseline:

  ```bash
  PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
  PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
  ```

**Deliverable:** `docs/analyzer/acquisition/reports/2026-05-15-cockpit-polish-stage0-note.md`
listing baselines + the actual PyInstaller spec path + any open follow-ups.

**Exit criteria:** all pre-existing suites green; PyInstaller spec path
confirmed.

## Stage 1 — Band Helpers Refactor (CR2 follow-up)

**Goal:** Move every right-pane inline band classifier into shared
`band_*` helpers in `preflight_estimates.py`.

**Owned files:**

- Modify: `mf4_analyzer/acquisition_capture/preflight_estimates.py` (add 6 new
  helpers).
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py` (remove inline
  classifiers; consume the new helpers).
- Create: `tests/test_acquisition_band_helpers.py`.
- Modify: `tests/test_acquisition_preflight_estimates.py` (add cross-reference
  smoke that uses the new helpers).

**Tasks:**

- [ ] Write tests first (TDD red phase): green / yellow / red + boundary case
  for each of `band_can_load`, `band_daq_slot`, `band_record_duration_s`,
  `band_ring_buffer`, `band_dropped_frames`, `band_rec_last_rx_age_s`.
- [ ] Implement each helper. Constants come from
  `mf4_analyzer.acquisition_capture.thresholds`.
- [ ] Replace `_can_load_level / _disk_free_level / _duration_level /
  _ring_buffer_level / _samples_per_s_level` (already removed) and the
  inline `if/elif` blocks in `IdlePreflightPage.apply` (DAQ band) and
  `RecordingQualityPage.apply` (dropped, last-rx-age) with imports + calls.
- [ ] Grep `right_panel.py` for any remaining `thresholds.*_MAX_PCT` /
  `*_MIN_S` direct access; should be zero after the refactor.

**Verification:**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_band_helpers.py tests/test_acquisition_preflight_estimates.py -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_right_panel.py -v
```

**Exit criteria:** new helpers pass; right-panel tests still pass; zero
threshold-constant references in `right_panel.py`.

## Stage 2 — Settings Dialog v1 + Threshold Overrides

**Goal:** Make every spec-§Threshold-Contract constant editable from a
modal dialog with per-user persistence.

**Owned files:**

- Modify: `mf4_analyzer/acquisition_capture/thresholds.py` — add
  `default_user_settings_path()`, `load_user_settings(path: Path | None = None)`,
  `save_user_settings(payload, path: Path | None = None)`,
  `apply_overrides(overrides: Mapping[str, float | int]) -> None`,
  `reset_defaults()`, and `VALID_THRESHOLD_KEYS`.
- Modify: `mf4_analyzer/acquisition_capture/__init__.py` — auto-invoke
  `apply_overrides(load_user_settings())` once on import (silent on failure).
- Create: `mf4_analyzer/acquisition_ui/settings_dialog.py` —
  `SettingsDialog(QDialog)` with the 预检阈值 tab form.
- Modify: `mf4_analyzer/acquisition_ui/main_window.py` — add a toolbar
  `Settings` action (gear icon) that opens the dialog modally.
- Create: `tests/acquisition_ui/test_settings_dialog.py`.
- Create: `tests/test_acquisition_settings_overrides.py`.

**Tasks:**

- [ ] Tests first: schema round-trip, apply_overrides round-trip, dialog
  save persists to disk, reset writes empty overrides, dialog cancels
  without writing.
- [ ] Implement `apply_overrides` and `load_user_settings` with explicit
  `encoding='utf-8'` per
  `docs/lessons-learned/signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md`.
- [ ] `apply_overrides` validates unknown keys and non-numeric values with
  `ConfigSchemaError`; tests call `reset_defaults()` in teardown so overrides
  cannot leak into later tests.
- [ ] Implement `SettingsDialog` UI. Form rows use `QSpinBox` /
  `QDoubleSpinBox`; unit conversion (GB ↔ bytes, hours ↔ seconds, kHz ↔ Hz)
  inside the dialog only — the on-disk schema uses the same numeric units as
  `thresholds.py` constants.
- [ ] Wire `Settings` toolbar action in `CockpitMainWindow`.
- [ ] After Save, force a `HealthAggregator.poll_once()` + `RightPanel.show_*`
  refresh so chip colours update immediately.

**Verification:**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_settings_overrides.py -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_settings_dialog.py -v
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test
```

**Exit criteria:** edit-Save-reflect cycle works in offscreen tests; settings
file lives at `~/.acquisition-cockpit/settings.json`; reset writes
`{"version": 1, "thresholds": {}}`.

## Stage 3 — 历史 Tab

**Goal:** Implement the secondary `历史` tab as a manifest-backed browser.

**Owned files:**

- Create: `mf4_analyzer/acquisition_ui/history_tab.py` — `HistoryTab(QWidget)`
  with `QTableView`, filter row, double-click handler.
- Modify: `mf4_analyzer/acquisition_ui/main_window.py` — replace the
  `(待开放)` placeholder in the `历史` tab body with `HistoryTab`. Add a
  `set_manifest_path(path)` method so the user can point at a non-default
  manifest.
- Create: `tests/acquisition_ui/test_history_tab.py`.

**Tasks:**

- [ ] Tests first: load manifest with 3+ entries, filter by vehicle reduces
  rows, double-click invokes `MainWindow.load_file`, missing-path entry shows
  red `缺失` chip, empty-state when no manifest.
- [ ] Implement table model that wraps `list[Mf4DatasetEntry]`.
- [ ] Resolve local paths with `resolve_entry_path(entry, manifest_path=...)`;
  do not resolve relative entries against the process working directory.
- [ ] Implement filter row (vehicle / scenario / path_kind dropdowns; tag chips;
  search box).
- [ ] Implement background path-resolution via `QThreadPool` + `QRunnable`;
  results land via Qt queued signal.
- [ ] Wire double-click → emit `analyzer_open_requested(path)` and connect it
  through the same Cockpit `_on_analyzer_open_requested` bridge used by the
  review modal.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_history_tab.py -v
```

**Exit criteria:** browser usable on a manifest produced by Stage-5 archive
flow; missing-path entries surface but never crash.

## Stage 4 — 回放 Tab

**Goal:** Replace the `(待开放)` placeholder with a real replay UI driven by
`ReplayRecorderBackend`.

**Owned files:**

- Create: `mf4_analyzer/acquisition_ui/replay_tab.py` — `ReplayTab(QWidget)`,
  read-only replay controller, tab-local live cards/right-panel instances.
- Modify: `mf4_analyzer/acquisition_ui/main_window.py` — install
  `ReplayTab` into the `回放` tab body. Do NOT route replay through a
  `CaptureController` writer session.
- Modify: `mf4_analyzer/acquisition_capture/backends.py::ReplayRecorderBackend`
  add `speed_multiplier` and an MF4-to-`source_samples` helper. Keep the
  existing synthetic/source-samples behavior additive.
- Create: `tests/acquisition_ui/test_replay_tab.py`.

**Tasks:**

- [ ] Tests first: load an MF4 + Play → tab-local replay state is `playing`;
  speed control changes ReplayRecorderBackend's emit rate; Stop returns replay
  tab to `stopped` without changing Cockpit capture state.
- [ ] Implement file picker + speed segmented control + transport row +
  position slider.
- [ ] During replay, keep live capture controls disabled only inside the replay
  tab; switching back to `采集` restores the normal capture controls.
- [ ] Replays do NOT create a writer, do NOT write `session_summary.json`, and
  do NOT write to `manifest.json` in this wave.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_replay_tab.py -v
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_capture --backend fake --duration 2 --output /tmp/replay_input.mf4
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo  # manually: 回放 tab → pick /tmp/replay_input.mf4 → Play
```

**Exit criteria:** replay drives live cards with the same visuals as capture;
Stop returns cleanly.

## Stage 5 — Polish: Right-click Menu + Segment Marker + Status Bar Audit + CR3 Follow-ups

**Goal:** Close the remaining UX gaps from the design report and the optional
CR3 follow-ups. One mixed stage because each item is small and they share
test files.

**Owned files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py` — install
  `customContextMenuRequested` handler; populate single-row vs multi-row
  menu per spec.
- Modify: `mf4_analyzer/acquisition_capture/config_store.py` — add
  `toggle_favorite(name)` if not already present.
- Modify: `mf4_analyzer/acquisition_capture/controller.py` — add
  `mark_segment(label: str | None = None) -> None`. The implementation
  closes the current open segment at `now`, starts a new segment at the same
  timestamp, and stores `label` on the newly-open segment. The stop path closes
  the final open segment.
- Modify: `mf4_analyzer/acquisition_ui/main_window.py` —
  add a `+ 段` toolbar action visible only in `Recording`; keyboard shortcut
  `M`; status-bar text audit per spec §Status Bar.
- Modify: `tests/acquisition_ui/test_review_handoff.py` — CR3 follow-ups
  (use `do_save_only()` in discard test; `assert not modal.isVisible()` in
  real-flow test; writer-spy fixture in dropped-channel test).
- Create: `tests/acquisition_ui/test_right_click_menu.py`.
- Create: `tests/acquisition_ui/test_segment_marker.py`.
- Create: `tests/acquisition_ui/test_status_bar_text.py`.
- Modify: `tests/test_acquisition_capture_controller.py` — add
  `test_mark_segment_appends_to_summary`.

**Tasks:**

- [ ] Tests first across the three new files.
- [ ] Implement right-click menu items, wiring each to the
  clipboard / config_store / batch-raster popup as spec says.
- [ ] Implement `mark_segment` + button + shortcut.
- [ ] Audit `_update_status_bar()` (or the equivalent) in Cockpit
  `main_window.py`; align each state's text with spec §Status Bar exactly.
- [ ] Apply CR3 follow-ups inside `test_review_handoff.py`.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_right_click_menu.py \
  tests/acquisition_ui/test_segment_marker.py \
  tests/acquisition_ui/test_status_bar_text.py \
  tests/acquisition_ui/test_review_handoff.py -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_capture_controller.py -v
```

**Exit criteria:** each new test green; CR3 follow-up tests no longer touch
private attributes; status-bar text round-trip matches spec.

## Stage 6 — Analyzer Launch Integration

**Goal:** Add the cockpit entry point inside Analyzer.

**Owned files:**

- Modify: `mf4_analyzer/ui/main_window.py` — add (ONLY) a public method
  `open_acquisition_cockpit() -> None`, a `工具 → 打开 Acquisition Cockpit`
  menu action, and a toolbar action with a line icon. Do NOT touch
  `_load_one` or any other existing surface.
- Modify: `mf4_analyzer/ui/toolbar.py` — expose a custom toolbar button/signal
  for the cockpit action. `mf4_analyzer/app.py` should not need cockpit-specific
  imports.
- Create: `tests/ui/test_analyzer_opens_cockpit.py`.

**Tasks:**

- [ ] Tests first: action opens new Cockpit when none exists; action raises
  existing Cockpit when one is open; Cockpit creation does not block on A2L.
- [ ] Implement `open_acquisition_cockpit` body:
  ```python
  from PyQt5.QtWidgets import QApplication

  def open_acquisition_cockpit(self) -> None:
      from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

      for w in QApplication.topLevelWidgets():
          if isinstance(w, CockpitMainWindow):
              w.raise_(); w.activateWindow()
              return
      cockpit = CockpitMainWindow(); cockpit.show()
  ```
- [ ] Install the menu action and toolbar action. Use existing icon family;
  if no fitting icon exists in `ui_kit/icons`, add a minimal one and
  reference it by placeholder name.
- [ ] Add/import-boundary test proof that `mf4_analyzer.ui.main_window` can be
  imported without importing `mf4_analyzer.acquisition_ui.main_window` first.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analyzer_opens_cockpit.py tests/ui/test_main_window_smoke.py -v
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app  # manual: 工具 → 打开 Acquisition Cockpit
```

**Exit criteria:** Analyzer smoke remains green; cockpit opens / raises as
expected.

## Stage 7 — PyInstaller Spec + Windows Build Verification

**Goal:** Package the new modules so the Windows distribution includes
ui_kit / acquisition_capture / acquisition_ui.

**Owned files:**

- Modify: `build/spec/MF4DataAnalyzer.spec` (or actual spec filename from
  Stage 0 note) — add the hidden-imports + datas listed in spec
  §PyInstaller / Windows Build Contract.
- Modify: `tools/build_windows_folder.ps1` — verify `--hidden-import`
  arguments or `--collect-submodules` cover the new modules, including
  `settings_dialog`, `history_tab`, `replay_tab`, and concrete widget modules.
- Create: `tests/test_packaging_imports.py` — static parse of the spec file
  plus a runtime smoke that imports every new module on macOS.

**Tasks:**

- [ ] Static parse test: open the spec file, ensure each module name from the
  spec's hidden-imports list is present.
- [ ] Runtime import smoke: a single test that `importlib.import_module` over
  every new module name; fails loudly if any module is missing.
- [ ] On macOS: rerun `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app` to
  prove no breakage.
- [ ] On Windows host (deferred to user, but documented):

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests\acquisition_ui tests\ui\test_main_window_smoke.py tests\test_packaging_imports.py -v
  powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1
  .\dist\MF4DataAnalyzer\MF4DataAnalyzer.exe
  ```

**Exit criteria:** static parse + runtime smoke pass on macOS; Windows
packaging step ready to run when a Windows host is available.

## Stage 8 — Final Rollup & Report

**Goal:** Verify the full polish wave is consistent and write the execution
report.

**Owned files:**

- Create: `docs/analyzer/acquisition/reports/2026-05-15-cockpit-polish-execute-report.md`.

**Tasks:**

- [ ] Run the full rollup:

  ```bash
  PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
  PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
  PYTHONPATH=. .venv/bin/python scripts/acquisition_smoke.py --skip-regression
  PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py -v
  rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
  rg -n '(^|[`[:space:]+])python scripts/|expected[_]signals' docs/analyzer/acquisition
  git diff --check
  ```
- [ ] Run the manual demo gate from spec §Acceptance Gates.
- [ ] Write the report with per-stage outcomes, test counts, screenshots of
  the new Settings dialog / 历史 tab / 回放 tab if reasonable, plus the
  deferred-work list (Stage 8 of the original plan, Vector hardware, raw CAN,
  Bench Console, theme switching).

**Exit criteria:** rollup green; report at the path above; ready to merge.

## Final Rollup Gate

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py -v
PYTHONPATH=. .venv/bin/python scripts/acquisition_smoke.py --skip-regression
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
rg -n '(^|[`[:space:]+])python scripts/|expected[_]signals' docs/analyzer/acquisition
git diff --check
```

Manual:

- `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app` → open Cockpit via
  `工具 → 打开 Acquisition Cockpit`.
- Settings → edit a threshold → Save → verify chip colour changes.
- 历史 tab → open default manifest → double-click row → Analyzer loads it.
- 回放 tab → pick `/tmp/replay_input.mf4` → Play → live cards stream.
- Live capture → mark segment → Stop → review modal shows segments list +
  `auto_stop` flag where appropriate.
- Right-click a measurement in the left pane → copy name → confirm clipboard.

## Defaults Locked For This Wave

- Settings dialog has only the 预检阈值 tab; other tabs reserved for v2.
- Settings persistence lives at `~/.acquisition-cockpit/settings.json` (per-user).
- 历史 tab default manifest path is `<project_root>/manifest.json`.
- 回放 tab speed defaults to `1×`; speeds: 0.25 / 0.5 / 1 / 2 / 4.
- Right-click `跳到 A2L 源行` is best-effort (OS default editor at line
  number if pya2l surfaces it; silent no-op otherwise).
- Segment marker shortcut is `M`; only active during `Recording`.
- Analyzer toolbar action goes under `工具` menu; toolbar icon is a line icon
  in the existing family.
- PyInstaller spec lives at the path resolved in Stage 0.
- macOS builds do not exercise Vector / raw CAN; Windows packaging exercise
  is captured by `tools/build_windows_folder.ps1` on the Windows host.
