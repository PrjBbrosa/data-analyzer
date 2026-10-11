---
id: result-cache-tokens-must-be-unique-across-canvases
status: active
owners: [codex]
keywords: [heatmap, db-cache, result-identity, comparison, cross-canvas]
paths: [mf4_analyzer/ui/pg_canvas/heatmap_canvas.py]
checks: []
tests: [tests/ui/test_pg_heatmap_canvas.py::test_db_memo_identity_survives_results_moving_between_canvases]
---

# Result cache tokens must be unique across canvases

Trigger: Caching transformed results that can move between host, peer, or restored canvases.

Past failure: Each heatmap canvas stamped its first result with epoch 1. A peer result moved to the host then hit the host's unrelated epoch-1 dB matrix; correct View and request identities still displayed another View's data.

Rule: Tokens attached to shared results must be allocated across the whole process, never from a receiving canvas's local counter. Keep result identity distinct from reference/display settings and preserve eviction safety.

Verification: Render different results on separate canvases, swap them both ways, and compare each displayed matrix with its known conversion for float32/float64. Also navigate between independently computed Views. For line plots compare retained full data, since rendered curves may be legitimately decimated for different geometry.
