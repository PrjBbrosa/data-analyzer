---
id: codex-windows-sidecar-fsync-writable-handle
status: active
owners: [codex]
keywords: [ultraview, sidecar, fsync, windows, preview, persistence]
paths: [mf4_analyzer/ui/chart_stack/ultraview/preview_sidecar.py, tests/ui/test_ultraview_preview_sidecar.py]
checks: [.venv/Scripts/python.exe -m pytest tests/ui/test_ultraview_preview_sidecar.py -q]
tests: [tests/ui/test_ultraview_preview_sidecar.py]
---

# Windows Sidecar Fsync Needs A Writable Handle

Trigger: Changing UltraView sidecar archive persistence or its durable-write
sequence on Windows.

Past failure: The ZIP archive was completed, then reopened as ``rb`` for
``os.fsync``. Windows rejected the read-only handle with ``[Errno 9] Bad file
descriptor``, so every project saved its View layout but no preview archive.

Rule: Before atomically replacing a sidecar archive, sync it through a
non-truncating writable handle (or the original writable descriptor). Preserve
the completed-archive, sync, then replace ordering.

Verification: Run
``.venv/Scripts/python.exe -m pytest tests/ui/test_ultraview_preview_sidecar.py -q``
on Windows and confirm the archive round trip succeeds.
