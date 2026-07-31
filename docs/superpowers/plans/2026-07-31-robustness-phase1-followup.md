# Robustness Phase 1 Follow-up Punch List

> **For executors:** Steps use checkbox (`- [ ]`) syntax for tracking. The
> `Expert` labels are routing hints, not a requirement to mirror another
> tool's squad rules. The active runner follows `AGENTS.md` and may delegate
> only when its own instructions and the user authorize delegation.

**Goal:** Close the seven defects found in the independent review of Phase 1,
make suppressed-event accounting trustworthy through normal runtime and
shutdown, and reach **PROCEED TO WINDOWS ACCEPTANCE**. This plan alone cannot
declare the `--windowed` package safe to ship; that verdict requires a real
Windows build and foreground smoke.

**Why there is no companion spec:** This punch list corrects Phase 1 against its
existing acceptance contract rather than introducing a new product workflow.
Task 2 contains the only non-trivial state-machine choice and specifies it in
full below. If execution needs a different persistence model, logging policy, or
Python support policy, stop and create a separate dated spec instead of growing
this plan implicitly.

**Reviewed base commit:** `b5d7956eb8c80c7981d174ed92575e876d171c2b`.
**Reviewed working tree:** Phase 1 is uncommitted, so the base SHA alone does
not identify it. The 2026-07-31 review snapshot of all `*.py` files under
`mf4_analyzer/` and `tests/` has aggregate SHA-256
`2560a2fad1016f270391bba170e970c5b2fed13d0ad9f15e77a5a4a103ecb37b`;
Task 0 reproduces the exact command before any edit.
**Phase 1 plan:** `docs/superpowers/plans/2026-07-30-robustness-remediation-phase1.md`
**Phase 1 spec:** `docs/superpowers/specs/2026-07-30-robustness-remediation-phase1-design.md`
**Supersedes:** only the Phase 1 W1b oversized-window sketch and the W2
per-frame/rate-limit and suppressed-summary clauses. All other Phase 1 scope,
evidence, and non-goals remain historical and authoritative.
**Environment:** `.venv/bin/python` 3.12.13, Qt 5.15.14 / PyQt5 5.15.11,
pyqtgraph 0.14.0, numpy 2.5.1, pytest 9.1.1, pytest-qt 4.5.0, macOS 27.0 arm64.

---

## What the review confirmed (do not re-litigate)

These were verified independently and need no rework. Listed so nobody
"improves" them while fixing the items below.

| Verified | Method |
|---|---|
| W1a same-name Y-axis crosstalk is fixed | A pre-Phase-1 probe (not a Phase 1 test) went from `(95.0000169803578, 204.9999830196422)` to `(-1.099999660392844, 1.099999660392844)` |
| W3 `_refresh` fully deleted, four live `_refresh_*` names intact | `grep -rn "\._refresh\b"` empty; `_refresh_pending` 20, `_refresh_timer` 20, `_refresh_visible_data` 18, `_refresh_overlay_axis_labels` 5 |
| W3 `_channel_render_profiles` owned | zero `getattr` touchpoints; created `canvas.py:370`, cleared `canvas.py:2570` |
| W3 backref invariant test actually bites | Injected `self._probe = 1` into `QualityManager` on a temp copy; the scan reported `['_probe']` and the assertion failed |
| W2 wiring works end to end | Real `app.main()` run: log file created, Qt handler captured a live font warning, both excepthooks installed **and chaining**, an injected unhandled exception landed with a full traceback |
| W4 sampling is reproducible | Re-ran the recorded seed `20260730`; `manifest_sha256` matched byte for byte |
| `DenseDiscreteRasterLayer` / `QualityManager` direct attribute access is safe | Both are constructed only from `canvas.py:568-569` with a `TimeDomainCanvasPG` |

---

## Global Constraints

- Every run uses `.venv/bin/python` with `QT_QPA_PLATFORM=offscreen` and
  `PYTHONPATH=<repo>`.
- All 70 Phase 1 tests
  (`tests/ui/test_pg_channel_key_dict.py`, `tests/signal/test_channel_math.py`,
  `tests/test_diagnostics.py`, `tests/ui/test_pg_canvas_backref_invariants.py`,
  `tests/ui/test_pg_diagnostics_seams.py`,
  `tests/ui/test_pg_multifile_samename_curves.py`) must stay green. Baseline:
  `70 passed in 1.05 s` on the 2026-07-31 Codex recheck.
- No behaviour change to any instrumented seam's control flow.
- No new third-party dependency.
- The repository has no declared `requires-python` / `python_requires` floor.
  Task 1 removes an unnecessary 3.11-only API but must not invent or claim a
  supported minimum Python version.
- “Suppressed events are not lost” means a normal running process, throttle-key
  eviction, and orderly interpreter shutdown. `SIGKILL`, power loss, and a
  native crash cannot be made durable by an in-memory throttle and are not
  covered by this plan.
- If Task 0 does not reproduce both the base SHA and source/test-tree digest,
  stop and re-review the drift. Do not apply this punch list to a merely
  similar working tree.

---

## Task 0 — Revalidate the uncommitted review baseline

**Owner:** executing session · **Files:** none

- [x] Confirm `git rev-parse HEAD` is exactly
      `b5d7956eb8c80c7981d174ed92575e876d171c2b` and record
      `git status --short` without cleaning or absorbing unrelated files.
- [x] From the repository root, reproduce the reviewed source/test digest:

      ```bash
      find mf4_analyzer tests -type f -name '*.py' -print0 \
        | LC_ALL=C sort -z \
        | xargs -0 shasum -a 256 \
        | shasum -a 256
      ```

      Expected: `2560a2fad1016f270391bba170e970c5b2fed13d0ad9f15e77a5a4a103ecb37b`.
- [x] Run the exact six-file Phase 1 test command from Appendix A. Expected:
      `70 passed`; timing is informational.
- [x] Run the throttle micro-benchmark from Appendix A before edits and record
      all seven trials plus the median. The 2026-07-31 recheck was
      `165.8–237.9 ns/call`, median `197.4 ns/call`.

**Acceptance:** commit, working-tree digest, tests, and performance baseline are
recorded before implementation. Any mismatch is a review stop, not permission
to refresh the expected value silently.

---

## Task 1 — F1 · Remove the unnecessary Python 3.11-only startup API

**Expert:** `pyqt-ui-engineer` · **File:** `mf4_analyzer/diagnostics.py`

`diagnostics.py:63` calls `logging.getLevelNamesMapping()`, added in Python
**3.11**. No `requires-python` / `python_requires` is declared, and both Windows
build scripts select a generic `py -3` interpreter. The review did **not** prove
the whole application supports every older Python; the actionable fact is
narrower: this startup-only 3.11 dependency is unnecessary and can be removed
without changing behaviour.

Why it blocks Windows acceptance rather than being a nit:

- `_logging_level()` is called at `diagnostics.py:92`, **outside** the `try`
  block in `setup_logging`.
- `setup_logging()` is the **first statement** of `app.main()`
  (`app.py:72`).
- `tools/build_windows_folder.ps1:25-31` and
  `tools/build_windows_folder_lite.ps1:37-45` resolve the interpreter with
  `py -3` (falling back to whatever `python` is on PATH) — whichever Python 3
  the build machine happens to provide.
- The packaged build is `--windowed` (`build_windows_folder.ps1:272`), so there
  is no stderr.

On a 3.10 build machine that otherwise satisfies the application's syntax and
dependency requirements, the packaged app therefore dies at startup with an
`AttributeError` that nobody can see, and the diagnostics that would have
reported it are not installed yet. The observability floor would take the app
down.

- [x] Replace the `getLevelNamesMapping()` call with the bidirectional
      `logging.getLevelName()` lookup, which has existed since Python 3.4:

      ```python
      resolved = logging.getLevelName(text)
      return resolved if isinstance(resolved, int) else logging.INFO
      ```

      Verified behaviour: `getLevelName("INFO") -> 20`,
      `getLevelName("NOPE") -> 'Level NOPE'` (a `str`), so the `isinstance`
      guard is the whole check.
- [x] Add a test asserting `_logging_level` maps `"DEBUG"/"INFO"/"WARNING"/
      "ERROR"/"CRITICAL"`, a numeric string, an `int`, `None`, and an unknown
      name (→ `INFO`).
- [x] Add a behavioural regression guard: monkeypatch-delete
      `logging.getLevelNamesMapping` (with `raising=False`) and assert all named
      mappings still work. This simulates the missing API directly and avoids a
      brittle repo-wide denylist. Do **not** include `itertools.pairwise` in a
      “3.11+” list; it was introduced in Python 3.10.
- [x] Record “declare and enforce the supported Python range” as a separate open
      packaging-policy question. It is not solved by this compatibility fix and
      must not block the behaviour-preserving replacement.

**Acceptance:** `_logging_level` has identical values on the current runtime and
still passes when `logging.getLevelNamesMapping` is absent. The result removes
this specific 3.11-only dependency; it does not claim a project-wide Python
support floor.

---

## Task 2 — F2 · Quiet bursts must still be summarized

**Expert:** `pyqt-ui-engineer` · **File:** `mf4_analyzer/diagnostics.py`

`throttled` emits its "suppressed N occurrences" summary **lazily**, only when
the *next* call for the same key arrives after the window has expired
(`diagnostics.py:172-177`). Measured:

```
10,000 rapid failures on one key
  -> 3 records emitted, 9,997 counted as suppressed
  -> if that seam then goes quiet, the 9,997 are never reported
```

The Phase 1 spec's acceptance criterion — *"a seam failing 10,000 times
produces `BURST` records plus periodic summaries"* — therefore only holds while
failures keep arriving. This matters because W2's purpose is to **size**
problems, not merely detect them: a burst that ends looks identical to three
isolated events.

### Design

Three options were considered:

1. **Sweep every call.** Correct but O(`MAX_KEYS`) on a path that can run per
   frame. Rejected.
2. **`atexit` flush only.** Cheap, but a burst in hour 1 of a multi-day session
   is not reported until shutdown. Insufficient alone.
3. **Amortized time-boxed sweep + `atexit` flush.** Accepted.

Accepted design: keep a module-level `_last_sweep` timestamp. On each
`throttled` call, if `now - _last_sweep >= WINDOW`, take the lock once, walk
`_THROTTLE_STATE` (bounded at `MAX_KEYS = 512`), reset every expired key's
window, and collect a summary for those with a non-zero suppressed count. Each
expired state becomes `[now, 0, 0, logging.NOTSET]`; then set
`_last_sweep = now`. The current call
then runs against the reset state and becomes the first emitted record in its
new burst. Emit all collected summaries **after releasing the lock**. Amortized
cost is at most 512 iterations per 60 s.

The same collector must cover two non-periodic loss paths:

- `flush_throttle_summaries()` collects every non-zero suppressed count without
  waiting for window expiry and zeroes only that count. Register it with
  `atexit` exactly once; repeated `setup_logging()` calls must not register
  duplicate exit hooks.
- Oldest-first eviction must emit the evicted entry's pending count instead of
  silently dropping it. The summary reason must distinguish `window`,
  `shutdown/manual flush`, and `eviction`; do not claim “in 60 s” for a flush
  that happened earlier.

This requires each state to remember its level, because a sweep may be triggered
by another key. Change the state list from
`[window_start, emitted, suppressed]` to
`[window_start, emitted, suppressed, level]`. Reconstruct the logger with
`logging.getLogger(logger_name)` outside the lock rather than retaining logger
objects in the bounded map. If a key is called with different levels, retain
the highest severity for its pending summary. After that window is summarized,
reset the remembered level to `logging.NOTSET` so a new window cannot inherit an
old severity.

One control-flow trap is explicit: the current suppressed branch returns from
inside the lock. After adding cross-key sweeps, it must instead defer that
return until collected summaries have been emitted; otherwise a suppressed
current key can discard summaries collected for other keys.

- [x] Write the failing test first: fire 10,000 events on one key, advance the
      clock past `WINDOW` (monkeypatch `diagnostics._monotonic`), fire **one
      event on a different key**, and assert the first key's summary was
      emitted with the count `9997`.
- [x] Add the second failing test: fire a burst, advance the clock, and call
      `flush_throttle_summaries()` directly — assert the summary appears with
      no further `throttled` call at all.
- [x] Extend the state list with the level; keep the comment describing the
      slots accurate, and update the autouse test fixture to reset the map and
      `_last_sweep`. Do not blindly reset a process-wide atexit-registration
      flag: either preserve it across tests or call `atexit.unregister` before
      resetting it.
- [x] Implement the time-boxed sweep as designed. Collect under the lock, emit
      outside it, and leave no early return capable of discarding an already
      collected cross-key summary.
- [x] Add a public `flush_throttle_summaries()` and register it with
      `atexit` exactly once from `setup_logging()`, so a burst before orderly
      shutdown is still accounted for. Test repeated `setup_logging()` calls do
      not duplicate registration or summaries.
- [x] Add an eviction regression test: fill `MAX_KEYS`, create a pending
      suppressed count on the oldest key, insert one more key, and assert the
      evicted count is summarized once with reason `eviction`.
- [x] Test that a manual flush before `WINDOW` does not describe the count as a
      full 60-second window and that a second flush emits no duplicate.
- [x] Confirm the suppressed-path cost has not regressed: re-run the 200,000
      iteration × seven-trial micro-benchmark from Appendix A and record every
      trial plus the median. Gate: median ≤2× the Task 0 median and <1 µs/call.

**Acceptance:** a burst that stops still reports its suppressed count exactly
once via a later cross-key sweep, manual/orderly-shutdown flush, or key eviction;
no logging call occurs while `_THROTTLE_LOCK` is held; the measured median meets
the explicit performance gate.

---

## Task 3 — F3 · Keep third-party INFO chatter out of the diagnostics file

**Expert:** `pyqt-ui-engineer` · **File:** `mf4_analyzer/diagnostics.py`

`setup_logging` sets the root logger to `INFO` (`diagnostics.py:96-98`) and the
file handler to the same level (`:125`), so every third-party library's INFO
records land in the rotating file. Confirmed in a **real** `app.main()` startup,
not a synthetic test — the second line written was:

```
INFO [MainThread] numexpr.utils: NumExpr defaulting to 10 threads.
```

`asammdf`, `PIL`, `h5py`, `matplotlib`, and `numexpr` are all enabled at INFO.
`asammdf` in particular is chatty during MF4 import, so the 30 MiB rotation
budget can be spent on noise and roll the actual diagnostics out of the file —
defeating W2's purpose.

### Design

Filter, do not enumerate. An allowlist of library names goes stale the moment a
dependency is added. Attach a filter to the **file handler only** that passes a
record when either condition holds:

```python
(
    record.name == "mf4_analyzer"
    or record.name.startswith("mf4_analyzer.")
    or record.levelno >= logging.WARNING
)
```

Third-party warnings and errors — which you *do* want — still land. Their INFO
and DEBUG chatter does not. The boundary-aware prefix avoids admitting an
unrelated logger such as `mf4_analyzer_plugin`. The stderr handler is already
pinned at `WARNING` and needs no change. The Qt bridge logs under
`mf4_analyzer.diagnostics`, so it passes the package clause.

- [x] Write the failing test: after `setup_logging` into a `tmp_path`, an INFO
      record from a `numexpr.utils` logger must **not** appear in the file,
      while a WARNING from the same logger and an INFO from an
      `mf4_analyzer.*` logger both must. Also assert INFO from the lookalike
      `mf4_analyzer_plugin` is rejected.
- [x] Implement the filter and attach it to the file handler.
- [x] Verify against a real startup, not only the unit test: run `app.main()`
      with `QApplication.exec_` stubbed and confirm the `numexpr` INFO line is
      gone while `Diagnostics initialized:` remains.

**Acceptance:** third-party INFO/DEBUG is excluded from the file; third-party
WARNING and above still lands; `mf4_analyzer.*` INFO is unaffected.

---

## Task 4 — F5/F6/F7 · Three small corrections

**Experts:** `signal-processing-expert` (4.1) · `pyqt-ui-engineer` (4.2, 4.3)

These are independent and may be done in any order.

### 4.1 — `moving_avg` boundary semantics are undocumented

`signal/channel_math.py`. The implementation special-cases `ws >= sig.size` and
returns `np.full(shape, sig.mean())`. **This is the correct choice** — the
Phase 1 spec's implementation sketch (clamp `ws`, then convolve) contradicted
the spec's own test requirement, because `mode='same'` zero-pads and therefore
attenuates the edges instead of producing a flat mean. Codex resolved the
contradiction in favour of the stated semantics.

What is missing is that the resulting discontinuity is invisible: `ws == n - 1`
returns an edge-tapered curve, `ws == n` returns a flat line.

- [x] Add a comment on the `ws >= sig.size` branch stating the choice and why
      convolution cannot express it.
- [x] Add a test pinning both sides of the boundary: `ws == n - 1` is **not**
      constant, `ws == n` **is** constant and equals `sig.mean()`.

### 4.2 — Redundant lookup in `_fit_channel_y_to_visible_x`

`canvas.py:2092-2102`. `row = self.channel_data.get(channel_key)` runs before
`resolve_unique`, then is discarded and re-fetched whenever
`resolved_key != channel_key`. Harmless, but it makes the fail-closed logic read
as though the first lookup matters.

- [x] Resolve first, then fetch once by the resolved key. Keep the existing
      comments explaining why an ambiguous label fails closed — they are the
      valuable part.
- [x] `tests/ui/test_pg_multifile_samename_curves.py` must stay green
      unmodified.

### 4.3 — An unhandled crash is announced as an `info` toast

`app.py:94` passes `window.toast` bare, and `toast(msg, level='info')`
(`window.py:551`) defaults accordingly. So a process-level unhandled exception
gets the same visual weight and 3.5 s hold as "游标已重置".

The toast widget supports `info` / `success` / `warning` / `error`
(`ui/widgets/__init__.py:1679`), and `error` holds for 7 s.

- [x] Pass an error-level notifier, e.g.
      `install_excepthooks(on_error=lambda text: window.toast(text, "error"))`.
- [x] Keep `install_excepthooks`'s existing `except BaseException: pass` around
      the notify call — a deleted C++ window must not mask the original error.
- [x] Update `test_app_main_wires_diagnostics_in_required_order`: it currently
      asserts that `on_error` is the bare bound `window.toast` method. Capture
      the callback, invoke it with a probe message, and assert the fake window
      receives `(message, "error")`. Keep the existing startup-order assertions.

---

## Task 5 — F4 · Add explicit Phase 1 errata (docs only)

**Owner:** documentation owner · **Files:** the two Phase 1 documents

The Phase 1 plan's Global Constraints forbade instrumenting per-frame paths,
while the same spec listed `_sync_x_axis_item_range` as sanctioned seam #6.
Those contradict each other, and the seam **is** per-frame:

```
sigXRangeChanged -> _on_xrange_changed (canvas.py:3153)
                 -> _propagate_xlim_to_siblings
                 -> _sync_x_axis_item_range        (once per sibling axis, per drag tick)
```

This is a defect in the Phase 1 documentation, not in the implementation.
Measured impact is negligible, so the seam stays. Preserve the dated Phase 1
documents as historical evidence: add clearly labelled
`Correction (2026-07-31)` blocks that point to this follow-up instead of
silently rewriting the original claim as though it had always been correct.

```
throttled suppressed path : median 197.4 ns/call (7 trials)
60 fps x 8 axes, persistently failing : 480 calls/s = 94.8 us/s CPU (0.01%)
```

- [x] Add a correction immediately after the Phase 1 plan's original Global
      Constraint: a per-frame path may be instrumented **only** when the call is
      rate-limited, the suppressed-path cost is measured, and the exact seam is
      named. Retain the original text and link the correction to this plan.
- [x] Add the same correction to Phase 1 spec §5.4, including the two measured
      values above, so sanctioned seam #6 has an evidence-backed exception.
- [x] Add a correction beside the Phase 1 spec §5.2 `moving_avg` sketch: the
      sketch's clamp-plus-convolve result contradicts the acceptance test for
      `ws >= len(sig)`; Phase 1 intentionally followed the flat whole-signal
      mean semantics. Show the shipped branch, not another pseudocode variant.
- [x] Near the top of this follow-up, keep the references to both Phase 1
      documents and state that this plan supersedes only their W1b boundary and
      W2 rate-limit/documentation clauses, not the rest of Phase 1.

---

## Task 6 — Integrated verification and truthful handoff

**Owner:** executing session · **Files:** no new production scope

- [x] Run the exact six-file Phase 1/follow-up command in Appendix A. All tests,
      including the newly added cases, must pass; record the new total.
- [x] Run `tests/test_diagnostics.py` once more in a fresh pytest process to
      catch leaked root handlers, throttle state, `_last_sweep`, or atexit
      registration state.
- [x] Repeat the real `app.main()` startup probe from Task 3. Record separately:
      log creation, absence of third-party INFO, presence of
      `Diagnostics initialized:`, Qt warning capture, both exception hooks, and
      error-level toast delivery.
- [x] Run the Appendix A micro-benchmark after all changes and evaluate the
      explicit Task 2 threshold against Task 0's median.
- [x] Run one clean default suite. If it completes, compare failing node IDs to
      the Phase 1 baseline of 64; any new failing node ID is `NEEDS REWORK`. If
      the known Qt lifecycle SIGSEGV recurs,
      preserve the faulthandler evidence and report the full-suite gate as
      `UNVERIFIED`; a focused green run must not be presented as a full-suite
      pass. Do not loop until a lucky green result hides intermittency.
- [x] Run `git diff --check`, compile the changed Python modules, and run
      `/usr/bin/python3 scripts/lessons/check.py --doctor --verbose` plus the
      project lesson completion gate.
- [x] Report the final status as one of:
      `PROCEED TO WINDOWS ACCEPTANCE`, `NEEDS REWORK`, or `BLOCKED`. Never use
      `safe to ship` until a real Windows `--windowed` artifact has passed its
      foreground startup and crash-log smoke.

### External Windows release gate (not runnable on this macOS host)

- [ ] On Windows, record the exact interpreter chosen by the build script and
      build the intended full or lite `--windowed` artifact.
- [ ] Start that artifact in the foreground, confirm the UI opens, and verify
      the rotating file under `%LOCALAPPDATA%\TraceLab\logs` contains
      `Diagnostics initialized:` without third-party INFO chatter. Do not claim
      an unhandled-crash path was tested unless a deliberate safe injection was
      actually performed.
- [ ] In the Windows source environment, run the focused diagnostics tests and
      a subprocess that creates a pending suppressed count then exits normally;
      confirm the atexit summary reaches the file. Record this source-side proof
      separately from the packaged artifact/version/hash proof.

---

## Verification Log

| Item | Revalidated value (2026-07-31) | After |
|---|---|---|
| Base commit | `b5d7956eb8c80c7981d174ed92575e876d171c2b` | unchanged |
| Source/test-tree SHA-256 | `2560a2fad1016f270391bba170e970c5b2fed13d0ad9f15e77a5a4a103ecb37b` | `a30acc926aa8536e6e3fb724722174a3cda310b4727623cfb7d788301b9072b7` |
| Phase 1/follow-up test files | 70 passed in 1.32 s | 82 passed in 0.97 s |
| `tests/test_diagnostics.py` fresh process | 13 passed before follow-up | 23 passed in 0.11 s |
| `throttled` suppressed path | trials `199.5, 194.6, 211.9, 192.6, 195.1, 198.7, 201.6`; median 198.7 ns/call | trials `253.7, 253.3, 409.0, 257.6, 255.6, 246.5, 249.8`; median 253.7 ns/call (1.28×, PASS) |
| Persistent per-frame failure cost | ≈95.4 µs/s at 480 calls/s (≈0.01% of one core) | ≈121.8 µs/s (≈0.012% of one core) |
| 10,000-event quiet burst | 3 emitted / 9,997 pending but unreported | 3 burst records + one exact 9,997 summary; manual, shutdown, and eviction paths pinned |
| Third-party INFO in log file | present (`numexpr.utils`) | excluded; third-party WARNING and `mf4_analyzer.*` INFO retained |
| A-11 crosstalk probe | `(-1.0999, 1.0999)` — fixed | unchanged; 405 TimeDomain/Y-fit/seam tests passed, 1 deselected |
| Startup smoke (`app.main()`) | log + Qt handler + both hooks OK | initialization, Qt warning, both tracebacks/hooks, error toasts, and INFO filter verified |
| `diagnostics.py` logging API floor | **3.11** (unnecessary); project support floor undeclared | `getLevelNamesMapping` removed; missing-API simulation passes; support floor still undeclared |
| Default suite | Phase 1 complete run: 64 failed / 4,117 passed / 8 skipped / 3 deselected | `UNVERIFIED`: known `ScientificReferenceSpinBox` teardown SIGSEGV recurred at 51%; no retry loop |

**Final local status:** `PROCEED TO WINDOWS ACCEPTANCE`. All follow-up-focused,
signal, TimeDomain, startup, performance, static, and lessons gates passed. The
default-suite result remains explicitly `UNVERIFIED` because of the reproduced
pre-existing Qt lifecycle crash, and the external Windows checkboxes below
remain open.

---

## Out of scope — but you will hit it

**The default suite intermittently segfaults on this machine at ~51%; current
evidence does not attribute it to Phase 1.**

```
exit 139 (SIGSEGV)
RuntimeError: wrapped C/C++ object of type ScientificReferenceSpinBox has been deleted
  mf4_analyzer/ui/db_reference_dialog.py:117  updateEditorGeometry
Fatal Python error: Segmentation fault
  pytestqt/plugin.py:220 in _process_events
```

Evidence of intermittency: `db_reference_dialog.py` is untouched by Phase 1;
one final Phase 1 run crashed at 51%, while a fresh second run completed with
`64 failed, 4117 passed, 8 skipped, 3 deselected` and the same 64 baseline
failing node IDs. The independent review later hit the same crash after 2,195
tests and 6 failures. A clean completion does not erase the crash, and a crash
does not prove that every run is impossible.

Consequences, stated plainly:

- Phase 1's headline claim — *the same 64 pre-existing failing node IDs, plus
  64 new passing tests* — was produced by one complete run but was not
  independently reproduced by the later reviewer. Keep both evidence classes.
- Until the lifecycle crash is fixed, the suite is not a reliable local commit
  hook on this machine. Whether a separate CI environment is reliable remains
  unverified, not disproven.

Also still unrun, and acknowledged as such by the Phase 1 spec: **Windows
`--windowed` packaging**. This follow-up may clear the code-review blockers, but
only Task 6's external Windows gate can clear release acceptance.

The repository's supported Python range is also still undeclared. This
follow-up removes the unnecessary `logging.getLevelNamesMapping()` dependency
but does not choose or enforce a packaging policy; that remains a separate
owner decision.

Other deferrals are unchanged from the Phase 1 plan's own "Out of scope"
table — in particular, W4 concluded that `canvas.py` is **not** test-blocked
(canvas-adjacent category A at 3.6%, 95% upper bound 8.2%), so that premise
should be retired rather than carried forward.

---

## Appendix A — Exact local verification commands

Run from the repository root. These commands are part of the plan contract;
record deviations instead of silently substituting another interpreter or test
scope.

### A.1 Phase 1/follow-up focused suite

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" \
  .venv/bin/python -m pytest -q \
  tests/ui/test_pg_channel_key_dict.py \
  tests/signal/test_channel_math.py \
  tests/test_diagnostics.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_pg_diagnostics_seams.py \
  tests/ui/test_pg_multifile_samename_curves.py
```

### A.2 Suppressed-path micro-benchmark

```bash
PYTHONPATH="$PWD" .venv/bin/python - <<'PY'
import logging
import statistics
import timeit

from mf4_analyzer import diagnostics

logger = logging.getLogger("bench.diagnostics.throttle")
logger.handlers[:] = [logging.NullHandler()]
logger.propagate = False
logger.setLevel(logging.CRITICAL)
diagnostics._THROTTLE_STATE.clear()
if hasattr(diagnostics, "_last_sweep"):
    diagnostics._last_sweep = diagnostics._monotonic()
for _ in range(diagnostics.BURST + 1):
    diagnostics.throttled(logger, "stable", logging.WARNING, "failure")

statement = (
    "diagnostics.throttled(logger, 'stable', logging.WARNING, 'failure')"
)
seconds = timeit.repeat(statement, repeat=7, number=200_000, globals=globals())
ns_per_call = [value / 200_000 * 1e9 for value in seconds]
print("ns/call:", [round(value, 1) for value in ns_per_call])
print("median:", round(statistics.median(ns_per_call), 1))
PY
```

### A.3 Static and full-suite gates

```bash
git diff --check
.venv/bin/python -m py_compile \
  mf4_analyzer/diagnostics.py \
  mf4_analyzer/app.py \
  mf4_analyzer/signal/channel_math.py \
  mf4_analyzer/ui/pg_canvas/canvas.py
/usr/bin/python3 scripts/lessons/check.py --doctor --verbose
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" \
  .venv/bin/python -m pytest -q
```
