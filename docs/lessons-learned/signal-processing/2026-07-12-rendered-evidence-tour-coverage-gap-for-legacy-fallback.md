---
role: signal-processing
tags: [fft, legacy-fallback, reachability, rendered-evidence, ui-tour, amplitude-label, dba, weighting, guard-test]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

# A green visual-parity tour does not prove a legacy fallback branch is safe if the tour never drives it

## Context
Task 11's stale-string audit flagged `_fft_mixin.py`'s `_do_fft_single` — the back-compat
"no navigator-checked sources" single-signal fallback — as ambiguous: hardcode a bare
`'Amplitude (dB)'`/`'Amplitude'` label and convert with the raw `fft_params.get('db_reference',
1.0)`, bypassing the per-source resolver (`_resolve_db_reference_for_source`) and shared formatter
(`db_reference.format_amplitude_label`) that the checked-source overlay path already used. The
9-state `scripts/db_reference_ui_tour.py` (Task 10's rendered-parity evidence) had been green
through every prior task, which could be misread as proof this branch was already fine.

## Lesson
The tour's own driver code always calls `navigator.set_checked_channels(...)` before `do_fft()`,
so it exercises ONLY the per-source overlay path and NEVER `_do_fft_single` — a fully green,
carefully-asserted rendered-evidence suite can still have zero coverage of a legacy branch that a
real user hits by simply not checking any navigator channels. Classifying "intentional documented
default" vs "live reachable bug" needs two independent checks, not one: (1) grep the call graph to
confirm the branch is actually reachable in the current build (not dead code left from a refactor),
and (2) grep the SAME rendered-evidence driver's setup calls to confirm it actually reaches that
branch — a passing tour proves nothing about code paths it structurally cannot enter.

## How to apply
When a task hands you a "classify this hardcode as default-vs-bug" item inside a fallback/back-
compat branch: trace real callers first (is the branch reachable at all — some sibling branches in
the same function turn out to be dead, e.g. an `else: order` arm never taken because the entry
point is only wired for one mode); then check whether the project's own rendered-evidence/tour
script's setup ever puts the app into the state that reaches this specific branch before trusting
its green run as coverage. If the spec has a stop-gate for the value this branch produces (e.g. "A-
weighting must always show dBA"), a reachable-but-uncovered branch is a live target render path,
not a documented default — fix it and add a unit-level TDD guard test scoped to that exact branch,
since the tour cannot be relied on to catch a regression there.
