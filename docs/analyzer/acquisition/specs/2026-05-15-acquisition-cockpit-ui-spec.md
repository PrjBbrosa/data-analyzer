# Acquisition Cockpit UI Spec

Date: 2026-05-15
Status: Execution-ready draft
Plan: `docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md`

## Source Inputs

- `docs/analyzer/acquisition/2026-05-14-cockpit-ui-design-report.md`
- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-options.html`
- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v2.html`
- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html`
- `docs/analyzer/acquisition/reports/2026-05-15-capture-priority-replay-findings.md`
- `docs/analyzer/acquisition/P0_Runbook.md`
- `docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md`

## Goal

Build an Acquisition Cockpit that is visually consistent with the existing MF4
Analyzer, but remains a separate same-process partner window. Its first useful
outcome is capture-first: receive data, show live health, stop cleanly, save a
finalized MF4, then optionally run post-record diagnostics and hand the file to
Analyzer.

The UI must embody the v3 decision:

```text
[未连接] -> [已连接 · 待机] -> [录制中] -> [复盘 modal] -> [已连接 · 待机]
```

Connected idle already streams live charts. The `采集` button starts writing to
disk; it does not start the data stream.

## Scope

In scope:

- A new `mf4_analyzer/acquisition_ui/` package with a `QMainWindow` Cockpit.
- Same-process dual-window architecture with the existing Analyzer.
- Shared visual primitives moved into `mf4_analyzer/ui_kit/` so Analyzer and
  Cockpit do not import each other's UI internals.
- Four UI states: disconnected, connected idle, recording, and review modal.
- A2L measurement search, filters, selected-signal list, raster/event display,
  and per-project selection/favorite persistence.
- Health strip with `HW`, `CAN`, `XCP`, `DAQ`, and `REC` chips.
- Capture-first recorder architecture with fake/replay backends on macOS and
  lazy Windows-gated Vector/XCP integration later.
- Post-record diagnostics using the existing acquisition preflight/manifest
  modules after a recording is saved or ready to save.
- Analyzer handoff only after the MF4 is finalized and closed.

Out of scope for the first implementation wave:

- Embedding acquisition as a new Analyzer toolbar mode.
- QWizard acquisition workflow.
- Bench Console full-screen mode.
- Production Vector live capture release without Windows + Vector + powered ECU
  evidence.
- Multi-A2L or multi-ECU selection.
- Raw DBC-based CAN capture. The DBC selector is metadata/future slot only
  until a separate CAN raw-capture spec exists.
- Replay tab functionality. The slot may exist, but implementation is deferred.
- Allowing Analyzer to open a file that is still being written.

## Product Decisions

| Topic | Decision |
| --- | --- |
| Window model | Approach A: separate Cockpit partner window, same visual language. |
| Process model | Same `QApplication`, two `QMainWindow` instances. |
| Startup command | `.venv/bin/python -m mf4_analyzer.acquisition_ui`. |
| Analyzer entry | Add a menu/toolbar action later to open Cockpit from Analyzer; do not fold Cockpit into Analyzer modes. |
| Default tab | `采集`. |
| Top modes | `采集 / 回放 / 历史`; `回放` is a reserved/deferred slot. |
| Arm mode | Removed. Main button is `[连接 ECU]`, `[● 采集]`, or `[■ Stop & 复盘]`. |
| Pause | Removed for MVP. XCP DAQ has no graceful pause contract. |
| Segment marker | Allowed as a later recording action; not a state-machine blocker. |
| Favorites | Per-project in `acquisition_config.yaml`. |
| Recent | Per-user in `~/.acquisition-cockpit/recent.json`. |
| Threshold editing | Settings tab/dialog later; defaults must exist in code first. |
| Capture vs diagnostics | Capture save succeeds or fails on recorder/writer health. Preflight/replay quality warnings are post-record diagnostics and must not discard raw capture. |
| P0 tension | UI shell, fake backend, and replay backend can proceed on macOS. Production Vector/XCP recording remains gated by Windows hardware evidence. |

## State Machine Contract

### `Disconnected`

- Health strip LEDs are off/gray.
- Main button label is `连接 ECU`.
- Left A2L tree can load/search/select, but live chart area is a gray
  disconnected placeholder.
- Right panel shows connection readiness: A2L parse, hardware availability,
  DAQ capacity estimate, and selected-signal feasibility.
- Clicking `连接 ECU` creates a backend session, configures DAQ for selected
  measurements where supported, starts the receiver thread, and transitions to
  `ConnectedIdle` only after the live stream is healthy.

### `ConnectedIdle`

- Health strip is the source of truth for connection state.
- Center charts stream continuously with `REC OFF`.
- A2L selection and raster changes are allowed. Changes reconfigure DAQ only
  when not recording.
- Right panel shows record readiness: CAN load, DAQ slot per event, disk, and
  total sample events per second.
- Any red record-readiness item disables `[● 采集]` and shows the blocker.
- Yellow readiness does not block recording, but displays a warning.

### `Recording`

- Center charts continue without relayout. REC indicator is red and elapsed time
  is visible.
- A2L selection and raster controls become read-only.
- Main button becomes `[■ Stop & 复盘]`.
- Right panel shows live quality: ring buffer, write rate, dropped frames, CAN
  load, recorder thread, and disk space.
- Receiver must not block on UI drawing or file writes. If implementation uses
  Python locking internally, the public hot-path contract is still non-blocking
  for receiver enqueue.
- Stop flushes the writer, closes file handles, builds session metadata, then
  opens the review modal.

### `ReviewModal`

- Appears immediately after stop or auto-stop.
- Charts remain paused at the stop point.
- `丢弃（不归档）` is always enabled.
- `仅保存文件` and `保存并归档` operate only on finalized writer output.
- `在 Analyzer 打开` is disabled until the file is finalized, SHA has been
  computed when requested, manifest writes have completed when requested, and
  file handles are closed.
- Closing the modal returns to `ConnectedIdle`.

## Main Screen Layout Contract

### Toolbar

- Height target: 48 px.
- Contents:
  `[A2L 选择] [DBC 选择] [输出目录] | [采集 回放 历史] ... [REC 指示器] [主按钮]`
- `A2L` is required for XCP measurement selection.
- `DBC` is optional metadata in MVP and must not block XCP capture.

### Health Strip

- Height target: 32 px.
- Chips: `HW`, `CAN`, `XCP`, `DAQ`, `REC`.
- Each chip has LED state: green, yellow, red, or off.
- Tooltips must contain backing evidence, for example driver/version,
  slave id, DAQ event binding, ring buffer water level, or writer state.
- Any red or off chip that makes recording impossible disables the record
  button. Yellow chips warn but do not necessarily block.

### Left Pane: A2L Measurement

- Width target: 280 px.
- Fixed search box at the top.
- Filters: `只看已选`, `有 DAQ`, `最近`, `收藏`, `组`, `类型`.
- Default filter state:
  - `有 DAQ`: on.
  - all others: off or all.
- Filter logic is AND.
- Footer shows selected count, estimated bandwidth, and event distribution.
- Multi-select supports command/control click, shift range, and command/control
  A for current filtered results only.
- Raster dropdown lists A2L-declared events. Unsupported events are visible but
  disabled.

### Center Pane: Live Charts

- Live charts appear as soon as connected.
- Each selected signal card shows sparkline, current value, unit, raster pill,
  and compact stats.
- Recording changes indicator and stats scope, not layout.
- UI draw rate starts at 30 fps cap and can degrade to 10 fps under pressure.

### Right Pane

- Width target: 300 px.
- Disconnected: connection checklist.
- Connected idle: record preflight/readiness.
- Recording: live quality monitor.
- Review modal owns post-record preflight and manifest fields.

### Status Bar

- Disconnected: connection/A2L summary.
- Connected idle: streaming event rate and ring buffer water level.
- Recording: recording duration, samples, file size, dropped count, and buffer.

## Search And Filter Contract

Input mode detection:

| Input | Mode |
| --- | --- |
| starts like `0x...` or hex-heavy | address search |
| unit-like text such as `rpm`, `km/h`, `Nm` | unit search |
| otherwise | name search |

Name search ranking:

| Score | Match |
| --- | --- |
| 1000 | exact |
| 800 | name prefix |
| 700 | all tokens in order |
| 600 | all tokens any order |
| 500 | all tokens are substrings |
| 200 | Levenshtein distance <= 2 |

Return the top 50 visible results. Highlight matched characters. Fuzzy search
defaults on and can later be disabled from settings.

## Threshold Contract

Record readiness defaults:

| Metric | Green | Yellow | Red |
| --- | --- | --- | --- |
| CAN bus load | `< 60%` | `60-80%` | `>= 80%` |
| DAQ slot per event | `< 75%` | `75-95%` | `= 100%` |
| Disk remaining | `> 5 GB` | `1-5 GB` | `< 1 GB` |
| Estimated record duration | `> 4 h` | `30 min-4 h` | `< 30 min` |
| Total sample events per second | `< 30 k` | `30-80 k` | `> 80 k` |

Recording quality defaults:

| Signal | UI/action |
| --- | --- |
| Ring buffer `0-50%` | green |
| Ring buffer `50-70%` | yellow + status warning |
| Ring buffer `70-85%` | red + UI draw 30 fps to 10 fps |
| Ring buffer `85-95%` | red + drop oldest display/queued sample, count in `dropped_frames` |
| Ring buffer `>= 95%` for 5 s | auto-stop, save what exists, show error modal |
| Dropped frames `1-10` | yellow and add post-record problem |
| Dropped frames `> 10 / 10 s` | red status warning |
| Dropped frames `> 100` total | ask whether to stop, do not force stop |
| Disk `< 100 MB` | auto-stop |

## Architecture Contract

### Packages

```text
mf4_analyzer/
├── acquisition/          # existing offline validation/manifest/preflight
├── acquisition_ui/       # new Cockpit QMainWindow and widgets
├── acquisition_capture/  # recorder/session/ring/writer services
├── ui/                   # existing Analyzer window
└── ui_kit/               # shared style/icons/fonts/widgets after extraction
```

The exact package names may be adjusted during implementation review, but these
ownership boundaries must hold:

- `mf4_analyzer.ui` must not import `mf4_analyzer.acquisition_ui`.
- `mf4_analyzer.acquisition_ui` must not import Analyzer internals except a
  public handoff API.
- Shared UI pieces live below `mf4_analyzer.ui_kit`.
- Capture hot path lives outside Qt widgets and can be tested without Qt.

### Analyzer Handoff

- Add a public Analyzer method such as `load_file(path: str | Path)` that wraps
  the existing load path.
- Cockpit finds existing Analyzer windows through `QApplication.topLevelWidgets()`.
- If an Analyzer window exists, call the public load method, then `raise_()` and
  `activateWindow()`.
- If none exists, create one and load the finalized file.
- Never call Analyzer handoff on an open writer file.

### Recorder Backend

Define a backend interface before Vector integration:

```text
RecorderBackend.start(config) -> stream/session handle
RecorderBackend.stop() -> final health snapshot
RecorderBackend.status() -> health snapshot
```

Required implementations by stage:

- `FakeRecorderBackend`: deterministic synthetic samples for macOS tests.
- `ReplayRecorderBackend`: reads local/canned data for UI/manual testing.
- `VectorXcpRecorderBackend`: lazy imports `python-can`/`pyxcp`, Windows-gated,
  implemented only after P0 hardware evidence.

### Session Metadata

Every capture attempt that writes data must produce a session summary adjacent
to the MF4 or in the archive manifest:

```text
duration_s
rx_count
write_count
queue_overflow_count
bus_error_count
dropped_frames
max_queue_depth
segments
output_mf4
warnings
```

Diagnostic warnings may be red, but they are not the same thing as a failed
recording. Recording failure means the receiver/writer could not create a
recoverable saved artifact.

## Acceptance Gates

Documentation and drift checks:

```bash
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
rg -n '(^|[`[:space:]+])python scripts/|expected[_]signals' docs/analyzer/acquisition
```

Existing acquisition validation remains green:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
.venv/bin/python scripts/acquisition_smoke.py --skip-regression
```

Existing Analyzer UI remains green after `ui_kit` extraction:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_searchable_combo.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_drawers.py -v
```

New Cockpit tests pass once implemented:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_capture_* -v
```

Manual smoke after UI shell exists:

```bash
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo
```

Windows Vector release gate:

```text
Run on Windows + Vector + powered ECU only:
.\.venv\Scripts\python.exe -m can_logger.p0.vector_probe --open
.\.venv\Scripts\python.exe -m can_logger.p0.xcp_short_upload_probe ...
```

Production Vector/XCP recording cannot be marked PASS until the actual command
output is appended to `docs/analyzer/acquisition/P0_Runbook.md`.
