---
id: batch-spool-mmap-close-before-cleanup
status: active
owners: [codex]
keywords: [batch, spool, numpy, mmap, windows, cleanup, cancellation, qt, renderer, lifecycle]
paths: [mf4_analyzer/batch_series_spool.py, mf4_analyzer/batch.py, mf4_analyzer/batch_render_qt/*]
checks: [git diff --check]
tests: [tests/test_batch_series_spool.py, tests/test_batch_runner.py]
---

# Close Batch Spool Mmaps Before Cleanup

Trigger: Changing batch series spooling, memory-mapped array loading, grouped
render cleanup, cancellation, temporary-directory ownership, or a test that
captures a grouped render payload for later consumption.

Past failure: On Windows, arrays loaded with `np.load(..., mmap_mode="r")`
kept `.npy` handles open, so context-manager cleanup raised `WinError 32` while
removing the spool directory even though the same deletion pattern worked on
platforms that permit unlinking open files. A later producer-shaped Qt test
captured the grouped payload but built its scene only after `BatchRunner.run()`
returned; the spool mapping had already been closed, and NumPy/Qt consumption
ended in a native SIGSEGV rather than a Python exception.

Rule: The spool must own every mapping it creates. Close each mapping before
removing files, then delete only the exact private temporary directory created
by that spool. Grouped success, exception, and cancellation paths must enter
and exit the spool context manager rather than deleting spool paths directly.
Consumers must not retain spool-backed arrays beyond that context. A
producer-shaped renderer test must render inside the runner's image-writer
callback while the spool is alive, or explicitly copy the payload to owned
memory before the callback returns.

Verification: Run `tests/test_batch_series_spool.py`, including mapped-load
cleanup on success and exception, plus grouped cancellation cleanup in
`tests/test_batch_runner.py`. Also run the source/channel grouped producer
tests that build the real Qt scene inside `_write_image`, then run
`git diff --check`.
