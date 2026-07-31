# Robustness Remediation Phase 1 Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.
> Per `CLAUDE.md` agent-squad routing, the main session does **not** edit `.py`
> files — every task below is dispatched to the expert named in its header.

**Goal:** Fix the two correctness bugs that were reproduced end-to-end, close the
`_ChannelKeyDict` write-surface holes, put a cross-platform rate-limited
exception log under the whole process, remove the two ownerless canvas state
slots, and buy the evidence needed to decide whether the test suite actually
blocks refactoring — without touching `canvas.py`'s size or the 288 broad silent
handlers as a batch.

**Architecture:** Six independent work packages. W1c adds `resolve_unique` to
`_ChannelKeyDict` and fixes its write surface; W1a then routes the canvas Y-fit
fallback through composite keys using that helper; W1b clamps `ChannelMath`
window/dtype contracts and gives the module its first tests. W2 adds
`mf4_analyzer/diagnostics.py` (log dir resolution, rotating handler, throttle,
`sys`/`threading` excepthooks, Qt message handler), wires it into
`app.main()`, and converts 5–10 named non-hot-path silent handlers to throttled
logging with unchanged control flow. W3 deletes `canvas._refresh`, gives
`_channel_render_profiles` an `__init__`/`clear()` owner, moves
`AnnotationManager._artist` into `_owned_names`, and locks the `_CanvasBackref`
write-through set with an AST + runtime invariant test. W4 is a read-only
stratified classification of the 1,232 private-attribute assertions.

**Tech Stack:** Python 3.12.13, PyQt5 5.15.11 / Qt 5.15.14, pyqtgraph 0.14.0,
numpy 2.5.1, pytest 9.1.1, pytest-qt 4.5.0, stdlib `logging.handlers`.

**Design spec:** `docs/superpowers/specs/2026-07-30-robustness-remediation-phase1-design.md`
**Source audit:** `docs/robustness-audit-2026-07-30.md` (rev2)
**Baseline commit:** `b5d7956eb8c80c7981d174ed92575e876d171c2b`

---

## Global Constraints

- Every runtime probe and test run uses `.venv/bin/python`. The system `python3`
  is 3.14.6 with **no PyQt5** and cannot run any GUI test.
- GUI probes need `QT_QPA_PLATFORM=offscreen` and `PYTHONPATH=<repo>`.
- No task may change the control flow of an existing `except` handler. W2 adds a
  log call *before* the existing `pass` / `continue` / `return`; the branch taken
  stays identical.
- No task may add `logger.debug` to a handler reached from a per-frame path:
  `Renderer._refresh_visible_data`'s per-channel loop body, any
  `mouseMoveEvent` / `wheelEvent` / `paint*` override, or any function they call
  per channel per frame.

> **Correction (2026-07-31):** The exclusion above was too broad for sanctioned
> seam #6, `_sync_x_axis_item_range`, which is reached once per sibling axis per
> drag tick. A per-frame seam may be instrumented only when it is named
> explicitly, rate-limited, and its suppressed-path cost is measured. The
> follow-up baseline was median 197.4 ns/call, or about 94.8 µs/s at 60 fps × 8
> axes. See `2026-07-31-robustness-phase1-followup.md`, Task 5.

- The four live names `_refresh_pending`, `_refresh_timer`,
  `_refresh_visible_data`, `_refresh_overlay_axis_labels` must survive W3
  untouched. Only the bare `_refresh` boolean is deleted.
- `dict(d)` / `{**d}` on `_ChannelKeyDict` stay collapsing. W1c pins that as a
  documented baseline; changing the iteration surface is Phase 2.
- No new third-party dependency without asking the user first. This applies to
  `pytest-cov` in Task 6.
- Every package records `tests_before` / `tests_after` and, where applicable,
  `ui_verified`. Per `CLAUDE.md`, a UI/visual claim requires real-render
  evidence — a passing unit test asserting an attribute is not sufficient.
- Report `blocked` rather than guessing if a measured number in the spec does not
  reproduce.

---

## Task 0 — Re-verify the baseline (main session, no `.py` edits)

The audit's first version had drifted numbers. Confirm the four headline counts
still hold before anything is edited.

- [x] Confirm `git rev-parse HEAD` is `b5d7956eb8c80c7981d174ed92575e876d171c2b`,
      or record the new SHA in this plan and re-run every check below.
- [x] Re-run audit appendix A-1 and A-1b; confirm `ui/pg_canvas` = 16,914 LOC /
      522 handlers / 296 silent / **288 broad `except Exception`**.
- [x] Re-run A-2; confirm 19 `._refresh` writes, 0 production reads, 1 test
      reference at `tests/ui/test_pg_timedomain_canvas.py:1533-1538`.
- [x] Re-run A-6; confirm `1,232 / 894 / 47`.
- [x] Re-run A-11; confirm file A's axis lands at
      `(95.0000169803578, 204.9999830196422)`.
- [x] Record the full default suite baseline: `.venv/bin/python -m pytest -q`
      with `QT_QPA_PLATFORM=offscreen`. Write pass/fail/skip counts and wall time
      into the Verification Log at the bottom of this file. **Every later task
      compares against these numbers.**

Task 0 live result: the default suite was already red before any remediation
edit (`64 failed, 4053 passed, 8 skipped, 3 deselected`; pytest `1038.33 s`,
process wall clock `1038.74 s`). Later tasks must preserve this exact existing
failure set or reduce it; any new failing node is a regression.

---

## Task 1 — W1c · `_ChannelKeyDict` write surface + `resolve_unique`

**Expert:** `pyqt-ui-engineer` · **Files:** `mf4_analyzer/ui/pg_canvas/_shared.py`,
new/extended tests · **Depends on:** Task 0

Runs before W1a because W1a consumes `resolve_unique`, and both would otherwise
touch `_shared.py` (rework-collision risk per `CLAUDE.md` §Aggregate).

- [x] Write the failing tests first: `setdefault` on an existing display name
      must return the existing value and leave `len(d) == 2`; today it returns
      the default and makes `len(d) == 3` with a bare-name phantom entry that
      then wins every later bare-name read. Assert the masking too, not just the
      length.
- [x] Add failing tests for `copy()` (must return `_ChannelKeyDict` with both
      colliding entries) and `update()` from another `_ChannelKeyDict` (must
      preserve both).
- [x] Implement `setdefault(key, default=None)`: resolve through `_resolve`
      first, return the existing value on a hit, otherwise `self[key] = default`
      and return it.
- [x] Implement `copy()` via `composite_items()` + `set_with_label` into a
      `type(self)()` clone.
- [x] Implement `update(other=(), **kwargs)`: composite-preserving when `other`
      is a `_ChannelKeyDict`, otherwise the ordinary mapping / pair-iterable
      behaviour through `__setitem__`.
- [x] Add `as_composite_dict()` — lossless plain dict keyed by composite key —
      as the sanctioned alternative to `dict(d)`.
- [x] Add `resolve_unique(key)`: returns the stored composite key when `key` is
      itself a stored key or a display name bound to exactly **one** entry;
      returns `None` when absent or ambiguous. Do not change `_resolve`.
      Docstring must state why an identity-sensitive caller needs it.
- [x] Add the **baseline** test asserting the accepted limitation: `dict(d)`,
      `{**d}`, and `{k: v for k, v in d.items()}` each collapse to `len == 1`,
      with a comment naming `as_composite_dict()` and pointing at the Phase 2
      surface-separation item.
- [x] Run the full `tests/ui/` subset plus `tests/ui/test_pg_multifile_samename_curves.py`;
      report `tests_before` / `tests_after`.

Focused verification: RED `7 failed / 4 passed`; GREEN `11 passed`; W1c plus
the existing same-name file `20 passed`. Full `tests/ui/` was attempted but
aborted at about 8% in the pre-existing BatchSheet Qt-thread teardown path.

**Acceptance:** all five new behaviours tested; `dict(d)` collapse documented,
not silently accepted; `resolve_unique` covered for absent / unique / ambiguous /
composite inputs.

---

## Task 2 — W1a · Composite key through the Y-fit fallback

**Expert:** `pyqt-ui-engineer` · **Files:** `mf4_analyzer/ui/pg_canvas/canvas.py`,
`tests/ui/test_pg_multifile_samename_curves.py` · **Depends on:** Task 1

- [x] Write the failing regression test in the existing
      `tests/ui/test_pg_multifile_samename_curves.py` (it already has the
      colliding-`short_name` fixtures and 9 passing tests). Two files with the
      same prefixed display name, data ranges `[-1, 1]` and `[100, 200]`; save
      only file B's ylim; call `restore_visible_ylims`; assert file A's axis is
      inside its own range and specifically **not** inside `(90, 210)`.
      Confirm it fails on the current code with the axis at ≈`(95, 205)`.
- [x] Parametrise that test over `mode="subplot"` and `mode="overlay"`.
- [x] Add non-regression tests: a two-file layout with **distinct** display names
      and a single-file layout both still auto-fit the un-restored channel
      correctly.
- [x] In `restore_visible_ylims`, drop the `get_label()` hop and pass the
      composite `key` to `_fit_channel_y_to_visible_x`.
- [x] Rename that method's first parameter to `channel_key`; update the
      docstring to state that it takes a composite key.
- [x] Inside the fitter, look up `self.channel_data.get(channel_key)` first; on a
      miss, fall back to the display label **only** via
      `resolve_unique` from Task 1 — an ambiguous label returns `False` and
      leaves the axis untouched. Add a comment explaining the fail-closed choice.
- [x] Confirm `test_restore_visible_ylims_fits_new_overlay_channel_to_visible_x`
      (`tests/ui/test_pg_timedomain_canvas.py:2486`) still passes **unmodified** —
      it is the single-file contract this change must not disturb.
- [x] `ui_verified`: run the A-11 probe against the patched tree and paste the
      before/after axis numbers into the return. Expected after:
      ≈`(-1.0999, 1.0999)`.
- [x] Run `tests/ui/` in full; report `tests_before` / `tests_after`.

Focused verification: RED `3 failed / 2 passed`; GREEN `5 passed`; W1a+W1c
`25 passed`; full `test_pg_timedomain_canvas.py` `379 passed / 1 deselected`.
A-11 after: file A `(-1.099999660392844, 1.099999660392844)` and file B remains
`(100.0, 200.0)`. The whole `tests/ui/` run is covered by the same pre-existing
BatchSheet teardown limitation recorded in Task 1.

**Acceptance:** the crosstalk test fails on `HEAD~` and passes after, in both
plot modes; ambiguous lookups fail closed; the existing single-file auto-fit test
is untouched and green.

---

## Task 3 — W1b · `ChannelMath` contracts + first test file

**Expert:** `signal-processing-expert` · **Files:**
`mf4_analyzer/signal/channel_math.py`, new `tests/signal/test_channel_math.py`
· **Depends on:** Task 0 · **Parallel with:** Tasks 1–2 (no file overlap)

- [x] Create `tests/signal/test_channel_math.py` (the directory exists with
      `test_order.py`, `test_order_cot.py`). Write the failing length test first:
      `len(moving_avg(sig, ws)) == len(sig)` over
      `(3,50) (10,100) (2000,5000) (1000,50) (1,1) (5,1)`. Confirm the first
      three fail today with lengths 50 / 100 / 5000.
- [x] Add the failing dtype test: `integral(np.array([0,1,2,3]), np.array([0,1,2,3]))`
      must equal `[0, 0.5, 2, 4.5]` and be `float64`; today it is `int64`
      `[0, 0, 2, 4]`.
- [x] Implement `moving_avg`: coerce to a float array; empty input returns an
      empty float array without raising; `ws = max(1, min(int(ws), sig.size))`.
- [x] Implement `integral`: allocate with `np.zeros(sig.shape, dtype=float)` so
      the accumulator never inherits an integer dtype; coerce `t` to float;
      `size < 2` returns the zero array.
- [x] Give `derivative` an explicit `size < 2` precondition raising `ValueError`
      with a clear message instead of leaking `np.gradient`'s `IndexError`.
      Match the language convention already used in `mf4_analyzer/signal/` —
      check before choosing Chinese or English.
- [x] Pin the clamp *semantics*, not only the length: for `ws >= len(sig)`,
      `moving_avg` must equal `np.full(len(sig), sig.mean())` within tolerance.
- [x] Add analytic correctness tests: `integral` of `sig = t` over a fine grid
      approaches `t²/2`; `derivative` of `sin` approaches `cos`; plus `scale`
      and `offset`. This is the module's first test file — cover the whole public
      surface.
- [x] Do **not** modify `mf4_analyzer/ui/dialogs.py`. The clamp belongs in the
      algorithm so every future caller inherits it; `dialogs.py:362`'s
      `max(int(p), 3)` and the `±1e12` spin range stay as they are.
- [x] Run `.venv/bin/python -m pytest tests/signal -q`; report
      `tests_before` / `tests_after`.

Verification: three RED→GREEN rounds; new module tests `21 passed`, complete
`tests/signal` `39 passed`, and dialogs caller regression `24 passed`.

**Acceptance:** output length always equals input length; `integral` always
returns float; all five public operations covered including empty/short/large-
window boundaries; no `dialogs.py` diff.

---

## Task 4 — W2 · Diagnostics infrastructure

**Expert:** `pyqt-ui-engineer` · **Files:** new
`mf4_analyzer/diagnostics.py`, `mf4_analyzer/app.py`, 5–10 `ui/pg_canvas`
handlers, new tests · **Depends on:** Task 0 (Tasks 1–3 may run in parallel)

### Step 4.1 — the module

- [x] Create `mf4_analyzer/diagnostics.py`. It must import with **no PyQt
      import at module level**, so `batch.py` / CLI / non-GUI tests can use it.
      The Qt message handler imports PyQt lazily inside its own function.
- [x] `resolve_log_dir()`: Windows `%LOCALAPPDATA%\TraceLab\logs` (fallback
      `~/AppData/Local/...`), macOS `~/Library/Logs/TraceLab`, otherwise
      `${XDG_STATE_HOME:-~/.local/state}/TraceLab/logs`. `TRACELAB_LOG_DIR`
      overrides. Windows correctness matters most — it is the only packaged
      target (`tools/build_windows_folder.ps1`, `--windowed` at line 272), and
      there is no macOS packaging script.
- [x] `setup_logging(level=None)`: `RotatingFileHandler`, `maxBytes=5*1024*1024`,
      `backupCount=5` (30 MiB hard ceiling). File level `INFO`, raised by
      `TRACELAB_LOG_LEVEL`. `WARNING`+ also to stderr when one exists. An
      unwritable directory degrades to stderr-only and **must not raise** —
      diagnostics must never stop the app from starting. Returns the resolved
      path.
- [x] `throttled(logger, key, level, msg, *args, exc_info=False)`: per key, emit
      the first `BURST = 3`, then suppress; after `WINDOW = 60 s` emit one
      summary naming the suppressed count and reopen the burst. Bound the key map
      at `MAX_KEYS = 512` with oldest-first eviction. The suppressed path must be
      one dict lookup and one integer compare — **no string formatting until a
      record is actually emitted**.

> **Correction (2026-07-31):** Same-key lazy rollover alone leaves a quiet
> burst unreported. The follow-up adds an amortized cross-key sweep,
> `flush_throttle_summaries()` for manual/orderly-shutdown accounting, and an
> eviction summary before the oldest key is removed. All logger calls remain
> outside `_THROTTLE_LOCK`; see the follow-up Task 2 tests and performance gate.

- [x] `install_excepthooks(on_error=None)`: set `sys.excepthook` **and**
      `threading.excepthook`, chaining to the previous hooks so pytest and IDE
      integrations keep working. `on_error` receives a short user-facing string.
- [x] `install_qt_message_handler()`: `qInstallMessageHandler`; map
      `QtDebugMsg`/`QtInfoMsg`/`QtWarningMsg`/`QtCriticalMsg`/`QtFatalMsg` to
      debug/info/warning/error/error; route through `throttled` keyed on the Qt
      category plus the message's first 80 characters (Qt repeats identical
      warnings per frame). The handler must never raise back into Qt.

### Step 4.2 — wiring

- [x] In `app.main()`: `setup_logging()` first, before `_configure_high_dpi()`,
      so import-time failures are captured; `install_qt_message_handler()`
      immediately after `QApplication(...)`; `install_excepthooks(on_error=...)`
      after `MainWindow()` exists, passing `window.toast`
      (`ui/main_window/window.py:551`) so the user gets a visible notice plus the
      log path.

### Step 4.3 — seams

- [x] Instrument **5–10** handlers from this list, converting
      `except Exception: pass` into `except Exception: throttled(...)` followed
      by the **identical** original statement:
      1. `canvas.py:2024` `get_visible_ylims` per-channel getter
      2. `canvas.py:2035` `restore_visible_ylims` per-channel `set_ylim`
      3. `canvas.py:2069` `_fit_channel_y_to_visible_x` `get_xlim`
      4. `canvas.py:2076` same, array coercion
      5. `canvas.py:2098` same, `set_ylim`
      6. `canvas.py` `_sync_x_axis_item_range` axis-handle and `setRange`
      7. `overlay_axes.py` overlay tick repin failure path
      8. `chart_stack/stack.py` `enter_split` / `exit_split`
      Line numbers are from the baseline SHA — re-locate them, and if Tasks 1–3
      have already shifted `canvas.py`, use the current lines and say so.
- [x] Do **not** touch any handler inside `Renderer._refresh_visible_data`'s
      per-channel loop, any mouse/wheel/paint override, or anything they call
      per channel per frame. Justify each chosen seam in one line.
- [x] Every log message must name the channel key or axis involved — a record
      without an identifier is not actionable.

### Step 4.4 — tests and gate

- [x] Tests: per-platform `resolve_log_dir` with `sys.platform` monkeypatched;
      `TRACELAB_LOG_DIR` override; rotation caps at `backupCount`; unwritable
      directory degrades without raising; `throttled` burst/suppress/summary
      counts and key-map bound; both excepthooks write a full traceback and chain
      to the previous hook; Qt level mapping; per-seam failure injection
      asserting **unchanged control flow plus a log record with an identifier**.
- [x] Performance gate: run `scripts/benchmark_timedomain_interaction.py` before
      and after and paste both results. A regression beyond run-to-run noise
      blocks the task — report `blocked` rather than shipping it.
- [x] Report `tests_before` / `tests_after` for the full default suite.

W2 verification: initial RED was two collection errors before
`diagnostics.py` existed; integrated diagnostics/seam/timedomain scope is
`414 passed / 1 deselected`, with startup/build smoke `56 passed`. Eight
low-frequency seams are instrumented. The old Task 0 Cocoa timing tier did not
reproduce, so W2 was compared with `b5d7956` on the same machine and time:
W2 versus baseline was -0.1% initial, -1.7%/-0.9% pan p50/p95,
-2.7%/-7.2% resize p50/p95, and +0.5%/+0.2% checkbox callback/paint p50.
No W2 regression was measured. The final full-suite comparison remains the
main-session integration gate because the baseline itself has 64 failures.

**Acceptance:** an injected slot exception produces a full traceback in the
platform-correct rotating file; total log size cannot exceed 30 MiB; a seam
failing 10,000 times yields `BURST` records plus periodic summaries, not 10,000
records; benchmark shows no regression; 5–10 seams instrumented with control flow
provably unchanged.

---

## Task 5 — W3 · State hygiene

**Expert:** `refactor-architect` · **Files:** `mf4_analyzer/ui/main_window/window.py`,
`mf4_analyzer/ui/pg_canvas/{canvas,overlay_axes,cursor,renderer,tick_density,annotations,quality,dense_raster}.py`,
`tests/ui/test_pg_timedomain_canvas.py`, new
`tests/ui/test_pg_canvas_backref_invariants.py` · **Depends on:** Task 4

Execution routing note: `refactor-architect` completed a read-only audit and
correctly flagged that its write boundary permits moves/shims/imports, not UI
state function-body edits. The main session rerouted this package unchanged to
`pyqt-ui-engineer`; no file was modified by the blocked first dispatch.

Ordered after W2 so the deletions land with observability in place.

### Step 5.1 — delete `canvas._refresh`

- [x] Remove all 19 assignments: `window.py:2022`;
      `canvas.py:385,1000,2247,2299,2499`; `overlay_axes.py` ×8;
      `cursor.py` ×2; `renderer.py:717`; `tick_density.py` ×2.
- [x] Remove the assertion at `tests/ui/test_pg_timedomain_canvas.py:1533-1538`.
- [x] Leave `_refresh_pending`, `_refresh_timer`, `_refresh_visible_data`,
      `_refresh_overlay_axis_labels` untouched — all four are live.
- [x] Post-condition: `grep -rn "\._refresh\b" mf4_analyzer/ tests/ --include="*.py"`
      returns nothing. Paste the empty result.

### Step 5.2 — give `_channel_render_profiles` an owner

- [x] `canvas.__init__`: add `self._channel_render_profiles = {}`.
- [x] `canvas.clear()`: add `self._channel_render_profiles.clear()`.
- [x] Replace the 3 lazy-creation blocks (`renderer.py:527-530`,
      `overlay_axes.py:315-318`, `overlay_axes.py:425-428`) with direct
      attribute access.
- [x] Replace the 5 `getattr(..., {})` reads (`dense_raster.py:241/403/435`,
      `quality.py:88/300`) with direct reads. `dense_raster.py` reaches the
      canvas as `self.canvas`, not through `_CanvasBackref`, so it becomes
      `self.canvas._channel_render_profiles`.
- [x] Keep the three existing readers green unmodified:
      `test_pg_timedomain_canvas.py:6592`,
      `test_high_variation_envelope.py:293/310`.
- [x] Add tests: `{}` immediately after `__init__`; populated after a render;
      empty after `clear()`.
- [x] Note the behaviour change in the return: profiles no longer survive a
      `clear()`, so the first frame after a file switch re-classifies each
      channel. Re-run `scripts/benchmark_timedomain_interaction.py` and confirm
      no regression.

### Step 5.3 — own `AnnotationManager._artist`

- [x] Verify nothing outside `annotations.py` reads `canvas._artist` (the audit
      found no reader in sources or tests; the sibling canvases use
      `_remark_artist`). Paste the grep.
- [x] Add `"_artist"` to `AnnotationManager._owned_names`.
- [x] Test: `'_artist' in vars(manager)` and `'_artist' not in vars(canvas)`;
      remark add / remove / clear behaviour unchanged.

### Step 5.4 — lock the write-through set

- [x] Create `tests/ui/test_pg_canvas_backref_invariants.py`.
- [x] AST invariant, reusing audit appendix A-8: for each `_CanvasBackref`
      subclass, `self.X = ...` targets minus `_owned_names ∪ _delegate_names`
      must equal an explicit expected set. After Steps 5.1–5.3:

      ```python
      EXPECTED_WRITE_THROUGH = {
          "Renderer": {"_display_x_coverage", "_display_x_coverage_by_channel",
                       "_last_refresh_signature", "_refresh_pending",
                       "_y_overflow_wall_active"},
          "OverlayAxisManager": set(),
          "CursorController": set(),
          "TickDensityController": set(),
          "AnnotationManager": {"_last_rclick_scene_pos"},
          "QualityManager": set(),
      }
      ```

- [x] The test must also **fail on an unknown class name**, so a new
      `_CanvasBackref` subclass cannot slip through by omission.
- [x] Shadowing invariant: instantiate a real `TimeDomainCanvasPG` and assert
      every collaborator's `_delegate_names` is disjoint from `vars(canvas)` —
      the currently-lucky 0 becomes an enforced 0.
- [x] Prove the test bites: temporarily add a stray `self._probe = 1` to one
      collaborator, confirm the test fails naming `_probe`, then revert. Paste
      the failure output.
- [x] Run the full default suite (this task touches 8 source files); report
      `tests_before` / `tests_after`.

W3 verification: RED `4 failed / 2 passed`, GREEN `6 passed`; an injected
`Renderer.self._probe` failed naming `_probe` and was removed. Integrated W1–W3
scope is `487 passed / 1 deselected`. Cocoa harness exercised plot, profile
creation, annotation add/remove, clear, and dense redraw. Full default suite
completed on the clean retry with the exact same 64 failing node IDs as Task 0
and 64 additional passing tests.

**Acceptance:** the `_refresh` grep is empty; `_channel_render_profiles` is
`{}` after `__init__` and empty after `clear()` with zero `getattr` access left;
`_artist` lives on the manager; both invariant tests pass and demonstrably fail
when a write-through is added; full suite matches the Task 0 baseline; no
benchmark regression.

---

## Task 6 — W4 · Test coupling classification study

**Expert:** `refactor-architect` · **Files:** new
`docs/reports/2026-07-30-test-coupling-classification.md` **only** · **Depends
on:** Task 0 · **Parallel with:** Tasks 1–5

Read-only. **No production or test code changes.** The point is to replace an
unproven premise with data.

- [x] Enumerate the population: the 1,232 lines matching
      `grep -rn "assert [a-z_]*\._[a-z_]*" tests --include="*.py"`. Record the
      exact command and the count.
- [x] Stratify: S1 `tests/ui/test_pg_timedomain_canvas.py`; S2 other
      canvas-adjacent `tests/ui/*pg*`; S3 `tests/ui/test_chart_stack*.py`;
      S4 `tests/ui/` main-window / inspector / widgets; S5 everything outside
      `tests/ui/`.
- [x] Sample ≥30 per stratum (all of it where a stratum is smaller) with a
      **fixed seed recorded in the report**, so anyone can regenerate the same
      sample.
- [x] Classify each sampled assertion into exactly one label:
      **A** implementation-detail coupling (a public equivalent exists; would
      break on a pure move/rename);
      **B** intentional white-box invariant (performance state machine, cache
      key, render-internal invariant; no public equivalent; breaking it *should*
      be loud);
      **C** migratable to a behaviour-level assertion at reasonable cost.
- [x] For every sampled item record file:line, target attribute, stratum, label,
      and a one-line reason. Cite any `docs/lessons-learned/` entry that
      motivated the assertion — a B label backed by a lesson is the study's
      strongest evidence.
- [x] Coverage numbers are **optional** and need a new dependency: neither
      `pytest-cov` nor `coverage` is installed in `.venv`. **Ask the user before
      installing anything.** If approved, add
      `coverage run -m pytest tests/ui -q` plus a report scoped to
      `mf4_analyzer/ui/pg_canvas`.
- [x] Write the report with per-stratum A/B/C counts and confidence intervals,
      the seed and commands, 5–10 concrete examples per label, and an explicit
      yes/no answer to each of:
      1. Is a behaviour-level contract-test layer worth building, and for which
         surfaces?
      2. Is a `@pytest.mark.whitebox` rule for new tests justified, or would it
         just annotate category B everywhere?
      3. Is the `canvas.py` split actually test-blocked, or is that a myth the
         audit inherited?
- [x] State the limitations honestly: sample size, single-classifier subjectivity,
      and the fact that label A does not by itself prove a refactor was ever
      abandoned because of it.

**Acceptance:** report exists; ≥30 samples per stratum; the recorded seed
reproduces the sample; all three questions answered with a recommendation.
**A "no action needed" conclusion is a valid, useful result** — it retires a
premise that would otherwise justify weeks of refactoring.

---

## Task 7 — Documentation and lessons (main session + experts)

**Depends on:** the tasks each item refers to

- [x] `CLAUDE.md`: replace "`tests/`（164 个 pytest 用例，用 pytest-qt）" with a
      non-numeric description. Actual count is 3,714 test functions. **Do not
      touch the 12-View wording** — it was re-verified as correct
      (`CLAUDE.md:17` says *main time-domain*, `window.py:237` passes
      `max_views=12`, and `view_state.py:16-18` documents why the module default
      is 6 for the analysis sections).
- [x] `docs/lessons-learned/pyqt-ui/`: a display-label fallback on an
      identity-sensitive path reintroduces the exact multi-file same-name bug the
      composite-key storage class was built to fix (from Task 2).
- [x] `docs/lessons-learned/pyqt-ui/`: `dict.setdefault` bypasses an overridden
      `__contains__`, so a `dict` subclass with key aliasing gets a phantom
      bare-key entry that then masks the real ones (from Task 1).
- [x] `docs/lessons-learned/signal-processing/`:
      `np.convolve(mode='same')` returns `max(len(sig), ws)`, so any window
      parameter reachable from the UI needs a length clamp (from Task 3).
- [x] `docs/lessons-learned/refactor/`: an audit without a commit SHA cannot be
      acted on — two of this audit's headline numbers had drifted or were wrong
      when re-measured on a fixed baseline.
- [x] Add an index line for each new lesson in `LESSONS.md` (double-write per
      `CLAUDE.md`).
- [x] If Task 4 shipped `TRACELAB_LOG_DIR` / `TRACELAB_LOG_LEVEL`, document both
      plus the per-platform log paths under `docs/analyzer/`, and add the log
      location to the in-app help if it lists diagnostics.

Diagnostics are documented in `docs/analyzer/diagnostics.md` and routed from
`docs/analyzer/README.md`. The current in-app help does not list runtime
diagnostics, so no unrelated help-page section was added.
- [x] Update `docs/superpowers/specs/2026-07-30-robustness-remediation-phase1-design.md`
      **Status** to reflect what actually shipped, including anything reported
      `blocked`.

---

## Verification Log

Fill in as tasks complete. Numbers, not adjectives.

| Item | Baseline (Task 0) | After |
|---|---|---|
| Default suite pass/fail/skip | 4,053 passed / 64 failed / 8 skipped / 3 deselected | 4,117 passed / 64 failed / 8 skipped / 3 deselected; same 64 failing node IDs |
| Default suite wall time | 1,038.33 s pytest / 1,038.74 s process | 904.11 s pytest / 904.66 s process |
| `pg_canvas` broad `except Exception: pass` | 288 | 287 |
| `._refresh` write sites | 19 | 0 |
| `_channel_render_profiles` `getattr` touchpoints | 8 | 0 |
| A-6 triple | 1,232 / 894 / 47 | 1,236 / 912 / 47 |
| A-11 file-A axis after restore | (95.0000169803578, 204.9999830196422) | (-1.099999660392844, 1.099999660392844) |
| `moving_avg(3, ws=50)` output length | 50 | 3 |
| `integral` int-input dtype | int64 | float64 |
| `benchmark_timedomain_interaction.py` | initial 123.470 ms; pan p50/p95 8.091/8.178 ms; resize p50/p95 11.184/11.645 ms; checkbox callback/paint p50 2.039/9.757 ms | initial 112.299 ms; pan p50/p95 6.817/6.993 ms; resize p50/p95 9.340/9.385 ms; checkbox callback/paint p50 1.748/8.164 ms |
| Log dir resolved (this platform) | n/a | `~/Library/Logs/TraceLab` (Cocoa file/Qt warning/traceback verified) |

Integration limitation: the first final full-suite attempt reached 51% and
then hit a pre-existing Qt lifecycle failure (`ScientificReferenceSpinBox` was
deleted during `updateEditorGeometry`) followed by SIGSEGV. A fresh second run
completed to 100% and produced the exact Task 0 failure set shown above.

---

## Out of scope for Phase 1

Each with the reason it waits, so nobody re-litigates it mid-execution:

| Item | Why not now |
|---|---|
| Adding `logger.debug` to all 288 broad handlers | Many are per-frame; a persistently-firing exception becomes a log storm and a new stall. Task 4 instruments 5–10 named seams; the rest wait for a real signal in the logs |
| Narrowing broad `except Exception` clauses | Behaviour-changing; needs Task 4's logs to know which ones actually fire |
| Splitting `canvas.py` (4,042 lines / 158 methods) | Task 6 has not run, so "tests block it" is unproven; and without Task 4 there is no way to observe whether a split broke anything |
| Behaviour-level contract-test layer, `@pytest.mark.whitebox` rule | Gated on Task 6's answer |
| `_ChannelKeyDict` identity/label surface separation | `dict(d)` cannot be fixed by overriding — a plain dict physically cannot hold two equal display keys. Needs its own design document |
| `MainWindowProtocol` + mypy over the 8 mixins | No mypy baseline exists in the repo; introducing one is its own project |
| `_CanvasBackref.__setattr__` raising outside a whitelist | Let Task 5's whitelist test run for a while and collect real write-through churn first |
| `clear()` / `__init__` symmetry test | Depends on Task 5 settling `_channel_render_profiles`; otherwise the whitelist has to carve out a known defect |
| `ui/inspector_sections` silent-handler cleanup | Re-measurement: 34 of 37 are narrow `(TypeError, ValueError)` legacy-preset guards with docstrings. Only 3 are broad. Low value |
| `_applying_view` guard initialization | Real (no initializer anywhere; read only via `getattr(..., False)`), but it belongs with the mixin-protocol work, not here |
