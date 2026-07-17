---
id: codex-release-version-labels-stay-synchronized
status: active
owners: [codex]
keywords: [release, version, packaging, Windows, build scripts, runbook, app_meta]
paths: [mf4_analyzer/app_meta.py, tools/build_windows_folder.ps1, tools/build_windows_folder_lite.ps1, docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md, tests/ui/test_project_session.py, tests/test_windows_build_script.py]
checks: [rg -n '7\\.6|v7\\.6' mf4_analyzer/app_meta.py tools/build_windows_folder.ps1 tools/build_windows_folder_lite.ps1 docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md tests/ui/test_project_session.py tests/test_windows_build_script.py]
tests: [tests/ui/test_project_session.py, tests/test_windows_build_script.py]
---

# Release Version Labels Stay Synchronized

Trigger: Bumping the TraceLab application release version, especially when its
runtime label and Windows build defaults change.

Past failure: The v7.7 update changed `APP_VERSION`, build-script parameters,
and runbook commands but initially left the lite build's default-output comment
at 7.6. This gave users a stale package path despite the actual default being
7.7.

Rule: Update every user-facing release label together: runtime metadata, both
Windows build parameter defaults and output comments, release runbook commands,
and the corresponding test expectations. Do not change data-format or schema
versions for an application release bump.

Verification: Run the app-meta version test and all Windows build-script tests,
then search the affected release files for the prior version string.
