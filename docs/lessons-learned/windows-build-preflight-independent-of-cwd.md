---
id: windows-build-preflight-independent-of-cwd
status: active
owners: [codex]
keywords: [windows, packaging, powershell, cwd, preflight]
paths: [tools/build_windows_folder_lite.ps1]
checks: [.venv/Scripts/python.exe -m pytest tests/test_import_packaging.py -q]
tests: [tests/test_import_packaging.py]
---

# Windows Build Preflight Must Resolve Repository Imports

Trigger: Adding Python import probes to Windows BAT/PowerShell builders.

Past failure: After fixing patch CRLF hashing, Lite packaging still failed before
PyInstaller because its Python -c probe inherited tools/ as the current directory
and could not import mf4_analyzer. Source-text packaging tests missed this.

Rule: Resolve the repository from the script location and pass it as a separate
native argument to Python before project imports. Do not assume the BAT caller
starts at the repository root or supplies PYTHONPATH.

Verification: Execute the actual PowerShell invocation from another directory,
with a space-containing repository path and without PYTHONPATH. Run
tests/test_import_packaging.py and a real BAT build from tools/; distinguish
script-test success from fresh frozen executable acceptance.
