---
role: signal-processing
tags: [tdd, migration, monkeypatch, coincidental-pass, contract-change, db-reference, fft, guard-test]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

# A test surviving a global-value → per-entity-resolution migration by numeric coincidence is a silent false pass

## Context
FFT's per-curve dB-reference conversion moved from "read a single shared
`current_params()['db_reference']` value" to "resolve each `(fid, ch)`
entry's own reference via the catalog service" (spec §15 C1). An existing
test monkeypatched `current_params` to return `{"db_reference": 1.0, ...}`
and asserted the converted amplitude used reference `1.0`. After the
migration, `_fft_entry_from_cache` no longer reads that dict key at all —
it resolves a fresh reference from empty facts (no file loaded), which
degrades to the resolver's `generic` default, also `1.0`. The test kept
passing, but for a completely different, accidental reason: the monkeypatch
became dead code the moment its target value happened to equal the new
mechanism's default.

## Lesson
When a redesign replaces "one shared input value everything reads" with
"each entity resolves its own value independently", any test that pins the
OLD input to the same numeric value the NEW mechanism defaults to cannot
distinguish "the new wiring is live" from "the new wiring is silently
bypassed and a coincidence saved the assertion". This is invisible in a
green test run — there is no crash, no wrong number, just a mechanism that
quietly stopped being exercised.

## How to apply
After migrating a "single control value" call site to "per-entity
resolution", audit every existing test that drives the OLD input and check
whether its numeric value differs from the NEW mechanism's fallback/default.
If it coincides, change the test to use a value that could only be produced
by the NEW mechanism (e.g., set a Manual-mode reference distinctly different
from the resolver's generic default, or give the entity real metadata that
resolves to a unique value) and assert the resolution object/identity
directly (not just the numeric output), so the test would fail loudly if
the old dead code path were still silently in charge.
