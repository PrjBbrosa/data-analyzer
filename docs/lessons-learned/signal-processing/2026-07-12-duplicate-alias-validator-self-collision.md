---
role: signal-processing
tags: [validator, alias, normalization, catalog, db-reference, guard-test]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

# A cross-entry duplicate-alias validator must dedupe an entry's own alias list before the global-seen check

## Context
Building the QSettings-backed dB-reference catalog store (Task 2), calling
the already-merged `db_reference.validate_catalog()` on the merged
system+user catalog raised `DuplicateAliasError` with ZERO user overrides —
on the bare `FACTORY_CATALOG_V1` itself. `acceleration.si`'s own
`aliases=("m/s²", "m/s^2", "m/s2")` all normalize to the identical token
`m/s2`; the original loop folded every alias of every entry into ONE global
`seen` set, so an entry's second/third spelling variant collided with its
own first one.

## Lesson
A catalog author legitimately lists several spellings of ONE unit on a
single entry — that is the entire purpose of `aliases`. "Duplicate" should
only mean TWO DIFFERENT entries claiming the same normalized `(quantity,
alias)`. A naive accumulate-into-one-set loop cannot distinguish "this
entry's own repeat" from "a different entry's collision"; it must dedupe
aliases PER ENTRY (`{normalize_unit(a) for a in entry.aliases}`) before
checking/adding to the cross-entry `seen` set.

## How to apply
When writing or reviewing a duplicate-detection loop over `(container,
repeatable-sub-items)` pairs where sub-items legitimately repeat within one
container (aliases-per-catalog-entry, tags-per-record, etc.), add a
regression test that calls the validator against REAL production data, not
just a synthetic two-entry fixture — `validate_catalog` had a passing test
with two distinct 1-alias entries, but `validate_catalog(FACTORY_CATALOG_V1)`
itself (one entry, three alias spellings) was never exercised and crashed
the very first real caller.
