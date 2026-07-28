---
id: batch-render-facts-use-producer-contract
status: active
owners: [codex]
keywords: [batch, renderer, effective-facts, nfft, integration]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_render.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py, tests/test_batch_renderer.py]
---

# Batch Render Facts Must Use Producer-Shaped Tests

Trigger: Adding or renaming effective analysis facts shown in batch titles, subtitles, labels, or manifests.

Past failure: The runner emitted `nfft_effective`, but renderer code and its isolated test used `effective_nfft`. Tests passed while real Auto NFFT exports displayed the requested value `auto` instead of the actual numeric NFFT.

Rule: Freeze effective-fact keys at the runner-to-renderer boundary. Renderer tests must use the exact mapping produced by `BatchRunner`; compatibility aliases may be read only after the canonical producer key.

Verification: Run `tests/test_batch_runner.py` and `tests/test_batch_renderer.py`; include a case with requested `nfft="auto"` and canonical `nfft_effective=64`, then assert the figure displays only `NFFT=64`.
