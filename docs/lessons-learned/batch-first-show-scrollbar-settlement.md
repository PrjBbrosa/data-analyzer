---
id: batch-first-show-scrollbar-settlement
status: active
owners: [codex]
keywords: [BatchSheet, QScrollArea, showEvent, scrollbar, first-frame, width, height, LayoutRequest]
paths: [mf4_analyzer/ui/drawers/batch/sheet.py]
checks: [pre-event-loop viewport widths, Cocoa Fusion probe, short-window scroll reachability]
tests: [tests/ui/test_batch_smoke.py::test_batch_sheet_viewport_widths_settle_before_show_returns, tests/ui/test_batch_first_show_geometry.py]
---

# Batch First Show Must Settle Scrollbar Gutters

Trigger: Changing Batch window startup or scroll-pane geometry.

Past failure: Fusion scroll areas retained visible vertical scrollbars with a zero range immediately after show. Queued scrollbar hides widened all three viewports by 8 px on the next event-loop turn; tests that waited before measuring missed this transition.

Rule: After child geometry and screen correction settle in showEvent, reapply each pane's existing scrollbar policy to synchronously settle its gutter. Preserve ScrollBarAsNeeded and avoid global event pumping or delayed window exposure. Compare geometry immediately after show returns with geometry after queued events, rather than asserting only the settled size.

Verification: Run the named regression for time and time-frequency methods, short-window scrolling, and repeated show/hide. Record viewport resize events in a Cocoa window using the production Fusion style; widths must remain stable after show returns.

Height follow-up: stable viewport widths did not prevent nested content from painting stale FFT/default sizes. Time/FRF forms changed by +26/+140 px and output axes by -102 px after first paint. In Batch showEvent, settle polished child layouts and deliver only descendant LayoutRequest events bottom-up, refresh the dB control against its allocated editor height, propagate requests again, then settle scrollbar policies. Never call processEvents or expose the window late to hide the symptom.

Height verification: compare every visible descendant rectangle immediately after show and after events, across all five methods, compact/wide/short windows and reopen. Assert unrelated queued timers remain pending during show. Cocoa probes must record each widget’s own first Paint geometry, not just the parent window’s paint.
