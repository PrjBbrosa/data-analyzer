---
id: codex-powershell-json-native-argv
status: active
owners: [codex]
keywords: [powershell, windows, json, pyinstaller, argv]
paths: [tools/build_windows_folder_lite.ps1, tools/build_windows_folder_lite_modular.ps1, tests/test_windows_build_script.py]
checks: [Windows PowerShell 5.1 native argv regression]
tests: [tests/test_windows_build_script.py, tests/test_windows_lite_modular_build_script.py]
---

# Preserve JSON Argument Boundaries Across Typed PowerShell Helpers

Trigger: Passing JSON-generated command arguments through a PowerShell helper.

Past failure: Windows PowerShell 5.1 kept the ConvertFrom-Json array inside
an outer @() array. The Lite logger's [string[]] parameter joined all 40
dependency tokens into one argument, causing PyInstaller to exit 2. Direct
native invocation in the Full build still worked, so the helper boundary mattered.

Rule: Convert the JSON result directly to a flat string[] before appending
native arguments. Do not split the joined string on spaces; paths may contain
spaces. Test argv received by a native child through the actual typed helper,
not only JSON validity or script text.

Verification: Run test_windows_build_dependency_json_preserves_native_argument_boundaries
on Windows PowerShell 5.1. It compares every argument and preserves a spaced
entry path for both Lite and Full. Before the fix Lite failed and Full passed.

The Modular extension emitter repeated this failure with site.getsitepackages():
Windows returned both the venv root and Lib/site-packages, and PS 5.1 joined
them into one invalid path. For one native-package directory, emit a scalar
JSON string from sysconfig.get_path("platlib") and decode that string directly.
Run test_extension_emitter_receives_one_real_site_packages_directory on Windows.
