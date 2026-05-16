# Acquisition UI Overflow / Scroll-Container Spec

Date: 2026-05-16
Status: Execution-ready draft
Branch: `feat/acquisition`
Wave scope: strictly `mf4_analyzer/acquisition_ui/*` and `tests/acquisition_ui/*`.
`mf4_analyzer/acquisition_capture/*` is **off-limits for the whole wave** —
no edits, no symbol relocations, no signature changes.

Cited lessons (all four MUST be honored by the executing specialists):

- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`
  — narrow/wide-pane verification at three widths; container-first
  diagnosis; cap+left-anchor for splitter slots.
- `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`
  — `body.setMaximumWidth(<form_natural_width>)` plus an
  `addStretch`-padded host so the cap visibly leaves a right-side gap
  at the wide end.
- `docs/lessons-learned/pyqt-ui/2026-05-15-save-action-must-not-close-gating-modal.md`
  — the `在 Analyzer 打开` button must remain reachable; do NOT mutate
  the save→accept flow; do NOT close the modal on save.
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`
  — when wrapping content in a `QScrollArea` or stretch host, run the
  visibility helper once at `__init__` end so initial state is honest
  before `show()`.

## Goal

Four discrete container defects in the acquisition Cockpit UI surface as
out-of-window content, clipping, single-line concatenation, and broken
toolbar layout at narrow widths. None of them are algorithm bugs — every
fix lives at the **container/layout** level inside `acquisition_ui/`.
Each defect gets its own contract, its own resize matrix, and its own
regression test set.

Out of scope for this wave (explicit, see §Deferred):

- LeftPane 二级 chip 行 overflow
- ReplayTab transport row 8-button overflow
- Elide / 字符截断 治理
- `QMessageBox.open()` 模态语义复核
- Color-token 治理
- HistoryTab `filter_row` / `_tag_row` overflow (P2 — deferred to a
  later wave; do NOT touch in this one)

## Source Inputs

- `mf4_analyzer/acquisition_ui/widgets/live_cards.py:341-347` —
  `LiveCardGrid.__init__` builds a plain `QVBoxLayout` with
  `addStretch(1)`, no `QScrollArea`. Each `LiveSignalCard`'s
  `Sparkline.setMinimumHeight(36)` at line 89 plus header rows pushes
  per-card height to ~110 px. At ≥6 cards on a 760-tall window the
  bottom card runs off the central pane.
- `mf4_analyzer/acquisition_ui/replay_tab.py:142` — ReplayTab embeds
  the same `LiveCardGrid` inside a horizontal `QSplitter`; the fix to
  LiveCardGrid benefits this surface for free.
- `mf4_analyzer/acquisition_ui/review_modal.py:145-205` —
  `_build_ui` lays out the modal with a plain `QVBoxLayout`. No
  `QScrollArea`, no `setMinimumSize`, no `setSizeGripEnabled`.
  `pf_label` at lines 180-187 concatenates the entire
  `preflight.missing_channels` list via `", ".join(...)` into one
  `QLabel`; a 100-entry list balloons the modal width past any
  practical screen.
- `mf4_analyzer/acquisition_ui/widgets/right_panel.py:455-465` —
  `RightPanel.__init__` calls `setFixedWidth(300)`; each
  `_BasePanelPage` is a `QFrame` with a `QVBoxLayout` ending in
  `addStretch(1)`. `IdlePreflightPage` adds 5 metric sections + 1
  verdict banner. At 96 dpi with default font this fits; at any
  larger system font or shorter window the bottom section clips.
- `mf4_analyzer/acquisition_ui/main_window.py:298-388` —
  `_build_toolbar` rolls its own `QFrame + QHBoxLayout`, not a
  `QToolBar`. Selectors use `setFixedWidth(130/150/180)`; mode
  segment + REC indicator + primary button consume ≥600 px of fixed
  width before the spacer. `MainWindow.resize(1280, 760)` at line 174
  sets the *initial* size but no `setMinimumSize`. Dragging the
  window narrower than ~1100 px clips the right edge.

## Scope

In scope (per defect — exhaustive list):

- **S1 LiveCardGrid scroll.** Wrap the cards layout in a
  `QScrollArea`. Keep `Sparkline.setMinimumHeight(36)` intact;
  vertical overflow is solved at the container, not by shrinking the
  cards.
- **S2 ReviewModal resize + scroll + missing-channels list.** Add
  size grip, minimum size, body-level `QScrollArea`. Replace the
  joined `QLabel` for `missing_channels` with a capped `QListWidget`.
- **S3 RightPanel page scroll + width policy.** Replace
  `setFixedWidth(300)` with `setMinimumWidth(280) + setMaximumWidth(360)`.
  Each page wraps its existing body in a `QScrollArea`, with the
  scroll body capped + left-anchored per the inspector-cap lesson.
- **S4 MainWindow toolbar overflow + window minimum.** Add
  `MainWindow.setMinimumSize(960, 600)`. Loosen the toolbar's
  fixed-width selectors to a `min+max` range. Add an overflow
  `[≡]` `QToolButton` that auto-hides actions whose accumulated
  width exceeds the toolbar's outer width and re-exposes them via a
  `QMenu` of the same `QAction`s.

Out of scope inside the same wave: see §Deferred at the end of this
file. Bumping into any item in that list during execution MUST be
flagged back to the orchestrator, not silently absorbed.

## Source-of-truth boundaries

- **`mf4_analyzer/acquisition_capture/*` is read-only for this wave.**
  No imports added, no signatures touched, no constants added or
  moved.
- The four-state machine (`DISCONNECTED → CONNECTED_IDLE → RECORDING
  → REVIEW`) transitions must not change.
- `MainWindow.load_file(path)` public wrapper installed by the prior
  Stage 5 wave must remain untouched (signature, location, side
  effects).
- `ReviewModal.do_save_only` / `do_archive` MUST continue NOT to
  close the modal (CR3 contract from the
  `save-action-must-not-close-gating-modal` lesson). Adding scroll +
  size grip MUST NOT route a new code path that calls
  `accept()/reject()` from a save action.

---

## Defect S1 — LiveCardGrid overflow

### S1.1 User story

**Today** — the user connects an ECU and selects 8 measurements. The
center pane renders eight live cards stacked vertically. Cards 7 and 8
fall below the visible center pane; there is no scrollbar, so the user
cannot reach them. ReplayTab inherits the same defect because it
embeds `LiveCardGrid` inside its splitter.

**After the fix** — selecting any number of measurements always shows
the first cards in the visible viewport; the center pane shows a
vertical scrollbar when total card height exceeds the viewport;
horizontal scrolling never appears (cards size to the viewport width).
The placeholder ("未连接 ECU") still occupies the full pane when no
signal is selected. Sparkline height remains 36 px (the card height
contract from §Center Pane is unchanged).

### S1.2 Container contract

LiveCardGrid wraps its inner `QVBoxLayout` of cards in a
`QScrollArea` with:

- `verticalScrollBarPolicy = Qt.ScrollBarAsNeeded`
- `horizontalScrollBarPolicy = Qt.ScrollBarAlwaysOff`
- `widgetResizable = True`
- The placeholder "未连接 ECU" path bypasses the scroll area
  (`addStretch(1)` host inside the scroll viewport is fine; the
  empty-state must still center vertically).
- `LiveCardGrid.sizeHint().height()` MUST NOT scale linearly with
  channel count above `N=6`. Above N=6 the outer widget's
  `sizeHint().height()` MUST stay within ±20% of the N=6 value.
  Implementation: the scroll viewport reports its own size hint, not
  the inner content's hint.
- `LiveCardGrid.cards` mapping must continue to return one entry per
  signal regardless of viewport visibility (tests rely on it).
- Sparkline `setMinimumHeight(36)` at `live_cards.py:89` is preserved.

### S1.3 Resize/scroll behavior matrix

| Width (px) | N=3 cards | N=8 cards | N=20 cards |
|---|---|---|---|
| Narrow 800 (window minimum, see S4) | No vScroll, all visible | vScroll visible, top 3-4 in viewport | vScroll visible, top 3-4 in viewport |
| Default 1280 | No vScroll, all visible | vScroll visible, top ~5 in viewport | vScroll visible, top ~5 in viewport |
| Wide 1920 (~1.5× default) | No vScroll, all visible | vScroll visible, top ~6 in viewport | vScroll visible, top ~6 in viewport |

In all three widths: no horizontal scrollbar; cards' inner width
follows the viewport width (cards stretch horizontally because
viewport is `widgetResizable=True`); no clipping outside the
LiveCardGrid bounds.

### S1.4 Regression test requirements

`tests/acquisition_ui/test_live_cards.py` — new tests:

- `test_live_card_grid_wraps_scroll_area_when_overflowing`:
  set N=20 signals, assert `grid.findChild(QScrollArea)` is not
  `None`, `scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded`,
  `scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff`,
  `scroll.widgetResizable() is True`.
- `test_live_card_grid_size_hint_does_not_grow_linearly`:
  measure `grid.sizeHint().height()` at N=6 and at N=20; assert
  `abs(h20 - h6) / h6 <= 0.20`.
- `test_live_card_grid_vertical_scrollbar_visible_when_overflow`:
  resize grid to 800×500, set N=20, `grid.show()`, process events,
  assert `scroll.verticalScrollBar().isVisible() is True`.
- `test_live_card_grid_horizontal_scrollbar_never_visible`:
  resize grid to 800×500, set N=20, assert
  `scroll.horizontalScrollBar().isVisible() is False`.
- `test_live_card_grid_empty_state_still_centered`:
  call `set_signals([])`, assert placeholder
  `cockpitDisconnectedCanvas` is visible and the scroll area, if
  present, does not show a vertical scrollbar.

ReplayTab regression (in `tests/acquisition_ui/test_replay_tab.py`):

- `test_replay_tab_live_cards_scroll_when_overflowing`: existing
  ReplayTab fixture, push N=20 signals through `_live_cards`, assert
  vertical scrollbar visible.

### S1.5 Out-of-regression contracts (S1)

- Sparkline `setMinimumHeight(36)` unchanged.
- `LiveSignalCard._build_ui` unchanged.
- `LiveCardGrid.cards`, `push_sample`, `set_recording`,
  `refresh_all` public API unchanged.
- ReplayTab splitter topology unchanged.

---

## Defect S2 — ReviewModal unbounded text + non-resizable

### S2.1 User story

**Today** — after a recording that produced a 100-entry
`missing_channels` list, the review modal opens with a single 100-name
concatenated `QLabel`. The modal is wider than the monitor; the user
cannot read the buttons because they are off-screen, cannot resize the
modal (no size grip), and cannot scroll (no scroll area). Even on a
clean run with no missing channels, the modal cannot be made smaller
than its content because there is no `setMinimumSize`.

**After the fix** — the modal opens at a sane default
(`sizeHint()`-driven) but no larger than the parent window. The user
can grab the size grip and resize freely down to a minimum (420×320).
When `missing_channels` has many entries the list is rendered as a
scrollable `QListWidget` capped at a max height; the rest of the modal
body becomes scrollable when the available height is too small to fit
the action button row. The four action buttons remain in their fixed
row at the bottom, always visible.

### S2.2 Container contract

`ReviewModal._build_ui` is reorganized as:

- `self.setSizeGripEnabled(True)`
- `self.setMinimumSize(420, 320)`
- Top-level layout becomes: optional auto-stop banner, **scrollable
  body** (`QScrollArea`, `widgetResizable=True`,
  vScrollBarPolicy=AsNeeded, hScrollBarPolicy=AlwaysOff), then a
  pinned action button row outside the scroll area.
- Scroll body contents = the existing header + preflight summary
  block + status label, all preserved verbatim except for
  missing-channels handling.
- `pf_label` text never contains `", ".join(pf.missing_channels)`.
  Instead, when `pf.missing_channels` is non-empty:
  - The textual `pf_label` shows the COUNT only:
    `f"缺失通道 ({len(pf.missing_channels)})"`.
  - A sibling `QListWidget` named `reviewMissingChannelsList`
    renders one channel per row, with
    `setMaximumHeight(180)`,
    `setSelectionMode(QAbstractItemView.NoSelection)`,
    `setFocusPolicy(Qt.NoFocus)`,
    horizontal scrolling disabled, vertical scrolling AsNeeded.
- `pf.problems` continues to render as-is in the textual label (no
  new list for problems in this wave).

### S2.3 Resize/scroll behavior matrix

| Modal size (px) | `missing_channels` = 0 | `missing_channels` = 12 | `missing_channels` = 100 |
|---|---|---|---|
| 420×320 (minimum) | No body vScroll, all visible, no list | Body vScroll visible (banner + header + list compete), list shows ~4 rows w/ its own vScroll | Same as col-12; list still capped at 180 px and scrolls internally |
| 720×520 (default size hint) | No body vScroll | No body vScroll, list shows ~8 rows + its own vScroll | No body vScroll, list at 180 px w/ its own vScroll |
| 1100×800 (wide / max practical) | No body vScroll | No body vScroll, list shows full or scrolls if >8 rows | No body vScroll, list at 180 px w/ its own vScroll |

In all sizes: action button row remains visible at the bottom; size
grip remains hit-testable in the bottom-right.

### S2.4 Regression test requirements

`tests/acquisition_ui/test_review_handoff.py` (or a new
`test_review_modal_overflow.py`) — new tests:

- `test_review_modal_has_size_grip_and_minimum_size`: assert
  `modal.isSizeGripEnabled() is True`,
  `modal.minimumSize() == QSize(420, 320)`.
- `test_review_modal_body_wraps_scroll_area`: assert at least one
  `QScrollArea` descendant exists, with
  `widgetResizable() is True`,
  `verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded`,
  `horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff`.
- `test_review_modal_missing_channels_uses_qlistwidget_not_joined_label`:
  build a `ReviewContext` whose `preflight.missing_channels` is
  `tuple(f"chan_{i}" for i in range(100))`, assert:
  - The `reviewMissingChannelsList` `QListWidget` exists,
    `count() == 100`.
  - `reviewMissingChannelsList.maximumHeight() == 180`.
  - The `reviewPreflight` `QLabel` text does NOT contain
    `"chan_0, chan_1"` (i.e. the joined form is absent).
  - The `reviewPreflight` `QLabel` text DOES contain
    `"缺失通道 (100)"`.
- `test_review_modal_open_analyzer_button_still_reachable_after_save`:
  call `modal.do_save_only()`, assert `modal.isVisible()` semantics
  match the pre-existing test (modal stays open),
  `modal._btn_open_analyzer.isEnabled() is True`,
  `modal.is_open_in_analyzer_enabled() is True`. This is the
  reachability regression guard from the
  `save-action-must-not-close-gating-modal` lesson.

### S2.5 Out-of-regression contracts (S2)

- Action constants (`ACTION_DISCARD`, `ACTION_SAVE_ONLY`,
  `ACTION_SAVE_AND_ARCHIVE`, `ACTION_OPEN_ANALYZER`) unchanged —
  buttons still display verbatim spec strings.
- `do_discard`, `do_save_only`, `do_archive`, `do_open_in_analyzer`
  semantics unchanged. Save/archive STILL must not call
  `self.accept()`.
- `_can_open_in_analyzer`, `_refresh_action_enabled`, `_set_status`
  unchanged.
- `AUTO_STOP_BANNER_TEXT` rendering path (banner above header when
  `summary.auto_stop` is True) unchanged.
- `_is_closing` idempotency guard unchanged.
- `analyzer_open_requested` signal contract unchanged.
- Existing `test_review_handoff.py` tests continue to pass with no
  edits to their assertions.

---

## Defect S3 — RightPanel three pages have no scroll

### S3.1 User story

**Today** — at 1280×760 with the default system font, the
`IdlePreflightPage`'s five metric sections + verdict banner fit
exactly. At any larger system font (Windows 125% scaling, macOS
"larger text") or any cockpit window shorter than ~720 px, the bottom
metric ("输出") and the verdict banner clip below the right pane.
DisconnectedPage and RecordingQualityPage are slightly shorter but
share the same single-`QVBoxLayout`-with-`addStretch(1)` topology.
Because `RightPanel.setFixedWidth(300)`, the pane cannot grow to
absorb wider metric values either.

**After the fix** — all three pages independently scroll vertically
when their content height exceeds the available pane height. The pane
itself can grow between 280 and 360 px wide via splitter drag (giving
~20% width slack for translated labels and wider numeric values)
without forcing layout shifts elsewhere. At wide pane widths the
metric content stays capped + left-anchored so the right side shows a
deliberate gap (per inspector-cap lesson).

### S3.2 Container contract

- `RightPanel`:
  - Replace `setFixedWidth(300)` with
    `setMinimumWidth(280)` and `setMaximumWidth(360)`.
  - Default size hint remains ~300 px (the QStackedWidget reports the
    page's preferred width).
- Each of `DisconnectedPage`, `IdlePreflightPage`,
  `RecordingQualityPage` is refactored as a
  `_BasePanelPage` outer layout containing exactly one widget: a
  `QScrollArea` (objectName `rightPanelScroll`, one of
  `rightPanelScrollDisconnected/Idle/Recording`).
  - `QScrollArea(widgetResizable=True,
    verticalScrollBarPolicy=ScrollBarAsNeeded,
    horizontalScrollBarPolicy=ScrollBarAlwaysOff)`.
  - The scroll body is a `QWidget` ("scroll_body") that hosts the
    existing `QVBoxLayout` of section frames + verdict banner.
  - `scroll_body.setMaximumWidth(<form_natural_width>)` where
    `form_natural_width = 340` (one px below the pane's
    `setMaximumWidth(360)` minus 20px host margin slack). The
    `scroll_body` lives inside an outer
    `QVBoxLayout([scroll_body, addStretch(1)])` to enforce the
    left-anchor pattern. This is the cap-and-left-anchor pattern
    from `inspector-content-max-width-and-tinted-card-bleed.md`.
- Section/banner construction order inside each page MUST remain
  identical (`_add_header_row`, `_add_metric_section`,
  `_add_verdict_banner`, the `_substatus` label, etc. all keep the
  same wiring; only the layout topology gains an outer scroll
  wrapper).
- `RightPanel.disconnected_page`, `.idle_page`, `.recording_page`
  introspection helpers continue to return the same page-frame
  instances (used by `apply` methods + tests).

### S3.3 Resize/scroll behavior matrix

| Pane height × width | Page = Disconnected | Page = IdlePreflight (5 sections) | Page = RecordingQuality |
|---|---|---|---|
| 500 × 280 (narrow / minWidth) | No vScroll (4 rows fit) | vScroll visible (5 metric sections + banner exceed 500 px) | vScroll visible (6 metric sections exceed 500 px) |
| 760 × 300 (default cockpit) | No vScroll | No vScroll at default font; vScroll AsNeeded at 125% scaling | No vScroll |
| 1000 × 360 (wide / maxWidth) | No vScroll, right-side gap visible (cap at 340 px) | No vScroll, right-side gap visible | No vScroll, right-side gap visible |

In every cell: no horizontal scrollbar; no metric section clips;
verdict banner ("rightVerdictBanner") always reachable via scroll.

### S3.4 Regression test requirements

`tests/acquisition_ui/test_right_panel.py` — new tests:

- `test_right_panel_uses_min_max_width_not_fixed_width`:
  assert `panel.minimumWidth() == 280`,
  `panel.maximumWidth() == 360`.
  Negative: `panel.minimumWidth() != panel.maximumWidth()` (catches
  accidental `setFixedWidth` regression).
- `test_each_page_wraps_scroll_area`:
  for each page (`panel.disconnected_page`, `panel.idle_page`,
  `panel.recording_page`):
  - assert at least one `QScrollArea` descendant exists,
  - `scroll.widgetResizable() is True`,
  - `scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded`,
  - `scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff`,
  - the scroll body widget has
    `body.maximumWidth() == 340`.
- `test_idle_page_vertical_scrollbar_visible_at_short_height`:
  resize the panel to (280, 360) i.e. shorter than the natural
  IdlePreflight content height, switch to idle, process events;
  assert the page's `QScrollArea.verticalScrollBar().isVisible() is True`.
- `test_idle_page_no_horizontal_scrollbar_at_max_width`:
  resize panel to 360 px wide, switch to idle, assert
  `scroll.horizontalScrollBar().isVisible() is False`.
- `test_right_panel_existing_apply_still_works`: smoke test calling
  `show_idle(...)` with a small `SelectedMeasurement` fixture; assert
  `_row_can.text()` contains the expected band markup. Confirms the
  scroll wrapper does not break introspection paths used by other
  tests.

### S3.5 Out-of-regression contracts (S3)

- `_LEVEL_COLOR` map, `_format_band_value`, `_new_value_label`,
  `_add_header_row`, `_add_section`, `_add_metric_section`,
  `_add_value_row`, `_add_verdict_banner` helpers unchanged in
  signature and body.
- `DisconnectedPage.apply`, `IdlePreflightPage.apply`,
  `RecordingQualityPage.apply` parameter sets unchanged.
- `RightPanel.show_disconnected/show_idle/show_recording` public
  signatures unchanged.
- `RightPanel.PAGE_DISCONNECTED/PAGE_IDLE/PAGE_RECORDING` indices
  unchanged.
- Color tokens in `_LEVEL_COLOR` are NOT in scope for this wave (see
  §Deferred — "color token 治理").
- No imports added from `mf4_analyzer/acquisition_capture/*` (the
  page bodies already import what they need; the wrap is layout-only).

---

## Defect S4 — Toolbar narrow-window overflow + window minimum

### S4.1 User story

**Today** — the cockpit opens at 1280×760. Dragging the window narrower
than ~1100 px clips the right edge of the toolbar (REC indicator and
primary button disappear behind the window frame). On a 1366×768
laptop with the window maximized this is hidden, but on a smaller
secondary display or after a user resize, primary actions become
unreachable. The toolbar is a hand-rolled `QFrame + QHBoxLayout`, not a
`QToolBar`, so there is no native overflow chevron either.

**After the fix** — the cockpit has a minimum window size of 960×600.
Below the toolbar's natural width the selectors degrade gracefully
(elide their `value` text — note: full elide governance is a separate
wave, here we only loosen the fixed widths so layout can compress
without clipping primary actions). When the accumulated toolbar
content width still exceeds the outer width an overflow `[≡]`
`QToolButton` appears at the right, exposing the hidden actions
through a `QMenu` whose items reuse the SAME `QAction` instances
(triggered handlers and shortcuts are reused, not duplicated). At
≥1280 px the toolbar looks identical to today.

### S4.2 Container contract

- `MainWindow.setMinimumSize(960, 600)` added inside `__init__` near
  the existing `resize(1280, 760)` call at `main_window.py:174`.
  `resize(1280, 760)` stays as-is.
- `_build_toolbar` replaces `setFixedWidth(widths[...])` in
  `_make_selector_button` with
  `setMinimumWidth(<min>)` + `setMaximumWidth(<max>)` +
  `setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)` per
  selector. Recommended bounds:
  - `cockpitSelectorA2l`: min 90, max 160
  - `cockpitSelectorDbc`: min 90, max 170
  - `cockpitSelectorOutput`: min 110, max 220
  These keep current rendered widths inside the band so visible diff
  at default size is zero.
- A new `QToolButton` `_overflow_btn` (objectName
  `cockpitToolbarOverflow`, text `≡`, `setToolButtonStyle(Qt.ToolButtonTextOnly)`,
  `setFixedSize(30, 30)`) is appended to the toolbar layout AFTER
  the primary button. It is hidden by default and has its own empty
  `QMenu` (`_overflow_menu`).
- An overflow recalculation runs:
  - On `MainWindow.resizeEvent` (call a private
    `_recompute_toolbar_overflow()` method).
  - Once at the end of `_build_toolbar` so initial state is correct
    (initial-state-sync rule from
    `2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`).
- `_recompute_toolbar_overflow` rule (precise, testable):
  - Inputs: outer toolbar width `W = self._toolbar.width()`, ordered
    list of overflow-eligible widgets `[A2L, DBC, Output, Settings,
    SegmentMarker, ModeSegment]`. The primary `_main_btn` and the
    `_rec_indicator` are NEVER eligible for overflow (they remain
    always visible).
  - Compute the sum of `sizeHint().width()` plus layout spacing
    plus the always-visible widgets' widths. If `sum > W`, hide the
    rightmost eligible widgets one at a time until `sum ≤ W`, and
    show `_overflow_btn`. Otherwise show all eligible widgets and
    hide `_overflow_btn`.
  - For each hidden widget that is action-backed
    (`_settings_action`, `_segment_action`, and the new
    `_a2l_action`/`_output_action` wrappers we add around the
    selector clicks — see §S4.5), add the same `QAction` to
    `_overflow_menu`. For widgets without a `QAction` wrapper, the
    spec REQUIRES one to be added so the overflow menu can route the
    click. Re-use the existing slot (`_on_pick_a2l`,
    `_on_pick_output_dir`).
- The `_overflow_menu` MUST contain every hidden action with the
  same `triggered` signal target as the visible affordance, so the
  user has functional parity through the menu.

### S4.3 Resize/scroll behavior matrix

| Outer window width (px) | A2L / DBC / Output | Settings ⚙ | Mode segment | REC indicator | Primary btn | Overflow ≡ |
|---|---|---|---|---|---|---|
| 800 (narrow / minWidth proxy — note: minWidth is 960; 800 used only as a forcing-function test value, exercised by directly resizing the toolbar widget) | hidden, all 3 in overflow menu | hidden, in overflow menu | hidden, in overflow menu | visible | visible | visible |
| 960 (minWidth) | A2L visible, DBC + Output in overflow | hidden, in overflow menu | hidden, in overflow menu | visible | visible | visible |
| 1280 (default) | all visible | visible | visible | visible | visible | hidden |
| 1920 (wide, ≥1.5× default) | all visible | visible | visible | visible | visible | hidden |

In every cell: no horizontal scrollbar on the toolbar; primary
button + REC indicator never go off-screen; clicking the overflow
button opens a `QMenu` whose `QAction` count equals the number of
hidden eligible widgets.

### S4.4 Regression test requirements

`tests/acquisition_ui/test_visual_shell.py` (or a new
`test_toolbar_overflow.py`) — new tests:

- `test_main_window_has_minimum_size`: assert
  `win.minimumSize() == QSize(960, 600)`.
- `test_toolbar_selectors_use_min_max_width_not_fixed`:
  for each selector objectName
  (`cockpitSelectorA2l`, `cockpitSelectorDbc`,
  `cockpitSelectorOutput`):
  - assert `btn.minimumWidth() < btn.maximumWidth()`
  - assert `btn.sizePolicy().horizontalPolicy() == QSizePolicy.Preferred`.
- `test_toolbar_overflow_hidden_at_1280`:
  set the cockpit toolbar width to 1280, process events,
  assert `_overflow_btn.isVisible() is False`,
  all of A2L/DBC/Output/Settings/SegmentMarker/ModeSegment have
  `isVisible() is True`.
- `test_toolbar_overflow_visible_at_800`:
  set the cockpit toolbar width to 800, process events,
  assert `_overflow_btn.isVisible() is True`,
  assert `_overflow_menu.actions()` length ≥ 3 (at minimum
  the right-edge eligible widgets get demoted),
  assert `_main_btn.isVisible() is True`,
  assert `_rec_indicator.isVisible() is True`.
- `test_toolbar_overflow_menu_actions_route_to_same_slots`:
  set the toolbar width to 800, get `_overflow_menu.actions()`,
  for each `QAction` assert its `text()` matches the corresponding
  hidden affordance's text and that triggering it invokes the same
  slot the visible affordance would (spy on `_on_pick_a2l`,
  `_on_pick_output_dir`, `_open_settings_dialog`,
  `_on_mark_segment`).
- `test_toolbar_overflow_recomputes_on_resize`:
  start at width 1280 (overflow hidden), resize toolbar to 800
  (overflow visible), back to 1920 (overflow hidden). Assert
  overflow-button visibility transitions in that order; no widgets
  end up permanently hidden after the wide resize.
- `test_toolbar_rec_and_primary_always_visible`:
  at widths 800, 960, 1280, 1920 assert
  `_main_btn.isVisible() and _rec_indicator.isVisible()`.

### S4.5 Out-of-regression contracts (S4)

- `_build_toolbar` return type (`QFrame`) and `setFixedHeight(50)`
  unchanged.
- `_make_selector_button` signature (`(object_name, key, value)`)
  unchanged. Only the internal width assignment changes from
  `setFixedWidth` to min+max+SizePolicy.
- `_set_selector_value` unchanged.
- `_toolbar_separator`, `_build_mode_segment` unchanged.
- `_main_btn` properties (`role="primary"`,
  `setFixedHeight(36)`, `setMinimumWidth(106)`) unchanged.
- `_rec_indicator` properties unchanged.
- `MainWindow.load_file` public wrapper unchanged.
- `MainWindow.resize(1280, 760)` initial size unchanged — the
  new `setMinimumSize(960, 600)` is additive.
- `MODE_SEGMENTS` tuple unchanged.
- Adding a `QAction` wrapper around the A2L / Output / DBC selector
  clicks is permitted; the wrapper's `triggered` slot must reuse the
  existing `_on_pick_a2l` / `_on_pick_output_dir` slots verbatim, and
  the wrapper must NOT change disabled-state semantics for DBC
  (it stays `setEnabled(False)` with the
  `DBC_DISABLED_TOOLTIP` tooltip).

---

## Cross-cutting non-functional contracts

- **No `acquisition_capture` edits.** The spec is repeated here
  because the wave is small and the boundary is the most common
  rework vector. Specialists touching any path in
  `mf4_analyzer/acquisition_capture/*` MUST refuse and flag back.
- **No four-state-machine edits.** `CockpitStateMachine`,
  `CockpitState` enum, transitions in `main_window._on_state_changed`
  / `_apply_state_to_ui` MUST NOT be touched. The toolbar overflow
  recompute is a pure UI hook, not a state-machine event.
- **No `ReviewModal.do_save_only`/`do_archive` semantic edits.**
  Adding the scroll wrapper inside `_build_ui` MUST NOT introduce a
  code path that calls `accept()` / `reject()` from inside save or
  archive (the reachability lesson). The
  `test_review_modal_open_analyzer_button_still_reachable_after_save`
  test guards this.
- **No initial-state-skipped helpers.** Per the
  `conditional-visibility-init-sync-and-paired-field-children` lesson:
  the new toolbar overflow recompute MUST be invoked once at the end
  of `_build_toolbar` (or end of `_build_ui`), not only on
  `resizeEvent` — otherwise the overflow button's initial visibility
  is wrong before the first user resize.
- **Cap-and-left-anchor for splitter panes** (RightPanel S3) is the
  only acceptable wide-pane pattern per the inspector-cap lesson;
  unbounded Expanding children inside a `QScrollArea` body are
  forbidden.

## Verification (manual exercise, not test-only)

After all four defects ship, the implementing specialist MUST start
the Cockpit (`python -m mf4_analyzer.acquisition_ui`) at three window
sizes per defect and observe:

- S1: connect a fake backend, force selection of 12 channels (or use
  the demo path with the largest available pool), confirm the center
  pane shows a vertical scrollbar and the bottom card is reachable by
  scroll. Switch to Replay tab, open an MF4, confirm the replay
  surface scrolls the same way.
- S2: build a `ReviewContext` whose `preflight.missing_channels` has
  ≥30 entries (test fixture is fine for the manual run), open the
  modal, confirm the list is scrollable inside a 180 px cap,
  the modal is resizable down to 420×320, and the four action buttons
  stay visible at the bottom.
- S3: drag the central splitter so the right pane is at 280, 300,
  and 360 px. At 280 px on a short window confirm the
  IdlePreflightPage scrolls; at 360 px confirm the right-side gap
  inside the pane is visible (cap is honored). Toggle to recording
  page and disconnected page, confirm the same scroll behavior.
- S4: resize the cockpit window from 1920 → 1280 → 960 → 800 width;
  observe the overflow chevron appears below 1280 and the menu
  exposes the demoted actions. Click each menu item; confirm the
  same dialog or slot fires as if the visible affordance had been
  clicked.

If any of the four defects cannot be exercised (e.g. headless CI),
the specialist MUST return `status: needs_info` rather than
`done` per pyqt-ui's UI verification rule.

## Lesson-citation map

| Defect | Cited lesson | Why it applies |
|---|---|---|
| S1 | `2026-04-24-responsive-pane-containers.md` | Three-width verification rule applies to the center pane the same way it applies to splitter panes. |
| S2 | `2026-05-15-save-action-must-not-close-gating-modal.md` | The reachability guard test is the only safeguard that the scroll wrapper does not silently change closure semantics. |
| S3 | `2026-04-24-responsive-pane-containers.md` + `2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md` | Cap + left-anchor pattern for splitter-pane content; wide-pane visual gap is the *correct* outcome. |
| S4 | `2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` | The overflow-recompute helper must seed initial state at the end of `_build_toolbar`, not only on first `resizeEvent`. |

## Deferred / explicitly out of scope (do NOT touch in this wave)

The following items are deferred to a later wave. Bumping into any of
them during implementation MUST be flagged back to the orchestrator,
not silently absorbed:

- **P2 HistoryTab `filter_row` / `_tag_row` overflow.** Explicitly
  deferred per the task brief. Do NOT add scroll wrappers, min/max
  widths, or overflow chevrons to `history_tab.py`.
- LeftPane 二级 chip 行 overflow.
- ReplayTab transport row 8-button overflow.
- Elide / 字符截断 治理 (the toolbar selectors loosen widths but do
  NOT switch to `Qt.ElideMiddle` text policy this wave).
- `QMessageBox.open()` 模态语义复核 (the `_show_archive_failure`
  modal path is untouched).
- Color-token 治理 (`_LEVEL_COLOR`, swatch colors in
  `live_cards._CARD_TRACE_COLORS`, etc. are all out of scope).
- Any edits in `mf4_analyzer/acquisition_capture/*`.
- Any signature change to `MainWindow.load_file`.
- Any change to the four-state machine.
