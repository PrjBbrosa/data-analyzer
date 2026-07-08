# Acquisition Cockpit Live Monitoring UX Plan Report

- Date: 2026-07-08
- Scope: Acquisition Cockpit live monitoring, multi-channel display, overlay
  comparison, focus/zoom workflow, and follow-up UI polish.
- Evidence base:
  - Scripted cockpit tour:
    `scripts/cockpit_ui_tour.py --assert --shots output/cockpit-ui-tour-2026-07-07 --out output/cockpit-ui-tour-recordings-2026-07-07`
  - Output screenshots:
    `output/cockpit-ui-tour-2026-07-07/01-scrolled-select.png` through
    `07-narrow.png`
  - Generated demo recording artifacts:
    `output/cockpit-ui-tour-recordings-2026-07-07/capture_20260707_235541.mf4`,
    `.session_summary.json`, and `.preflight.json`

## Boundary

This report covers the live Cockpit user experience and proposed UI behavior.
The evidence above was produced with the `FAKE·演示` backend and offscreen Qt
rendering. It proves UI routing, rendering, recording handoff, and demo MF4
creation; it does not prove Windows Vector/XCP hardware capture or ECU
behavior.

## Current State

The July 7 render-review fixes moved the Cockpit from "visually present but
fragile" to a usable demo surface:

- Sparkline buffers are no longer empty in idle or recording.
- Idle mode no longer fills the recording ring buffer.
- A new channel added while idle receives data after the idle stream restarts.
- The record button remains enabled after a long idle soak.
- The review modal opens from a real finalized demo recording.
- The 960 px narrow-window path keeps the center pane alive and avoids
  clipping the current value.
- The center pane uses a `QScrollArea`, so selected live cards scroll instead
  of overflowing the window.

Important implementation facts:

- `LiveCardGrid` wraps live cards in a vertical `QScrollArea` and turns each
  selected signal into one `LiveSignalCard`.
- Each sparkline keeps a bounded 4096-point deque and renders through min/max
  downsampling.
- Live UI refresh runs at 30 fps normally and can degrade to 10 fps under ring
  watermark pressure.

## Problems Found

### P1 - Live Cards Can Lose Signal Identity

The center cards currently prioritize raster, unit, and current value so
strongly that the signal name can disappear at normal or narrow widths. This is
the most important human-factors issue because users cannot reliably identify
which curve they are watching without cross-checking the left pane.

Recommended fix:

- Signal name must always be visible on each live card.
- Stats may collapse first at narrow width.
- Long names should use middle or end elision with a tooltip containing the
  full channel name.
- Color remains an auxiliary identifier, not the primary identifier.

### P1 - Recording Quality Terms Are Still Mixed Language

The recording quality panel still exposes English labels such as `ring buffer`,
`dropped frames`, `last frame delay`, and `disk remaining`. The main status bar
also uses `RECORDING`, `samples`, `drop`, and `buf`.

Recommended labels:

| Current | Recommended |
| --- | --- |
| `ring buffer` | `缓冲占用` |
| `写入速率` | `写入速率` |
| `dropped frames` | `丢帧` |
| `CAN load` | `CAN 总线负载` |
| `last frame delay` | `最近帧延迟` |
| `disk remaining` | `磁盘剩余` |
| `RECORDING · ... samples · drop ... · buf ...` | `录制中 · ... 样本 · 丢帧 ... · 缓冲 ...` |

### P2 - Output Path Selector Is Hard To Confirm

The toolbar output selector keeps the full path in a narrow control, so screenshots
show truncated strings such as `output/cockpit-ui-to...` or `output/c`. The
tooltip contains the full path, but screenshots and live glance checks still
lose context.

Recommended fix:

- Keep the full path in the tooltip.
- Show a compact display string:
  - project-relative paths: `output/.../<leaf>`
  - absolute paths outside the project: `.../<parent>/<leaf>`
- Do not simply widen the selector; it would steal space from primary controls.

### P2 - Review Modal Is Functionally Correct But Visually Weak

The review modal now has a close button and a clearer diagnostic line, but the
layout is sparse and does not distinguish destructive and safe actions strongly
enough.

Recommended fix:

- Add a clear `录制完成` title.
- Present three compact facts: duration, received frames, dropped frames.
- Keep diagnostic details as secondary text:
  `已选 N · 缺失 M · fs≈X Hz`.
- Style `丢弃（不归档）` as a destructive action, visually separated from save
  actions.
- Preserve the existing gating: saving must not close the modal, and
  `在 Analyzer 打开` remains disabled until save/archive is valid.

## Multi-Channel Behavior

### What Happens With More Than 5 Or 10 Channels?

Current behavior:

- The window does not overflow because the center pane scrolls vertically.
- Usability declines after about 5 live cards because the operator must scroll
  to see all channels.
- At 10+ live cards, the center pane becomes a monitoring list rather than a
  cockpit overview.

Performance expectation:

- The UI is designed to repaint at 30 fps rather than per sample.
- Each sparkline is bounded and downsampled, so high sample counts do not map
  one-to-one to painted pixels.
- However, many 1 ms channels still add pressure on backend poll, Qt event
  handling, per-card buffers, downsampling, status updates, and MF4 writing.
  Real 10+ channel, 1 ms validation still requires a focused performance run.

Recommended product rule:

- Separate **captured channels** from **pinned live-monitor channels**.
- Allow many channels to be recorded.
- Default live display should show only 4-6 pinned channels.
- Additional captured channels remain in the left selection list and session
  summary, not necessarily in the live dashboard.

## Overlay Display

CANape-style overlay is useful, but it should be intentional rather than the
default for every selected signal.

Recommended model:

- Default: card mode for fast health monitoring.
- Optional: overlay mode for pinned channels only.
- If all selected overlay channels share the same unit, use a real shared y
  axis.
- If units differ, use normalized overlay (`%` or relative change from current
  window baseline) and show the normalization clearly.
- Keep overlay channel count small, ideally 2-4 signals.

Why not overlay everything:

- Ten mixed-unit channels on one axis are visually noisy.
- Operators lose immediate value readability.
- Different physical quantities such as rpm, Nm, V, and degC do not share a
  meaningful y scale.

## Focus / Zoom / Axis Workflow

Current live cards are sparklines, not interactive plots. They do not expose
real axes, wheel zoom, pan, cursor readout, or manual y-axis controls. Trying to
put full axis controls into every small card would make the Cockpit crowded and
slow to use.

Recommended workflow: add a **Focus View**.

Entry points:

- Double-click a live card.
- Right-click a live card and choose `聚焦查看`.
- Optionally use a small focus icon in the card header.

Focus View capabilities:

- One primary channel shown in a larger pyqtgraph plot.
- Time window controls: `5 s`, `10 s`, `30 s`, `60 s`, `全录制中`.
- Wheel zoom and drag pan.
- Auto y-axis and manual y-axis min/max.
- Cursor readout: time, value, and delta.
- Pause display without pausing acquisition.
- Add one or more pinned channels for comparison.
- Return to the live card overview without stopping recording.

This is the best place for local zoom and axis work because it provides enough
screen space for axes and controls while keeping the main Cockpit readable.

## Recommended Architecture

The Cockpit should distinguish three layers:

```text
Selection layer
Left pane: choose what to capture and set raster/event.

Monitoring layer
Center cards: show pinned, operator-relevant live signals.

Inspection layer
Focus View: zoom, axes, cursor readout, and controlled overlay comparison.
```

This keeps acquisition durable while still giving the operator CANape-like
inspection affordances when needed.

## Proposed Phases

### Phase 1 - Readability And Localization

Goal: make the current Cockpit easier to read without changing behavior.

Tasks:

- Keep live card signal names visible.
- Localize recording quality and status-bar labels.
- Improve compact output-path display.
- Improve review-modal visual hierarchy.

Validation:

- Add or update UI tests for label visibility and text.
- Rerun the cockpit tour with screenshots at 1280 px and 960 px.

### Phase 2 - Pinned Live Monitoring

Goal: prevent the live dashboard from turning into an unbounded card list.

Tasks:

- Introduce a pinned/live-visible distinction.
- Keep capture selection independent from visible live cards.
- Add a small counter such as `已采集 18 · 实时显示 5`.
- Default to 4-6 pinned cards and allow manual pin/unpin.

Validation:

- 20 selected channels do not create an unreadable primary dashboard by
  default.
- Recording still includes all selected captured channels.
- Screenshots show a stable dashboard with 4-6 cards.

### Phase 3 - Focus View

Goal: support detailed inspection of a single channel while recording.

Tasks:

- Add Focus View entry from a live card.
- Use a larger interactive plot for one channel.
- Add time-window, y-axis, cursor, and pause-display controls.
- Keep acquisition running while the view is paused or zoomed.

Validation:

- User can zoom/pan a focused channel without affecting capture.
- Cursor values are readable.
- Returning to card overview preserves recording state.

### Phase 4 - Overlay Mode

Goal: support CANape-style comparison without making the default cockpit noisy.

Tasks:

- Add overlay for pinned/focused channels.
- Support same-unit real y-axis overlay.
- Support mixed-unit normalized overlay.
- Cap or warn when too many channels are added.

Validation:

- Two to four channels are readable.
- Mixed-unit overlay is clearly labeled as normalized.
- Overlay mode does not degrade recording health under expected signal counts.

### Phase 5 - Real Performance Evidence

Goal: verify the design against realistic high-frequency loads.

Suggested scenarios:

- 4 channels at 1 ms.
- 10 channels at 1 ms.
- 20 selected channels with only 5 pinned live cards.
- 10 pinned live cards, to define the practical warning threshold.

Metrics:

- UI frame interval / redraw lag.
- Poll duration.
- Writer throughput.
- Ring buffer fill.
- Dropped frames.
- CPU and memory trend.
- Operator-visible responsiveness during zoom/pan/focus changes.

## Decision Summary

Recommended direction:

1. Keep the Cockpit card view as the default monitoring surface.
2. Do not display every captured channel as a full live card by default.
3. Add pinned live channels before adding overlay.
4. Add Focus View for zoom, axes, cursor, and detailed inspection.
5. Add overlay as an intentional comparison mode for a small number of channels.
6. Validate 1 ms / 10+ channel behavior with real performance evidence before
   claiming field readiness.

## Suggested Next Prompt

Use this report as the starting point:

`docs/analyzer/acquisition/reports/2026-07-08-cockpit-live-monitoring-ux-plan-report.md`

Next goal: write a focused spec for Phase 1 and Phase 2:

- live card signal-name visibility,
- localized recording/status labels,
- compact output-path display,
- review-modal hierarchy,
- pinned live-monitor channels separated from captured channel selection.
