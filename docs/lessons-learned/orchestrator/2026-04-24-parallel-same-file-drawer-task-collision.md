# Parallel same-expert tasks on the same file cause git-add commit collisions

**Date:** 2026-04-24
**Tag:** cause: decomposition · parallel-serialization
**Run:** 2026-04-23 Mac 3-pane UI refactor (Phase 2 squad execution, Wave 9)
**Specialist:** pyqt-ui-engineer (all four)
**Overlapping files:** `mf4_analyzer/ui/main_window.py`, `tests/ui/test_drawers.py`, `mf4_analyzer/ui/drawers/__init__.py`

## What happened

Wave 9 dispatched four `pyqt-ui-engineer` subtasks in parallel:

- `drawer-channel-editor`
- `drawer-export-sheet`
- `drawer-rebuild-time-popover`
- `drawer-axis-lock-popover`

The decomposition audit marked them parallelisable because they create
four **different** new files under `mf4_analyzer/ui/drawers/`. Correct
— but each also makes a small edit to `main_window.py` (switching its
`open_editor` / `_show_rebuild_popover` / `_show_axis_lock_popover` /
`export_excel` call site) and appends tests to the **shared** file
`tests/ui/test_drawers.py`. Plus all four need to create
`drawers/__init__.py` (race).

When four specialists ran in parallel, their working-tree edits
overlapped. `git add <file>` in one specialist swept in-progress
changes that another specialist had written to the same file. The
net result:

- `drawer-axis-lock-popover` commit `17c0f68` absorbed the
  `open_editor` rewrite + test_drawers.py content that `drawer-channel-editor`
  had authored.
- `drawer-rebuild-time-popover` commit `06265a6` absorbed
  `drawers/__init__.py` + `drawers/channel_editor_drawer.py`.
- `drawer-channel-editor` reported `commit: "N/A"` because by the time
  its `git add` ran, the working tree was already at HEAD via the other
  two commits.

End state was **correct** (all content landed; all tests passed), but
commit titles don't match contents, and post-hoc bisection is harder.

## Why the decomposition audit missed it

The audit enumerated `files_moved` / `files_changed` per subtask but
didn't flag that **all four** mutated the same `main_window.py` call
site (small 1-line edit each) and appended to the same test file.
Shared-file edits were invisible because each was "small" — below the
mental threshold of "needs serialization".

## Preventative guidance

1. **Parallelise only when no two tasks touch the same file**, even for
   small edits. A single line overlap is enough to race `git add`.
2. When shared-file edits are unavoidable, **bundle them into one
   specialist's brief** (e.g., "after your drawer file, also
   switch the call site in main_window.py"). That removes the shared
   file from the parallel set without reassigning the work.
3. Alternative: **one tail-task after the parallel fan-out** picks up
   every shared-file edit the parallel tasks wrote as "please append to
   main_window.py". But this is hard to coordinate when the parallel
   tasks write their edits to disk without committing; the tail-task
   would need to collect diffs, which isn't well supported in our
   current subagent contract.
4. `drawers/__init__.py` creation race: always assign to **one** task or
   pre-create in a prior wave. This lesson documents the second-best
   option ("pre-create").

## Action items applied to the 2026-04-23 run

- The three commits that landed (17c0f68, 06265a6, fd3fe4b) were
  verified correct at HEAD. No in-place fix was done, because the net
  state is correct and a rewrite would just churn git history.
- `ui-reset-methods-rewrite` (Task 3.5) was dispatched **serially**
  after Wave 9, not parallelised — correct per plan even though it
  depends on many Wave-9 outputs.

## Future orchestrator hint

Add a "shared-files" field to each subtask in the decomposition JSON,
separate from "files_changed". If two `pyqt-ui-engineer` subtasks
share any file in `shared_files`, they MUST be serialized even if
their primary outputs are in different files.
