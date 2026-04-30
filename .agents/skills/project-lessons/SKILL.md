---
name: project-lessons
description: Use for Codex project work involving bug fixes, reviews, repeated errors, risky refactors, workflow failures, or any request mentioning lessons learned, postmortem, regression prevention, or recurring mistakes.
---

# Project Lessons

Use the repository's lessons-learned loop to prevent repeated mistakes without
loading unnecessary context.

## Workflow

1. Inspect `docs/lessons-learned/INDEX.md` or use hook-selected lessons.
2. Read only the relevant lesson files for the current task.
3. During implementation or review, mark a lesson requirement when the issue is
   durable and likely to recur:

   ```bash
   /usr/bin/python3 scripts/lessons/check.py --require "short reason"
   ```

4. If a lesson is required, create `.state/lesson-candidate.md` from
   `docs/lessons-learned/_template.md`, fill it in, and promote it:

   ```bash
   /usr/bin/python3 scripts/lessons/promote.py
   ```

5. Run relevant checks/tests from the lesson before finalizing.

## Rules

- Do not bulk-load all lesson files unless the user asks for a lessons audit.
- Prefer executable checks over prose-only rules.
- Keep each lesson short: trigger, past failure, rule, verification.
- If no durable lesson is needed, do not create one.
- If a lesson requirement was marked but later rejected, explain why and run:

  ```bash
  /usr/bin/python3 scripts/lessons/check.py --clear
  ```
