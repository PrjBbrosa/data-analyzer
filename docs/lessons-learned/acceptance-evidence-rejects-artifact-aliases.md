---
id: acceptance-evidence-rejects-artifact-aliases
status: active
owners: [codex]
keywords: [acceptance, artifacts, manifest, resume, aliases]
paths: [mf4_analyzer/*acceptance*.py, tests/test_*acceptance*.py]
checks: [git diff --check]
tests: [tests/test_batch_time_group_acceptance.py]
---

# Acceptance Evidence Must Prove Physical Artifacts

Trigger: An acceptance harness claims exact artifact counts, grouping semantics,
or safe manifest-based resume.

Past failure: Counting manifest references let several entries point to the same
CSV or image while still reporting the expected count. Member linkage did not
prove the requested grouping dimension or bind each image to its group's stem.
The harness also trusted the manifest's own directory instead of the caller's
requested directory. Resume evidence inspected the old artifacts without
validating the newly written manifest or excluding extra auto-numbered files.

Rule: Resolve artifact paths before counting; require unique in-scope physical
paths in the caller-requested directory, validate the grouping dimension from
member task facts, and bind each group ID, stem, and artifact path. After
resume, reload and fully validate the new manifest, compare retained data and
group artifact mappings plus healthy-file bytes/mtimes, and require the output
file set to remain exact.

Verification: Add mutation tests for aliased paths, out-of-scope paths, and
wrong-dimension or swapped-artifact groups. Run the real deleted-artifact resume
and assert the new manifest checksums/statuses plus unchanged group mappings,
healthy artifacts, and directory file sets.
