---
id: diagnostic-throttle-pending-count-lifecycle
status: active
owners: [codex]
keywords: [diagnostics, throttle, suppressed, atexit, eviction, lock]
paths: [mf4_analyzer/diagnostics.py]
checks: [logging outside throttle lock, bounded state accounting]
tests: [tests/test_diagnostics.py]
---

# Diagnostic throttles must account for every pending count

Trigger: Changing a bounded diagnostic throttle, its rollover, eviction, or shutdown behavior.

Past failure: The throttle emitted a suppressed-count summary only when the
same key fired after its window expired. A burst that went quiet stayed
unreported, and oldest-key eviction could discard its pending count entirely.

Rule: Collect pending counts for expired windows, key eviction, and orderly
shutdown. Register the shutdown flush once, emit each count once, distinguish
early flushes from full-window summaries, and never call a logger while holding
the throttle state lock.

Verification: Run `.venv/bin/python -m pytest tests/test_diagnostics.py -q`;
cover cross-key sweep, manual and subprocess-exit flush, oldest-key eviction,
registration idempotence, and a lock-state probe around every emitted record.
