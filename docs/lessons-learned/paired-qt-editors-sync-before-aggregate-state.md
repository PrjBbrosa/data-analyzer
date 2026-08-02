---
id: paired-qt-editors-sync-before-aggregate-state
status: active
owners: [codex]
keywords: [PyQt, slider, spinbox, signal, render-style]
paths: [mf4_analyzer/ui/drawers/batch/render_style_popover.py]
checks: [paired editor values agree before aggregate state reconstruction]
tests: [tests/ui/test_batch_output_panel.py]
---

# Paired Qt Editors Sync Before Aggregate State Reconstruction

Trigger: A slider and spinbox edit the same value while one handler rebuilds an
aggregate settings object from several controls.

Past failure: A slider emitted first, the handler read the paired spinbox's stale
value, and `set_style()` immediately restored that stale value so the handle
appeared impossible to drag.

Rule: Make the changed control explicit, synchronize its peer with signals
blocked, then reconstruct aggregate state from the synchronized controls and
emit one final change.

Verification: Use real `QTest.mousePress`, `mouseMove`, and `mouseRelease` for
every slider pair; assert slider, spinbox, summary, emitted recipe, and the value
after closing and reopening the popover all agree.
