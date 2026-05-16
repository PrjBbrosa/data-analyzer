# Acquisition UI Overflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate four container-level overflow defects in the acquisition Cockpit UI (LiveCardGrid, ReviewModal, RightPanel pages, MainWindow toolbar) by adding scroll wrappers, min/max width policies, and a toolbar overflow chevron — all strictly within `mf4_analyzer/acquisition_ui/*`.

**Architecture:** Four disjoint UI surfaces, each owning one primary file and one test file. Stages S1–S4 are fully parallel (verified disjoint primary + test files); S5 is a serial verification join. No `acquisition_capture/*` edits, no four-state-machine edits, no `MainWindow.load_file` signature change. Every fix is a container-layout change, not an algorithm change.

**Tech Stack:** PyQt5 (`QScrollArea`, `QListWidget`, `QSplitter`, `QToolButton`, `QMenu`, `QAction`, `QSizePolicy`), pytest + `pytestqt`, matplotlib only via existing Sparkline wiring (untouched).

**Spec:** `docs/analyzer/acquisition/specs/2026-05-16-acquisition-ui-overflow-spec.md` — every contract there is authoritative; this plan only restates the implementation route and TDD ordering.

---

## Stage table (spec section → stage → files)

| Stage | Spec defect | Slug | Primary file | Test file |
|---|---|---|---|---|
| S1 | §Defect S1 — LiveCardGrid overflow | `S1-LIVECARDS` | `mf4_analyzer/acquisition_ui/widgets/live_cards.py` | `tests/acquisition_ui/test_live_cards.py` |
| S2 | §Defect S2 — ReviewModal unbounded text + non-resizable | `S2-REVIEWMODAL` | `mf4_analyzer/acquisition_ui/review_modal.py` | `tests/acquisition_ui/test_review_handoff.py` |
| S3 | §Defect S3 — RightPanel three pages have no scroll | `S3-RIGHTPANEL` | `mf4_analyzer/acquisition_ui/widgets/right_panel.py` | `tests/acquisition_ui/test_right_panel.py` |
| S4 | §Defect S4 — Toolbar narrow-window overflow + window minimum | `S4-TOOLBAR` | `mf4_analyzer/acquisition_ui/main_window.py` | `tests/acquisition_ui/test_visual_shell.py` |
| S5 | §Verification | `S5-VERIFY` | (none — manual exercise + post-merge `pytest tests/acquisition_ui -q`) | (n/a) |

All four primary files are disjoint. All four test files are disjoint. No two stages share a `.py` import target, a `QSS` token, or an `__init__` constructor.

---

## Dependency graph

```
            S1-LIVECARDS  ─┐
            S2-REVIEWMODAL ├──►  S5-VERIFY  (serial join)
            S3-RIGHTPANEL  ─┤
            S4-TOOLBAR    ─┘
```

- `S1 ‖ S2 ‖ S3 ‖ S4` are **parallel**. They run in a single fan-out
  dispatch block.
- `S5-VERIFY` has `depends_on = [S1, S2, S3, S4]`. It must run **after**
  all four are reported `status: done` (or `needs_info` for headless).

**Why parallel-safe (file-by-file disjointness audit):**

| Stage | Primary writes | Test writes | Touches `main_window.py`? | Touches `__init__.py`? | Touches a shared QSS file? |
|---|---|---|---|---|---|
| S1 | `widgets/live_cards.py` only | `test_live_cards.py` only | no | no | no |
| S2 | `review_modal.py` only | `test_review_handoff.py` only | no | no | no |
| S3 | `widgets/right_panel.py` only | `test_right_panel.py` only | no | no | no |
| S4 | `main_window.py` only | `test_visual_shell.py` only | **yes (owner)** | no | no |

Only S4 touches `main_window.py`, and only S4 touches `test_visual_shell.py`. No shared file across stages. No `widgets/__init__.py` edit is needed in any stage (`live_cards`, `right_panel` already exported).

**Citation —** `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`: that lesson failed precisely because four parallel pyqt-ui tasks each made a "small" `main_window.py` edit and each appended to a shared `test_drawers.py`, racing `git add`. This plan defends against that by (a) restricting `main_window.py` to S4 only, (b) giving every stage its own dedicated test file, and (c) explicitly listing the disjointness audit above as a precondition. Per that lesson's "preventative guidance" #2, any shared-file edit that emerges during execution MUST be bundled into the owning stage's brief, not split across stages.

---

## TDD red→green order (per stage)

Every stage follows the same five-step rhythm and lists the **exact** new test functions, the **exact** assertion that will be red, and the **exact** pytest invocation.

### Stage S1 — LiveCardGrid scroll wrapper

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py` (specifically `LiveCardGrid.__init__` and `LiveCardGrid.set_signals` at lines 341–347, plus a new placeholder bypass branch)
- Create-or-extend: `tests/acquisition_ui/test_live_cards.py` (add five new test functions)

**Forbidden in this stage:**
- `mf4_analyzer/acquisition_capture/*` (any file)
- `mf4_analyzer/acquisition_ui/replay_tab.py`
- `mf4_analyzer/acquisition_ui/history_tab.py`
- `mf4_analyzer/acquisition_ui/review_modal.py`
- `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- `mf4_analyzer/acquisition_ui/main_window.py`
- `Sparkline.setMinimumHeight(36)` at `live_cards.py:89` (must remain `36`)

**TDD steps:**

- [ ] **S1.a Write the failing tests first.** Append these five functions to `tests/acquisition_ui/test_live_cards.py`:

  - `test_live_card_grid_wraps_scroll_area_when_overflowing`
  - `test_live_card_grid_size_hint_does_not_grow_linearly`
  - `test_live_card_grid_vertical_scrollbar_visible_when_overflow`
  - `test_live_card_grid_horizontal_scrollbar_never_visible`
  - `test_live_card_grid_empty_state_still_centered`

  The first failing assertion will be (verbatim):

  ```python
  assert grid.findChild(QScrollArea) is not None
  ```

  inside `test_live_card_grid_wraps_scroll_area_when_overflowing` — today's `LiveCardGrid.__init__` builds a plain `QVBoxLayout` and no `QScrollArea`, so the descendant lookup returns `None`.

- [ ] **S1.b Run pytest and capture red.**

  ```
  python -m pytest tests/acquisition_ui/test_live_cards.py -q
  ```

  Expected red output: `AssertionError: assert None is not None` (from the first test). Capture the failure tail in the specialist's `notes` field.

- [ ] **S1.c Implement the container fix.** Inside `LiveCardGrid.__init__` wrap the cards `QVBoxLayout` in a `QScrollArea(widgetResizable=True, verticalScrollBarPolicy=ScrollBarAsNeeded, horizontalScrollBarPolicy=ScrollBarAlwaysOff)`. Keep the empty-state placeholder ("未连接 ECU" / `cockpitDisconnectedCanvas`) outside the scroll viewport. Do NOT change `Sparkline.setMinimumHeight(36)`. Keep `LiveCardGrid.cards`, `push_sample`, `set_recording`, `refresh_all` public API byte-identical.

- [ ] **S1.d Re-run pytest, go green.**

  ```
  python -m pytest tests/acquisition_ui/test_live_cards.py -q
  ```

  Expected: all five new tests pass. The pre-existing `test_live_cards.py` tests must remain green (do not edit them).

- [ ] **S1.e Run the full acquisition_ui suite to catch ReplayTab regression.**

  ```
  python -m pytest tests/acquisition_ui -q
  ```

  Expected: no regressions. ReplayTab inherits the scroll behavior for free.

---

### Stage S2 — ReviewModal scroll + size grip + QListWidget for missing channels

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/review_modal.py` (specifically `_build_ui` at lines 145–205; replace the joined `pf_label` text path)
- Create-or-extend: `tests/acquisition_ui/test_review_handoff.py` (add four new test functions)

**Forbidden in this stage:**
- `mf4_analyzer/acquisition_capture/*` (any file)
- `mf4_analyzer/acquisition_ui/replay_tab.py`
- `mf4_analyzer/acquisition_ui/history_tab.py`
- `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- `mf4_analyzer/acquisition_ui/main_window.py`
- `ReviewModal.do_save_only` body, `ReviewModal.do_archive` body (must not call `accept()`/`reject()`)
- `ACTION_DISCARD`, `ACTION_SAVE_ONLY`, `ACTION_SAVE_AND_ARCHIVE`, `ACTION_OPEN_ANALYZER` constants
- `_can_open_in_analyzer`, `_refresh_action_enabled`, `_set_status`, `_is_closing` (semantics unchanged)
- `analyzer_open_requested` signal contract

**TDD steps:**

- [ ] **S2.a Write the failing tests first.** Append these four functions to `tests/acquisition_ui/test_review_handoff.py`:

  - `test_review_modal_has_size_grip_and_minimum_size`
  - `test_review_modal_body_wraps_scroll_area`
  - `test_review_modal_missing_channels_uses_qlistwidget_not_joined_label`
  - `test_review_modal_open_analyzer_button_still_reachable_after_save`

  The first failing assertion will be (verbatim):

  ```python
  assert modal.isSizeGripEnabled() is True
  ```

  inside `test_review_modal_has_size_grip_and_minimum_size` — today's `_build_ui` never calls `setSizeGripEnabled(True)`, so this returns `False`.

- [ ] **S2.b Run pytest and capture red.**

  ```
  python -m pytest tests/acquisition_ui/test_review_handoff.py -q
  ```

  Expected red: `AssertionError: assert False is True`. Capture the failure tail.

- [ ] **S2.c Implement the container fix.** In `_build_ui`:
  - Call `self.setSizeGripEnabled(True)` and `self.setMinimumSize(420, 320)`.
  - Reorganize the top-level layout into `[optional auto-stop banner, QScrollArea(body, widgetResizable=True, vScroll=AsNeeded, hScroll=AlwaysOff), pinned action button row]`.
  - When `pf.missing_channels` is non-empty: set `pf_label` text to `f"缺失通道 ({len(pf.missing_channels)})"` (count-only, no `", ".join`). Create `reviewMissingChannelsList = QListWidget(...)` with `setMaximumHeight(180)`, `setSelectionMode(QAbstractItemView.NoSelection)`, `setFocusPolicy(Qt.NoFocus)`, hScroll off, vScroll AsNeeded; populate one row per channel.
  - DO NOT add any `accept()`/`reject()` call in `do_save_only` or `do_archive` (the save-action-must-not-close-gating-modal lesson is the contract).

- [ ] **S2.d Re-run pytest, go green.**

  ```
  python -m pytest tests/acquisition_ui/test_review_handoff.py -q
  ```

  Expected: all four new tests pass; the pre-existing `test_review_handoff.py` tests pass unmodified (especially any test asserting the modal stays open after `do_save_only`).

---

### Stage S3 — RightPanel pages scroll + min/max width

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py` (specifically `RightPanel.__init__` at lines 455–465 and the three page bodies `DisconnectedPage`, `IdlePreflightPage`, `RecordingQualityPage`)
- Create-or-extend: `tests/acquisition_ui/test_right_panel.py` (add five new test functions)

**Forbidden in this stage:**
- `mf4_analyzer/acquisition_capture/*` (any file)
- `mf4_analyzer/acquisition_ui/replay_tab.py`
- `mf4_analyzer/acquisition_ui/history_tab.py`
- `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- `mf4_analyzer/acquisition_ui/review_modal.py`
- `mf4_analyzer/acquisition_ui/main_window.py`
- `_LEVEL_COLOR` map, `_format_band_value`, `_new_value_label` (untouched)
- `_add_header_row`, `_add_section`, `_add_metric_section`, `_add_value_row`, `_add_verdict_banner` signatures and bodies (untouched)
- `RightPanel.show_disconnected/show_idle/show_recording` public signatures
- `PAGE_DISCONNECTED/PAGE_IDLE/PAGE_RECORDING` indices

**TDD steps:**

- [ ] **S3.a Write the failing tests first.** Append these five functions to `tests/acquisition_ui/test_right_panel.py`:

  - `test_right_panel_uses_min_max_width_not_fixed_width`
  - `test_each_page_wraps_scroll_area`
  - `test_idle_page_vertical_scrollbar_visible_at_short_height`
  - `test_idle_page_no_horizontal_scrollbar_at_max_width`
  - `test_right_panel_existing_apply_still_works`

  The first failing assertion will be (verbatim):

  ```python
  assert panel.minimumWidth() == 280
  ```

  inside `test_right_panel_uses_min_max_width_not_fixed_width` — today's `RightPanel.__init__` calls `setFixedWidth(300)`, which makes `minimumWidth() == 300`, not `280`.

- [ ] **S3.b Run pytest and capture red.**

  ```
  python -m pytest tests/acquisition_ui/test_right_panel.py -q
  ```

  Expected red: `AssertionError: assert 300 == 280`. Capture the failure tail.

- [ ] **S3.c Implement the container fix.**
  - Replace `self.setFixedWidth(300)` in `RightPanel.__init__` with `self.setMinimumWidth(280)` + `self.setMaximumWidth(360)`.
  - For each of `DisconnectedPage`, `IdlePreflightPage`, `RecordingQualityPage`: rewrite the outer layout as `QVBoxLayout([QScrollArea(scroll_body, widgetResizable=True, vScroll=AsNeeded, hScroll=AlwaysOff), addStretch(1)])` where `scroll_body` is a `QWidget` hosting the previously-existing `QVBoxLayout` of metric sections + verdict banner. Set `scroll_body.setMaximumWidth(340)` (cap-and-left-anchor pattern). Give each scroll area an `objectName` of `rightPanelScrollDisconnected/Idle/Recording`.
  - Keep `RightPanel.disconnected_page/idle_page/recording_page` pointing to the same outer frames that the existing tests introspect.

- [ ] **S3.d Re-run pytest, go green.**

  ```
  python -m pytest tests/acquisition_ui/test_right_panel.py -q
  ```

  Expected: all five new tests pass; pre-existing tests unchanged.

---

### Stage S4 — MainWindow setMinimumSize + toolbar overflow chevron

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window.py` (specifically `MainWindow.__init__` near line 174 and `_build_toolbar` at lines 298–388, plus a new private `_recompute_toolbar_overflow` method and override of `resizeEvent`)
- Create-or-extend: `tests/acquisition_ui/test_visual_shell.py` (add seven new test functions)

**Forbidden in this stage:**
- `mf4_analyzer/acquisition_capture/*` (any file)
- `mf4_analyzer/acquisition_ui/replay_tab.py`
- `mf4_analyzer/acquisition_ui/history_tab.py`
- `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- `mf4_analyzer/acquisition_ui/review_modal.py`
- **`MainWindow.load_file()` body** (public wrapper installed in a prior wave — must stay byte-identical)
- **The four-state machine** (`CockpitStateMachine`, `CockpitState` enum, `_on_state_changed`, `_apply_state_to_ui`)
- `_build_toolbar` return type (`QFrame`), `setFixedHeight(50)`
- `_make_selector_button` signature `(object_name, key, value)`
- `_set_selector_value`, `_toolbar_separator`, `_build_mode_segment`
- `_main_btn` properties, `_rec_indicator` properties
- `MODE_SEGMENTS` tuple
- `MainWindow.resize(1280, 760)` initial size call (additive `setMinimumSize` only)
- `DBC_DISABLED_TOOLTIP` semantics (DBC selector stays `setEnabled(False)`)

**TDD steps:**

- [ ] **S4.a Write the failing tests first.** Append these seven functions to `tests/acquisition_ui/test_visual_shell.py`:

  - `test_main_window_has_minimum_size`
  - `test_toolbar_selectors_use_min_max_width_not_fixed`
  - `test_toolbar_overflow_hidden_at_1280`
  - `test_toolbar_overflow_visible_at_800`
  - `test_toolbar_overflow_menu_actions_route_to_same_slots`
  - `test_toolbar_overflow_recomputes_on_resize`
  - `test_toolbar_rec_and_primary_always_visible`

  The first failing assertion will be (verbatim):

  ```python
  assert win.minimumSize() == QSize(960, 600)
  ```

  inside `test_main_window_has_minimum_size` — today's `__init__` does not call `setMinimumSize`, so `minimumSize()` defaults to `QSize(0, 0)`.

- [ ] **S4.b Run pytest and capture red.**

  ```
  python -m pytest tests/acquisition_ui/test_visual_shell.py -q
  ```

  Expected red: `AssertionError: assert PyQt5.QtCore.QSize(0, 0) == PyQt5.QtCore.QSize(960, 600)`. Capture the failure tail.

- [ ] **S4.c Implement the container fix.**
  - Add `self.setMinimumSize(960, 600)` immediately after `self.resize(1280, 760)` in `__init__`.
  - Inside `_make_selector_button`, replace `setFixedWidth(width)` with `btn.setMinimumWidth(min_w)`, `btn.setMaximumWidth(max_w)`, `btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)`. Bounds: A2L (90, 160), DBC (90, 170), Output (110, 220).
  - Add `_overflow_btn = QToolButton(text="≡", objectName="cockpitToolbarOverflow")` with `setFixedSize(30, 30)` and `setToolButtonStyle(Qt.ToolButtonTextOnly)`, appended to the toolbar `QHBoxLayout` after `_main_btn`. Default-hidden. Attach a `QMenu` named `_overflow_menu`.
  - Wrap the A2L / Output / Settings / SegmentMarker / Mode-segment click handlers in `QAction` instances (reuse existing slots verbatim — `_on_pick_a2l`, `_on_pick_output_dir`, `_open_settings_dialog`, `_on_mark_segment`, the mode-segment slot). DBC stays disabled (no QAction needed).
  - Add `_recompute_toolbar_overflow(self)` per the spec §S4.2 rule. Hide eligible widgets right-to-left until the total width fits; show `_overflow_btn` when at least one widget is hidden; rebuild `_overflow_menu` to contain the corresponding `QAction`s.
  - Override `resizeEvent(self, event)` to call `_recompute_toolbar_overflow()` after `super().resizeEvent(event)`.
  - Call `_recompute_toolbar_overflow()` once at the **end** of `_build_toolbar` (initial-state-sync rule from the conditional-visibility-init lesson).
  - DO NOT touch `load_file`, the state machine, `_main_btn` style, or `_rec_indicator` style.

- [ ] **S4.d Re-run pytest, go green.**

  ```
  python -m pytest tests/acquisition_ui/test_visual_shell.py -q
  ```

  Expected: all seven new tests pass; pre-existing `test_visual_shell.py` tests pass unmodified.

---

### Stage S5 — Verification join (serial, after S1–S4 are all done)

**Files:** none (manual exercise + suite-wide pytest).

- [ ] **S5.a Run the full acquisition_ui pytest suite.**

  ```
  python -m pytest tests/acquisition_ui -q
  ```

  Expected: green. If any stage's test file was edited by another stage (rework signal), STOP and surface the overlap to the orchestrator before continuing — this is the `parallel-same-file-drawer-task-collision` failure mode.

- [ ] **S5.b Headless detection.** Check `$DISPLAY` (Linux) / desktop session (macOS/Windows). If unavailable, the verifier returns `status: needs_info` and skips S5.c per the pyqt-ui UI-verification rule.

- [ ] **S5.c Manual exercise.** Run

  ```
  python -m mf4_analyzer.acquisition_ui --demo
  ```

  and walk the checklist in the next section.

---

## File-touch matrix

| Stage | Primary file (write) | Test file (write) | Forbidden files (must NOT touch) |
|---|---|---|---|
| **S1** | `mf4_analyzer/acquisition_ui/widgets/live_cards.py` | `tests/acquisition_ui/test_live_cards.py` | `mf4_analyzer/acquisition_capture/*`, `mf4_analyzer/acquisition_ui/replay_tab.py`, `mf4_analyzer/acquisition_ui/history_tab.py`, `mf4_analyzer/acquisition_ui/review_modal.py`, `mf4_analyzer/acquisition_ui/widgets/right_panel.py`, `mf4_analyzer/acquisition_ui/main_window.py` |
| **S2** | `mf4_analyzer/acquisition_ui/review_modal.py` | `tests/acquisition_ui/test_review_handoff.py` | `mf4_analyzer/acquisition_capture/*`, `mf4_analyzer/acquisition_ui/replay_tab.py`, `mf4_analyzer/acquisition_ui/history_tab.py`, `mf4_analyzer/acquisition_ui/widgets/live_cards.py`, `mf4_analyzer/acquisition_ui/widgets/right_panel.py`, `mf4_analyzer/acquisition_ui/main_window.py`, `ReviewModal.do_save_only`/`do_archive` body changes (no `accept()`/`reject()`) |
| **S3** | `mf4_analyzer/acquisition_ui/widgets/right_panel.py` | `tests/acquisition_ui/test_right_panel.py` | `mf4_analyzer/acquisition_capture/*`, `mf4_analyzer/acquisition_ui/replay_tab.py`, `mf4_analyzer/acquisition_ui/history_tab.py`, `mf4_analyzer/acquisition_ui/widgets/live_cards.py`, `mf4_analyzer/acquisition_ui/review_modal.py`, `mf4_analyzer/acquisition_ui/main_window.py`, `_LEVEL_COLOR`, `_add_*` helper bodies/signatures |
| **S4** | `mf4_analyzer/acquisition_ui/main_window.py` | `tests/acquisition_ui/test_visual_shell.py` | `mf4_analyzer/acquisition_capture/*`, `mf4_analyzer/acquisition_ui/replay_tab.py`, `mf4_analyzer/acquisition_ui/history_tab.py`, `mf4_analyzer/acquisition_ui/widgets/live_cards.py`, `mf4_analyzer/acquisition_ui/widgets/right_panel.py`, `mf4_analyzer/acquisition_ui/review_modal.py`, **`MainWindow.load_file()` body**, **the four-state machine (`CockpitStateMachine`, `CockpitState`, `_on_state_changed`, `_apply_state_to_ui`)**, `_make_selector_button` signature, `MODE_SEGMENTS`, `_main_btn`/`_rec_indicator` style |
| **S5** | (none) | (none) | All `.py` files — S5 is read-only verification + manual exercise |

A specialist that bumps into any item in its "forbidden files" column MUST refuse with `status: blocked` and surface a `flagged[]` entry, per the pyqt-ui hard-boundaries rule.

---

## Manual verification checklist (S5.c)

Invocation: `python -m mf4_analyzer.acquisition_ui --demo`

Walk the four defect surfaces in order. Each surface has one happy path
and one edge case.

- [ ] **S1 — LiveCards scroll.** With the demo backend producing ≥6
  signals, confirm the center pane shows **4+ live cards** stacked
  vertically. Confirm a **vertical scrollbar** is visible inside
  `LiveCardGrid` and the bottom card is reachable by scrolling. Confirm
  no horizontal scrollbar appears. Resize the window narrower (~800 px
  wide) and confirm cards stretch to viewport width without clipping.
  Switch to the Replay tab; load an MF4 with ≥6 channels; confirm the
  same scroll behavior is inherited (free benefit of fixing
  LiveCardGrid).
- [ ] **S2 — ReviewModal resize + scroll + missing-channel list.**
  Build a fixture `ReviewContext` whose `preflight.missing_channels`
  has **100 entries** (the demo flag should support this, otherwise
  patch the demo's preflight constructor inline for the manual check
  only). Open the review modal. Confirm:
  - The modal is **resizable** via the bottom-right size grip.
  - Dragging it down to **420×320** clamps at the minimum size; below
    that size the body shows a vertical scrollbar and the four action
    buttons remain visible at the bottom.
  - The `reviewPreflight` `QLabel` text reads `"缺失通道 (100)"`, not a
    100-name `", ".join(...)`.
  - The `reviewMissingChannelsList` `QListWidget` has 100 rows, is
    capped at 180 px tall, and has its own internal vertical
    scrollbar.
  - Clicking "仅保存" leaves the modal **open** (reachability lesson);
    the "在 Analyzer 打开" button is now enabled and clickable.
- [ ] **S3 — RightPanel pages scroll at 1024×600.** Resize the cockpit
  window to **1024×600**. Drag the central splitter so the right pane
  is at 280, 300, and 360 px in turn. At 280 px on this short window
  confirm the `IdlePreflightPage` scrolls vertically (the bottom
  metric and verdict banner are reachable by scroll). At 360 px
  confirm a **right-side gap** is visible inside the pane (cap-and-
  left-anchor honored at 340 px). Toggle to `RecordingQualityPage`
  and `DisconnectedPage`; confirm each scrolls when content exceeds
  pane height and shows the same right-side gap at wide width. No
  horizontal scrollbar in any state.
- [ ] **S4 — Toolbar overflow at 800 px.** Drag the cockpit window
  width down from 1920 → 1280 → 960 → 800 (Qt will clamp at the new
  960 minimum; force the toolbar widget width to 800 directly via a
  developer hook or temporary resize call for this verification step
  only — the spec's S4.3 matrix already lists 800 as a forcing-function
  width). Confirm:
  - At 1920 and 1280 px: the **`[≡]` overflow button is hidden**; all
    of A2L / DBC / Output / Settings / SegmentMarker / Mode-segment
    are visible.
  - At 960 px: A2L visible, DBC + Output + Settings + SegmentMarker +
    Mode-segment in the overflow menu; `[≡]` visible.
  - At 800 px: all six eligible affordances are in the **overflow
    menu** behind `[≡]`; the REC indicator and primary button remain
    visible.
  - Clicking each menu item in the overflow menu invokes the **same
    slot** as the visible affordance would (verify A2L picker opens,
    Output picker opens, Settings dialog opens, Segment marker
    triggers, mode segment switches).

If any of the four cannot be exercised (headless), the verifier returns
`status: needs_info` with the reason in `notes` rather than `done`.

---

## Reference lessons

**pyqt-ui lessons (four — every one cited in the spec):**

1. `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`
   — three-width verification (narrow / default / wide ≥ 1.5× default);
   container-first diagnosis; cap+left-anchor for splitter slots.
   Applies to **S1** (center pane width verification) and **S3** (right
   pane cap+left-anchor at 340 px).
2. `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`
   — `body.setMaximumWidth(<form_natural_width>)` plus an
   `addStretch`-padded host so the cap visibly leaves a right-side gap
   at the wide end. Applies to **S3** (`scroll_body.setMaximumWidth(340)`
   + outer `addStretch(1)`).
3. `docs/lessons-learned/pyqt-ui/2026-05-15-save-action-must-not-close-gating-modal.md`
   — the `在 Analyzer 打开` button must remain reachable; do NOT mutate
   the save→accept flow; do NOT close the modal on save. Applies to
   **S2** (reachability test guards the scroll-wrapper refactor).
4. `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`
   — visibility helpers must run once at `__init__` end to seed initial
   state. Applies to **S4** (`_recompute_toolbar_overflow()` called
   once at end of `_build_toolbar`, not only on first `resizeEvent`).

**orchestrator lessons (four — informing decomposition shape):**

1. `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
   — primary citation for the parallel-safety audit. The file-by-file
   disjointness matrix above is the direct mitigation for this lesson.
2. `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
   — informs why each stage's brief includes the test-edit step inline
   rather than splitting "write impl" from "write test" across two
   specialists. Each stage is a single specialist's red→green cycle.
3. `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
   — informs the explicit "forbidden methods/files per brief"
   enumeration in the file-touch matrix. Forbidden symbols are
   enumerated per stage so rework detection has zero false positives
   and zero false negatives.
4. `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
   — informs the requirement that every stage's specialist returns
   `symbols_touched` in addition to `files_changed`, so the post-stage
   review can grep for forbidden symbols (e.g., `load_file`,
   `CockpitState`) and catch silent boundary leaks.

---

## Out-of-scope (verbatim user P2 deferrals)

The following items are **out of scope for this wave**. Bumping into
any of them during implementation MUST be flagged back to the
orchestrator (`status: blocked` with a `flagged[]` entry), not silently
absorbed. Repeated here so each parallel specialist sees them in their
brief:

- **P2 HistoryTab `filter_row` / `_tag_row` overflow.** Explicitly
  deferred. Do NOT add scroll wrappers, min/max widths, or overflow
  chevrons to `mf4_analyzer/acquisition_ui/history_tab.py`.
- **LeftPane 二级 chip 行 overflow.** Deferred.
- **ReplayTab transport row 8-button overflow.** Deferred. (The
  ReplayTab regression test in S1 only confirms that LiveCardGrid
  scroll is inherited; it does NOT touch the transport row.)
- **Elide / 字符截断 治理.** Toolbar selectors loosen widths in S4 but
  do NOT switch to `Qt.ElideMiddle` text policy this wave.
- **`QMessageBox.open()` 模态语义复核.** The `_show_archive_failure`
  modal path is untouched.
- **Color-token 治理.** `_LEVEL_COLOR`, `live_cards._CARD_TRACE_COLORS`,
  swatch colors are all out of scope.
- **Any edits in `mf4_analyzer/acquisition_capture/*`.** Read-only for
  the whole wave.
- **Any signature change to `MainWindow.load_file`.** Body and
  signature stay byte-identical.
- **Any change to the four-state machine** (`CockpitStateMachine`,
  `CockpitState` enum, transitions in `_on_state_changed` /
  `_apply_state_to_ui`). The toolbar overflow recompute is a pure UI
  hook, not a state-machine event.
