---
id: zsh-path-variable-clobbers-command-search
status: active
owners: [codex]
keywords: [zsh, path, PATH, shell, command-not-found]
paths: [scripts]
checks: ["rg -n --glob '*.sh' --glob '*.zsh' '\\b(for\\s+path\\s+in|path=)' scripts"]
tests: []
---

# Zsh Path Variables Can Clobber Command Search

Trigger: Writing an inline zsh loop or helper that assigns a shell variable
named `path`.

Past failure: zsh exposes `path` as a special array tied to `PATH`. Using
`for path in ...` replaced the command search path, so later commands in the
same shell reported `command not found` even though the tools were installed.

Rule: Use task-specific names such as `file_path`, `target_path`, or
`artifact_path` for shell variables. Never use zsh's `path` as an ordinary
scalar or loop variable.

Verification: Review multi-command zsh snippets for assignments to `path` and
confirm commands after each loop still resolve normally.
