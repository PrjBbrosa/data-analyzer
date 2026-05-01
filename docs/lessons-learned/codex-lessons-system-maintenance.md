---
id: codex-lessons-system-maintenance
status: active
owners: [codex]
keywords: [lesson, lessons, lessons-learned, hook, hooks, master, template, promote, select.py, check.py, doctor]
paths: [AGENTS.md, .codex/*, .agents/skills/project-lessons/*, docs/lessons-learned/*, scripts/lessons/*]
checks: [/usr/bin/python3 scripts/lessons/check.py --doctor --verbose, /usr/bin/python3 scripts/lessons/select.py --prompt "lessons hook maintenance" --max 5]
tests: []
---

# Codex Lessons System Maintenance

Trigger: Load for Codex lessons-learned system changes, hook tuning, master-kit synchronization, project-lessons skill updates, or edits to `scripts/lessons/*`.

Past failure: Lessons-system questions had no selectable Codex meta lesson, default `PostToolUse` produced noisy event logs, and the reusable master kit could drift behind project-local script fixes.

Rule: Keep the default Codex lessons loop quiet with `UserPromptSubmit` plus `Stop`; keep `PostToolUse` in an explicit audit config; run the doctor check after framework changes; and sync reusable script or template fixes back to the master kit when they are not project-specific.

Verification: Run `/usr/bin/python3 scripts/lessons/check.py --doctor --verbose`, validate hook JSON, run a selector prompt that mentions lessons maintenance, and compare changed project scripts against the master kit before finalizing.
