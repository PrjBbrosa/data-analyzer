# Repository Instructions

This file is for Codex only. Claude Code instructions live in `CLAUDE.md`
and `.claude/`; do not edit those files unless the user explicitly asks.

## Codex Scope

- Prefer the repository's existing Python, PyQt, test, and documentation
  patterns over new workflow abstractions.
- Keep Codex-specific local state under `.state/`.
- Do not mirror Claude Code squad routing into Codex unless a Codex-native
  adapter is explicitly implemented.

<!-- BEGIN CODEX LESSONS SYSTEM -->

## Codex Lessons Learned System

This repository uses a checked-in lessons-learned loop. The goal is to prevent
repeated mistakes by loading only relevant lessons and turning durable failures
into tests, checks, or explicit rules.

### Start Of Task

- Check `docs/lessons-learned/INDEX.md` before risky edits, bug fixes, reviews,
  or work touching known fragile areas.
- Prefer `scripts/lessons/select.py` or the Codex hook-selected lesson list over
  manually reading every lesson file.
- Load only the selected lessons needed for the current task.

### During Work

- If a bug pattern is repeated, a workflow failure is likely to recur, or a new
  project convention is discovered, mark a lesson requirement:

  ```bash
  /usr/bin/python3 scripts/lessons/check.py --require "short reason"
  ```

- If a fix needs durable protection, add or update a test/check first whenever
  feasible.
- Keep lessons short and operational: trigger, past failure, rule,
  verification.

### Completion Gate

Before the final answer, verify whether a lesson is required. A lesson is
required when:

- the same class of mistake occurred again
- a regression test was added for a previously missed bug
- review found a generalizable future-agent risk
- a tool or workflow failure is likely to recur
- project behavior or conventions changed

If required, create `.state/lesson-candidate.md` from
`docs/lessons-learned/_template.md`, fill it in, then promote it with:

```bash
/usr/bin/python3 scripts/lessons/promote.py
```

Run `scripts/lessons/check.py --clear` only after the lesson has been promoted
or after recording why no durable lesson is needed.

<!-- END CODEX LESSONS SYSTEM -->
