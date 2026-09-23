---
id: windows-native-probe-exit-file-contention
status: active
owners: [codex]
keywords: [Windows, ARM, XtaCache, native, PermissionError, probe]
paths: [tools/extension_manager/transaction.py, tools/verify_extension_delivery.py]
checks: [Windows native installation and frozen combination gate]
tests: [tests/test_extension_transaction.py, tests/test_windows_lite_modular_build_script.py]
---

# Native Probe Exit Can Leave Brief Windows File Contention

Trigger: Moving or deleting a verified native package immediately after a probe exits.

Past failure: On Windows ARM, Restart Manager identified XtaCache holding the x64 probe's PYD after the child was reaped. Publishing the staging directory failed with WinError 5; a measured retry succeeded after about 0.6 seconds. Cleanup errors then masked the original failure.

Rule: Identify the owner before adding retries. For observed Windows access/sharing contention, use a bounded retry under the existing transaction lease, retain cancellation, log the wait once, and propagate permanent or unrelated errors. Do not kill the system cache service or weaken verification. Cleanup must preserve the original diagnostic if verification already failed.

Verification: Test recovery, retry exhaustion without committing active state, unrelated-error propagation, and cleanup preserving the primary failure. Confirm the real Windows install and frozen native reads.
