---
id: extension-production-boundaries-need-real-collaborators
status: active
owners: [codex]
keywords: [extensions, installer, integration, native-probe, test-doubles, completion]
paths: [mf4_analyzer/extensions/*, tools/extension_manager/*, tools/build_windows_extension_installer.ps1]
checks: [git diff --check]
tests: [tests/test_extension_repository.py, tests/test_extension_native_probe.py, tests/test_extension_transaction.py]
---

# Extension Production Boundaries Need Real Collaborators

Trigger: Implementing or reviewing extension installation, native probes, and completion claims.

Past failure: Focused tests passed while the default bootstrap referenced an undefined constant, the engine called a fake repository signature, and marker-file probes accepted unusable native packages. A real PyAV/SciPy probe additionally exposed false native-collision rules hidden by tiny fixtures.

Rule: Keep pure protocol/state-machine doubles explicit. Add a signed local repository test across the actual selection/download/transaction interfaces, and a fresh target-interpreter probe that verifies origins and decodes fixed files. A production default must not use a test stand-in. Distinguish source-child decoding, Windows frozen acceptance, and actual frontend behavior. Guard shared transaction writes with the exclusive lock before creating a recovery journal.

Verification: Run the three owner files above plus importer/packaging boundaries. Frozen readiness requires the actual Windows manager/base/component artifacts; an unrun or blocked native gate remains unverified even if source tests pass.
