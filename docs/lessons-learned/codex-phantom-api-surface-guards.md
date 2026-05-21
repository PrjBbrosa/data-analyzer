---
id: codex-phantom-api-surface-guards
status: active
owners: [codex]
keywords: [phantom-api, MagicMock, vector, python-can, api-surface, acquisition]
paths:
  - can_logger/p0/
  - mf4_analyzer/acquisition_capture/vector_hw_probe.py
  - tests/test_vector_hw_probe.py
  - tests/test_vector_probe_stages.py
checks:
  - rg -n "MagicMock\\(\\)" tests/test_vector_hw_probe.py tests/test_vector_probe_stages.py
tests:
  - PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_vector_probe_stages.py tests/test_vector_hw_probe.py -q
---

# Phantom API Surface Guards

Trigger: Mocking external library surfaces for acquisition probes, especially Vector/python-can, `pyxcp`, or other optional native dependencies.

Past failure: Tests used unrestricted `MagicMock` module surfaces and patched entire probe bodies, so production code called nonexistent python-can APIs (`canlib.get_application_config`, `canlib.get_channel_count`) while CI stayed green.

Rule: Do not fake an external module with unrestricted `MagicMock` when the production code is proving API compatibility. Use structured fakes, `create_autospec()` from the real module when available, or explicit regression assertions that the production code calls the documented API.

Verification: Run the Vector probe tests and grep for unrestricted module-level `MagicMock()` fakes in those tests before claiming the probe surface is guarded.
