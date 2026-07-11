---
id: codex-pinned-protocol-adapters-own-vendor-abi
status: active
owners: [codex]
keywords: [pyxcp, seed-key, dll, abi, external-api, vector, xcp]
paths:
  - mf4_analyzer/acquisition_capture/xcp_auth.py
  - mf4_analyzer/acquisition_capture/pyxcp_runtime.py
  - tests/test_xcp_auth.py
  - tests/test_pyxcp_029_contract.py
checks:
  - rg -n "ASAP1A_XCP_ComputeKeyFromSeed|_compute_key_from_seed|_read_seed" mf4_analyzer tests
tests:
  - PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_xcp_auth.py tests/test_pyxcp_029_contract.py -q
---

# Pinned Protocol Adapters Own Vendor ABI

Trigger: Implementing or reviewing Seed&Key, native DLL calls, multi-part XCP
commands, or another vendor ABI already wrapped by the pinned protocol library.

Past failure: The Vector/XCP readiness path copied a historical four-argument
Seed&Key DLL signature into custom ctypes code. Hardware-free mocks stayed
green, while pyxcp 0.29.10 actually owns a different privilege-aware DLL
adapter plus multi-part seed/key and bitness-loader behavior.

Rule: Delegate vendor ABI and multi-part protocol handling to the exact pinned
library's documented adapter when it exists. Pin the real adapter method and
signature in a Windows package contract; do not maintain a guessed ctypes
fallback or permissive fake.

Verification: Assert the real pyxcp package exposes
`Master.cond_unlock(self, resources)`, use `cond_unlock("DAQ")` between explicit
GET_STATUS checks, grep out custom Seed&Key ABI helpers, and run the focused
auth plus Windows package-contract tests.
