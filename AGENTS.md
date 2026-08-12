# Repository Instructions

This file is for Codex only. Claude Code instructions live in `CLAUDE.md`
and `.claude/`; do not edit those files unless the user explicitly asks.

## Scope And Source Of Truth

- Treat the current checkout, runtime behavior, and executable tests as the
  source of truth. Dated specs, plans, reviews, and files under
  `docs/analyzer/verify/` are historical evidence, not proof that the current
  tree is complete or green.
- `AGENTS.md` and `CLAUDE.md` are peer instructions for different agents but
  describe shared product and architecture contracts. Compare both when a
  shared guard changes; keep their semantics aligned without copying
  tool-specific commands or editing `CLAUDE.md` unless the user asks.
- Make the smallest change in the module that owns the behavior. Do not put new
  implementation into a compatibility facade merely because the old import
  path is convenient.
- Keep Codex-specific temporary state and evidence under `.state/`. Do not add
  generated evidence or local runtime artifacts to Git unless the task calls
  for a durable artifact.

## Version And Documentation Contracts

- `mf4_analyzer/app_meta.py:APP_VERSION` is the version source of truth; do not
  introduce another product-version constant. A release bump must synchronize
  README/current-baseline text, the main help deck and four analysis guides,
  the analyzer user guide, Windows build/launcher scripts, and the existing
  help, packaging, and project-session version tests. Do not rewrite dated
  specs, plans, or acquisition records to make their historical version look
  current.
- Put new analyzer specs, plans, reviews, user guides, UI prototypes, and
  verification notes under the routed `docs/analyzer/` tree.
  `docs/superpowers/` is a historical workflow archive, not the destination for
  new work.
- When user-visible interactions are added, removed, or renamed, update both
  `ui/hints.py` and `ui/quickref.py`; do not rely on a Claude-only command name
  to enforce this product requirement.

## Architecture Contracts

### Dependency Direction And Compatibility

- Keep neutral layers import-safe: `signal/`, `io/`, `render_profile.py`,
  `batch_types.py`, `batch_compute.py`, `batch_output.py`,
  `batch_render_models.py`, and `qt_analysis_shared.py` must not pull in
  `mf4_analyzer.ui`, `MainWindow`, or
  the Qt renderer at module import time. Optional renderer imports stay lazy.
- `batch.py` owns batch orchestration and backward-compatible runner exports;
  DSP belongs in `batch_compute.py`, byte/output work in `batch_output.py`, and
  render DTOs in `batch_render_models.py`. Do not reintroduce copied compute or
  renderer logic into the runner.
- `batch_render.py`, `ui/canvases.py`, and `ui/pg_canvases.py` are compatibility
  facades. Keep them thin, preserve supported imports and monkeypatch seams,
  and put new behavior in `batch_render_qt/` or `ui/pg_canvas/` respectively.
- `render_profile.py` owns UI-neutral render policy and ink calculations;
  `ui/pg_canvas/render_profile.py` is a re-export shim, not an implementation
  home.
- Treat `batch_render_qt/contract.py` as the runner-to-renderer seam. An optional
  backend may degrade only for a recognized optional-renderer import failure;
  unrelated `ImportError`, UI bugs, and programming errors must propagate.
- Shared GUI/Batch analysis math belongs in a neutral module such as
  `qt_analysis_shared.py`. Before consolidating similar code, prove semantic
  equivalence; retain and document intentional differences instead of forcing
  false deduplication.
- The runtime chart stack is pyqtgraph-based. Do not reintroduce PyQt5 or
  `matplotlib.pyplot` into `signal/`, or add matplotlib back as a runtime
  rendering dependency.

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
  explicit collaborators such as `analysis_context.py`,
  `fft_time_coordinator.py`, and `_state_holders.py`. Prefer extending an owning
  holder/coordinator to expanding `window.py` or creating another cross-mixin
  state cluster.
- `ui/pg_canvas/canvas.py` is the host; renderer, quality, cursor, overlay,
  annotation, tick, raster, and slice collaborators cross the host boundary
  through `_CanvasBackref`. Keep each collaborator's `_owned_names` and
  `_delegate_names` declarations accurate instead of adding undeclared writes.

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

### Product Data Contracts

- Never invent a sampling rate, time axis, engineering unit, or channel match.
  Use format metadata or an explicitly documented and user-visible estimate.
- One physical file may expand into multiple `LoadedSource` objects with
  different and even disjoint channel sets. Planning and selection must retain
  logical-source identity; Batch callers must seed probed source channels via
  `BatchRunner.seed_source_channels()` rather than assuming every split source
  contains the requested signal.
- View limits are manager-specific but share one product ceiling: the
  time-domain workspace and analysis sections both use
  `ui/view_state.py:MAX_VIEWS` (currently 12). Use the manager's limit
  instead of hard-coding a second cap, and preserve active-tab visibility,
  full-name tooltips, reorder, overflow, and context-menu behavior.

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
- Batch progress emission and result recording are single-owner behavior in the
  private `_RunReporter`. New grouped or sequential branches must route through
  it and must not add a second hand-written emit/record path.
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
  `tests/ui/test_pg_canvas_backref_invariants.py`,
  `tests/ui/test_import_boundaries.py`,
  `tests/test_signal_no_gui_import.py`,
  `tests/test_batch_render_import_boundary.py`,
  `tests/test_native_import_boundaries.py`,
  `tests/test_packaging_imports.py`, and
  `tests/ui/test_main_window_state_ownership.py`. Also keep
  `tests/ui_kit/test_qss_border_shorthand.py` (border-shorthand vs radius),
  `tests/ui/test_no_lambda_signal_connections.py` (shrink-only `.connect(lambda`
  ratchet), and the paint-timer backstop in
  `tests/ui/test_pg_timedomain_canvas.py`. Batch orchestration changes
  also run `tests/test_batch_run_reporter.py`.
- Renderer parity proves two paths do not diverge; it does not prove a shared
  implementation is absolutely correct. Pair parity with owner-level unit tests
  and, for visual/output changes, deterministic real-render or artifact diffs.
- Use the project runtime for Qt checks, normally:
  `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`.
  An abnormal exit, crash, timeout, or interrupted full suite is `UNVERIFIED`,
  never a pass inferred from the tests that completed first.
- The current full-suite gate is two fresh processes because combining
  `tests/acquisition_ui` with the main suite can trigger an order-sensitive Qt
  teardown segfault. Record the pre-change baseline, then run the main suite
  with `--ignore=tests/acquisition_ui` and run `tests/acquisition_ui` separately;
  do not hard-code historical pass counts into this file.
- The repo-root `conftest.py` exists solely to repair a pytest collection
  regression: when the argument list leaves and re-enters a directory
  (`pytest tests/ui/a.py tests/x.py tests/ui/b.py`), pytest rebuilds that
  directory's collector node, and because fixture lookup matches on node
  identity, every fixture from the directory's `conftest.py` silently stops
  applying — no error, no warning, the tests just run without them. Keep that
  file, keep project fixtures out of it (directory conftests own those), and
  treat `tests/test_conftest_autouse_scope.py` as the gate that says whether it
  is still needed. `tests/ui/test_qsettings_isolation.py` is the second alarm:
  without the UI isolation fixtures the suite reads and writes the developer's
  real `MF4Analyzer/DataAnalyzer` store, so machine-local leftovers become
  invisible test preconditions. A test that only fails for some argument
  orderings is this failure mode until proven otherwise; diagnose it by
  comparing the item's fixture closure across orderings, and never paper over
  it with a fixed test order, `xfail`, or a sleep.
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
- `envelope_ink_dev_px` in the neutral `render_profile.py` is the canonical
  time-domain cost metric. Raw source density may drive fidelity-preserving
  decimation but must not return as a render-cost gate; unmeasured curves are
  measured, never treated as zero ink. Changing ink thresholds requires the
  governing spec, focused `TestInkBudget` coverage, a real Cocoa probe, and the
  interaction benchmark rather than an offscreen timing claim.

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
