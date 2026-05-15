# Acquisition Cockpit v3 Visual Parity Spec

## Context

This spec is a corrective visual-parity pass for the Acquisition Cockpit Qt UI.
It does not change capture semantics, Vector/XCP production scope, recording
finalization, or Analyzer handoff behavior. The target is the already-approved
v3 prototype:

- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html`
- Existing functional spec:
  `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`
- Existing implementation plan:
  `docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md`

The current Qt implementation satisfies much of the behavioral wiring but
renders too close to native PyQt defaults. This pass must make the first
screen read as the v3 capture cockpit: compact toolbar, selector controls,
health chips with values, state-aware panels, dense A2L selection, live-card
visuals, and right-panel preflight meters.

## Non-Goals

- No production Vector/XCP backend work.
- No new capture core thresholds, unless a test proves a current visual label
  must consume an existing value at runtime.
- No rewrite of `CaptureController`, writer, manifest, review modal, replay
  backend, or history model.
- No Analyzer-wide restyle beyond scoped cockpit selectors in
  `mf4_analyzer/ui_kit/style.qss`.
- No pixel-perfect screenshot test in this pass. Assertions are structural,
  object-name/property based, and text/value based.

## Evidence Baseline

### v3 prototype anchors

- Window shell, toolbar, selector, segment, REC pill, and health chip styling:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html:75-220`
- Connected-idle toolbar and health strip:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html:742-790`
- Left-pane A2L Measurement tree, filters, batch bar, event pill:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html:794-835`
- Center live cards and preflight right panel:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html:909-1088`
- Disconnected first screen:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html:1124-1233`
- v3 product deltas:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html:1435-1442`

### Current implementation anchors

- Cockpit currently builds a native `QToolBar`, native `QTabWidget` mode tabs,
  and a plain REC `QLabel`:
  `mf4_analyzer/acquisition_ui/main_window.py:253-357`
- The three-pane splitter is already present:
  `mf4_analyzer/acquisition_ui/main_window.py:359-383`
- State text currently drives the main button and REC label:
  `mf4_analyzer/acquisition_ui/main_window.py:405-452`
- Health levels currently only repaint a small LED plus the chip name:
  `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
- Left pane currently renders header/search/two checkboxes/QListWidget/footer:
  `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
- Right panel currently renders form rows:
  `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- Live cards currently render functional sparkline cards without v3 card
  hierarchy, multi-color swatches, or disconnected canvas:
  `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Shared QSS only scopes Analyzer's custom `Toolbar`; no cockpit-specific
  stylesheet selectors exist:
  `mf4_analyzer/ui_kit/style.qss`

## Visual Contract

### 1. Window And Surface

- The cockpit window keeps title `"MF4 采集 Cockpit"` unless a later product
  spec renames it.
- The root surface remains `#f5f7fb`; pane/card surfaces are `#ffffff`;
  divider hairlines use `#eef2f7` or `#dfe5ee`.
- No nested card-in-card composition. Page sections are full-width bands or
  pane surfaces. Cards are only live signal cards, right-panel metric sections,
  and modal/review surfaces.
- The implementation must use object names and dynamic properties so visual
  tests can assert structure without screenshots.

### 2. Top Toolbar

The current native `QToolBar` must be replaced or visually neutralized so it
matches the v3 toolbar band.

Required hierarchy:

```text
[A2L selector] [DBC selector disabled] [输出 selector] | [采集 回放 历史 segment] ... [REC pill] [main button]
```

Selector contract:

- Use compact selector widgets with object names:
  - `cockpitSelectorA2l`
  - `cockpitSelectorDbc`
  - `cockpitSelectorOutput`
- Each selector displays a small key (`A2L`, `DBC`, `输出`) and a value.
- Initial values:
  - A2L: `未加载`
  - DBC: `可选`
  - 输出: `data/runs`
- DBC remains disabled and keeps tooltip
  `"Reserved for raw CAN capture; XCP path uses A2L."`
- A2L selector still opens the A2L file dialog.
- Output selector still opens the output directory dialog.
- Settings remains reachable, but it must not become the dominant fourth
  primary toolbar button. It may be an icon/tool button or compact ghost action.

Mode segment contract:

- `采集 / 回放 / 历史` is a toolbar segmented control, not visible native tab
  chrome below the health strip.
- The hidden or neutralized `QTabWidget` may remain as the page container for
  existing behavior, but its tab bar must not appear as a second navigation row.
- Segment buttons must mirror and drive `cockpitModeTabs.currentIndex()`.
- Segment buttons object names/properties:
  - host `cockpitModeSegment`
  - buttons with property `cockpitMode = capture|replay|history`
  - active button checked.

Main button contract:

- Disconnected: blue `连接 ECU`, role/property `cockpitAction = connect`.
- Connected idle: red `● 采集`, role/property `cockpitAction = record`.
- Recording: red `■ Stop & 复盘`, role/property `cockpitAction = stop`.
- Review modal: disabled, keeps last safe text.
- Button min-height target is 36 px. Do not let global `QPushButton` padding
  inflate it into the oversized native look from the current screenshot.

REC pill contract:

- Global REC indicator object name remains `cockpitRecIndicator`.
- It must include a visible dot and text in one pill-like surface.
- Dynamic property `recState` must be one of `off`, `recording`, `warn`, `error`.
- Disconnected and idle use `REC OFF` with gray dot.
- Recording uses `REC mm:ss` or `● REC` with red dot; elapsed text may be added
  later, but the state property and red styling must be present now.

### 3. Health Strip

Health strip target is not just five LED labels. Each chip is a pill:

```text
HW VN1610 | CAN 2 ch online | XCP slave 0x55 | DAQ 12 sig / 3 evt | REC ready
```

Required widget contracts:

- `HealthChip` displays LED, label, and value.
- `HealthChip.set_level(level)` still writes dynamic property `level`.
- Add `HealthChip.set_value(text)`.
- `HealthStrip.apply_snapshot(snapshot)` must set chip values from typed
  snapshot fields and must preserve existing tooltip rules.
- Health strip includes:
  - right summary label object name `healthSummary`
  - optional disconnect button object name `healthDisconnectButton`
- Disconnected state may show dimmed/off values, but chip pills still exist.

Value mapping:

- `HW`: `VN1610` when hardware is ok and `driver_version` exists; otherwise
  `offline` or `--`.
- `CAN`: if `bus_load_pct` known, show `NN% load`; if channels are present,
  prefer `<n> ch online`.
- `XCP`: if connected and `slave_id` exists, show `slave 0x...`; if connected
  without id, show `connected`; otherwise `--`.
- `DAQ`: if capacity exists, show `<used> sig / <event_count> evt`; otherwise
  `--`.
- `REC`: `ready`, `recording`, `warn`, or `--` derived from `RecHealth.state`
  and level.

### 4. Left Pane

The left pane must read as v3 `A2L Measurement`, not a generic checkbox list.

Required structure:

- Header row:
  - title `A2L Measurement`
  - summary label object name `leftPaneSummary`
  - text format: `<total> · 显示 <visible> · 选 <selected>`
- Search placeholder: `搜索 name / 0x40A...`
- Filter chips row:
  - `只看已选`
  - `有 DAQ`
  - `最近`
  - `收藏`
  - `组: All`
  - `类型`
- Only `只看已选` and `有 DAQ` must change filtering in this pass. The other
  chips can be disabled/passive but must render as compact chips so visual
  density matches v3.
- A batch bar appears when at least two selected measurements share a common
  event:
  - object name `leftBatchBar`
  - text contains `已选` and the first common event.
  - actions may remain no-op in this pass.
- Rows must not use default `QListWidget` checkbox chrome as the primary visual
  identity. Acceptable minimum:
  - selected row background via `QListWidget::item:selected` or custom row
    widget;
  - row text includes name, unit, and raster/event pill text such as `@ 10ms`.
- Footer must include selected count, estimated bandwidth/load, and event
  distribution if events are present.

### 5. Center Pane

Disconnected state:

- Center pane shows a designed empty canvas, not a one-line placeholder.
- Object name `cockpitDisconnectedCanvas`.
- Text includes:
  - title `未连接 ECU`
  - copy explaining data stream appears after connection
  - compact `连接 ECU` action or existing toolbar action reference.

Connected idle and recording:

- Live cards are white rounded cards with hairline border.
- Each card header contains:
  - color swatch
  - signal name
  - unit
  - raster pill
  - stats
  - right-aligned current value
- Cards must use deterministic color assignment across order:
  `#2563eb`, `#059669`, `#ea580c`, `#0891b2`, `#64748b`, then repeat.
- Sparkline gridlines use hairline color, not a blank white canvas.
- The card's per-signal REC label remains consistent with the global REC state.

### 6. Right Pane

Right pane must switch from form layout rows to v3-like sections with meters.

Disconnected page:

- Header `连接前检查`.
- Sections:
  - `A2L`
  - `硬件`
  - `当前选择`
  - verdict banner
- It may use available current data, but must not invent successful hardware
  state when the snapshot is unknown. Unknown is shown as `--` or `等待中`.

Connected idle page:

- Header `录制预检`, ready/substatus label on the right.
- Sections:
  - `CAN 总线负载`
  - `DAQ slot · ECU 端容量`
  - `磁盘写速`
  - `采样事件 / 秒`
  - `输出`
- `CAN`, `DAQ`, `磁盘`, and `采样事件 / 秒` continue to use the pure helpers in
  `mf4_analyzer/acquisition_capture/preflight_estimates.py`; do not duplicate
  threshold formulas in the widget.
- Each section must expose labels that tests can inspect:
  - `idleCanValue`
  - `idleDaqValue`
  - `idleDiskValue`
  - `idleSamplesValue`
  - `idleVerdictBanner`
- Meters may be implemented with `QProgressBar`, `QFrame` width tricks, or
  text-only bars in this pass. The object-name contract is more important than
  pixel tests.

Recording page:

- Header `实时质量监控`.
- Sections:
  - ring buffer
  - write rate
  - dropped frames
  - CAN load
  - last frame delay
  - disk remaining
- Use `RecHealth`, `CanHealth`, and current disk-free values. No free-form
  recorder status parsing.

### 7. Style Sheet

Add cockpit-scoped QSS to `mf4_analyzer/ui_kit/style.qss`.

Required selector families:

- `QWidget#cockpitToolbarBand`
- `QFrame#cockpitSelector`
- `QWidget#cockpitModeSegment`
- `QLabel#cockpitRecIndicator`
- `QFrame#healthStrip`, `QFrame#healthChip`
- `QFrame#leftPane`, `QWidget#filterChip`, `QFrame#leftBatchBar`
- `QWidget#cockpitDisconnectedCanvas`
- `QFrame#liveSignalCard`
- `QFrame#rightPanelPage`, `QFrame#rightMetricSection`, `QLabel#rightVerdictBanner`

The stylesheet must remain loaded through the existing
`mf4_analyzer.ui_kit.load_stylesheet(app)` path used by both Analyzer and
Cockpit.

### 8. Tests And Verification

New or updated tests must cover structure, not screenshots:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui -v
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_toolbar.py -v
git diff --check
```

Minimum visual contract tests:

- Toolbar selectors exist and tab bar is hidden/neutralized.
- Mode segment drives `cockpitModeTabs`.
- Main button dynamic `cockpitAction` changes by state.
- REC indicator dynamic `recState` changes by state/health.
- Health chips expose label + value and snapshot-derived levels.
- Left pane renders six filter chips and updates summary.
- Center disconnected canvas exists before connection.
- Live cards expose swatch/raster/value/stat labels.
- Right panel exposes section labels and keeps helper delegation tests passing.
- QSS contains all required cockpit selector families.

## Acceptance

This pass is accepted when:

- Current screenshot's native-default appearance is removed from toolbar,
  mode tabs, health strip, left pane, center empty state, live cards, and right
  panel.
- The v3 hierarchy is structurally represented in Qt widgets.
- Existing capture, right-panel helper delegation, status, and demo smoke tests
  remain green.
- No production hardware claims are made without Windows + Vector evidence.
