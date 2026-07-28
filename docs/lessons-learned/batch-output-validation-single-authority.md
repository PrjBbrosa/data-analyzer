---
id: batch-output-validation-single-authority
status: active
owners: [codex]
keywords: [batch, output, validation, preflight, schema]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_validation.py, mf4_analyzer/ui/drawers/batch/sheet.py]
checks: [git diff --check]
tests: [tests/test_batch_validation.py, tests/test_batch_runner.py, tests/ui/test_batch_smoke.py]
---

# Batch Output Validation Has One Pure Authority

Trigger: Adding or changing batch output fields, formats, sizes, conflict policies, resume settings, or UI preflight behavior.

Past failure: Phase 3 image and operations fields were checked in a runner-local helper while the public preflight validator still understood only the legacy data/image flags and data format. The UI could accept a recipe that execution later rejected.

Rule: Define every output-schema validation rule in the GUI-free `validate_outputs` path and make runner, preview, and UI preflight consume that result. Do not add a second runner- or UI-local validator for the same fields.

Verification: Run `tests/test_batch_validation.py`, the output-validation cases in `tests/test_batch_runner.py`, and the BatchSheet preflight tests in `tests/ui/test_batch_smoke.py`; verify Mapping and duck-typed outputs produce the same field-level issues.
