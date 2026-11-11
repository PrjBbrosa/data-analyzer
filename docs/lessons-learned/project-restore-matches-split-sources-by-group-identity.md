---
id: project-restore-matches-split-sources-by-group-identity
status: active
owners: [codex]
keywords: [project, restore, logical-source, group-identity, channel-edits, sampling-rate]
paths: [mf4_analyzer/ui/main_window/_project_io_mixin.py, mf4_analyzer/ui/project_source_match.py, mf4_analyzer/io/source_adapters.py]
checks: [git diff --check]
tests: [tests/test_project_source_match.py, tests/ui/test_project_session.py]
---

# Project Restore Matches Split Sources By Group Identity

Trigger: Changing project save or open for a file that expands into multiple
logical sources, including the sampling rate, channel order, View references,
and derived-channel recipes restored with those sources.

Past failure: Saved file rows were paired with reloaded groups by position.
When the same path later loaded in a different group order or with fewer
groups, the saved sampling rate, View references, and derived-channel recipes
landed on another source, often with no warning. A file loaded twice when a
saved row had no group left. A single-source file is a different case: its
one group is the file, and a missing column must still replay so the real
skip reason is shown.

Rule: Persist the existing Batch group identity on each split-source row and
match on it at restore. Load each path once. Use unique channel-name
evidence, with a measured-rate tie-break, only for rows that have no
identity. When one row and one group remain, that group is the file. When
several groups stay unmatched, do not replay recipes or apply the saved
sampling rate; report the source as unconfirmed. A saved row with no
remaining group is missing; do not load the file again.

Verification: `tests/test_project_source_match.py` and the split-source cases
in `tests/ui/test_project_session.py` (re-exported MAT order, fewer groups,
legacy same-name groups, whole-card reorder).
