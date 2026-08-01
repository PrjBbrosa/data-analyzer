---
id: batch-spool-mmap-close-before-cleanup
status: active
owners: [codex]
keywords: [batch, spool, numpy, mmap, windows, cleanup, cancellation]
paths: [mf4_analyzer/batch_series_spool.py, mf4_analyzer/batch.py]
checks: [git diff --check]
tests: [tests/test_batch_series_spool.py, tests/test_batch_runner.py]
---

# Close Batch Spool Mmaps Before Cleanup

Trigger: Changing batch series spooling, memory-mapped array loading, grouped
render cleanup, cancellation, or temporary-directory ownership.

Past failure: On Windows, arrays loaded with `np.load(..., mmap_mode="r")`
kept `.npy` handles open, so context-manager cleanup raised `WinError 32` while
removing the spool directory even though the same deletion pattern worked on
platforms that permit unlinking open files.

Rule: The spool must own every mapping it creates. Close each mapping before
removing files, then delete only the exact private temporary directory created
by that spool. Grouped success, exception, and cancellation paths must enter
and exit the spool context manager rather than deleting spool paths directly.

Verification: Run `tests/test_batch_series_spool.py`, including mapped-load
cleanup on success and exception, plus the grouped cancellation cleanup test in
`tests/test_batch_runner.py`; then run `git diff --check`.
