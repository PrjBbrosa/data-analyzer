---
id: windows-builders-probe-python-architecture
status: active
owners: [codex]
keywords: [windows, arm64, x64, python, installer, one-click, venv]
paths: [tools/build_windows_extension_installer.ps1, tools/build_windows_folder_lite_modular.ps1]
checks: [Windows real ARM64 and x64 interpreter probes, installer frozen self-test]
tests: [tests/test_extension_installer_python.py]
---

# Windows Builders Must Probe Python Build Architecture

Trigger: Adding automatic Python selection or chaining Windows packaging scripts.

Past failure: One-click packaging used PATH's ARM64 Python despite a working repository x64 toolchain. Stubbed orchestration probes passed. The architecture guard also used platform.machine(), which reports ARM64 for the emulated x64 interpreter on this machine.

Rule: Probe sysconfig.get_platform() and required native modules before creating a build environment. Prefer the existing compatible repository toolchain. Validate the replacement first, preserve an incompatible environment, then recreate only the task-owned environment. A newly created environment needs dependencies even when SkipInstall was requested. Keep native command arguments, stderr and exit codes visible. Pass filesystem ProviderPath values to native programs when resolving UNC paths in PowerShell.

Verification: tests/test_extension_installer_python.py covers real ARM64-to-x64 repair, healthy x64 reuse, and rejecting an explicit incompatible interpreter without moving the existing environment. Run with TRACELAB_TEST_X64_PYTHON and TRACELAB_TEST_ARM64_PYTHON on Windows; source checks or mocked packaging steps do not prove interpreter compatibility. Run the actual installer build and frozen self-test before claiming build acceptance.
