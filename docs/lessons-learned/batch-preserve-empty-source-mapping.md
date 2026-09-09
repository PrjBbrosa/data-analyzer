---
id: batch-preserve-empty-source-mapping
status: active
owners: [codex]
keywords: [batch, loaded-files, mapping, identity, empty]
paths: [mf4_analyzer/ui/drawers/batch/]
checks: []
tests: [tests/ui/test_batch_recent_intake.py]
---

# Preserve Initially Empty Shared Source Mappings

Trigger: A dialog retains a source mapping owned by the main window.

Past failure: Both BatchSheet and FileListWidget used `files or {}`. Opening
Batch before loading any file detached both consumers from the live mapping,
so the loaded-file menu never saw files subsequently added in the main window.

Rule: Use `files if files is not None else {}` when identity must survive an
empty collection. Verify every forwarding layer and keep menu reads live.

Verification: `tests/ui/test_batch_recent_intake.py` opens Batch with an empty
mapping, inserts a source afterwards, selects it from the menu, then clears
the owner mapping and verifies the next menu reflects the removal.
