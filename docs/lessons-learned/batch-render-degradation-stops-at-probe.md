---
id: batch-render-degradation-stops-at-probe
status: active
owners: [codex]
keywords: [batch, render, degradation, atomic-write, checksum, cancellation, manifest, resume]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_manifest.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py, tests/test_batch_manifest.py]
---

# Batch Render Degradation Stops At The Probe

Trigger: Changing batch image/PDF backend imports, effective output selection,
coordinated artifact writers, checksum collection, cancellation, manifests, or
resume behavior.

Past failure: A missing renderer import was discovered after reserving the full
data-plus-image set, so the data artifact was lost with the image. Broadly
catching renderer failures would also weaken the required all-or-nothing
rollback for writer-time failures. Separately, cancellation during grouped
artifact checksumming could leave an incomplete checksum while the item, group,
run, and manifest were still published as `done`.

Rule: Probe a requested renderer before output reservation. Only an
`ImportError` or `ModuleNotFoundError` from that probe may reduce a
data-plus-image request to data-only. Keep every later render/write exception
inside the single `atomic_write_set` transaction, and record requested outputs,
effective outputs, and the degraded reason so resume cannot treat the item as
complete. An artifact or group is not done until every required checksum is
complete. If cancellation interrupts checksum collection, retain the artifact
as incomplete and propagate `cancelled` through the item, group, run, and
manifest.

Verification: Run the backend-unavailable, writer-import-error rollback,
degraded-resume, and grouped checksum-cancellation tests in
`tests/test_batch_runner.py` and `tests/test_batch_manifest.py`; assert no
cancelled checksum path publishes `done`, then run `git diff --check`.
