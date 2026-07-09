---
role: pyqt-ui
tags: [status-bar, font-metrics, horizontaladvance, width-budget, degrade, drop-branch, test-determinism, cjk, overlay, zero-shift, escalation-bar, statusbar]
created: 2026-07-10
updated: 2026-07-10
cause: insight
supersedes: []
---

## Context

Task B-3 replaced the recording status bar with a priority-degraded facts
stream (`_recording_fact_parts(width_px)` drops the lowest-priority field
whole via `QFontMetrics.horizontalAdvance`, no mid-elide) and added an
`EscalationBar` overlay above the `QStatusBar`. The plan specified a
"1280px→5 fields / 960px→degrade" test.

## Lesson

A realistic 5-field CJK status string ("00:00 · 剩余 ∞ · 0 样本 · 缓冲中 ·
0 样本/s") is only ~500px wide, so a literal 960px (or 1280px) budget fits
ALL fields and the drop branch NEVER executes — the "narrow degrades" test is
a false green that locks in nothing. Derive the tight budget from MEASURED
field widths in the test (`w3 = fm.horizontalAdvance(join(full[:3]))`, pass
`(w3+w4)//2`) so exactly N fields fit deterministically across fonts/DPI;
reserve the literal-1280 case only for the "roomy → all five" assertion.
Separately: an alarm/escalation band that must not reflow the body has to be
parented to the window OUTSIDE any layout (a status-bar-adjacent overlay,
re-anchored in `resizeEvent`), and its zero-shift must be proven by asserting
`center.geometry()` equality across green/yellow/red/ack/recovery — not by
eyeballing that "it looks fine". Also honor the field's real unit: a
`write_rate_bps` named "…bps" is samples/s here, so disk-remaining-time must
come from the byte-throughput estimator; assert it stays ∞ on an empty
selection even when the samples/s rate is huge, proving the byte path.

## How to apply

When a widget drops whole fields to fit a pixel budget, write the "degrades"
test against a QFontMetrics-measured budget (N-field width), never a plan's
literal window px; keep the literal wide value only for the all-fields case.
For any banner/overlay that must not move the body, parent it off-layout and
gate the test on `container.geometry()` equality across every state.
