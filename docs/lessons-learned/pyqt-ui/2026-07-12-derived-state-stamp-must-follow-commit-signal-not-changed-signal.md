---
role: pyqt-ui
tags: [qsignal][signal-ordering][valuechanged][value-committed][spinbox][mode-flip][derived-state][nudge][race-condition]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

## Context

Wiring a live footer-nudge fact stamp (dB-reference-defaults spec S5 / A17)
to `ScientificReferenceSpinBox`'s `valueChanged` inside `DbReferenceControl`.
The editor auto-promotes Auto→Manual on a genuine user commit from its OWN
`_commit_or_revert()`: it calls `self.setValue(parsed)` first (which fires
the inherited `valueChanged` synchronously), THEN emits its custom
`value_committed` signal, which a sibling handler (`_on_editor_value_committed`)
uses to call `set_mode('manual')`. A stamp connected to `valueChanged` reads
`control.mode()` and observed the STALE pre-flip `'auto'` for exactly the one
keystroke that performs the promotion — verified only by an on-screen replay
with real `QTest.keyClicks` + `Qt.Key_Return`, not by driving the widget's
public `set_mode()`/`setValue()` APIs directly (which bypass the ordering
entirely and always look correct).

## Lesson

When a low-level Qt signal (`valueChanged`) and a widget's own higher-level
custom "commit" signal (`value_committed`) both fire from the SAME triggering
action, the low-level one fires FIRST if the commit handler's own code path
calls `setValue()` before emitting its custom signal. A derived-state stamp
that needs the POST-mutation state (e.g. a mode flip performed by the
commit handler) must attach to the higher-level commit signal, not the
low-level changed signal, even though both appear to fire "at the same time"
in a manual test. Driving a widget via its own public setter methods
(`set_mode`, `setValue`) directly in a test never reproduces this ordering
hazard — it must be exercised through the real user gesture (`QTest.keyClicks`
+ `Qt.Key_Return` / focus-out) to observe the actual signal sequence.

## How to apply

Before wiring a stamp/derived-state update to a widget's `valueChanged` (or
any low-level "changed" signal) when the SAME widget also exposes a
higher-level "committed"/"applied" signal that a sibling handler uses to
mutate other state (mode, cache, flags), grep that sibling handler for
whether it calls a low-level setter (`setValue`, `setText`, ...) BEFORE
emitting the higher-level signal — if so, add a SEPARATE connection to the
higher-level signal for anything that needs the post-mutation state, and
verify with a real keypress-driven exercise (`QTest.keyClicks` + Enter), not
a direct call to the widget's own public mutator methods.
