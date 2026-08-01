---
id: batch-deferred-terminals-preserve-task-order
status: active
owners: [codex]
keywords: [batch, progress, events, grouping, ordering, callbacks]
paths: [mf4_analyzer/batch.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py]
---

# Batch Deferred Terminals Preserve Task Order

Trigger: Deferring batch task terminal events or progress callbacks until a
later group-level render, checksum, or publication decision is known.

Past failure: Grouped rendering correctly delayed `task_done`, but flushed each
deferred event as its render group completed. Channel-major group order differed
from source-major task order, producing terminal indices `2,4,1,3`; the progress
bar reached 100% and then moved backward.

Rule: Group processing may determine terminal state in group order, but public
task terminal events and legacy progress callbacks must be buffered until all
relevant groups settle, then emitted in stable original `task_index` order.
Cancellation may change the event kind, never its sequence position. Do not use
render-group iteration order as user-visible task progress order.

Verification: Run a successful multi-source, multi-channel `group_by=channel`
case and assert terminal indices and progress callback indices are exactly
`1..N`. Also run grouped checksum cancellation and assert the same order emits
only `task_cancelled`, with no earlier `task_done`; then run `git diff --check`.
