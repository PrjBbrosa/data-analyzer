---
id: codex-windows-vendoring-network-retry
status: active
owners: [codex]
keywords: [windows, pyinstaller, pip, pypi, vendoring, retry]
paths:
  - tools/build_windows_folder.ps1
  - requirements-windows-acquisition.txt
checks:
  - $env:PIP_DEFAULT_TIMEOUT='60'; $env:PIP_RETRIES='10'; tools\build_windows_folder.bat -Console -SkipInstall
tests:
  - tests/test_windows_build_script.py
  - tests/test_acquisition_runtime_smoke.py
---

# Windows Vendoring Network Failures Keep The Gate Red

Trigger: A Windows folder build fails while pip vendors the pinned Vector/XCP
closure after the source/build dependency contract has already passed.

Past failure: PyPI connections reset and timed out while resolving Pygments,
so pip reported `ResolutionImpossible` and the build stopped before
PyInstaller. The installed pins were valid; a bounded retry used the warmed
cache and completed both the frozen build and packaged runtime smoke.

Rule: Do not loosen pins, bypass the vendoring failure, or accept stale smoke
JSON. Preserve the failed gate, verify the error is transport/download related,
then retry with bounded `PIP_DEFAULT_TIMEOUT` and `PIP_RETRIES`; use
`-SkipInstall` only when the build venv preparation already succeeded. Claim
success only from a fresh EXE and smoke JSON whose command paths name that EXE.

Verification: Run the retry command above and require exit code zero. Confirm
the produced `packaged-runtime-smoke.json` has `ok: true`, `frozen: true`, a
new timestamp, and probe command paths under the freshly built application.
