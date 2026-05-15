# Acquisition Cockpit UI Implementation Plan

> For agentic workers: keep work stage-scoped. Use separate branches or
> separate agents only when file ownership is disjoint. Do not edit Analyzer
> behavior while implementing capture services, and do not edit capture services
> while doing pure `ui_kit` extraction unless the stage explicitly says so.

Date: 2026-05-15
Status: Execution-ready draft
Spec: `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`

## Goal

Turn the approved v3 Acquisition Cockpit design into an executable staged
implementation path. The first production value is reliable recording and
finalized-file handoff, while the UI keeps the capture-first mental model:
live stream after connection, record button starts disk writing, preflight and
manifest are post-record review actions.

## Non-Negotiable Constraints

- Keep new analyzer-facing docs under `docs/analyzer/acquisition/`.
- Use `.venv/bin/python` or `PYTHONPATH=. .venv/bin/python` in executable doc
  commands.
- Do not add acquisition as a new Analyzer mode.
- Do not let post-record diagnostics block saving raw capture.
- Do not import Vector/python-can/pyxcp at normal macOS import time.
- Do not hand Analyzer an MF4 until the writer has flushed, closed, and
  finalized it.
- Leave existing loader behavior unchanged: no edits to
  `DataLoader.load_mf4` for this feature.

## Source Decision Map

| Decision | Source | Implementation meaning |
| --- | --- | --- |
| Approach A partner window | `2026-05-14-cockpit-ui-design-report.md` | New `mf4_analyzer/acquisition_ui/` package, no Analyzer mode pivot. |
| v3 single-window four-state model | `2026-05-14-acquisition-ui-option-a-v3.html` | Implement explicit state model before painting complex widgets. |
| Health strip as truth source | v3 prototype | `HW/CAN/XCP/DAQ/REC` model and UI tests come before record button wiring. |
| A2L search/raster panel | design report + v3 prototype | Pure search/filter/event model first; Qt tree consumes that model. |
| Capture-first priority | `2026-05-15-capture-priority-replay-findings.md` | Recorder/session core precedes production UI release. |
| P0 hardware remains partial | `P0_Runbook.md` | Fake/replay UI may proceed; Vector/XCP PASS waits for Windows evidence. |
| Existing validation ladder | validation roadmap | Preflight/replay remain diagnostic evidence after capture. |

## Branch Strategy

Recommended sequence:

```bash
git switch -c feat/acquisition-cockpit-ui-kit
git switch -c feat/acquisition-capture-core
git switch -c feat/acquisition-cockpit-shell
git switch -c feat/acquisition-cockpit-review-handoff
git switch -c feat/acquisition-cockpit-vector-gate
```

If the team prefers one branch, keep commits grouped by the stages below and do
not interleave unrelated file ownership.

## Stage 0 - Preflight The Implementation Inputs

**Goal:** Make sure implementation starts from current files, not stale report
assumptions.

**Files:**

- Read only: design report and prototype HTML files.
- Read only: `P0_Runbook.md`, capture-priority report, validation roadmap.
- Read only: `mf4_analyzer/app.py`, `mf4_analyzer/ui/main_window.py`,
  `can_logger/p0/*.py`, `mf4_analyzer/acquisition/*.py`.

**Tasks:**

- [ ] Confirm the prototype files are in `docs/analyzer/ui-prototypes/`.
- [ ] Confirm `mf4_analyzer.ui.MainWindow` has a public or addable file-load
  handoff path. Current implementation has `_load_one(fp)` at
  `mf4_analyzer/ui/main_window.py:580`; **no public wrapper exists today**.
  Record this gap explicitly; the wrapper `MainWindow.load_file(path)` is
  owned by Stage 5 (see Stage 5 "Owned files"). Cockpit code in Stages 2–4
  MUST NOT reference `_load_one`.
- [ ] Confirm P0 status. If Vector/XCP is still PARTIAL, keep Vector release
  behind the Windows hardware gate.
- [ ] Confirm local commands use `.venv/bin/python`.
- [ ] Capture a "Stage 0 gap note" listing the four pieces of green-field
  scope this plan introduces: `acquisition_capture/health.py`,
  `acquisition_capture/preflight_estimates.py`, `acquisition_ui/`, and the
  Stage-5 Analyzer handoff method. Future stages cross-check against this
  list so nothing gets skipped silently.

**Verification:**

```bash
git status --short
rg -n '(^|[`[:space:]+])python scripts/|expected[_]signals' docs/analyzer/acquisition
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
```

**Exit criteria:**

- Current acquisition validation suite is green or any failure is documented as
  unrelated before coding starts.

## Stage 1 - Extract Shared `ui_kit`

**Goal:** Let Analyzer and Cockpit share style, icons, fonts, and lightweight
widgets without importing each other's windows.

**Owned files:**

- Create: `mf4_analyzer/ui_kit/`
- Move or copy-then-migrate (source path → target path):
  - `mf4_analyzer/ui/icons.py` → `mf4_analyzer/ui_kit/icons.py`
  - `mf4_analyzer/_fonts.py` (top-level, NOT under `ui/`) →
    `mf4_analyzer/ui_kit/fonts.py`
  - `mf4_analyzer/ui/style.qss` → `mf4_analyzer/ui_kit/style.qss`
  - `mf4_analyzer/ui/widgets/searchable_combo.py` →
    `mf4_analyzer/ui_kit/widgets/searchable_combo.py`
  - selected drawer primitives only if Cockpit actually needs them
- Modify:
  - `mf4_analyzer/app.py`
  - existing Analyzer imports/tests touched by moved modules
  - `build/spec/MF4DataAnalyzer.spec` only after imports settle

**Tasks:**

- [ ] Write import compatibility tests first:
  - Analyzer imports still work.
  - `ui_kit` imports without constructing Analyzer `MainWindow`.
  - icon cache still fails loud if called before `QApplication`.
  - **Import-boundary test** (`tests/ui/test_import_boundaries.py`): assert
    that `mf4_analyzer.ui_kit.*` modules never import from
    `mf4_analyzer.ui.*` or `mf4_analyzer.acquisition_ui.*`, and that
    `mf4_analyzer.ui` never imports from `mf4_analyzer.acquisition_ui`.
    Use `ast.walk` over the source files, not runtime imports.
- [ ] Extract `load_stylesheet(app)` from `mf4_analyzer.app._load_stylesheet`
  into `mf4_analyzer/ui_kit/stylesheet.py`.
- [ ] Move shared icon and font helpers into `ui_kit`; keep thin compatibility
  imports in old modules if needed for staged safety.
- [ ] Move `SearchableComboBox` only if no Analyzer-specific dependency leaks
  with it.
- [ ] Keep `mf4_analyzer/ui/` as Analyzer-owned; do not move large Analyzer
  components such as `inspector_sections.py`.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_searchable_combo.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_drawers.py -v

PYTHONPATH=. .venv/bin/python - <<'PY'
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet
from mf4_analyzer.ui_kit.widgets.searchable_combo import SearchableComboBox
print(load_stylesheet, SearchableComboBox)
PY
```

**Exit criteria:**

- Existing Analyzer UI tests pass.
- No acquisition UI package imports Analyzer internals yet.

## Stage 2 - Capture Core And Session Model

**Capture-First Cut (added 2026-05-15):** Stage 2 is the operational equivalent of `reports/2026-05-15-capture-priority-replay-findings.md` §P1 "Minimal Recorder Backend". It owns only `mf4_analyzer/acquisition_capture/` and has **no Qt or `ui_kit` dependency** — therefore it can ship as a CLI-first MVP **before** Stage 1 (ui_kit extraction) or Stage 4 (cockpit shell). When sequenced as the CLI MVP it adds one extra deliverable: a thin `python -m mf4_analyzer.acquisition_capture` entrypoint that takes a `SessionConfig`, runs `CaptureController` against `FakeRecorderBackend` or `ReplayRecorderBackend`, writes a finalized MF4, and emits `session_summary.json`. The capture-first stance from the validation program master plan applies: data-quality warnings (timestamp jumps, dropped frames, bus congestion) populate the session summary but never fail the run as long as the MF4 was flushed and closed.

**Goal:** Build the hot-path capture abstractions without Qt widgets. This
keeps recording behavior testable on macOS and prevents the UI from becoming
the recorder.

**Owned files:**

- Create: `mf4_analyzer/acquisition_capture/`
- Create tests: `tests/test_acquisition_capture_*.py`
- Modify only as needed:
  - `can_logger/p0/mf4_probe.py` or new writer helper module
  - docs if command contracts change

**Core types:**

```text
SessionConfig
SelectedMeasurement
RecorderHealth                 # alias for RecHealth; see health.py
SessionSummary
RingBuffer                     # emits watermark_changed Qt signal
RecorderBackend                # exposes last_frame_monotonic() too
FakeRecorderBackend
ReplayRecorderBackend
VectorXcpRecorderBackend (stub/lazy, not production yet)
CaptureController
Mf4Writer                      # channel-naming contract per spec
```

**Health and thresholds modules (new in this stage):**

- `mf4_analyzer/acquisition_capture/health.py` — HwHealth, CanHealth,
  XcpHealth, DaqHealth, RecHealth dataclasses and their `level()` helpers,
  plus `HealthAggregator`. See spec §Health Snapshot Model Contract.
- `mf4_analyzer/acquisition_capture/thresholds.py` — every numeric constant
  referenced by spec §Threshold Contract. UI must only import from here.

**Tasks:**

- [ ] Write tests for `SessionConfig` serialization, default thresholds, and
  output path validation.
- [ ] Implement `RingBuffer` watermarks:
  - `0-50%` green.
  - `50-70%` yellow.
  - `70-85%` red/degrade UI recommendation.
  - `85-95%` drop oldest and increment `dropped_frames`.
  - `>= 95%` for 5 s requests auto-stop.
- [ ] Implement `FakeRecorderBackend` that emits deterministic timestamped
  samples for at least three signals and supports forced warning states.
- [ ] Implement `ReplayRecorderBackend` that can replay a small checked-in or
  generated source without Vector dependencies.
- [ ] Implement `CaptureController` start/stop/flush with a session summary.
- [ ] Implement a writer spike:
  - If `asammdf` supports the needed safe incremental write pattern, wrap it.
  - If not, buffer bounded chunks and write finalized MF4 on stop for the MVP.
  - **Channel-naming contract (spec §Recorder Backend):** every MF4 channel
    name MUST equal the A2L measurement `name` verbatim. The spike report
    pins this contract and the unit test
    `tests/test_acquisition_capture_writer.py::test_channel_names_match_a2l`
    proves it (write fake recording → reload via `DataLoader.load_mf4` →
    assert `set(channels) == set(selected_names)`).
  - Record the decision in
    `docs/analyzer/acquisition/reports/2026-05-15-mf4-writer-spike.md`.
- [ ] Implement `HealthAggregator` polling loop (default 500 ms):
  - Pulls `HwHealth` from `vector_probe.probe_hw_snapshot()` (Stage 8 supplies
    the real implementation; Stage 2 supplies a macOS-friendly stub that
    returns `ok=False, error="non-windows host"`).
  - Pulls `RecHealth` from the active backend via `last_frame_monotonic()`
    and `RingBuffer.level_pct`.
  - Tests cover the watchdog rule: `last_rx_age_s ≥ 2.0` ⇒ `level == 'red'`.
- [ ] Add a CLI entry `python -m mf4_analyzer.acquisition_capture` for the
  CLI-first MVP:
  - Accepts `--backend {fake,replay}`, `--duration`, `--output`,
    `--signals`, `--segment` (optional segment length seconds).
  - Writes the finalized MF4 to `--output` and a sibling
    `session_summary.json` containing `duration_s`, `rx_count`,
    `write_count`, `queue_overflow_count`, `bus_error_count`,
    `max_queue_depth`, `segments`, `output_mf4`, and a `problems[]`
    array sourced from `RecorderHealth`.
  - Returns exit 0 on flushed-and-closed file (even with quality warnings)
    and non-zero only on writer / config / file-IO failure.
  - Ctrl-C performs a clean stop/flush (no partial-MF4 risk).
  - Vector / XCP backend remains absent from this entry until Stage 8.

**Verification:**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_capture_* -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_mf4_probe.py -v
```

**Exit criteria:**

- Fake capture can write a finalized MF4.
- The produced MF4 opens through existing `DataLoader` or the blocker is
  documented in the writer spike report.
- Session summary includes health metadata even when quality warnings exist.
- `python -m mf4_analyzer.acquisition_capture --backend fake --duration 2
  --output /tmp/cap.mf4` exits 0, leaves a loadable MF4 and a sibling
  `session_summary.json`, and survives Ctrl-C without truncated output.

## Stage 3 - A2L Event, Search, And Config Models

**Goal:** Make the left-pane behavior real before Qt tree work.

**Owned files:**

- Modify: `can_logger/p0/a2l_probe.py`
- Create: `mf4_analyzer/acquisition_capture/a2l_events.py` or equivalent
- Create: `mf4_analyzer/acquisition_capture/search.py`
- Create: `mf4_analyzer/acquisition_capture/config_store.py`
- Create: `mf4_analyzer/acquisition_capture/preflight_estimates.py`
- Create tests: `tests/test_acquisition_a2l_events.py`,
  `tests/test_acquisition_measurement_search.py`,
  `tests/test_acquisition_config_store.py`,
  `tests/test_acquisition_preflight_estimates.py`

**Tasks:**

- [ ] Extend A2L summaries with the data shape so a measurement can expose
  available DAQ events and event capacity when the A2L contains
  `IF_DATA XCP DAQ_EVENT`. Output schema: `event_capacity: Mapping[str, int]`,
  `measurement_events: Mapping[str, tuple[str, ...]]`. When the A2L lacks
  IF_DATA XCP entirely, both maps are empty and a flag
  `a2l_has_daq_events: bool` is set false (consumed by §Left Pane fallback).
  **Scope note for MVP**: the data shape lands in this stage; the actual
  IF_DATA tree-walking is deferred to Stage 8 alongside production Vector/XCP
  (cockpit `--demo` consumes `FakeRecorderBackend` event metadata, not real
  A2L bytes — see spec §Preflight Computation Contract "Deferred: real
  IF_DATA XCP DAQ_EVENT extraction"). Default-empty-maps tests are sufficient
  for Stage 3 exit; deep-IF_DATA tests live in Stage 8.
- [ ] Keep the current `MeasurementSummary` import path compatible or add a
  deliberate migration test.
- [ ] Implement token-aware search with the spec scores. The search module
  returns `SearchHit(measurement, score, match_spans)` where `match_spans`
  is a list of half-open `(start, end)` character ranges. UI uses these
  spans directly for blue-highlight rendering — no re-matching in the view.
- [ ] Implement address/unit/name mode detection. Unit mode applies the
  normalization rules from spec §Search And Filter Contract (lower-case,
  strip, `°→deg`, `^` dropped); measurements with empty `phys_unit` are
  excluded from unit-mode results.
- [ ] Implement filter state with `有 DAQ` default on and AND semantics.
  When `a2l_has_daq_events` is false, the chip auto-disables; the filter
  module is the source of truth (UI just reflects).
- [ ] Implement `build_event_intersection(selected) -> set[str]` for the
  batch-raster dropdown. Empty result returns an empty set; UI disables the
  dropdown when the set is empty.
- [ ] Implement recent/favorites persistence per spec §Persistence Contract:
  - recent: `~/.acquisition-cockpit/recent.json` (schema in spec).
  - favorites and selected raster: per-project `acquisition_config.yaml`
    with the exact YAML schema from spec §Persistence Contract.
  - `config_store.load_or_default(project_root)` follows the 4-step lookup
    order in spec; missing config returns an in-memory default and sets a
    `pinned: bool` flag that the status bar reads.
- [ ] Do not require a real A2L in normal CI. Use tiny fixtures or pure unit
  tests for parsing helpers, and keep `P0_A2L_PATH` tests skip-gated.
- [ ] Implement five preflight-estimate pure functions plus the two band
  helpers per spec §Preflight Computation Contract:
  - `estimate_can_bus_load(selected, bitrate_bps)`
  - `daq_slot_usage(event_name, selected, event_capacity)`
  - `estimate_throughput_bps(selected)`
  - `estimate_record_duration_s(throughput_bps, disk_free_bytes)`
  - `estimate_sample_events_per_s(selected)`
  - `band_disk_remaining(disk_free_bytes) -> 'green' | 'yellow' | 'red'`
  - `band_sample_events_per_s(events_per_s) -> 'green' | 'yellow' | 'red'`
  Each function and each band helper is unit-tested against the
  green/yellow/red rows in spec §Threshold Contract.

**Verification:**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_p0_a2l_probe.py \
  tests/test_acquisition_a2l_events.py \
  tests/test_acquisition_measurement_search.py \
  tests/test_acquisition_config_store.py \
  tests/test_acquisition_preflight_estimates.py -v
```

**Exit criteria:**

- Search/filter tests prove the v3 left-pane contract without Qt.
- A missing real A2L keeps the same documented skip behavior.

## Stage 4 - Cockpit Shell And Four-State UI

**Goal:** Create the Cockpit window with fake/replay data, health strip, and
state transitions. Do not integrate Vector yet.

**Owned files:**

- Create: `mf4_analyzer/acquisition_ui/__init__.py`
- Create: `mf4_analyzer/acquisition_ui/__main__.py`
- Create: `mf4_analyzer/acquisition_ui/main_window.py`
- Create: `mf4_analyzer/acquisition_ui/state.py`
- Create: `mf4_analyzer/acquisition_ui/widgets/`
- Create: `mf4_analyzer/acquisition_ui/widgets/live_downsampler.py`
- Create tests: `tests/acquisition_ui/`

**Tasks:**

- [ ] Write state-machine tests first:
  - disconnected -> connected idle (gated by spec `healthy` predicate:
    `HwHealth.ok ∧ XcpHealth.connected ∧ first DAQ frame ≤ 3 s`).
  - connection timeout: 3 s without a frame returns to disconnected and
    surfaces the first failing predicate name in the right panel.
  - connected idle -> recording.
  - recording -> review modal (gated by `finalized` predicate from spec).
  - review close -> connected idle.
  - red health disables record.
  - yellow health warns but does not necessarily disable record.
  - dropped-frames > 100 opens the in-state "继续/停止" prompt; choosing
    `继续` keeps recording, choosing `停止` triggers the same flow as
    pressing Stop manually.
- [ ] Implement `python -m mf4_analyzer.acquisition_ui --demo`.
- [ ] Build toolbar with A2L/DBC/output controls, mode segment, REC indicator,
  and stateful main button.
- [ ] Build health strip using a model object so tests can assert button state
  without pixel inspection.
- [ ] Build the left pane using Stage 3 search/filter models.
- [ ] Build center live cards with fake/replay streaming data. Sparklines
  use `widgets/live_downsampler.py`:
  - Input: N timestamped samples and W target pixels.
  - Output: W `(min, max)` bins.
  - A dedicated unit test pins the input/output shape and tolerates
    `N < W` (one sample per pixel, no interpolation).
  - Card stats label which window applies (`since 60s` vs `since rec start`),
    matching spec §State Machine `stats window`.
- [ ] Build right panel variants for disconnected, idle preflight/readiness,
  and recording quality monitor. Each row binds to one
  `*Health` snapshot field; the widget MUST NOT compute thresholds inline.
  Numbers in the idle panel come from the four pure functions in
  `acquisition_capture/preflight_estimates.py`.
- [ ] Wire `RingBuffer.watermark_changed` to `MainWindow.set_target_fps`
  (30 → 10 fps) and to the auto-stop handler (≥ 95 % for 5 s or disk
  `< 100 MB`). Test: emit the signal directly and assert the slot fires;
  no recorder required.
- [ ] Wire `HealthAggregator.health_changed` to the health-strip view model.
  Test: simulate `last_rx_age_s = 2.5` and assert the REC chip turns red
  even when ring buffer fill is 0.
- [ ] Freeze A2L/raster controls while recording.
- [ ] Keep `回放` present but disabled or no-op until its own spec. Tab
  header reads `回放 (待开放)` and the body is a single-line placeholder
  per spec Product Decisions.
- [ ] DBC selector in the toolbar is `setEnabled(False)` with the tooltip
  string from spec Product Decisions. Test: clicking the disabled control
  does not trigger any file dialog or signal emission.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui -v
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test
```

Manual desktop check:

```bash
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo
```

**Exit criteria:**

- Demo starts on macOS without Vector packages.
- The first screen matches the v3 hierarchy: toolbar, health strip, A2L left
  pane, live center, state-aware right pane, status bar.
- No Analyzer files are loaded during Cockpit startup.

## Stage 5 - Recording Flow, Review Modal, And Analyzer Handoff

**Goal:** Wire fake/replay capture through stop, finalized MF4 save, post-record
diagnostics, archive choice, and Analyzer opening.

**Owned files:**

- Modify: `mf4_analyzer/ui/main_window.py` only to add public handoff method.
- Create/modify: `mf4_analyzer/acquisition_ui/review_modal.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window.py`
- Modify: capture controller/writer from Stage 2 as needed.
- Create tests: `tests/acquisition_ui/test_review_handoff.py`

**Tasks:**

- [ ] Add `MainWindow.load_file(path: str | Path) -> None` in Analyzer
  (`mf4_analyzer/ui/main_window.py`) as a public wrapper around the existing
  private `_load_one` flow. This is the only Analyzer-side modification in
  the plan; `_load_one` itself stays unchanged.
- [ ] Add tests proving Cockpit handoff calls the public method only after the
  writer reports finalized.
- [ ] Encode the `expected_channels` contract in the review-modal flow:
  - Cockpit passes `expected_channels = tuple(m.name for m in selected)` to
    `analyze_mf4(...)` verbatim.
  - This relies on Stage 2's writer channel-naming rule; if that rule is
    violated the round-trip test there fails before Stage 5 runs.
  - Add `tests/acquisition_ui/test_review_handoff.py::test_expected_channels`
    that drives a 1-second fake recording with three measurements and
    asserts `PreflightResult.missing_channels == ()`.
- [ ] Honour the `Recording` sub-state prompt: if `dropped_frames` crosses
  the 100-cumulative threshold while recording, show the non-modal
  "丢帧过多 · 是否停止？" prompt with two buttons. `继续录制` dismisses;
  `停止并复盘` runs the same stop/flush/finalize flow as the toolbar Stop.
  Test pins both branches without involving the real recorder.
- [ ] Implement stop/flush/finalize sequence:
  - stop backend.
  - drain writer.
  - close file handles.
  - write session summary.
  - compute SHA if archiving.
  - run post-record diagnostics.
  - open review modal.
- [ ] Review modal actions:
  - `丢弃（不归档）`: leaves file policy explicit and returns to idle.
  - `仅保存文件`: keeps finalized MF4 and summary.
  - `保存并归档`: writes manifest entry using existing manifest helpers.
  - `在 Analyzer 打开`: enabled only after finalized save/archive path.
- [ ] Make preflight warnings visible as diagnostics, not capture failure.
- [ ] Keep manifest failures from corrupting the saved MF4. If archive write
  fails, leave the file saved and report archive failure separately.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_review_handoff.py \
  tests/ui/test_main_window_smoke.py -v

PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_manifest.py tests/test_acquisition_preflight.py -v
```

**Exit criteria:**

- A fake/replay recording can be saved and opened in Analyzer.
- Analyzer never opens a still-writing file.
- Diagnostics can be warning/red while capture save remains successful.

## Stage 6 - History Tab And Asset Library Minimum

**Goal:** Add the de-prioritized `历史` tab as a small manifest-backed browser,
not as the opening screen.

**Owned files:**

- `mf4_analyzer/acquisition_ui/history_tab.py`
- manifest/query helpers if needed
- `tests/acquisition_ui/test_history_tab.py`

**Tasks:**

- [ ] Read existing manifest entries through current manifest helpers.
- [ ] Filter by vehicle, scenario, issue tags, set, and quality where present.
- [ ] Show local/LFS/external availability clearly.
- [ ] Right-click or button action uses the same Analyzer finalized-file handoff.
- [ ] Do not block the UI when a NAS/external path is unavailable.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_history_tab.py -v
```

**Exit criteria:**

- History exists for lookup, but `采集` remains the default tab.

## Stage 7 - Packaging And Analyzer Launch Integration

**Goal:** Make Cockpit reachable in normal local and Windows packaged flows.

**Owned files:**

- `mf4_analyzer/app.py`
- `MF4 Data Analyzer V1.py` only if an entry handoff is needed
- `build/spec/MF4DataAnalyzer.spec`
- `tools/build_windows_folder.ps1`
- docs under `docs/analyzer/acquisition/`

**Tasks:**

- [ ] Add an Analyzer menu/toolbar action `打开 Acquisition Cockpit...` that
  opens or raises the same-process Cockpit window.
- [ ] Ensure `mf4_analyzer.acquisition_ui` can also launch standalone.
- [ ] Update PyInstaller hidden imports and data files for `ui_kit`,
  `acquisition_ui`, and any shared QSS/icon resources.
- [ ] Verify macOS import and Windows spec paths separately.

**Verification:**

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py \
  tests/acquisition_ui -v

PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test
```

Windows-side packaging verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\acquisition_ui tests\ui\test_main_window_smoke.py -v
powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1
```

**Exit criteria:**

- Analyzer can open Cockpit.
- Cockpit can still run standalone.
- Packaged Windows app contains style/icon resources and imports.

## Stage 8 - Vector/XCP Production Gate

**Goal:** Replace fake/replay backend with production Vector/XCP only after
hardware proof exists.

**Owned files:**

- `mf4_analyzer/acquisition_capture/vector_backend.py`
- `can_logger/p0/vector_probe.py` and `xcp_short_upload_probe.py` only if probe
  fixes are required by actual hardware evidence.
- `docs/analyzer/acquisition/P0_Runbook.md`
- tests that stay hardware-free by default.

**Tasks:**

- [ ] On Windows + Vector + powered ECU, run `vector_probe --open`.
- [ ] Run `xcp_short_upload_probe` with real command/response IDs and A2L
  measurement address.
- [ ] Append exact command output to `P0_Runbook.md`.
- [ ] Implement `VectorXcpRecorderBackend` with lazy imports and clear
  non-Windows errors.
- [ ] Add hardware-free tests for import, argument validation, decode helpers,
  and backend factory gating.
- [ ] Add a hardware-marked manual test path that is skipped unless explicit
  environment variables are present.

**Verification:**

macOS/default:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_vector_probe.py tests/test_p0_xcp_probe.py -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_capture_* -v
```

Windows hardware:

```powershell
.\.venv\Scripts\python.exe -m can_logger.p0.vector_probe --open
.\.venv\Scripts\python.exe -m can_logger.p0.xcp_short_upload_probe ...
```

**Exit criteria:**

- P0 runbook moves from PARTIAL to PASS with actual evidence.
- Cockpit production Vector recording can be enabled behind configuration.

## Final Rollup Gate

Before claiming the Cockpit implementation is ready:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
.venv/bin/python scripts/acquisition_smoke.py --skip-regression
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
rg -n '(^|[`[:space:]+])python scripts/|expected[_]signals' docs/analyzer/acquisition
git diff --check
```

Manual checks:

- Launch Analyzer with `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app`.
- Launch Cockpit with `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo`.
- In Cockpit demo: connect, record, stop, save, open in Analyzer.
- Confirm recording warnings do not prevent saving.
- Confirm Analyzer receives only finalized files.

## Defaults Locked For First Pass

- `DBC` remains visible as an optional metadata selector in the toolbar because
  it appears in the v3 layout, but it never blocks XCP recording in MVP.
- Segment marker waits until after the first save/open demo. Pause remains out.
- Package names are `mf4_analyzer.acquisition_capture` for capture services and
  `mf4_analyzer.acquisition_ui` for Qt widgets.
- macOS builds expose only fake/replay recording through `--demo` until Vector
  hardware proof is appended to `P0_Runbook.md`.
