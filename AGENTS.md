# Repository Instructions

This file is for Codex only. Claude Code instructions live in `CLAUDE.md`
and `.claude/`; do not edit those files unless the user explicitly asks.

## Scope And Source Of Truth

- Treat the current checkout, runtime behavior, and executable tests as the
  source of truth. Dated specs, plans, reviews, and files under
  `docs/analyzer/verify/` are historical evidence, not proof that the current
  tree is complete or green.
- Make the smallest change in the module that owns the behavior. Do not put new
  implementation into a compatibility facade merely because the old import
  path is convenient.
- Keep Codex-specific temporary state and evidence under `.state/`. Do not add
  generated evidence or local runtime artifacts to Git unless the task calls
  for a durable artifact.

## Architecture Contracts

### Dependency Direction And Compatibility

- Keep neutral layers import-safe: `signal/`, `io/`, `batch_types.py`,
  `batch_compute.py`, `batch_output.py`, `batch_render_models.py`, and
  `qt_analysis_shared.py` must not pull in `mf4_analyzer.ui`, `MainWindow`, or
  the Qt renderer at module import time. Optional renderer imports stay lazy.
- `batch.py` owns batch orchestration and backward-compatible runner exports;
  DSP belongs in `batch_compute.py`, byte/output work in `batch_output.py`, and
  render DTOs in `batch_render_models.py`. Do not reintroduce copied compute or
  renderer logic into the runner.
- `batch_render.py` and `ui/pg_canvases.py` are compatibility facades. Keep them
  thin, preserve supported imports and monkeypatch seams, and put new behavior
  in `batch_render_qt/` or `ui/pg_canvas/` respectively.
- Treat `batch_render_qt/contract.py` as the runner-to-renderer seam. An optional
  backend may degrade only for a recognized optional-renderer import failure;
  unrelated `ImportError`, UI bugs, and programming errors must propagate.
- Shared GUI/Batch analysis math belongs in a neutral module such as
  `qt_analysis_shared.py`. Before consolidating similar code, prove semantic
  equivalence; retain and document intentional differences instead of forcing
  false deduplication.

### UI Package Ownership

- `ui/widgets/` owns reusable controls and presentation behavior;
  `ui/inspector_sections/` owns Inspector sections and their local settings;
  neither package should reach into `MainWindow` session state.
- `ui/chart_stack/` owns chart cards, toolbars, markup, focus presentation, and
  canvas composition. File/session identity and analysis orchestration remain
  outside it.
- `ui/drawers/batch/` owns Batch UI composition and worker wiring. Reuse the
  neutral Batch contracts and runner instead of placing compute, output, or
  renderer algorithms back into widgets.
- `ui/main_window/` coordinates product-level state through its mixins and
  collaborators. Prefer adding a typed coordinator/manager to expanding
  `window.py` or creating another cross-mixin state cluster.

### Identity And State Ownership

- Use composite source/channel identity for data, axes, caches, persistence,
  and render selection. Display names, shortened labels, and tooltip text are
  presentation only and must never become identity keys.
- Preserve `_ChannelKeyDict` identity semantics. Do not convert it with
  `dict(...)`, `{**mapping}`, or another display-key mapping operation that can
  collapse duplicate channel labels; use its explicit composite APIs.
- New mutable state must have one clear owner, be explicitly initialized, and
  be reset symmetrically in `clear()`, teardown, or project/view restoration.
  Required guards must not rely on a silent `getattr(..., False)` fallback.
- Do not add new multi-file `MainWindow` writes. Prefer a manager/coordinator or
  owner-held state object, and keep
  `tests/ui/test_main_window_state_ownership.py` as a shrink-only ratchet; fix
  ownership rather than widening its whitelist.
- Keep render-quality state inside the existing `pg_canvas` managers and shared
  predicates. Time-domain density decisions use measured screen-space ink,
  hysteresis, and the existing frame-time fallback; do not add a parallel raw
  point-count or full-height-wall heuristic without new measurements and
  contract tests.

## Robustness Rules

- Preserve the error taxonomy: user/data failures become explicit item status
  or actionable UI feedback; recoverable infrastructure failures are logged
  with context; programming errors and unexpected imports are not silently
  downgraded.
- Do not add broad `except Exception: pass`. Cleanup-only Qt guards must catch
  the narrow expected exception and explain why it is safe. Hot-path logging
  must use the existing diagnostics throttling rather than produce a log storm.
- Preserve the cross-platform diagnostics path and global Python/thread/Qt
  exception hooks. A fallback must remain observable through logs, returned
  warnings, run results, or user-visible status.
- Treat Qt ownership as a correctness contract: create and paint Qt objects on
  the GUI thread, give test widgets explicit ownership, drain deferred deletes
  when a test creates parentless dialogs, and stop timers/signals before their
  owners disappear. Cached Qt wrappers must clear on `destroyed` and be checked
  with `sip.isdeleted()` before reuse.
- Numeric changes must specify empty, short, non-finite, dtype, shape, and
  time-alignment behavior. Preserve output length where the API promises it;
  never hide incompatible X/Y data with an unexplained `min(len(x), len(y))`.
- Presets and persisted project state contain reproducible user intent, not
  transient run state, diagnostics, widget objects, or process-local caches.

## Change Discipline

- Preserve public imports and documented compatibility aliases unless the task
  explicitly includes a migration. Update all consumers, packaging hidden
  imports, tests, and documentation when intentionally changing a seam.
- Add a failing focused test or deterministic probe before fixing a reproduced
  bug whenever feasible. For a refactor, freeze behavior first with boundary,
  parity, artifact, or state-ownership evidence.
- Do not launch a broad decomposition from line count, private-test count, or an
  old audit alone. Trace live call sites and state mutation, identify the owner,
  and split one responsibility at a time.
- Do not duplicate a calculation to preserve an import boundary. Move the
  shared implementation to a neutral layer and keep the dependency direction
  protected by subprocess import tests.
- Keep unrelated dirty-worktree changes out of the patch, staging, and commit.

## Verification Gates

- Run focused tests for the changed owner first. Then run the relevant boundary
  gates, including as applicable:
  `tests/test_batch_render_import_boundary.py`,
  `tests/test_native_import_boundaries.py`,
  `tests/test_packaging_imports.py`, and
  `tests/ui/test_main_window_state_ownership.py`.
- Renderer parity proves two paths do not diverge; it does not prove a shared
  implementation is absolutely correct. Pair parity with owner-level unit tests
  and, for visual/output changes, deterministic real-render or artifact diffs.
- Use the project runtime for Qt checks, normally:
  `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`.
  An abnormal exit, crash, timeout, or interrupted full suite is `UNVERIFIED`,
  never a pass inferred from the tests that completed first.
- Keep evidence classes separate: offscreen Qt, real macOS Cocoa, foreground
  TraceLab, source-level Windows packaging checks, and fresh Windows Full/Lite
  frozen executables are distinct gates. Do not substitute one for another.
- For UI changes, verify the running widget path and rendered geometry or pixels;
  stylesheet tokens and offscreen assertions alone do not prove foreground
  appearance. For many artifacts, compare them automatically rather than asking
  the user to inspect each one.
- For releases, synchronize version/package/help surfaces, run focused release
  checks plus `git diff --check`, and report any unrun macOS foreground or
  Windows frozen acceptance explicitly.

<!-- BEGIN CODEX LESSONS SYSTEM -->

## Codex Lessons Learned System

- Before risky edits, bug fixes, or reviews, select only relevant entries from
  `docs/lessons-learned/INDEX.md`, preferably with
  `scripts/lessons/select.py`; do not bulk-load the corpus.
- When a failure pattern recurs, a regression test closes a missed bug, or a
  durable convention is discovered, run:

  ```bash
  /usr/bin/python3 scripts/lessons/check.py --require "short reason"
  ```

- Protect fixes with a test/check first when feasible. Keep each lesson short:
  trigger, past failure, rule, and verification.
- Before the final answer, inspect lesson status. If required, create
  `.state/lesson-candidate.md` from `docs/lessons-learned/_template.md` and run:

  ```bash
  /usr/bin/python3 scripts/lessons/promote.py
  ```

- Clear a lesson requirement only after promotion or after recording why no
  durable lesson is needed.

<!-- END CODEX LESSONS SYSTEM -->
