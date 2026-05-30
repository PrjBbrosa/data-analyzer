# Toolbar History + Alt Shortcuts + Overlay Primary-Axis Plan

> Three related UI changes reported 2026-05-29. Pure UI/PyQt; TDD, one commit
> per change. Preserve the W0 contract. Run tests with
> `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest <target> -q`.
> Files: `mf4_analyzer/ui/chart_stack.py` (toolbar + shortcuts),
> `mf4_analyzer/ui/file_navigator.py` + its channel-list widget + `main_window.py`
> (overlay primary axis), tests under `tests/ui/`.

---

## Task 1: Fix PgNavigationToolbar back/forward (view history)

**Root cause (confirmed):** `PgNavigationToolbar` (used only for the pyqtgraph
time canvas) pushes view history ONLY in `home()` (`chart_stack.py:424`);
pan/zoom never record (`pan()`/`zoom()` only set mouse modes,
`chart_stack.py:465-491`). matplotlib's real toolbar calls `push_current()` after
every nav. Also `_snapshot_view` stores `(axis_handle, xlim, ylim)` and after a
`plot_channels` rebuild those handles are stale objects → cross-replot restore is
a no-op. The matplotlib cards (FFT/order/spectrogram) use the real
`NavigationToolbar` and work — only the PG time toolbar is broken.

**Required behavior (matplotlib parity):**
- A baseline view is captured when the chart is built.
- Each completed pan/zoom gesture appends the RESULTING view (coalesced: one
  continuous drag = one history entry).
- `back()` steps to the previous view; `forward()` steps forward; a new gesture
  truncates the forward history.
- Restores must NOT push history (guard flag) and must survive a `plot_channels`
  rebuild — key snapshots by channel name + range, NOT by the live handle object.

**Implementation sketch:** Move to a single stack + pointer (matplotlib model).
Capture the resulting view via the canvas ViewBox's manual-range signal
(`sigRangeChangedManually`) connected through a short debounce (≈150–200 ms) so a
drag coalesces to one push; set a `_restoring` guard True around back/forward/home
restores so they don't re-push. Snapshot as `{channel_name: (xlim, ylim)}` (plus
the shared X) and resolve channels via `canvas._channel_lines` on restore so a
rebuilt handle is looked up fresh. Register the capture hook via the existing
`register_replot_callback` so it re-binds to fresh ViewBoxes after each rebuild
(disconnect old connections first — cite `2026-04-25-matplotlib-axes-callbacks-lifecycle.md`).

- [ ] Failing test: build PG time chart, pan (change xlim), `back()` → xlim
  returns to the pre-pan value; `forward()` → returns to the panned value; a pan
  after `back()` truncates forward. Also: rebuild via `plot_channels`, then a
  prior `back()` target still restores (range-keyed, not stale-handle).
- [ ] Run → FAIL.
- [ ] Implement per sketch.
- [ ] Run → PASS.
- [ ] Commit: `fix(ui): pg toolbar back/forward track pan/zoom history`

---

## Task 2: Switch keyboard shortcuts Ctrl → Alt (keyboard only)

**Decision:** keyboard shortcuts → Alt; wheel modifiers (`Ctrl+wheel`/`Shift+wheel`
in `_handle_wheel_dispatch`) STAY Ctrl/Shift. The app has NO `QMenuBar`
(whole-repo grep), so Alt+letter/digit will not collide with menu mnemonics, and
none of R/G/B/Z/1-5 clash with Windows system Alt combos. (Caveat noted: AltGr on
some international layouts — acceptable for this app's users.)

- [ ] Edit `_NAV_SHORTCUTS` (`chart_stack.py:160-166`): `Alt+R / Alt+Z /
  Alt+Shift+Z / Alt+G / Alt+B`. This also resolves the `Ctrl+Z`-vs-undo clash.
- [ ] Edit `_TIME_CARD_SHORTCUTS` (`chart_stack.py:170-176`): `Alt+1..5`.
- [ ] Do NOT touch the wheel modifiers or `_BOTTOM_HINT_PERSISTENT`'s
  `Ctrl+滚轮 / Shift+滚轮` line (`chart_stack.py:127-131`) — those stay Ctrl/Shift.
- [ ] Update any stale `Ctrl+G`/`Ctrl+B` references in comments/hints
  (`chart_stack.py:888`, `989`) to Alt for accuracy. Tooltips auto-render from
  `QKeySequence.toString(NativeText)`, so they update for free.
- [ ] Failing test: assert each nav action's `shortcut()` and the time-card
  `QShortcut`s now use the Alt modifier (and not Ctrl). Update any existing test
  that asserted the Ctrl bindings.
- [ ] Run → PASS.
- [ ] Commit: `feat(ui): move chart keyboard shortcuts from Ctrl to Alt`

---

## Task 3: Overlay — right-click channel → "设为左轴" (primary axis)

**Current behavior:** overlay binds the FIRST checked channel (`vis[0]`) to the
left axis; order comes from `navigator.get_checked_channels()`
(`main_window.py:652`) → `channel_list.get_checked_channels()`. No UI assigns the
left axis. The existing overlay curve-selection (`select_overlay_channel`) only
emphasizes + enables Y-drag; it does NOT change the axis.

**Approach (chosen):** a right-click context menu on the channel in the LEFT
channel panel with an action "设为左轴" (set as primary). Selecting it makes that
channel render on the left axis in overlay mode.

**Implementation sketch (no canvas change needed — reorder feeds the existing
`vis[0]`→left binding):**
- In the channel-list widget (inside `file_navigator.py` — find the per-channel
  row/item; `get_checked_channels` lives on `channel_list`), add a
  `setContextMenuPolicy(CustomContextMenu)` / `customContextMenuRequested` handler
  that shows "设为左轴" for the channel under the cursor and emits a new signal
  e.g. `primary_channel_requested(fid, ch)`. Bubble it up through `FileNavigator`.
- In `main_window.py`: store `_overlay_primary = (fid, ch)`; when building the
  overlay plot, reorder the checked-channel list so the primary is index 0 (left
  axis), then replot preserving xlim (use the canvas's
  `plot_channels_preserving_xlim`). Clear/ignore `_overlay_primary` when it is no
  longer checked or not in overlay mode.
- Only meaningful in overlay mode; in subplot/single the menu item may be hidden
  or a no-op.

- [ ] Failing test: with overlay built from channels [A, B, C] (A on left),
  invoke the primary-axis path for channel C (call the main_window slot or emit
  the navigator signal), assert the rebuilt overlay binds C to the left axis
  (`canvas.axes_list[0]` ↔ channel C via `_channel_lines`) and X is preserved.
- [ ] Run → FAIL.
- [ ] Implement per sketch.
- [ ] Run → PASS.
- [ ] Commit: `feat(ui): overlay right-click 设为左轴 sets the primary left-axis channel`

---

## Task 4: Regression sweep + live verify
- [ ] `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_chart_stack.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_main_window_smoke.py -q`
- [ ] `git diff --check`.
- [ ] LIVE GUI (REQUIRED): time chart — pan/zoom then back/forward step through
  the view history and Home resets; Alt+R/G/B/Z/1-5 work; overlay right-click
  "设为左轴" moves the chosen channel to the left axis.
- [ ] Report `ui_verified`, `tests_before/after`, `files_changed`, `symbols_touched`,
  `flagged[]`.
