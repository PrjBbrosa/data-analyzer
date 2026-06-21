---
role: signal-processing
tags: [heatmap, amplitude_db, dead-branch, clip, tdd, test-contract, display-only]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

## Context

`plot_or_update_heatmap` had an `amplitude_db` branch that clipped the
matrix to `[z_floor, z_ceiling]` in manual mode — the root cause of the
"拖色阶 vs 重算不一致" bug. The test `test_db_mode_manual_levels_clip`
asserted `img.min() == -30.0`, locking in the clip as the expected
contract.

## Lesson

A test that asserts the *result of the bug* (clipped floor) instead of
the *correct invariant* (unclipped matrix) turns into a red-herring when
the bug is fixed: it passes green against the broken code and fails red
against the correct code. Before deleting a dead branch, verify that
every test covering it asserts the intended contract, not the buggy
behaviour — otherwise the tests appear to protect the code while actually
protecting the bug. Grep the branch being removed and check each `assert`
against the design invariant ("colour-scale must be display-only").

## How to apply

When removing a dead branch: (1) grep every test that exercises it; (2)
for each `assert`, ask "does this assert the *intended* behaviour or the
*buggy* behaviour?"; (3) delete tests that assert buggy behaviour; (4)
add a new guard test that raises ValueError (or similar) on the removed
path so future callers get an immediate failure instead of silent
regression. Then confirm the new guard is RED before the deletion and
GREEN after.
