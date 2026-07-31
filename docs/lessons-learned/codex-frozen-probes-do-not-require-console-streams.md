---
id: codex-frozen-probes-do-not-require-console-streams
status: active
owners: [codex]
keywords: [windows, pyinstaller, windowed, stdout, stderr, acquisition, smoke]
paths:
  - MF4 Data Analyzer V1.py
  - mf4_analyzer/frozen_batch_acceptance.py
  - mf4_analyzer/acquisition_capture/runtime_smoke.py
  - can_logger/p0/_a2l_subprocess.py
  - docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md
checks:
  - rg -n "print\\(" mf4_analyzer/acquisition_capture/runtime_smoke.py
tests:
  - PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_acquisition_runtime_smoke.py -q
  - PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_frozen_batch_acceptance.py -q
---

# Frozen Probes Do Not Require Console Streams

Trigger: Adding a hidden child command, import probe, parser subprocess, or
runtime smoke to a PyInstaller Windows executable that may use `--windowed`.

Past failure: The acquisition import probes correctly loaded pyxcp and pya2l,
then used `print()`. A windowed PyInstaller process may expose `sys.stdout` and
`sys.stderr` as `None`, so console reporting could turn a successful probe or
completed JSON smoke into a false nonzero result. Frozen acceptance later
could overwrite a source, pollute an exact output set, and mislabel source
execution as frozen; a follow-up also found that two hidden modes competed by
source order, abbreviated hidden flags routed unexpectedly, and the result JSON
could overwrite the authoritative smoke JSON or running executable.

Rule: Carry probe truth through exit codes, explicit files, or binary pipes.
Treat text console output as best-effort and safe when either standard stream
is absent; do not make a windowed runtime gate depend on `print()`. Put every
hidden execution mode in one non-abbreviating mutually-exclusive parser group.
Resolve evidence paths before work and reject a result target that aliases an
input, the artifact directory, the authoritative smoke JSON, or
`sys.executable`. Evidence claiming frozen success must require `sys.frozen`,
record canonical `sys.executable` and its SHA-256, and match both against the
same-package frozen smoke JSON. W2 must run the production-default windowed
artifact; a console diagnostic build cannot substitute for it.

Verification: Cover every pair of hidden modes and an abbreviated hidden flag;
require exit `2`, no route call, and no output for conflicts. Simulate
`sys.stdout = sys.stderr = None`, require hidden import children to retain the
correct exit code, assert unsafe result aliases leave source/smoke/EXE/output
bytes unchanged and never enter BatchRunner, reject source-mode success and
smoke SHA mismatches, run runtime-smoke/build-script tests, and retain a real
Windows packaged W2 run before claiming the frozen gate passes.
