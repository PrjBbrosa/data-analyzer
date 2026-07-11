---
id: codex-frozen-probes-do-not-require-console-streams
status: active
owners: [codex]
keywords: [windows, pyinstaller, windowed, stdout, stderr, acquisition, smoke]
paths:
  - MF4 Data Analyzer V1.py
  - mf4_analyzer/acquisition_capture/runtime_smoke.py
  - can_logger/p0/_a2l_subprocess.py
  - docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md
checks:
  - rg -n "print\\(" mf4_analyzer/acquisition_capture/runtime_smoke.py
tests:
  - PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_acquisition_runtime_smoke.py -q
---

# Frozen Probes Do Not Require Console Streams

Trigger: Adding a hidden child command, import probe, parser subprocess, or
runtime smoke to a PyInstaller Windows executable that may use `--windowed`.

Past failure: The acquisition import probes correctly loaded pyxcp and pya2l,
then used `print()`. A windowed PyInstaller process may expose `sys.stdout` and
`sys.stderr` as `None`, so console reporting could turn a successful probe or
completed JSON smoke into a false nonzero result.

Rule: Carry probe truth through exit codes, explicit files, or binary pipes.
Treat text console output as best-effort and safe when either standard stream
is absent; do not make a windowed runtime gate depend on `print()`. W2 must run
the production-default windowed artifact. A console diagnostic build can help
explain a failure but cannot substitute for production packaged evidence.

Verification: Simulate `sys.stdout = sys.stderr = None`, require hidden import
children to retain the correct exit code, assert the bench runbook does not
build W2 with `-Console`, run the runtime-smoke/build-script tests, and retain a
real Windows packaged W2 run before claiming the frozen gate passes.
