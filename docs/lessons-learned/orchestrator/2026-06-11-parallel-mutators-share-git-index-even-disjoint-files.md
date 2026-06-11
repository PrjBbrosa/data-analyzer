# Parallel file-mutating subagents share one git index — even on disjoint files

**Tags:** [decomposition][parallel-serialization][git-index][worktree]

## Context

During plan-2 execution two subagents ran in parallel on the same branch:
V5b edited `inspector_sections.py` + `test_inspector.py`; V6 created
`analysis_section_page.py` + its test. **Disjoint file sets** — yet they
still collided. V5b staged its two files; while it was still working, V6
ran `git add` / `git commit`, and the shared index meant V6's first commit
attempt swept in V5b's already-staged inspector files. V6 had to
`git reset --soft` + `git restore --staged` V5b's files back to the working
tree (content preserved) and re-commit with an explicit pathspec. V5b in
turn observed HEAD move underneath it mid-session and committed with
`git commit -- <its two files>` to stay clean.

Both landed correctly **only because every brief mandates explicit
pathspec `git add` (never `git add -A`)** and both agents defensively
re-scoped. But it was luck-adjacent: a single `git add -A` in either would
have cross-contaminated the other's commit.

## The insight

The existing lesson `parallel-same-file-drawer-task-collision` covers
*same-file* parallel edits. This extends it: **the git index/HEAD is shared
across the whole working tree, so ANY two parallel file-mutating subagents
contend — disjoint files do not make them safe.** One agent's staging +
commit can sweep another's in-flight staged changes, and HEAD moving
under a working agent invalidates its line-number anchors.

## How to apply

- **Read-only agents (reviewers, explorers) parallelize freely** — they
  never touch the index. Keep fanning those out.
- **File-mutating agents on the same branch: serialize them by default.**
  Run one implementer at a time; only its review (read-only) overlaps the
  next implementer.
- If parallel mutation is genuinely needed, give each agent
  `isolation: "worktree"` so it commits in its own worktree — no shared
  index. (Costs ~200-500ms + disk per agent; worth it only for true
  parallelism.)
- Keep the standing rule: **explicit pathspec `git add <files>` only, never
  `git add -A`** — it's the last line of defence when overlap happens anyway.
- Big integration tasks (e.g. V7 touching `chart_stack.py` +
  `main_window.py`) MUST run solo — no concurrent mutator of any file.

See [[parallel-same-file-drawer-task-collision]] and
[[silent-boundary-leak-bypasses-rework-detection]].
