---
id: codex-build-logs-retain-native-stderr
status: active
owners: [codex]
keywords: [windows, powershell, pyinstaller, logging, stderr, frozen-smoke]
paths:
  - tools/build_windows_folder_lite.ps1
  - tools/verify_frozen_batch_render.py
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_windows_build_script.py tests/test_frozen_batch_render_smoke.py
tests:
  - tests/test_windows_build_script.py
  - tests/test_frozen_batch_render_smoke.py
---

# Build Logs Must Include Native And Frozen Child Diagnostics

Trigger: Adding build transcripts or investigating a frozen Windows failure.

Past failure: Lite builds retained only a summary JSON for a failed CJK render.
The verifier captured but discarded the executable's stdout/stderr and deleted
the rendered images. Merely adding Start-Transcript plus Out-Host can also
miss native stderr, where PyInstaller writes progress and diagnostics.

Rule: Use a unique evidence directory per attempt, begin logging before
validation/install, record native exit codes, and finalize logging on errors.
For PowerShell 5.1, handle redirected native stderr without treating ordinary
stderr output as a failed command. Preserve machine-readable stdout separately.
Opt-in persistent smoke diagnostics must retain child streams, JSON and PNGs
after both nonzero exits and timeouts; never reuse an earlier attempt's output.

Verification: Assert failure/timeout artifact survival and native command
stdout/stderr/exit behavior. The native PowerShell tests must run on Windows;
their skip on macOS is not Windows acceptance. The initial focused result was
43 passed, 5 Windows-only tests skipped; real Windows packaging remained unrun.
