# Cockpit Live-Cards Polish Design

**Date:** 2026-05-17
**Status:** Design approved by user from screenshot review of acquisition cockpit playback. Ready for implementation.

## User-Approved Direction

Overall cockpit visual style is OK. The center-pane live-signal cards are
visually correct in structure but have three problems that flatten the
sparkline curves into useless slivers:

1. Each card carries its own `REC OFF` / `● REC` row, duplicating the
   toolbar's global indicator and consuming a full text-row height ×
   N cards.
2. The sparkline minimum height is 36 px and the card lacks an
   `Expanding` size policy, so vertical viewport space leaks into the
   tail stretch instead of growing the curve.
3. The header is overstuffed (swatch · name · unit · raster · stats ·
   value, 7 widgets), with a constant `· since rec start` tail that is
   pure chrome.

A secondary signal-selection issue: raw bus-time channels
(`t [1:0]`, `t [2:0]`, `t [3:0]`) auto-populate as live cards with
near-identical monotonic ramps. They take card slots from the actual
signals the user cares about.

The overall cockpit chrome, palette, and typography family are unchanged.
This is a surgical polish, not a redesign.

## Problems To Solve

1. **REC chip waste.** `LiveSignalCard._build_ui` (`mf4_analyzer/acquisition_ui/widgets/live_cards.py:242-248`) installs a dedicated
   `QHBoxLayout` row holding only a `REC OFF` / `● REC` label and a
   stretch. The toolbar's global `cockpitRecIndicator`
   (`mf4_analyzer/acquisition_ui/main_window.py:376`) already exposes
   the same state, and the live-cards docstring at
   `widgets/live_cards.py:11-14` explicitly says the per-card indicator
   "MUST not disagree" with the toolbar one — i.e. it carries zero
   independent information. At 5 cards × ~22 px the row eats ~110 px
   of curve area.
2. **Squashed sparkline.** `Sparkline.setMinimumHeight(36)`
   (`widgets/live_cards.py:90`) plus `QSizePolicy(Expanding, Fixed)`
   floors curve height at ~36 px. `LiveCardGrid._layout`
   (`widgets/live_cards.py:362`) ends with `addStretch(1)`
   (line 434), so any free vertical pixels are absorbed by the bottom
   stretch instead of growing each card.
3. **Header overload.** `LiveSignalCard._build_ui`
   (`widgets/live_cards.py:207-240`) packs 7 widgets into one row. The
   stats label always carries a constant tail (`· since 60s` /
   `· since rec start`) that duplicates the global REC state.
4. **Typography ambiguity.** QSS (`mf4_analyzer/ui_kit/style.qss:651-666`)
   gives `liveCardName` weight 800 and `liveCardValue` weight 800.
   With both equally bold, the eye cannot pick out the current value —
   which is the most-read number on each card.
5. **Verbose raster pill.** Raster strings like `event_10ms` are passed
   through verbatim into the pill; the `event_` prefix is constant
   chrome.
6. **Default channel selection.** The signal selector seeds live cards
   with whatever channels the user picks, including raw `t [n:m]` time
   columns. These are near-monotonic ramps with very low information
   density per card and crowd out useful signals.

## Target Behavior

### A. Per-card recording state collapses into the swatch

Remove the dedicated REC row entirely. The recording state for each
card is conveyed by tinting the existing left-side swatch:

- `set_recording(False)`: swatch shows the trace color (unchanged).
- `set_recording(True)`: swatch turns solid red (`#dc2626`) with a thin
  white inner outline, and the card gains a 1 px red left border so the
  state is legible even when the swatch is the same color as the trace.

`LiveSignalCard.set_recording` keeps its current signature. The
existing toolbar `cockpitRecIndicator` is the source of truth for the
global state; the swatch reflects the same state via the
`MainWindow.set_recording` fan-out.

### B. Sparkline absorbs free vertical space

- `Sparkline.setMinimumHeight(36) → 72`.
- `Sparkline` size policy stays `QSizePolicy(Expanding, Expanding)`.
- `LiveSignalCard` size policy becomes `QSizePolicy(Expanding, Expanding)`.
- `LiveCardGrid._layout` removes the trailing `addStretch(1)` when at
  least one card is present. When zero cards are present (the
  "disconnected" canvas), the stretch is retained so the canvas stays
  centered.

Result: with N cards in a viewport of height H, each card receives
roughly `H / N` pixels and grows the sparkline as N decreases.

### C. Header consolidates to a tidy single row

Final header layout:

```text
[swatch] Name        ── stats(μ σ max)  raster·unit   value
```

- Drop the trailing `· since <window>` text. Move the window
  description to a tooltip on `liveCardStats`:
  `"Stats window: since recording start"` /
  `"Stats window: rolling 60 s"`.
- Move `unit_label` and `raster_pill` to the right side, just left of
  `value_label`, separated from stats by a stretch.
- Raster pill text strips the `event_` prefix: `event_10ms → 10 ms`.
  The full raster name is exposed via the pill's tooltip.

### D. Typography hierarchy

QSS changes in `mf4_analyzer/ui_kit/style.qss` (`liveCardName`,
`liveCardValue`):

| Selector | Before | After |
| --- | --- | --- |
| `liveCardName` | size 12 px, weight 800 | size 12 px, weight 700 |
| `liveCardValue` | size 14 px, weight 800 | size 16 px, weight 800 |
| `liveCardStats`, `liveCardUnit`, `liveCardRaster` | size 11 px, weight 600 | unchanged |

This re-orders the visual hierarchy: value > name > stats. The current
ordering reads name and value at equal prominence, which is wrong for
a live-data card.

### E. Inter-card spacing

`LiveCardGrid._layout.setSpacing(8) → 4`. Card vertical content
margins `(10, 8, 10, 8) → (10, 6, 10, 6)`. Horizontal margins
unchanged.

### F. Default time-channel exclusion

`LiveCardGrid.set_signals` gains a filter: any channel whose name
matches the regex `^t\s*\[\d+:\d+\]$` is silently dropped from the
auto-cards path. The channel remains available via the existing
signal selector right-click menu and is still recordable — only the
auto-card seeding skips it.

The filter lives at the grid boundary so the same call site is the
only place that decides what becomes a card, keeping the policy local
to the UI layer rather than leaking into capture-core.

## Non-Goals

- **No** redesign of the toolbar, header chrome, or status bar.
- **No** changes to capture-core, ring buffer, writer, or any
  signal-processing math. This is a pure UI polish.
- **No** new settings/preferences. The time-channel filter is
  hardcoded; if users want time channels they re-enable via existing
  channel selection UI.
- **No** changes to `Sparkline` rendering algorithm (min/max
  downsampling stays as-is per `widgets/live_downsampler.py`).

## Test Impact

- `tests/acquisition_ui/test_live_cards.py:38` asserts
  `"since 60s" in liveCardStats text`. This assertion moves to checking
  the stats label's tooltip.
- `tests/acquisition_ui/test_live_cards.py:44` asserts
  `"since rec start" in liveCardStats text` for the recording case.
  Same move — assert on tooltip.
- `tests/acquisition_ui/test_live_cards.py:43`
  `card.set_recording(True, rec_start_ts=0.0)` keeps working but the
  test should now also assert the swatch color flips to `#dc2626`
  (a new contract).
- `tests/acquisition_ui/test_visual_stylesheet_contract.py` already
  covers `liveCardSparkline` / `liveCardStats` selectors; the QSS
  font-size changes need a contract update if the contract pins exact
  values.
- New test: `LiveCardGrid.set_signals` filters `t [n:m]` channels by
  default. Cover both inclusion (regular channels stay) and exclusion
  (`t [1:0]` is dropped).
- New test: with 3 cards the cumulative card height + spacing leaves
  the sparkline floor at ≥ 72 px each (geometric check against
  `Sparkline.minimumHeight()`).

## Risk Notes

- The trailing `addStretch(1)` removal must keep working for the
  disconnected canvas (no cards). Verify by reading
  `LiveCardGrid._build_disconnected_canvas` and the `set_signals([])`
  path.
- The time-channel filter regex must be tight enough not to drop
  legitimate channel names that happen to start with `t`. The pattern
  `^t\s*\[\d+:\d+\]$` requires the exact `t [n:m]` shape.
- QSS font-size bumps may shift toolbar/right-panel layout slightly.
  Confirm via the existing visual-stylesheet contract test and a
  qtbot rendering smoke run.

## File Touch List (preview)

- `mf4_analyzer/acquisition_ui/widgets/live_cards.py` — structural
  layout changes (remove REC row, header reorder, swatch tinting,
  grid stretch policy, time-channel filter).
- `mf4_analyzer/ui_kit/style.qss` — typography weights + recording
  swatch style.
- `tests/acquisition_ui/test_live_cards.py` — update assertions, add
  new tests.
- `tests/acquisition_ui/test_visual_stylesheet_contract.py` — update
  QSS pins if any.
