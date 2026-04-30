---
id: codex-order-canvas-wave-review
status: active
owners: [codex]
keywords: [order-canvas, wave-review, envelope, build_envelope, stale-generation, boundary, append-only, cancel_requested, strict-scope]
paths: [mf4_analyzer/ui/canvases.py, mf4_analyzer/ui/inspector_sections.py, tests/ui/test_canvases_envelope.py, tests/ui/test_order_worker.py, tests/ui/test_order_smoke.py]
checks: [git status --short, git diff --name-only, git show HEAD, rg -n]
tests: [tests/ui/test_canvases_envelope.py, tests/ui/test_order_worker.py, tests/ui/test_order_smoke.py]
---

# Codex Order Canvas Wave Review

Trigger: Load for wave-scoped order-canvas performance reviews, append-only re-reviews, stale-generation tests, or strict boundary checks.

Past failure: Wave reviews over- or under-blocked when they treated every dirty file as a scope leak, trusted a stale-generation test that only carried a token, or rewrote a report section that the user asked to append narrowly.

Rule: Inspect scoped files directly, separate real boundary leaks from pre-existing or dependency-sync dirt, preserve append-only and one-line handoff contracts, and require stale-generation tests to prove the latest accepted render wins through production guard logic.

Verification: Start with `git status --short`, then use `git diff --name-only`, `git show HEAD:<file>`, blame/log, or reachability checks before calling a file out of scope; for stale-generation tests, assert exact accepted-generation lists after the production guard.
