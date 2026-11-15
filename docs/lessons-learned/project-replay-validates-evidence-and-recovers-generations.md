---
id: project-replay-validates-evidence-and-recovers-generations
status: active
owners: [codex]
keywords: [project, replay, channel-edits, recovery, malformed-input]
paths: [mf4_analyzer/io/channel_edit_log.py, mf4_analyzer/ui/project_source_match.py, mf4_analyzer/ui/main_window/_project_io_mixin.py]
checks: [git diff --check]
tests: [tests/test_channel_edit_log.py, tests/test_project_source_match.py, tests/ui/test_project_session.py]
---

# Project Replay Validates Evidence And Recovers Generations

Trigger: Changing recipe replay, source-matching evidence, or cleanup of failed channel references.

Past failure: A failed channel name poisoned a later successful generation and its View references. Malformed remove entries raised before replay could report them; ambiguous missing-source matching enumerated permutations.

Rule: Validate remove entries before using them as evidence or diagnostics. Track recovery in order: a successful generation clears earlier failures for that name without reviving earlier failed consumers. Reconcile restored references with recovered generations. Source matching must have polynomial work even when no covering assignment exists.

Verification: Run channel-edit owner and project-session recovery/malformed-input regressions. Compare small matching graphs with an exhaustive oracle and bound a Hall-deficient overlapping graph in a subprocess.
