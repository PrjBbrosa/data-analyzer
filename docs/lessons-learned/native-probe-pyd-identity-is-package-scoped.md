---
id: native-probe-pyd-identity-is-package-scoped
status: active
owners: [codex]
keywords: [Windows, frozen, PYD, native, manifest, cyutility]
paths: [mf4_analyzer/extensions/native_probe.py]
checks: [Frozen media and MATLAB combination gate]
tests: [tests/test_extension_native_probe.py, tests/test_extension_compatibility.py]
---

# Native Probe PYD Identity Is Package Scoped

Trigger: Auditing loaded native modules against base and extension manifests.

Past failure: The frozen MATLAB probe rejected pandas' legitimate `_cyutility.pyd` because SciPy supplied a different module with the same basename. Static package identity already allowed scoped PYDs, but the dynamic audit incorrectly treated their basenames as global DLL identities.

Rule: Bind observed modules to exact canonical manifested paths and hashes, including matching base modules. Normalize ordinary and extended Win32 path spellings for comparison. Keep shared-DLL basename conflict checks before loading, reject foreign paths even with identical bytes, and preserve both same-basename PYDs in evidence.

Verification: Test legitimate base/component same-basename PYDs, modified base bytes, and identical-byte files outside the authorized trees. Then rebuild and run the real frozen combination gate.
