---
id: core-owner-tests-use-in-repo-synthetic-fixtures
status: active
owners: [codex]
keywords: [testdoc, gitignore, fixtures, pytest, wwt, samples, owner-tests]
paths: [tests/**, tests/_helpers/**, .gitignore]
checks: [rg -n testdoc/WWT tests, pytest.skip not pytest.fail]
tests: [tests/test_wwt_document.py, tests/ui/test_wwt_import_flow.py]
---

# Core owner tests must use in-repo synthetic fixtures

Trigger: Adding or reviewing pytest owner tests that open `testdoc/` paths, customer WWT/MF4 files, or other gitignored local samples as required fixtures.

Past failure: The 2026-08-28 WWT native-layout plan treated `testdoc/WWT/*.wwt` as repository fixtures (“the repository contains this file”). New owner tests called `pytest.fail` when those gitignored customer samples were absent. A clean checkout had 15 failed / 12 skipped WWT tests, so the focused green was not portable.

Rule: Core owner tests must use in-repo synthetic fixtures. Optional customer samples may skip, never `pytest.fail`.

Verification: `rg -n 'testdoc/' tests` should only hit skip-guarded optional smoke. Missing `testdoc/` must not fail WWT owner tests (`tests/_helpers/wwt_factory.py` profiles, not customer bytes).
