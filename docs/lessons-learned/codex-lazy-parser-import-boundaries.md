---
id: codex-lazy-parser-import-boundaries
status: active
owners: [codex]
keywords: [pytest, import, pya2l, pya2ldb, native, acquisition, a2l]
paths: [can_logger/p0/a2l_probe.py, tests/test_p0_a2l_probe_import_safety.py]
checks: [.venv/Scripts/python.exe -m pytest tests/test_p0_a2l_probe_import_safety.py tests/test_p0_a2l_probe.py -q, .venv/Scripts/python.exe -m pytest --collect-only -q]
tests: [tests/test_p0_a2l_probe_import_safety.py]
---

# Lazy Parser Import Boundaries

Trigger: Touching A2L parsing, acquisition measurement summaries, or modules
that UI/search tests import for data classes only.

Past failure: Installing `pya2ldb` fixed the missing `pya2l` import but pytest
collection then crashed with a Windows access violation while importing
`pya2l.model` from `can_logger/p0/a2l_probe.py` at module load.

Rule: Keep native/heavy parser dependencies such as `pya2l` lazy. Plain imports
of DTOs like `MeasurementSummary` and `A2LSummary` must not import A2L parser
packages; only the real parser entrypoint may load them.

Verification: Run
`.venv/Scripts/python.exe -m pytest tests/test_p0_a2l_probe_import_safety.py tests/test_p0_a2l_probe.py -q`
and `.venv/Scripts/python.exe -m pytest --collect-only -q`.
