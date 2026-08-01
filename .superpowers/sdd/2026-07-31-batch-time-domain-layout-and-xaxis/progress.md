# SDD ledger — plan: docs/superpowers/plans/2026-07-31-batch-time-domain-layout-and-xaxis.md

Baseline: d4a77fd on codex/batch-time-domain-layout-xaxis
Baseline test: 59 passed — tests/test_batch_renderer.py + tests/test_db_conversion_convergence.py — dedicated worktree basetemp
Environment note: default C:\Users\hang\AppData\Local\Temp\pytest-of-hang is inaccessible; all pytest commands use a pre-created worktree-local .state/pytest-basetemp parent.

Task 1: complete (commits d4a77fd..0bf664f, review fix round 1, scoped re-review clean; 76-test gate passed)
Task 2: complete (commit 71e5755, task review clean; 17-test gate passed)
Task 3: complete (commit 2e09374, task review clean; 235-test scoped gate plus one pre-existing cmap assertion)
Integration fix: complete (commit 3fa03b4, scoped re-review clean; Task 3 gate 236 passed, Task 1 gate 76 passed)
Task 4: complete (commits fea167e..77b2c50 with fix round 1, scoped re-review clean; 206-test gate passed)
Lesson: promoted and committed as 4c998e7 (close Windows spool mmaps before cleanup)
Task 5: complete (commits d358009..fc90430 with two fix rounds, final scoped re-review clean; 59-test gate passed)
Lesson: promoted and committed as 2a7ae0d (manifest resume requires complete source facts)
Task 6: complete (commits 3d854a6..14d9381 with two fix rounds, final scoped re-review clean; 314-test gate passed)
Lesson: promoted as b4e0e4b and extended as 11ec261 (lazy locator identity and atomic replanning)
Task 7: complete (commits 93042db..cd64fba with two fix rounds, final scoped re-review clean; 275-test gate passed)
Lessons: provenance extended as c82dcfb; lazy execution-scope proof extended as da90d58
Task 8: complete (commits 804378c..0b291dd with fix round 1, scoped re-review clean; 42 contract tests passed, one recorded pre-edit narrow-button baseline failure remains)
Task 9: complete (commits de883f2..3d4604e with fix round 1, scoped re-review clean; 144 contract tests passed, six recorded pre-edit UI baseline failures remain)
Task 10: complete (commits 6382ff3 and 358d371; frozen/acceptance TDD complete; focused gate has only six recorded baseline failures; non-UI, acquisition UI, and 128-file isolated UI partitions have zero differences from detached 3d4604e; Full/Lite exact package commands exit 0 with 12-output frozen smoke success)
Task 10 review fix 1: complete (pre-3.11 font trees no longer require the 3.11-added LastResort file; 3.11 still preserves it; contract + frozen smoke gate 10 passed)
Task 10 review fix 2: complete (acceptance rejects artifact aliases/directory escapes and wrong grouping semantics; resumed manifest/artifacts and exact 26-file output set verified; combined gate 17 passed)
Task 10 review fix 3: complete (inspector is bound to the exact expected mode directory; grouped PNG stem ownership and pre/post resume group-artifact mappings are exact; combined gate 19 passed)
