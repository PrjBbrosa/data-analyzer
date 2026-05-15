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
| Threshold editing | Settings tab/dialog deferred to v2. MVP thresholds live as module-level constants in `mf4_analyzer/acquisition_capture/thresholds.py`; no YAML/JSON override path is wired. |
| Capture vs diagnostics | Capture save succeeds or fails on recorder/writer health. Preflight/replay quality warnings are post-record diagnostics and must not discard raw capture. |
| P0 tension resolution | macOS fake/replay UI ships as engineering preview only. Production Vector recording stays behind the `P0_Runbook.md` PASS gate; cockpit binary on macOS surfaces fake/replay backends only. |
| DBC selector | Visible but inert in MVP — control is `setEnabled(False)` with tooltip "Reserved for raw CAN capture; XCP path uses A2L." Becomes interactive only when a raw-CAN capture spec exists. |
| 回放 tab | Visible but inert in MVP — tab header reads `回放 (待开放)`, content area shows a one-line "Reserved for future replay workflow" placeholder. No widgets are loaded. |
| Writer channel naming | Mf4Writer MUST name each MF4 channel as the A2L measurement `name` verbatim. This is the only contract that lets post-record `analyze_mf4(expected_channels=...)` evaluate completeness without an extra name-mapping step. |
| Connection auto-reconnect | Out of scope for MVP. On XCP session loss during `Recording`, the recorder auto-stops with `connection_lost` in `session_summary.warnings[]`. Reconnect strategy is deferred to a follow-up spec. |

## State Machine Contract

### Shared definitions

- `healthy` for the purpose of `Disconnected -> ConnectedIdle` means: `HwHealth.ok ∧ XcpHealth.connected ∧ first DAQ frame received within connection_timeout_s` (default `3 s`). The three predicates come from the Health Snapshot Model Contract below; the receiver thread is the source of "first frame received".
- `finalized` for the purpose of `Recording -> ReviewModal` means: writer drained, file handles closed, `session_summary.json` written, and (when the user picked an action that requires it) SHA-256 computed and/or manifest entry written.
- `stats window` for the live signal cards:
  - `ConnectedIdle`: rolling 60 s window of received samples.
  - `Recording`: cumulative window starting at the recording start timestamp.
  Stats labels in the UI must show which window applies (`since 60s` vs `since rec start`).

### `Disconnected`

- Health strip LEDs are off/gray.
- Main button label is `连接 ECU`.
- Left A2L tree can load/search/select, but live chart area is a gray
  disconnected placeholder.
- Right panel shows connection readiness: A2L parse, hardware availability,
  DAQ capacity estimate, and selected-signal feasibility.
- Clicking `连接 ECU` creates a backend session, configures DAQ for selected
  measurements where supported, starts the receiver thread, and transitions to
  `ConnectedIdle` only after the `healthy` predicate above evaluates true.
- If `healthy` does not become true within `connection_timeout_s`, the session
  is torn down, the main button returns to `连接 ECU`, and the right panel
  surfaces the first failing predicate (`HW`, `XCP`, or "no frame received").

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
- A `dropped_frames > 100` cumulative event opens a non-modal "丢帧过多 · 是否
  停止？" prompt that stays inside the `Recording` state; the user chooses
  `继续录制` or `停止并复盘`. This prompt is the only `Recording` sub-state
  and never auto-dismisses.
- Stop flushes the writer, closes file handles, builds session metadata, then
  opens the review modal. The `finalized` predicate above guards the
  review-modal transition.

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
- `DBC` selector is rendered for visual parity with the v3 prototype but is
  `setEnabled(False)` in MVP with the tooltip declared in Product Decisions.
  It MUST NOT trigger any file dialog or capture-side logic until a future
  raw-CAN capture spec wires it up.

### Health Strip

- Height target: 32 px.
- Chips: `HW`, `CAN`, `XCP`, `DAQ`, `REC`.
- Each chip has LED state: green, yellow, red, or off.
- Each chip MUST be driven by the matching `*Health` snapshot defined in the
  Health Snapshot Model Contract below. UI MUST NOT compute chip color from
  free-form strings; mapping `snapshot -> level` is the canonical function in
  `mf4_analyzer/acquisition_capture/health.py`.
- Tooltips MUST quote one field from the backing snapshot, e.g.
  `HwHealth.driver_version`, `XcpHealth.slave_id`, `DaqHealth.event_capacity`,
  `RecHealth.ring_buffer_fill_pct`. A chip whose snapshot field is `None` /
  unknown shows tooltip `"no evidence yet"` and the chip stays `off`, not green.
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
- Fallback when the loaded A2L contains zero `IF_DATA XCP DAQ_EVENT` nodes
  (e.g. CAL-only A2L): the `有 DAQ` chip auto-flips to OFF, becomes
  `setEnabled(False)`, and the tooltip reads "该 A2L 不含 DAQ_EVENT 信息".
  This MUST NOT silently hide the entire tree.
- Footer shows selected count, estimated bandwidth, and event distribution.
- Multi-select supports command/control click, shift range, and command/control
  A for current filtered results only.
- Raster dropdown lists A2L-declared events. Unsupported events are visible but
  disabled.

### Center Pane: Live Charts

- Live charts appear as soon as connected.
- Each selected signal card shows sparkline, current value, unit, raster pill,
  and compact stats (`μ / σ / max`). Stats window follows the `stats window`
  rule in State Machine Contract (60 s rolling in idle, since-rec-start in
  recording); the card MUST label which window it is showing.
- Recording changes indicator and stats scope, not layout.
- Each card carries its own `REC OFF`/red dot indicator in the top-right
  corner; there is also a global REC indicator in the toolbar (Toolbar
  section). Card indicator and toolbar indicator are driven by the same
  `RecHealth.state` field and never disagree.
- UI draw rate starts at 30 fps cap and can degrade to 10 fps under pressure
  via the watermark wiring in Threshold Contract.
- Sparkline rendering downsamples per the `live_downsampler` contract:
  given N timestamped samples and W target pixels, emit min-max bins so each
  pixel column is one `(min, max)` pair. A separate UI test pins the
  downsampler input/output shape.

### Right Pane

- Width target: 300 px.
- Disconnected: connection checklist (rows: A2L parsed / HW available / current
  selection feasible). Each row's truth value comes from the matching
  `*Health` snapshot field, not from an ad-hoc widget computation.
- Connected idle: record preflight/readiness — the 5 numbers in the
  Threshold Contract table, each one computed by the matching function in
  the Preflight Computation Contract.
- Recording: live quality monitor — rows sourced from
  `RecHealth.ring_buffer_fill_pct`, `RecHealth.write_rate_bps`,
  `RecHealth.dropped_frames`, `CanHealth.bus_load_pct`,
  `RecHealth.last_rx_age_s`, `disk_free_bytes`. UI MUST NOT read free-form
  status strings from the recorder.
- Review modal owns post-record preflight and manifest fields.

### Status Bar

- Disconnected: connection/A2L summary.
- Connected idle: streaming event rate and ring buffer water level.
- Recording: recording duration, samples, file size, dropped count, and buffer.

## Search And Filter Contract

Input mode detection:

| Input | Mode |
| --- | --- |
| starts with `0x` (case-insensitive) | address search |
| unit-like text such as `rpm`, `km/h`, `Nm` | unit search |
| otherwise | name search |

Note: address mode triggers ONLY on an explicit `0x` prefix. Bare hex-looking
strings (`CAFE`, `EAD`, `BEEF`, etc.) are kept in name mode because A2L
measurements frequently use CamelCase tokens that collide with bare hex.

Unit-mode normalization:

- Query and measurement unit are both folded to lowercase, stripped, and
  whitespace-collapsed before comparison.
- `°` is normalized to `deg` on both sides; `^` is dropped; `/` is kept.
  Examples: `°C` matches `degc`, `kg/m^3` matches `kg/m3`.
- Match is exact-after-normalization. Fuzzy is not used in unit mode (a unit
  is meaningful only as a unit).
- If the loaded A2L exposes no `phys_unit` for a measurement, that
  measurement is invisible in unit mode (rather than matching empty string).

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

Search return shape:

```text
SearchHit
  measurement: MeasurementSummary
  score: int                     # one of the values in the table above
  match_spans: list[(int, int)]  # half-open character ranges in measurement.name
```

`match_spans` MUST be produced by the search module so the Qt tree can render
highlights directly. The UI MUST NOT re-run substring matching on hits.

Raster intersection helper (for the multi-select batch-raster dropdown):

```text
build_event_intersection(selected: Iterable[MeasurementSummary]) -> set[str]
```

Returns the set of DAQ event names that are simultaneously available for every
selected measurement. Empty set MUST disable the batch-raster dropdown with
tooltip `"选中信号没有共同的 DAQ event"`. Without this contract the UI cannot
honor §Batch Selection in the design report.

## Threshold Contract

All numeric thresholds in this section live as module-level constants in
`mf4_analyzer/acquisition_capture/thresholds.py`. UI MUST NOT inline literals
and MUST NOT read overrides from disk in MVP. Future Settings dialog will
load/save through this module; until then the module is the single source.

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

### Watermark wiring

`RingBuffer.watermark_changed(level: WatermarkLevel)` is a Qt signal emitted
on every level transition. Subscribers:

- `MainWindow.set_target_fps(fps: int)` — 30 fps for `green`/`yellow_low`,
  10 fps for `red`/`red_drop`.
- `MainWindow._on_auto_stop_request()` — connected to the `red_drop_sustained`
  transition (≥ 95% for 5 s) and the disk `< 100 MB` event. The handler
  invokes `CaptureController.stop()` synchronously, then opens the review
  modal with `auto_stop: true` in `session_summary`.

UI MUST NOT poll the ring-buffer level; all degradation is driven by this
signal. Stage 4 ships a signal/slot test that proves the wiring without
requiring a real recorder.

### Multi-channel CAN load

The "CAN load per channel" entry in the live quality monitor refers to one
field per physical CAN channel exposed by the backend. In MVP only one
channel is in scope (XCP request/response), so this view collapses to a
single row sourced from `CanHealth.bus_load_pct`. Multi-channel rendering
becomes meaningful once raw DBC capture exists; the widget MUST tolerate
`len(CanHealth.channels) == 1`.

## Health Snapshot Model Contract

The five health chips in §Health Strip MUST be driven by the snapshot
dataclasses defined here. They live in
`mf4_analyzer/acquisition_capture/health.py`. The `HealthAggregator` exposes
`poll_once() -> HealthSnapshot` and stays Qt-free so the capture core remains
testable without Qt; the caller (Cockpit's Qt `QTimer` in §Architecture, or
the CLI MVP's main loop) drives invocations at the cadence pinned by
`thresholds.HEALTH_POLL_INTERVAL_S` (default `500 ms`, configurable in
`thresholds.py`). A unit test MUST pin the constant binding (i.e. that
`SessionConfig.poll_interval_s` resolves to `thresholds.HEALTH_POLL_INTERVAL_S`
by default and equals `0.5`); cadence verification itself is the caller's
responsibility and lives in the Cockpit-side QTimer wiring test in Stage 4.

```text
@dataclass(frozen=True)
class HwHealth:
    ok: bool
    driver_version: str | None      # python-can vector wrapper version, if exposed
    channel_count: int              # from list_vector_channels()
    last_probe_ts: float            # monotonic seconds
    error: str | None               # populated on failure; chip turns red

@dataclass(frozen=True)
class CanHealth:
    bus_load_pct: float | None      # 0..100; None until first frame
    channels: tuple[ChannelHealth, ...]
    bus_error_count: int

@dataclass(frozen=True)
class XcpHealth:
    connected: bool
    slave_id: int | None
    last_response_age_s: float | None
    consecutive_timeouts: int

@dataclass(frozen=True)
class DaqHealth:
    event_capacity: Mapping[str, int]   # event_name -> max ODT entries (from A2L)
    event_used: Mapping[str, int]       # event_name -> ODT entries actually bound
    overflow: tuple[str, ...]           # events where used > capacity

@dataclass(frozen=True)
class RecHealth:
    state: Literal["off", "recording", "auto_stopped", "error"]
    ring_buffer_fill_pct: float
    dropped_frames: int
    write_rate_bps: float
    last_rx_age_s: float                # now - last received frame ts
    writer_thread_alive: bool
```

Level mapping (`level(snapshot) -> 'green' | 'yellow' | 'red' | 'off'`) lives
next to each dataclass. Rules:

- `HwHealth`: `ok` ⇒ green; `error is not None` ⇒ red; `last_probe_ts` more
  than `2 * poll_interval` ago ⇒ off (stale).
- `CanHealth`: green when `bus_load_pct < 60`; yellow `60..80`; red `≥ 80`
  or any element of `channels` red; off when `bus_load_pct is None`.
- `XcpHealth`: green when connected ∧ `consecutive_timeouts == 0`; yellow on
  `1..2` timeouts; red on `≥ 3` or `connected is False`.
- `DaqHealth`: green when `overflow` is empty; red when any event overflows.
- `RecHealth`: green when `state in {off, recording} ∧ writer_thread_alive ∧
  last_rx_age_s < 1.0 ∧ ring_buffer_fill_pct < 70`; yellow when ring buffer
  `70..85` or `last_rx_age_s 1.0..2.0`; red otherwise (including
  `state == error` and `last_rx_age_s ≥ 2.0`).

Recorder thread watchdog: `HealthAggregator` computes `RecHealth.last_rx_age_s`
from `now - RecorderBackend.last_frame_monotonic()`. If this exceeds `2.0 s`
the chip turns red and the live quality monitor surfaces "Recorder thread
silent". This is the only way the UI can detect a deadlocked receiver, and
it MUST be the metric tested in `tests/acquisition_ui/test_health_strip.py`.

## Preflight Computation Contract

Right-pane "record preflight" shows five numbers, each one a pure-function
output. Defined in `mf4_analyzer/acquisition_capture/preflight_estimates.py`:

```text
estimate_can_bus_load(
    selected: Sequence[SelectedMeasurement],
    bitrate_bps: int,
) -> float
    # returns 0..100; XCP-only model: sum(event_rate_hz * odt_bytes) * 8 / bitrate_bps * 100

daq_slot_usage(
    event_name: str,
    selected: Sequence[SelectedMeasurement],
    event_capacity: Mapping[str, int],
) -> float
    # returns 0..100; len([m for m in selected if m.event == event_name]) / capacity * 100
    # capacity 0 or missing key returns 100.0 (red on unknown)

estimate_throughput_bps(
    selected: Sequence[SelectedMeasurement],
) -> float
    # bytes/sec written to MF4; sum(event_rate_hz * payload_bytes); no compression

estimate_record_duration_s(
    throughput_bps: float,
    disk_free_bytes: int,
) -> float
    # disk_free_bytes / throughput_bps; returns float('inf') if throughput is 0

estimate_sample_events_per_s(
    selected: Sequence[SelectedMeasurement],
) -> float
    # total sample events per second; sum(event_rate_hz) over selected
```

Band helpers (also in `preflight_estimates.py`) return the canonical
`'green' | 'yellow' | 'red'` string for each Threshold Contract row that
isn't a percentage already covered above:

```text
band_disk_remaining(disk_free_bytes: int) -> str
band_sample_events_per_s(events_per_s: float) -> str
```

Each function and band helper is paired with at least one unit test whose
threshold bands match §Threshold Contract exactly. The right-pane widget
binds chip color purely from these numbers / band strings — no
widget-local computation, no fallback values.

Edge cases:

- A measurement whose `event` field is `None` (selection on an A2L without
  `IF_DATA XCP`) is excluded from `estimate_can_bus_load`,
  `estimate_throughput_bps`, and `estimate_sample_events_per_s`. The
  preflight row then shows "—" instead of a green `0%`, with tooltip
  explaining the A2L lacks DAQ events.
- `bitrate_bps` defaults to `500_000`; it is taken from `SessionConfig` and
  not hard-coded inside the estimator.

### Deferred: real IF_DATA XCP DAQ_EVENT extraction

The data shape (`MeasurementSummary.available_events`, `A2LSummary.event_capacity`,
`A2LSummary.measurement_events`, `A2LSummary.a2l_has_daq_events`) is in place
today, but `can_logger/p0/a2l_probe.load_measurement_summary()` returns
empty event maps and `a2l_has_daq_events=False` for every input until full
IF_DATA tree walking ships in Stage 8 alongside production Vector/XCP
support. Until then:

- Cockpit `--demo` and unit tests run against `FakeRecorderBackend` /
  `ReplayRecorderBackend`, which synthesize event metadata in code — the
  preflight pure functions never need real IF_DATA bytes.
- The `有 DAQ` filter auto-disables (§Left Pane fallback) so the UI never
  pretends DAQ information exists when it doesn't.
- A2L probe tests only assert backward-compatible field defaults; deeper
  IF_DATA parsing tests are deferred to Stage 8.

## Persistence Contract

### `acquisition_config.yaml` (per-project)

Lookup order:

1. Path provided by `--config` CLI flag (Cockpit).
2. `${A2L_DIR}/acquisition_config.yaml` (same directory as the loaded A2L).
3. `${PROJECT_ROOT}/acquisition_config.yaml` (git repo root if detectable).
4. None — Cockpit then operates in "no project pinned" mode; favorites and
   selections are kept in-memory only and a status-bar hint says so.

Schema:

```yaml
version: 1
a2l_path: "configs/a2l/X04C.a2l"           # informational, used to warn on mismatch
favorites:
  - name: EngSpdAvg
    address_hex: "0x40000000"               # optional, used to detect a2l drift
selected:
  - name: EngSpdAvg
    raster: event_10ms
  - name: EngTrqAct
    raster: event_10ms
filter_state:
  has_daq: true
  show_selected_only: false
  group: null
  datatype: null
threshold_overrides: {}                     # reserved; v1 ignores any non-empty value
```

`config_store.py` validates `version == 1` and raises a clear error on
unknown top-level keys.

### `~/.acquisition-cockpit/recent.json` (per-user)

```json
{
  "version": 1,
  "max_age_days": 14,
  "max_entries": 50,
  "entries": [
    {"name": "EngSpdAvg", "added_ts": 1715760000.0, "a2l_path": "..."},
    ...
  ]
}
```

The file is rewritten on every measurement selection; entries older than
`max_age_days` are pruned in-place.

### `session_summary.json` (per-recording, sidecar)

Written next to the finalized MF4 by `CaptureController.stop()`. The sidecar
filename is `<output_basename>.session_summary.json` (e.g. for
`captures/2026-05-15_141233.mf4` the sidecar is
`captures/2026-05-15_141233.session_summary.json`) so multiple captures
saved into the same directory never overwrite each other's diagnostics.

Field set is exact — no extra keys, no missing keys:

```json
{
  "version": 1,
  "duration_s": 12.4,
  "rx_count": 1240,
  "write_count": 1240,
  "queue_overflow_count": 0,
  "bus_error_count": 0,
  "dropped_frames": 0,
  "max_queue_depth": 17,
  "segments": [{"start_ts": 0.0, "end_ts": 12.4}],
  "output_mf4": "captures/2026-05-15_141233.mf4",
  "auto_stop": false,
  "warnings": []
}
```

Diagnostic information that the legacy `RecorderHealth.problems[]` list used
to carry (e.g. "ring buffer hit 90% for 3 s") MUST be folded into the
`warnings[]` array — there is no separate `problems` key. A unit test MUST
assert exact key-set equality against this schema.

### Relationship to `manifest.json`

`session_summary.json` is **always** written and is the capture-side artifact.
When the user clicks `保存并归档`, a new `Mf4DatasetEntry` is appended to
the project manifest with:

- `issue_tags` populated from `session_summary.warnings[]`.
- `expected_channels` populated from the A2L measurement names that were
  selected during recording (relies on the Writer channel-naming contract
  in Product Decisions).
- `sha256` computed during the save step.

`session_summary.json` is not embedded inside the manifest entry; manifest
points at the MF4, and the sidecar lives next to that MF4. This keeps the
diagnostic envelope decoupled from the archival index.

## Architecture Contract

### Packages

```text
mf4_analyzer/
├── acquisition/             # existing offline validation/manifest/preflight
├── acquisition_ui/          # new Cockpit QMainWindow and widgets
├── acquisition_capture/     # recorder/session/ring/writer services
│   ├── recorder.py          # backend interface + Fake/Replay/Vector impls
│   ├── ring_buffer.py       # lock-free ring + watermark Qt signal
│   ├── writer.py            # Mf4Writer (channel-name contract below)
│   ├── controller.py        # CaptureController (start/stop/flush)
│   ├── health.py            # HwHealth..RecHealth + HealthAggregator
│   ├── thresholds.py        # all numeric thresholds in §Threshold Contract
│   ├── preflight_estimates.py  # 4 pure functions in §Preflight Computation
│   ├── search.py            # SearchHit + scoring (§Search And Filter)
│   ├── a2l_events.py        # IF_DATA XCP DAQ_EVENT extraction
│   └── config_store.py      # acquisition_config.yaml + recent.json
├── ui/                      # existing Analyzer window
└── ui_kit/                  # shared style/icons/fonts/widgets after extraction
```

The exact package names may be adjusted during implementation review, but these
ownership boundaries must hold:

- `mf4_analyzer.ui` must not import `mf4_analyzer.acquisition_ui`.
- `mf4_analyzer.acquisition_ui` must not import Analyzer internals except a
  public handoff API.
- Shared UI pieces live below `mf4_analyzer.ui_kit`.
- Capture hot path lives outside Qt widgets and can be tested without Qt.

### Analyzer Handoff

- Add a public Analyzer method `MainWindow.load_file(path: str | Path) -> None`
  that wraps the existing private `_load_one` flow (`mf4_analyzer/ui/main_window.py`).
  The public method is the only handoff surface Cockpit is allowed to call;
  Cockpit MUST NOT touch `_load_one`. This addition is part of Stage 5 in the
  implementation plan and is the only Analyzer-side code change required.
- Cockpit finds existing Analyzer windows through `QApplication.topLevelWidgets()`.
- If an Analyzer window exists, call the public load method, then `raise_()` and
  `activateWindow()`.
- If none exists, create one and load the finalized file.
- Never call Analyzer handoff on an open writer file — the `finalized`
  predicate defined in §State Machine Contract guards this.

### Recorder Backend

Define a backend interface before Vector integration:

```text
RecorderBackend.start(config) -> stream/session handle
RecorderBackend.stop() -> final health snapshot
RecorderBackend.status() -> health snapshot
```

Required implementations by stage:

- `FakeRecorderBackend`: deterministic synthetic samples for macOS tests.
- `ReplayRecorderBackend`: reads a previously-captured MF4 (default) or a
  canned trace fixture (`tests/fixtures/replay_short.mf4`) and replays
  `(timestamp, channel, value)` tuples to the controller at wall-clock rate.
- `VectorXcpRecorderBackend`: lazy imports `python-can`/`pyxcp`, Windows-gated,
  implemented only after P0 hardware evidence.

All backends MUST also expose `last_frame_monotonic() -> float | None` so
that `HealthAggregator` can compute `RecHealth.last_rx_age_s`.

### Mf4Writer channel-naming rule

`Mf4Writer` MUST emit one MF4 channel per selected measurement using the A2L
measurement `name` verbatim (no prefix, no suffix, no transliteration).
This is the load-bearing contract for post-record diagnostics: the review
modal passes `expected_channels = tuple(m.name for m in selected)` to
`analyze_mf4(...)`, and that call only succeeds if the writer obeys this
rule. Stage 2's writer-spike report MUST cite this rule and include a round-
trip test that writes a fake recording, loads it via `DataLoader.load_mf4`,
and asserts channel set equality with the selected measurement names.

### Session Metadata

Every capture attempt that writes data MUST produce a `session_summary.json`
sidecar with the schema defined in §Persistence Contract. The capture
controller writes this file before signaling stop-complete; the review
modal reads it back rather than recomputing fields from in-memory state.

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
