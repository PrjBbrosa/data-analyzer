---
id: codex-acquisition-validation-evidence-gates
status: active
owners: [codex]
keywords: [acquisition, preflight, regression, smoke, P0, runnable-commands]
paths:
  - docs/analyzer/acquisition/
  - mf4_analyzer/acquisition/
  - scripts/acquisition_smoke.py
  - scripts/preflight.py
  - scripts/regression.py
  - can_logger/p0/
checks:
  - rg -n '(^|[`[:space:]+])python scripts/|expected_signals' docs/analyzer/acquisition
tests:
  - PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
  - .venv/bin/python scripts/acquisition_smoke.py --skip-regression
---

# Acquisition Validation Evidence Gates

Trigger: Touching acquisition validation docs, preflight/regression tooling, smoke
runners, or P0 probe evidence.

Past failure: Plans and reports claimed runnable validation evidence while still
containing stale identifiers (`expected_signals`) and bare `python scripts/...`
commands that fail on this macOS checkout because no `python` shim exists.
P0 helper probes also needed hardware-free tests to prevent false-positive
evidence.

Rule: Treat acquisition validation evidence as executable contract text. Use the
repo-verified `.venv/bin/python ...` or explicit shebang form in docs, preserve
real API names, and add tests for any P0 or regression guard that could
otherwise report success without proving behavior.

Verification: Run the acquisition/P0/synthetic pytest set and smoke runner, then
grep acquisition docs for retired command forms or stale identifiers before
claiming the validation workflow is ready.
