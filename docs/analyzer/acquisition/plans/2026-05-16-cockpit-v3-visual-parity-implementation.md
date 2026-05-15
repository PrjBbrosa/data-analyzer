# Acquisition Cockpit v3 Visual Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the current PyQt Acquisition Cockpit shell into structural and visual parity with the approved v3 HTML prototype without changing capture semantics.

**Architecture:** Keep the existing capture state machine, health snapshots, left-pane search model, right-panel helper delegation, replay/history tabs, and demo entrypoint. Replace native-looking shell pieces with cockpit-scoped Qt widgets and QSS object-name contracts. Split work by component so multiple workers can edit in parallel without sharing files.

**Tech Stack:** PyQt5 widgets, existing `mf4_analyzer.ui_kit.style.qss`, existing acquisition capture dataclasses/helpers, pytest with `QT_QPA_PLATFORM=offscreen`.

---

## Source Inputs

- Spec for this pass:
  `docs/analyzer/acquisition/specs/2026-05-16-cockpit-v3-visual-parity-spec.md`
- v3 prototype:
  `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html`
- Current cockpit shell:
  `mf4_analyzer/acquisition_ui/main_window.py`
- Current widgets:
  `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
  `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
  `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
  `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- Shared stylesheet:
  `mf4_analyzer/ui_kit/style.qss`

## Current Dirty-Tree Guard

The worktree already contains unrelated/uncommitted acquisition edits:

- `docs/lessons-learned/INDEX.md`
- `docs/lessons-learned/codex-acquisition-threshold-defaults-use-current-values.md`
- `mf4_analyzer/acquisition_capture/health.py`
- `mf4_analyzer/acquisition_capture/session.py`
- `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- `tests/acquisition_ui/test_right_panel.py`
- `tests/test_acquisition_settings_overrides.py`

Agents must not revert these changes. If editing a dirty file, read the current
file first and preserve existing threshold/runtime-default behavior.

## Parallel Work Decomposition

### Worker A - Shell And Toolbar

**Owned files:**

- Modify: `mf4_analyzer/acquisition_ui/main_window.py`
- Create or modify: `tests/acquisition_ui/test_visual_shell.py`

**Do not edit:** `mf4_analyzer/ui_kit/style.qss`,
`mf4_analyzer/acquisition_ui/widgets/right_panel.py`.

**Required behavior:**

- Replace native `QToolBar` visual shell with a `QWidget`/`QFrame` toolbar band
  added to the central layout above `HealthStrip`, or neutralize `QToolBar` so
  the hierarchy matches the v3 toolbar.
- Build compact selector widgets for A2L, DBC, and output with object names:
  `cockpitSelectorA2l`, `cockpitSelectorDbc`, `cockpitSelectorOutput`.
- Keep A2L/output click behavior and DBC disabled tooltip.
- Add toolbar mode segment:
  - host object name `cockpitModeSegment`
  - buttons property `cockpitMode = capture|replay|history`
  - checked state mirrors `cockpitModeTabs.currentIndex()`.
- Hide or neutralize the visible `QTabWidget` tab bar so `采集/回放/历史`
  appears only in the toolbar segment.
- Set main button property `cockpitAction` to `connect`, `record`, `stop`, or
  `disabled` in `_apply_state_to_ui`.
- Set REC indicator property `recState` to `off`, `recording`, `warn`, or
  `error`.

**Test steps:**

- [ ] Add `tests/acquisition_ui/test_visual_shell.py::test_toolbar_selectors_and_mode_segment_exist`.
  Assert the three selectors exist by object name, DBC is disabled, and the
  tooltip equals `Reserved for raw CAN capture; XCP path uses A2L.`
- [ ] Add `test_mode_segment_drives_hidden_tab_widget`.
  Click the replay/history/capture segment buttons and assert
  `window.mode_tabs().currentIndex()` changes to `1`, `2`, `0`.
- [ ] Add `test_main_button_visual_action_properties_follow_state`.
  Assert disconnected property is `connect`, connected idle is `record`, and
  recording is `stop`.
- [ ] Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_visual_shell.py \
  tests/acquisition_ui/test_state_machine.py \
  tests/acquisition_ui/test_status_bar_text.py -v
```

Expected: all selected tests PASS.

### Worker B - Cockpit Scoped QSS

**Owned files:**

- Modify: `mf4_analyzer/ui_kit/style.qss`
- Create: `tests/acquisition_ui/test_visual_stylesheet_contract.py`

**Do not edit:** Python widget files.

**Required behavior:**

- Add cockpit-scoped QSS selectors listed in the spec §7.
- Keep existing Analyzer `Toolbar` selectors unchanged.
- Add explicit rules for:
  - compact toolbar band height/padding
  - selector frame and label/value typography
  - segment checked state
  - REC pill properties by `recState`
  - health chip pill/value styling
  - filter chips and batch bar
  - disconnected canvas
  - live cards
  - right metric sections and verdict banner
- Do not add global `QPushButton` changes that alter Analyzer's toolbar.

**Test steps:**

- [ ] Add a text contract test that reads `mf4_analyzer/ui_kit/style.qss`.
- [ ] Assert required selectors exist:
  `cockpitToolbarBand`, `cockpitSelector`, `cockpitModeSegment`,
  `cockpitRecIndicator`, `healthChip`, `filterChip`,
  `cockpitDisconnectedCanvas`, `liveSignalCard`, `rightMetricSection`,
  `rightVerdictBanner`.
- [ ] Assert the existing `Toolbar QPushButton[segment="time"]` selector still
  exists.
- [ ] Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_visual_stylesheet_contract.py -v
git diff --check
```

Expected: PASS and no whitespace errors.

### Worker C - Health Strip

**Owned files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
- Modify: `tests/acquisition_ui/test_health_strip.py`

**Do not edit:** `main_window.py`, `style.qss`.

**Required behavior:**

- Extend `HealthChip` from LED + name to LED + label + value.
- Add `set_value(text: str)`.
- Set object names:
  - chip frame `healthChip`
  - led `healthChipLed`
  - label `healthChipLabel`
  - value `healthChipValue`
- `HealthStrip.apply_snapshot()` sets value text from the typed snapshot.
- Add summary label `healthSummary`.
- Preserve existing `current_levels()`, `chip(name)`, tooltip behavior, and
  `levels_changed` emission semantics.

**Test steps:**

- [ ] Extend `test_strip_all_green` to assert each chip has a non-empty value
  label after `_snap()`.
- [ ] Add `test_strip_chip_values_come_from_snapshot_fields`.
  Use `slave_id=0x55`, DAQ capacity/used, and `RecHealth.state="recording"`;
  assert XCP value contains `0x55`, DAQ value contains `sig` or `/`, and REC
  value contains `recording` or `ready`.
- [ ] Keep existing tooltip/no-evidence tests passing.
- [ ] Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_health_strip.py -v
```

Expected: PASS.

### Worker D - Left Pane

**Owned files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
- Modify: `tests/acquisition_ui/test_left_pane.py`

**Do not edit:** `style.qss`, `main_window.py`.

**Required behavior:**

- Change header title to `A2L Measurement`.
- Add summary label `leftPaneSummary` with text
  `<total> · 显示 <visible> · 选 <selected>`.
- Change search placeholder to `搜索 name / 0x40A...`.
- Render six compact filter chips:
  `只看已选`, `有 DAQ`, `最近`, `收藏`, `组: All`, `类型`.
- Only `只看已选` and `有 DAQ` need active filtering. Other chips may be
  disabled/passive but visible.
- Add `leftBatchBar`, hidden until at least two selected measurements share a
  common event. When shown, text includes `已选` and the common event.
- Row text includes measurement name, unit, and first event as `@ 10ms` /
  `@ 100ms` where possible. Preserve checkable behavior and freeze behavior.
- Footer includes selected count, CAN estimate, and event distribution when
  selected events exist.

**Test steps:**

- [ ] Update existing tests for the new title/placeholder without weakening
  filtering assertions.
- [ ] Add `test_filter_chip_row_has_v3_six_chips`.
  Assert visible chip texts contain all six names.
- [ ] Add `test_summary_updates_total_visible_selected_counts`.
  Seed pool, toggle one row, assert `leftPaneSummary` changes to include
  `选 1`.
- [ ] Add `test_batch_bar_appears_for_common_event_selection`.
  Select two `event_10ms` rows and assert `leftBatchBar.isVisible()` plus
  text contains `event_10ms`.
- [ ] Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py -v
```

Expected: PASS.

### Worker E - Center Pane And Live Cards

**Owned files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Create or modify: `tests/acquisition_ui/test_live_cards.py`

**Do not edit:** `main_window.py`, `style.qss`.

**Required behavior:**

- Replace the one-line placeholder with a disconnected canvas:
  - object name `cockpitDisconnectedCanvas`
  - title `未连接 ECU`
  - supporting text about data stream appearing after connection.
- Give each `LiveSignalCard` a header matching v3:
  - swatch label `liveCardSwatch`
  - name `liveCardName`
  - unit `liveCardUnit`
  - raster `liveCardRaster`
  - stats `liveCardStats`
  - value `liveCardValue`, right aligned.
- Assign deterministic trace/swatch colors by card index:
  `#2563eb`, `#059669`, `#ea580c`, `#0891b2`, `#64748b`, repeat.
- Sparkline keeps using `downsample_minmax`.
- Preserve `set_recording()` behavior and stats labels
  `since 60s` / `since rec start`.

**Test steps:**

- [ ] Add `test_disconnected_canvas_replaces_plain_placeholder`.
  Instantiate `LiveCardGrid`, assert `cockpitDisconnectedCanvas` exists and
  title text contains `未连接 ECU`.
- [ ] Add `test_live_card_visual_parts_exist`.
  Call `set_signals([("EngSpdAvg", "rpm", "event_10ms")])`; assert the card
  has swatch/name/unit/raster/value/stats labels.
- [ ] Add `test_live_card_colors_are_deterministic`.
  Add at least three signals and assert their swatch styles/properties expose
  different colors in the expected order.
- [ ] Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py \
  tests/acquisition_ui/test_live_downsampler.py -v
```

Expected: PASS.

### Worker F - Right Panel Visual Sections

**Owned files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- Modify: `tests/acquisition_ui/test_right_panel.py`

**Important dirty-file note:** preserve the existing runtime threshold change:
`IdlePreflightPage.apply(..., bitrate_bps: int | None = None)` must dereference
`thresholds.DEFAULT_CAN_BITRATE_BPS` at call time when `bitrate_bps is None`.

**Do not edit:** `style.qss`, `main_window.py`.

**Required behavior:**

- Convert pages from bare `QFormLayout` rows into titled metric sections.
- Disconnected page header must be `连接前检查`, with section labels for A2L,
  hardware, current selection, and verdict.
- Idle page header must be `录制预检`.
- Idle page object-name labels:
  - `idleCanValue`
  - `idleDaqValue`
  - `idleDiskValue`
  - `idleSamplesValue`
  - `idleVerdictBanner`
- Recording page header must be `实时质量监控`.
- Keep all helper delegation tests intact: do not inline formulas.
- It is acceptable for meters to be text-based in this pass if object names and
  section hierarchy are correct.

**Test steps:**

- [ ] Add `test_idle_page_v3_sections_exist`.
  Assert header text is `录制预检`, value labels are discoverable by object name,
  and verdict banner exists.
- [ ] Add `test_disconnected_page_v3_sections_exist`.
  Assert `连接前检查` and section labels for A2L/硬件/当前选择 exist.
- [ ] Add `test_recording_page_v3_sections_exist`.
  Assert `实时质量监控` and ring/write/drop/CAN/rx/disk labels exist.
- [ ] Preserve `test_idle_page_uses_current_default_can_bitrate`.
- [ ] Run:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_right_panel.py -v
```

Expected: PASS.

## Integration Steps

- [ ] Wait for all workers.
- [ ] Inspect changed files and resolve conflicts manually if two workers touched
  the same file unexpectedly.
- [ ] Run targeted acquisition UI suite:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui -v
```

- [ ] Run demo self-test:

```bash
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test
```

- [ ] Run Analyzer smoke guard:

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py tests/ui/test_toolbar.py -v
```

- [ ] Run docs routing and whitespace checks:

```bash
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
git diff --check
```

## Final Acceptance Checklist

- [ ] Toolbar selectors, mode segment, REC pill, and main button no longer read
  as native PyQt defaults.
- [ ] Native `QTabWidget` tab bar is not visible as a second navigation row.
- [ ] Health strip chips include snapshot-derived values.
- [ ] Left pane has v3 title, summary, six chips, row event pill text, and batch
  bar.
- [ ] Disconnected center state has a designed canvas.
- [ ] Live cards have swatches, raster pills, stats, and right-aligned values.
- [ ] Right panel has v3 sections and named values while preserving helper
  delegation.
- [ ] Existing capture behavior tests remain green.
- [ ] No unrelated dirty-tree changes were reverted.
