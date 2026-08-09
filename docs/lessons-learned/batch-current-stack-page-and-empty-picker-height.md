---
id: batch-current-stack-page-and-empty-picker-height
status: active
owners: [codex]
keywords: [batch, pyqt, qstackedwidget, signal-picker, popup, geometry, empty-state]
paths: [mf4_analyzer/ui/drawers/batch/input_panel.py, mf4_analyzer/ui/drawers/batch/signal_picker.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_input_panel.py, tests/ui/test_batch_signal_picker.py]
---

# Batch Picker Layout Uses The Current Stack Page And Readable Empty State

Trigger: Changing a Batch stacked field that swaps compact and multi-row pages, or the signal-picker popup's empty/list geometry.

Past failure: The target `QStackedWidget` used the hidden FRF pair editor's 191px height while its signal-picker page was only 38px, leaving a large blank gap in Order. Separately, an empty picker assigned its label 32px even though its padded text needed 48px, visibly clipping `无匹配信号`.

Rule: Height decisions for a method-specific stacked Batch field must use its current page and invalidate the owning form after a page switch. A fixed popup empty state must give its label at least its size hint (the shared picker keeps the list minimum height).

Verification: Run the focused input-panel and signal-picker tests, then render the Order Batch input panel and an empty RPM picker under the shipped stylesheet; confirm a 38px target row and a fully visible empty-state label.
