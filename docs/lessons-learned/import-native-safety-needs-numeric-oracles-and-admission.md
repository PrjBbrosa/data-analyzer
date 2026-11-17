---
id: import-native-safety-needs-numeric-oracles-and-admission
status: active
owners: [codex]
keywords: [MF4, asammdf, import, native-crash, resource-budget, array-strides]
paths: [mf4_analyzer/io, mf4_analyzer/ui/main_window/import_coordinator.py]
checks: []
tests: [tests/test_mdf_reader_safety.py, tests/test_import_process.py, tests/test_import_resource_preflight.py, tests/test_import_transport.py]
---

# Import safety needs numeric oracles and allocation admission

Trigger: Changing binary readers, array expansion, native dependencies, import isolation or resource limits.

Past failure: MDF rectangular array strides both corrupted native memory and returned wrong values while still inside the record. A 112-byte ZFD could request a 16-GiB implicit time axis; slicing read_bytes after reading did not bound a sniff. Moving parsing to another thread would not isolate native corruption.

Rule: Check every coordinate against an independent oracle, including non-square, inverse and 3-D arrays. Verify the actual Python and C artifacts, not only a package version. Admit metadata-derived and cumulative allocations before materialization; disk size is not expanded size. Parse fully in the disposable child, transfer bounded typed results and diagnostics, and never reparse in the parent. Cancellation and failure must not publish a partial source or a success terminal. Block QProgressDialog cancellation signals during programmatic completion cleanup; close() can otherwise cancel the next queued request.

Verification: Run the named owner tests; check raw-file element and time-axis hashes for the available incident sample. Prove a failed child can be followed by a normal import, transport preserves warnings and lazy/shared identities, and giant declarations fail before allocation. Keep source/offscreen, real Cocoa and Windows frozen evidence separate.
