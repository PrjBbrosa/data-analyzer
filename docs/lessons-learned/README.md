# Lessons-Learned Protocol

This file is read by EVERY squad agent at the start of its reflection phase.
Agents: follow it literally. Humans: see the design spec at
`docs/superpowers/specs/2026-04-22-agent-squad-design.md` for the why.

## When to reflect

- **Top-level task completion** — triggered by `squad-orchestrator` after
  a full user request is resolved. Every role that participated reflects.
- **Rework** — immediately, the moment you modify something previously
  reported as done. Write the lesson with `cause: rework` before continuing.
- **Non-obvious insight** — optional, any time you realise a fact worth
  keeping. Use `cause: insight`. If it is obvious, do NOT write it.

## Three-section body (required)

```
## Context
One or two sentences: what situation triggered this lesson.

## Lesson
One or two sentences: the non-obvious insight. Not a log entry.

## How to apply
One or two sentences: the trigger condition and the action for next time.
```

## Frontmatter

```yaml
---
role: <one of: orchestrator | signal-processing | pyqt-ui | refactor>
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
cause: rework | top-level | insight
supersedes: []
---
```

`tags` lists **content tags only** (e.g., `fft`, `window`, `rework-risk`). Do
NOT duplicate `role` inside `tags` — role lives in its own field and in the
`## <role>` heading of `LESSONS.md`. Always write `supersedes: []` as an
explicit empty list, never as `supersedes:` (null).

## Merge-on-conflict write protocol (MANDATORY order)

1. `Read` this file (you're doing it).
2. `Grep` your role's directory by the new lesson's tags and keywords.
3. **If a same-topic lesson exists:** update the existing file.
   - Integrate Context/Lesson/How-to-apply into the existing body.
   - Bump the `updated` date.
   - Update the existing row in `../LESSONS.md` in place.
   - Do NOT create a new file.
   - Only add to `supersedes` if you are fully replacing the old content.
   - **If multiple candidates match:** pick the one with the latest `updated`
     date; if still tied, return `status: needs_info` to the orchestrator
     rather than guessing.
4. **If no same-topic lesson exists:** create a new file
   `<role>/YYYY-MM-DD-<slug>.md` and append a new row to `../LESSONS.md`.
5. Return `lessons_added` and `lessons_merged` arrays to the caller.
6. **If either write fails** (lesson file or index row), surface the error to
   the caller and do NOT retry silently — partial writes must be reported.

## Master index format

`LESSONS.md` has no frontmatter. Each row, ≤ 150 characters:

```
- [<slug>](<role>/YYYY-MM-DD-<slug>.md) [tag1][tag2] — one-line hook
```

Rows are grouped by role with a `## <role>` heading.

## Forbidden water content

- "I used Grep to find the file."
- "The test passed on the first try."
- Any narration of routine steps.
- Anything you could derive by reading the code or running `git log`.

If you cannot state a non-obvious insight, do NOT write a lesson.

## Reading protocol (at agent startup)

1. `Read docs/lessons-learned/LESSONS.md`.
2. Restrict to rows under your role's `## <role>` heading, then keyword-match
   the bracketed content tags (e.g., `[fft]`, `[window]`) against the
   incoming task. Role selection is by heading; relevance filtering is by
   content tag.
3. `Read` at most 5 full lesson bodies, highest keyword-hit count first.

## Out-of-scope for the reader

Ignore `.gitkeep` entries under role directories — they exist only to
preserve empty directories in git. They are not lessons.
