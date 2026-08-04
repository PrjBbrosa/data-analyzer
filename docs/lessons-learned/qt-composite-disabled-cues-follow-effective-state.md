---
id: qt-composite-disabled-cues-follow-effective-state
status: active
owners: [codex]
keywords: [pyqt, disabled, cursor, icon, enabled-change, composite-control]
paths: [mf4_analyzer/ui/drawers/batch/signal_picker.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_signal_picker.py]
---

# Qt Composite Disabled Cues Follow Effective State

Trigger: Changing disabled styling or interaction cues on a composite Qt
control whose children can be disabled by an ancestor.

Past failure: The Batch signal picker changed its frame fill and border when
locked, but retained a pointing-hand cursor and a normal-color custom chevron,
so the disabled control still looked clickable.

Rule: Treat effective enabled state as one presentation contract. Handle
`QEvent.EnabledChange` on custom-drawn child controls, restore both disabled and
enabled cursors explicitly, and include enabled state in any icon cache key.

Verification: Disable and re-enable the real composite through its ancestor;
assert cursor shapes and inspect the real icon pixmap color in
`tests/ui/test_batch_signal_picker.py`, then run `git diff --check`.
