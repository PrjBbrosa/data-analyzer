---
role: pyqt-ui
tags: [qdialog, modal, gating, save-action, reachability, review-modal, test-backdoor]
created: 2026-05-15
updated: 2026-05-15
cause: insight
supersedes: []
---

## Context

The Acquisition Cockpit review modal exposed four actions: `丢弃`,
`仅保存文件`, `保存并归档`, `在 Analyzer 打开`. The Analyzer-open
button is gated — it becomes enabled only AFTER a successful save or
archive. The first implementation flipped `_save_ok = True` and then
immediately called `self.accept()` inside the save action, mirroring
the Stage 4 placeholder pattern of "action closes, returns to idle".

The gating change made the Analyzer-open button reachable on paper,
but in production it was unclickable: by the time it was enabled, the
modal was already closing. The test suite hid the regression by
setting `modal._save_ok = True` directly (a non-public attribute) and
calling `do_open_in_analyzer()` — a backdoor that bypassed the very
button click the test claimed to exercise.

## Lesson

When a save/archive action GATES a sibling button on the SAME modal,
the action must not also close the modal — otherwise the gated button
is permanently unreachable through the real UI even though it is
"enabled". The state-machine equivalent is: a transition that unlocks
a peer transition must not also fire a terminal transition. The fix is
to keep the modal open after save/archive and use an inline status
label (`已保存` / `已归档`) for non-blocking confirmation; closure is
only triggered by the user explicitly clicking the now-enabled
follow-up action or dismissing the modal.

Tests that "drive the action" by setting a private flag (here
`_save_ok = True`) and skipping the click are a code smell: they
prove the predicate works but bypass the only path that exercises
reachability. If the only way to make the test pass is to mutate
private state, the contract is wrong somewhere — fix the contract,
not the test setup.

## How to apply

For any modal with a gated-on-state action:

1. Implement save/archive actions as in-place state mutators: flip the
   gate flag, refresh button enabled state, render an inline status
   label, do NOT call `accept()` / `reject()`.
2. Closure of the modal is reserved for the explicit follow-up action
   (e.g., the gated button calling `accept()`) and for user dismissal
   (close button / Esc → `reject()`). The terminal `丢弃` action also
   closes — but its closure is its semantics, not a side effect of a
   sibling state mutation.
3. Tests for the gated action MUST drive the prerequisite action
   through its public method (`do_save_only()`, not
   `_save_ok = True`). If the test still needs a backdoor, the action
   is closing the modal — fix the action, not the test.
4. Add a "real-flow" test per gated path: call the prerequisite,
   assert the modal is still visible, assert the gated button is now
   enabled, call the gated action, assert it took the expected effect.
