---
id: codex-runtime-verification-entrypoints
status: active
owners: [codex]
keywords: [pytest, python, venv, tmpdir, mplconfigdir, qt_qpa_platform, offscreen, pyqt, matplotlib, validation]
paths: [tests/*, mf4_analyzer/*]
checks: [.venv/bin/python -m pytest, PYTHONPATH=. .venv/bin/pytest, TMPDIR=/tmp, MPLCONFIGDIR=/tmp]
tests: []
---

# Codex Runtime Verification Entrypoints

Trigger: Load before running tests, Qt smoke checks, Matplotlib-backed checks, or when a prompt includes expected pass counts.

Past failure: Verification stalled or became misleading when bare `python`/`pytest` was unavailable, temporary/cache directories were unwritable, or the final answer repeated stale expected counts instead of live command output.

Rule: Prefer the repo venv for local validation, use writable temp/cache locations for Matplotlib or Qt tests, and quote the live command result as authoritative. If `.venv` cannot satisfy dependencies, try the bundled Codex runtime before declaring tests impossible.

Verification: Use commands like `PYTHONPATH=. .venv/bin/python -m pytest ...` or `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`; for Matplotlib failures add `MPLCONFIGDIR=/tmp` or another writable cache dir.
