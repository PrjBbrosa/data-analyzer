---
id: codex-frozen-import-dependency-contract
status: active
owners: [codex]
keywords: [windows, pyinstaller, frozen, lazy-import, scipy, h5py, mat, dependencies]
paths:
  - mf4_analyzer/io/runtime_dependencies.py
  - tools/windows_runtime_dependencies.py
  - tools/build_windows_folder.ps1
  - tools/build_windows_folder_lite.ps1
checks:
  - PYTHONPATH=. .venv/bin/python tools/windows_runtime_dependencies.py --verify --require-installed --requirements requirements.txt --build-script tools/build_windows_folder.ps1 --build-script tools/build_windows_folder_lite.ps1
tests:
  - tests/test_windows_runtime_dependencies.py
  - tests/test_windows_build_script.py
---

# Frozen Import Dependencies Need One Contract

Trigger: Adding, removing, or packaging a supported data-file importer whose
dependency is imported lazily inside ``mf4_analyzer/io``.

Past failure: `.mat` support used lazy `scipy.io.loadmat` and `h5py`, while
both Windows build flavors still excluded SciPy under an obsolete size-saving
rule. The source could read MAT files, but the frozen EXE could only show the
misleading “install scipy” message.

Rule: Declare every optional importer dependency in
`mf4_analyzer.io.runtime_dependencies`. Keep it in `requirements.txt`; let
both Windows builders obtain PyInstaller collection arguments from the shared
tool; never independently exclude a declared package. The pre-build contract
must scan every lazy import in `mf4_analyzer/io` and reject an undeclared one.

Verification: Run the dependency-contract CLI and the focused Windows
build-script/MAT tests. Then build and smoke-test the final onedir artifact on
Windows before claiming frozen-runtime confirmation.
