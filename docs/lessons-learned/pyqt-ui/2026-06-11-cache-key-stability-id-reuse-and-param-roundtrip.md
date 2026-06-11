---
role: pyqt-ui
tags: [cache, lru, id-reuse, memo, round-trip, get-params, apply-params, cache-key, multiview, heatmap, fft]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
V7 introduced per-section ``AnalysisResultCache`` (LRU) plus view-switch
"render from cache, never recompute". Two independent cache-key
stability bugs surfaced: (1) ``PgHeatmapCanvas.plot_result`` memoized its
dB matrix on ``(id(result), db_ref)``; (2) the FFT view's compute key
included ``overlap`` captured/applied through ``FFTContextual`` across a
view switch.

## Lesson
A cache or memo key is only correct if every component is STABLE across
the object's whole lifetime AND survives a round-trip through whatever
serializes it. ``id(obj)`` is NOT stable once an upstream LRU evicts and
frees the object — CPython reuses the freed id() for the next allocation,
so an ``id()``-keyed memo returns the OLD payload for a NEW result (silent
stale image, never a crash). Fix: stamp a monotonic epoch token onto each
distinct object on first sight (``result._pg_db_epoch``); it travels with
the object and never collides. Separately, a param key is unstable if the
widget's ``get_params``/``apply_params`` are asymmetric: ``FFTContextual``
emits ``overlap`` as a FRACTION (0.5) but ``apply_params`` does
``spin_overlap.setValue(int(0.5))`` → 0, so the same view re-applied yields
``overlap=0.0`` and the key never re-hits. The compute didn't even consume
``overlap`` (FFT spectra use ``avg_overlap``), so it was a phantom key
component — exclude any field that (a) doesn't affect the compute or (b)
can't round-trip through the inspector's own get/apply.

## How to apply
Before keying a result cache or a per-result memo: never use ``id()`` if
the result can be evicted/freed elsewhere — use a stamped monotonic token
or a content fingerprint. When the key is built from inspector params that
also pass through ``apply_params`` on a view/preset restore, verify
``get_params() == apply_params(get_params()); get_params()`` for every
keyed field (a one-line round-trip assert), and drop any field the compute
doesn't actually read. Symptom to watch for: "switch away and back
recomputes / shows stale" — diff the cache key produced at compute time vs
at switch-back time; a mismatched float (0.5 vs 0.0) or a reused id is the
tell.
