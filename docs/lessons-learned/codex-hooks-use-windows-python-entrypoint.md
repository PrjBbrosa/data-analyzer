---
id: codex-hooks-use-windows-python-entrypoint
status: active
owners: [codex]
keywords: [codex, hooks, windows, lessons]
paths:
  - .codex/hooks.json
  - .codex/hooks.audit.json
  - scripts/lessons/select.py
  - scripts/lessons/check.py
checks:
  - .\.venv\Scripts\python.exe scripts\lessons\check.py --doctor --verbose
tests: []
---

# Codex Hooks Use Windows Python Entrypoint

Trigger: Editing Codex hook configuration or diagnosing repeated hook failures
in a Windows native Codex session.

Past failure: Repo hook commands used `/usr/bin/python3` plus POSIX shell
substitution, which is valid on Linux/macOS but repeatedly fails in Windows
native Codex.

Rule: For this Windows-native repo setup, keep `.codex/hooks*.json` commands on
the project venv entrypoint (`.\.venv\Scripts\python.exe ...`) and avoid POSIX
shell-only path expansion in hook commands.

Verification: Run `.\.venv\Scripts\python.exe scripts\lessons\check.py
--doctor --verbose` and inspect `.codex/hooks.json` / `.codex/hooks.audit.json`
for Windows-native Python commands.
