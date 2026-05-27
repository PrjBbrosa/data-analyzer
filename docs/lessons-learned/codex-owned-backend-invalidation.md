---
id: codex-owned-backend-invalidation
status: active
owners: [codex]
keywords: [acquisition, backend, vector, pyqt, state-machine]
paths:
  - mf4_analyzer/acquisition_ui/main_window.py
  - mf4_analyzer/acquisition_capture/backends.py
checks:
  - tests/acquisition_ui/test_record_backend_swap.py
  - tests/test_vector_xcp_backend.py
tests:
  - .venv/Scripts/python.exe -m pytest tests/acquisition_ui/test_record_backend_swap.py tests/test_vector_xcp_backend.py
---

# Owned Backend Invalidation

Trigger: Touching Acquisition Cockpit backend swapping, transport/A2L settings,
or connection state cleanup.

Past failure: A Vector backend created internally by Cockpit was treated like a
caller-injected backend after the first successful swap. Later A2L or transport
changes could bypass precondition checks and reuse stale ECU configuration.

Rule: Distinguish external backend injection from Cockpit-owned backend swaps.
Invalidate and best-effort stop owned backends whenever transport, A2L, or
vehicle preconditions change, and clean up partially started Vector resources
when backend start fails.

Verification: Add tests that prove owned backends are rechecked after IF_DATA
clears, real connections require a selected measurement, and failed Vector/XCP
session start disconnects master/bus.
