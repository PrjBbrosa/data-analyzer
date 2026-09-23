---
id: windows-build-validation-covers-every-profile
status: active
owners: [codex]
keywords: [windows, packaging, modular, dependency, profile, contract]
paths: [mf4_analyzer/io/runtime_dependencies.py, tools/build_windows_folder_lite_modular.ps1]
checks: [Windows packaging contract CLI for Full Lite and Modular, full Modular build with post-checks]
tests: [tests/test_windows_runtime_dependencies.py]
---

# Windows Build Validation Must Cover Every Delivery Profile

Trigger: Adding or changing a Windows build flavor, dependency profile, or parameterized build command.

Past failure: The Modular builder passed `$Flavor` and `$DependencyProfile`, but the validator recognized only literal Full/Lite commands and the current-builder test omitted Modular. One-click orchestration tests passed while the real build stopped at dependency preflight.

Rule: Include every shipped builder in the executable contract test. Resolve supported parameter defaults explicitly and reject unknown settings. Check required dependencies against the actual delivery profile: Modular can externalize its declared extensions, but it must still reject removal of base dependencies; bundled builds must retain their importer closure. A successful installer build is not evidence that the Modular pipeline finishes.

Verification: Run tests/test_windows_runtime_dependencies.py, including negative base-dependency exclusions and invalid settings, then the actual Modular builder through manifest emission and all frozen post-checks. Keep skipped or blocked native checks distinct from acceptance.
