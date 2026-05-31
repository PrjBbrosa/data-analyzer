# Pyqtgraph TimeDomain UI Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** restore pyqtgraph TimeDomain zoom/pan, cursor, subplot, and visual behavior to the original matplotlib canvas baseline.

**Architecture:** Prefer the existing pyqtgraph `PlotDataItem` as the visible rendering truth for this repair. The current `QPainterPath`/`QPixmap` cache is computed but not displayed, and its pixmap transform is not safe to connect directly; viewport refresh should update the visible item with the current envelope first, then future performance work can replace it with a correctly transformed custom item.

**Tech Stack:** Python, PyQt5, pyqtgraph, pytest/pytest-qt, existing `mf4_analyzer.ui.pg_canvases.TimeDomainCanvasPG`.

---

## Verified Scope

- P0-1 is real as a visible-data bug: viewport envelopes are computed but not shown.
- P0-1a is new: `_render_path_to_pixmap()` uses a fixed-height, untransformed data-space pixmap and should not become the visible layer.
- P0-2 is real: live single/dual cursor event handling and vertical lines are missing.
- P0-3 is partial: X sync exists and is tested, but wheel Y targeting and toolbar pan/zoom target only the primary ViewBox.
- P1-4, P1-6, P1-7, P1-8 are real.
- P1-5 is partial: checked text is visible dark blue, but white checked fill is too weak on the white toolbar.

## Agent Split

- Main Codex session owns `mf4_analyzer/ui/pg_canvases.py` and `tests/ui/test_pg_timedomain_canvas.py`.
- Worker A owns `mf4_analyzer/ui/chart_stack.py`, `mf4_analyzer/ui_kit/style.qss`, and `tests/ui/test_chart_stack.py`.
- Explorer agents have already completed read-only verification for render, cursor, and visual/sync evidence.

## Task 1: Visible Viewport Resampling

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] Add a RED test near `TestTimeDomainCanvasPGCurveCache` that binds a high-sample channel, captures `PlotDataItem.getData()`, applies `set_xlim(2.0, 5.0)` plus `_flush_pending_refresh()`, and asserts the visible x data is clipped to the viewport and differs from the full-range bind data.
- [ ] Run the single test and confirm it fails because the visible PlotDataItem still contains full-range data.
- [ ] Update `_refresh_visible_data()` to call the real `PlotDataItem.setData(env_t, env_s)` for the channel after `positions_envelope`.
- [ ] Keep raw `channel_data` unchanged for statistics/cursor values.
- [ ] Retire or de-emphasize the dead pixmap path in comments/tests so it is not described as visible blit until a correct custom layer exists.
- [ ] Run the visible-resampling test and the existing envelope/cache/statistics subset.

## Task 2: Live Cursor Interaction

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] Add a RED single-cursor interaction test that enables cursor mode, maps a known data x to a viewport point, sends a mouse move, and asserts `cursor_info` emits plus at least one visible cursor line exists.
- [ ] Add a RED dual-cursor interaction test that enables dual mode, sends two left clicks at different data x positions, and asserts `_ax`, `_bx`, `cursor_info`, `dual_cursor_info`, and visible A/B lines update.
- [ ] Implement cursor line storage using `pg.InfiniteLine` per subplot/ViewBox.
- [ ] Use the existing viewport/scene hit-test helpers to map mouse positions to the source ViewBox data coordinate.
- [ ] Route hover to `_emit_single_cursor_html()` or `_emit_dual_cursor_html(hover=...)` behavior equivalent, preserving existing HTML parity helpers.
- [ ] Run the cursor-focused tests and `tests/ui/test_chart_stack.py::test_cursor_pill_updates_on_time_signal`.

## Task 3: Subplot Interaction Targeting

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `mf4_analyzer/ui/chart_stack.py`

- [ ] Add a RED test proving `Shift+wheel` with `view_box=axes_list[2].view_box` changes only axis 2 Y range, not primary.
- [ ] Add a RED test proving plain wheel with a non-primary ViewBox pans that axis Y range.
- [ ] Add a RED toolbar test proving `PgNavigationToolbar.pan()` and `.zoom()` set mouse mode on every subplot ViewBox.
- [ ] Change `_handle_wheel_dispatch()` to choose the handle matching the source `view_box`; Ctrl+wheel still changes synchronized X through the source then propagation, while Shift/plain affect the source Y.
- [ ] Change `PgNavigationToolbar` to iterate all live ViewBoxes when setting mouse mode.
- [ ] Run focused scroll and chart-stack toolbar tests.

## Task 4: Visual Parity Defaults

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`

- [ ] Add RED tests for default grid enablement in single, overlay, and subplot builds.
- [ ] Add RED tests that non-bottom subplot x-axis tick values are hidden and the last subplot keeps them.
- [ ] Add RED tests that long subplot labels at normal width use inside `TextItem` labels and clear the left axis label.
- [ ] Add RED tests for baseline line width 1.05 and channel-colored left axis pen/text.
- [ ] Add a RED QSS token test that chart-choice checked fill is not white and uses the existing light-blue selection token.
- [ ] Implement a small `_style_plot_item(...)` / `_apply_axis_channel_style(...)` helper in `pg_canvases.py`; do not introduce a new visual system.
- [ ] Set default `showGrid(x=True, y=True, alpha=...)`, hide non-bottom bottom-axis values, use inside labels for subplot mode with long labels, set line width to 1.05, and color the left axis.
- [ ] Update checked button style to `#e8efff` fill with blue text/border.
- [ ] Run focused visual tests and render at least one offscreen screenshot.

## Task 5: Verification And Lessons Gate

**Files:**
- Modify only if required: `.state/lesson-candidate.md`

- [ ] Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_chart_stack.py -q`.
- [ ] Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py::test_timedomain_pan_refresh_pg_canvas -q` as a smoke/perf sanity check, not an absolute timing gate.
- [ ] Run a screenshot/render check and save temporary PNGs under `/tmp`.
- [ ] Run `/usr/bin/python3 scripts/lessons/check.py --status`.
- [ ] If this work creates a durable lesson requirement, promote it through the repo lessons workflow; otherwise leave lessons state clean.
