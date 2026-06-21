---
role: signal-processing
tags: [cache, cache-key, dataclass, compute-contract, display-param, phantom-field, fft, order, spectrogram, cot, guard-test, introspection]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

# The cache key and its compute-param dataclass must share ONE field set — and a dataclass field is not proof compute reads it

## Context
Root-causing "changed a compute param but hit a stale cached result" /
"changed a display param but it span a needless recompute" across the
FFT-vs-Time (`SpectrogramParams`) and Order (`COTParams`) pipelines. Two
opposite drifts coexisted: `db_reference` (display-only — `compute` never
reads it) was a `SpectrogramParams` field AND in the fft_time cache keys,
so changing it recomputed a byte-identical amplitude matrix; meanwhile
`window` (a real `COTParams` compute input) was MISSING from the Order
cache key, so changing the window silently reused the old-window result.

## Lesson
The frozen `*Params` dataclass should be the single authority for the
"compute parameter set", and the cache key must register exactly that
set (modulo external input dimensions: `fid`/`channel`/`time_range`/
`rpm_source`/`rpm_factor`, and UI nfft-resolution dims `nfft_mode`/
`nfft_effective`/`nfft_preview`). Human vigilance does not hold this
invariant — encode it as an introspection guard: parse each pure
dict-reading key function's source for `params.get('x')`/`p['x']`
(restrict the receiver to the params arg name to skip noise like
`self.caches['fft_time']`), and assert `registered_compute_fields ==
dataclasses.fields(DataClass)` after subtracting a per-field-justified
exemption map. Prove it bites by injecting an unkeyed field and watching
it go RED. SECOND, non-obvious half: a field LIVING on the compute
dataclass is NOT proof `compute` consumes it — `COTParams.time_res` is
carried but `compute` hardcodes a 75% angle-domain hop and never reads
it, and `COTParams.fs` is carry-through for batch-preset capture only.
So a naive "every dataclass field is consumed by compute()" assertion
false-fails; pin a documented consumption map instead and only assert the
fields you claim are read actually appear as `params.<name>` in
`compute`'s source.

## How to apply
When adding/auditing an analysis cache: (1) make the cache key field set
mechanically equal to the compute dataclass field set via a
`dataclasses.fields` + `inspect.getsource` guard with an explicit
exemption set, not a hand-maintained list; (2) keep display-only params
(`db_reference`, `cmap`, `z_*`, freq/amp ranges) OFF the dataclass and
OUT of the key — they belong in the render signature / plot kwargs (e.g.
`plot_result(db_reference=...)` sourced from the inspector at render
time); (3) before trusting "field X is a compute input", grep
`params.X` in the analyzer's `compute` body — a carry-through or
not-yet-wired field (Task-owned elsewhere) must be classified, never
keyed nor assumed consumed.
