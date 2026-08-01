# Progress: Vector/XCP Readiness Review Remediation

## 2026-08-01 TimeDomain Per-Source Custom X-Axis Planning

- Completed a plan-only analysis at `07c73e5`; no application source or tests
  were changed.
- Wrote `docs/superpowers/plans/2026-08-01-timedomain-per-source-custom-xaxis.md`.
- The plan explicitly covers the user clarification: unequal source lengths
  can overlay correctly when every source supplies its own aligned X/Y pair in
  the same physical X coordinate system; partial failures become chart-level
  diagnostics rather than an all-or-nothing error.
- The planning skill has `check-complete.sh` rather than the initially assumed
  `.py` checker; no planning content was affected.
- Reviewed Claude's updated plan with two independent read-only agents.  Both
  found the core architecture sound and no P0, but identified P1 ambiguities;
  the formal plan now closes them and is ready for three owned workstreams.
- Dispatched three non-overlapping implementation agents: resolver/Inspector,
  View/project migration, and runtime/diagnostics.  All are TDD-first, use the
  current worktree with the main checkout interpreter, do not touch Batch, and
  will not commit.
- Workstream A completed: pure resolver/spec/issue/unit-cohort helpers and the
  tagged Inspector payload are GREEN (`219 passed in 8.21s`); py_compile and
  `git diff --check` passed.
- Workstream B completed: resolver-aware View/project/channel-scope migration
  is GREEN (`72 passed` UI state suite and `15 passed` project I/O); py_compile,
  diff check, and its lessons gate passed.
- Workstream C completed: custom-X focused `14 passed`, TimeDomain canvas
  `384 passed, 1 deselected`, and filter/cache/hotpath `35 passed`.  Its full
  smoke run was `119 passed, 2 failed`; both failures are pre-existing
  dB-reference/attachment cases outside this feature.  Split-focus also still
  exposes the pre-existing empty-attached-View test-helper baseline.
- First combined directed invocation incorrectly mixed root and nested UI test
  paths, so pytest skipped `tests/ui/conftest.py` for later UI files; reran the
  UI suite separately and obtained `829 passed, 1 deselected, 20 known baseline
  failures`, plus `15 passed` for project I/O.
- Independent integration review then found two feature P1s: pre-filter unit
  cohort selection and blank-unit fallback.  The first full-repository run was
  intentionally terminated around 68% so those defects can be fixed before a
  meaningful final regression run.

## 2026-07-11

- Reviewed Terra branch `04591e57` against real pyxcp 0.29.10 package shapes,
  the acquisition state machine, A2L propagation, build scripts, and evidence
  runbook.
- Re-ran the focused acquisition suite: `132 passed, 1 skipped in 18.34s`.
- Issued `DO NOT PROCEED TO BENCH / NEEDS REWORK` because critical API,
  authentication, conversion, state invalidation, and Windows evidence gates
  remain open.
- Loaded acquisition evidence, native import, phantom API, backend
  invalidation, lazy parser, plan/spec, runtime-entrypoint, and documentation
  routing lessons.
- Replaced stale porcelain-surface planning files in this isolated worktree
  with the current Vector/XCP remediation state.
- Error recorded: initial lesson lookup used an obsolete filename; corrected to
  `codex-lazy-parser-import-boundaries.md`.
- Next: dispatch non-overlapping implementation agents for protocol/auth,
  diagnostics, and A2L/state correctness.

### Workstream A1/A2 — pyxcp CONNECT and DAQ protection

- Added a red-first regression using pyxcp 0.29.10's structured
  `response.resource`; the pre-fix probe failed at `int(response.resource)`.
- Replaced the opaque resource byte with named CONNECT resource facts and made
  every successful CONNECT execute GET_STATUS, including malformed-resource
  and no-provider paths.
- Added explicit DAQ protection outcomes (`unprotected`, `locked`, `unlocked`,
  `unknown`), post-UNLOCK verification, and red results for locked DAQ without
  a provider or uncertain GET_STATUS facts.
- Removed the guessed custom ctypes Seed&Key DLL ABI and delegated locked DAQ
  to pyxcp 0.29.10's official `master.cond_unlock("DAQ")`, with GET_STATUS
  verification before and after. The real package contract pins
  `cond_unlock(self, resources)` and DAQ `RESOURCE_VALUES` category `0x04`.
- Focused verification: `45 passed, 2 skipped in 7.22s`; both skips are the
  Windows-only real-package contract on macOS. Owned-file `git diff --check`
  and native-import/unrestricted-MagicMock greps passed.
- Dispatched three parallel agents with non-overlapping file ownership for
  protocol/auth, Vector diagnostics/decoder outcomes, and A2L/selection state.
- Audited the Windows verifier, runtime smoke, runtime hook, build script, and
  entrypoint. Confirmed the exact frozen-safe isolated probe, distribution
  metadata, dependency closure, and exe-name alignment remain open for the
  packaging workstream after the first agent wave.
- Integration review corrected diagnostics fact semantics: policy errors are
  not bus errors, total queue loss reaches `BackendStatus`, raw DTO arrival is
  separate from last valid sample, and bus errors are marked unobservable.
- Verified the A2L RAT_FUNC direction against ASAM MCD-2 MC; the agent's
  affine inverse is correct and nonlinear/table/formula conversions remain
  fail-closed.
- Found and rejected the historical custom four-argument Seed&Key DLL ABI.
  Assigned the protocol agent to delegate to pyxcp 0.29.10
  `Master.cond_unlock("DAQ")` and its official DLL adapter instead.
- Completed all agent workstreams without commits. The custom Seed&Key ctypes
  path was removed and the real-contract/verifier/smoke surfaces now pin
  `Master.cond_unlock(self, resources)`.
- Unified focused integration suite passed: `180 passed, 3 skipped in 17.18s`.
- Broader Acquisition/Cockpit suite covered 664 tests and exited 0:
  `663 passed, 1 skipped`; the skip is the opt-in real-A2L gate.
- `git diff --check`, native eager-import scan, retired Seed&Key ABI scan, and
  stale runbook identifier scan passed.
- Promoted lesson `codex-pinned-protocol-adapters-own-vendor-abi`; lesson gate
  is clear.
- Windows W1/W2 and physical ECU/Vector gates remain BLOCKED by host/hardware,
  with exact commands and evidence paths in the runbook.
- Final adversarial review found repeated Vector backend start did not reset
  old runtime/queues/counters; assigned a focused backend lifecycle fix.
- Final frozen-path review found A2L subprocess dispatch still depended on
  CPython `-m` semantics and pya2l vendoring lacked metadata/dependencies;
  assigned a hidden frozen A2L child plus exact pya2ldb closure fix.
- Independent review found the no-Seed&Key path wrote `None` into pyxcp's
  non-null Unicode trait. Assigned normalization to `""` plus a strict/real
  config-trait regression; the permissive SimpleNamespace fake was not
  accepted as evidence.
- Independent review found transport/A2L mutation could leave an invalidated
  owned Vector session in CONNECTED_IDLE or even stop it during RECORDING.
  Assigned strict active-state guards and full disconnect/reset semantics.
- Independent review found unknown-PID/decode/policy counters were absent from
  the UI DAQ gate. Assigned red/NO-GO health propagation so a later valid DTO
  cannot erase an earlier session error.
- Independent review found editable sample-point percentages were silently
  ignored because pyxcp requires clock-specific timing facts. Assigned a
  driver-automatic/disabled truthful UI plus fail-closed non-default overrides.
- Independent review found packaged smoke checked an adapter symbol without
  constructing real config/policies. Assigned no-hardware construction using
  pyxcp's actual config factory so trait mismatches fail W2.
- Closed repeated-start lifecycle with old resource release, queue/counter
  reset, per-thread captured session state, failed-start retry, and idempotent
  stop tests.
- Closed frozen A2L packaging with source/frozen child routing, exact
  `pya2ldb==1.0.332` metadata/dependency vendoring, Qt-loaded import probe, and
  a real one-signal A2L parse/pickle/fact probe in packaged runtime smoke.
- Closed runtime truth gaps: absent Seed&Key normalizes to `""`, sample-point
  controls are driver-automatic/disabled with non-default legacy values failing
  closed, and smoke constructs real pyxcp config plus DAQ policies without
  opening Vector.
- Closed Cockpit configuration/DAQ gates: transport/A2L changes fully
  disconnect idle Vector, active/review mutations are rejected, and any
  unknown-PID/decode/policy/overflow fact keeps DAQ red and Record disabled.
- Independent closure review marked all seven P0/P1 groups code-level
  `RESOLVED`; frozen Windows artifact execution remains W2 `UNKNOWN`.
- Final verification: focused `204 passed, 4 skipped in 19.27s`; broad
  Acquisition/Cockpit 700 tests exit 0 (`699 passed, 1 skipped`); full
  collection `3211/3214 collected (3 deselected)`; diff/lesson/import/ABI
  checks passed.

### Workstream B — Vector diagnostics and DTO outcomes

- Added a red-first structured DTO outcome contract while preserving the
  existing `decode_dto()` iterator API for compatibility.
- Moved Vector-only diagnostics off `FakeRecorderBackend` and onto the real
  Vector backend with synchronized snapshots for DTO/sample counts, queue
  depth/high-water/overflow, unknown PID, decode/policy errors, and last error.
- Kept DAQ ingress and sample emission bounded/non-blocking; malformed DTOs no
  longer silently disappear or terminate decoding of later valid frames.
- Added frozen-executable probe command selection: frozen builds use the
  hidden child flag while source runs retain the `-c` import probe.
- Focused verification: `27 passed in 2.56s`; owned-file `git diff --check`
  passed. A wider 176-test run reached `174 passed` with only the two expected,
  concurrently implemented A2L conversion and selection-invalidation red
  gates outside this workstream.
- Follow-up semantic review separated policy read failures from CAN bus-error
  facts, made `BackendStatus.queue_overflow_count` the non-duplicated sum of
  frame and sample queue drops, and kept `last_frame_monotonic()` tied only to
  successfully enqueued samples. Raw DTO arrival is exposed separately as
  `last_dto_monotonic_s`. Updated focused verification: `29 passed in 3.09s`.
- Final fact gate makes the source import probe fail closed if Qt cannot load
  before pyxcp, and marks CAN bus-error observation explicitly unavailable
  (`bus_error_observable=False`, `bus_state=None`) because pyxcp 0.29.10 does
  not forward python-can receive errors to the policy. Focused verification
  remained `29 passed` (`3.04s`).
- Repeated Vector backend `start()` now creates a clean capture boundary:
  previous session/runtime/decode-thread resources are released best-effort,
  the bounded sample queue is drained without changing capacity, and policy,
  counters, high-water marks, last error, and last valid-frame time are reset.
  Failed starts retain their error for diagnosis but the next retry clears it;
  `stop()` is idempotent. Updated focused verification: `31 passed in 3.82s`.

### Workstream C — A2L value correctness and selection ownership

- Added red-first parser regressions for `ECU_ADDRESS_EXTENSION`, LINEAR
  coefficients, affine/invertible RAT_FUNC coefficients, and explicit
  unsupported nonlinear/table/formula conversions while preserving the lazy
  `pya2l` import boundary.
- Propagated address extension and affine scale/offset through
  `MeasurementSummary` into `DaqMap`; DAQ construction now fails closed for an
  unsupported conversion instead of silently substituting identity.
- Pinned the known battery-voltage contract `0.015625 V/bit`: raw `640` maps to
  `10.0 V`, and the same upstream facts reach the ODT entry used by DTO decode.
- Connected measurement/event edits now immediately stop and invalidate a
  Cockpit-owned Vector backend, return the state machine to Disconnected, and
  require reconnect before Record. Caller-injected fake/replay behavior keeps
  the existing debounced live-selection restart.
- Ran both local CANape-generated A2Ls through the real crash-isolated pya2l
  subprocess. Each exposed 323 measurements; the full B-side pass reported
  323 supported, zero unsupported, address extension zero for all 323, and the
  battery signal at `0x60007e98` with scale `0.015625`, offset `0`, unit `V`.
- Nonzero address extension is covered by structured parser/DAQ tests but not
  by those two real A2Ls. Non-affine RAT_FUNC, FORM, TAB_INTP/TAB_VERB and
  other nonlinear dialects remain intentionally blocked rather than decoded.
- Focused verification: `73 passed, 1 skipped in 5.97s`; the skip is the
  opt-in `P0_A2L_PATH` probe. Full collection succeeded with `3186/3189 tests
  collected (3 deselected)` in 17.86s. `git diff --check` passed.

### Workstream A3/D2 — isolated verification and frozen packaging

- Added red-first verifier tests for native probe crash and timeout; source
  evidence now runs the production Qt-loaded pyxcp child probe and records its
  exact command, return code, stdout, and stderr before any in-process pyxcp
  import.
- Added the frozen-only `--pyxcp-import-probe-child` entrypoint. Packaged smoke
  reuses the production probe, then verifies pinned distribution metadata and
  Master signatures and constructs real pyxcp config plus DAQ policies without
  constructing a Master or touching a Vector channel.
- Replaced package-directory-only copying with pinned acquisition
  `pip --target` vendoring, requiring `pyxcp-0.29.10.dist-info` and retaining
  the resolved dependency closure for `importlib.metadata` and runtime imports.
- Unified the default executable as `TraceLab7.5.exe` and runtime evidence under
  `docs/analyzer/acquisition/evidence/vector-xcp/`; the runbook explicitly
  remains `BLOCKED` pending Windows source/frozen and physical ECU evidence.
- Full D1 plus verifier/smoke regression: `165 passed, 3 skipped in 15.92s`;
  skips are the two real pyxcp/Vector Windows package contracts and the opt-in
  real-A2L path gate that cannot run in this macOS job. Owned-file
  `git diff --check` passed; no Windows PASS evidence was fabricated.
- Frozen follow-up replaced the invalid `TraceLab.exe -m ...` A2L parser launch
  with `--a2l-probe-child`, preserving pickle stdout/stderr/exit-code behavior.
  A strict Qt-loaded `--pya2l-import-probe-child` now gates packaged smoke.
- Pinned `pya2ldb==1.0.332`; build vendoring now uses that installed exact
  version with `pip --target`, validates pya2l plus dist-info, and retains its
  dependency closure instead of copying only the package directory.
- Normalized absent Seed&Key to the pyxcp trait's required empty string while
  preserving real DLL paths. Packaged smoke now constructs the real pyxcp
  application config plus discard/bounded policies without constructing a
  Master or opening Vector, closing the prior callable-only false green.
- Sample-point controls are disabled and labelled driver automatic;
  diagnostics state `sample_point_applied=False`, and non-default legacy 75/70
  overrides fail closed instead of being silently ignored.
- Final expanded D1/packaging/UI regression: `193 passed, 4 skipped in 19.74s`.
  Skips are three Windows-only real-package contracts and the opt-in real-A2L
  gate. Global `git diff --check` passed; Windows W2 remains `BLOCKED`.
- Closure adds a real parser-child round trip to packaged smoke: it writes a
  one-measurement A2L to a temporary directory, obtains the command only from
  `_a2l_subprocess_command`, launches the source/frozen child, unpickles an
  `A2LSummary`, and verifies `RuntimeSmokeSignal`/`0x1000`/`UWORD`. Crash,
  invalid-pickle, and success results are independently tested and retained as
  `a2l_parse_probe` JSON.
- The exact fixture also passed locally through real `pya2ldb==1.0.332` and the
  source child (`returncode=0`, one measurement, 458 pickle bytes); this is not
  substituted for the still-blocked Windows frozen run. Final regression:
  `197 passed, 4 skipped in 19.16s`; global `git diff --check` passed.

### P0/P1 follow-up — configuration freeze and DAQ NO-GO

- Added red-first state regressions proving connected-idle transport/A2L
  changes previously stopped the owned Vector backend but left stale
  connection facts and `CONNECTED_IDLE`, while recording/review still allowed
  mutation entrypoints.
- Centralized owned-Vector configuration invalidation: transport, A2L, and
  selection/event changes now stop the stale backend, clear first-frame/XCP/
  attempt facts, return to Disconnected, and require an explicit reconnect.
  Production mode cannot Record the replacement Fake backend while stale.
- Settings, transport, and A2L UI entrypoints are disabled during Recording and
  ReviewModal. Programmatic guards reject the same mutations without stopping
  or swapping the backend/controller; rejected settings are not persisted.
- Mapped frame/sample overflow, unknown PID, DTO decode error, and DAQ policy
  error counters into persistent red `DaqHealth.overflow` facts. A DAQ error
  during connection is an immediate `DAQ` NO-GO even if a later valid DTO
  produced the first sample; after connection it disables Record and remains
  visible in the status facts.
- Focused state/backend gate: `49 passed in 4.94s`. Expanded settings/A2L/
  capture/state/health regression: `124 passed in 12.49s`. `git diff --check`
  passed.

### Independent post-remediation agent audit

- Split the candidate implementation into independent pyxcp contract,
  DTO/diagnostics, and A2L/configuration-ownership audits with strict file
  ownership; root retained frozen packaging and integration.
- The pyxcp contract audit found no residual P0/P1: structured CONNECT,
  unconditional GET_STATUS, `cond_unlock("DAQ")`, and the empty-string trait
  contract match the pinned 0.29.10 package. Focused result: `23 passed, 3
  skipped`; the skips remain Windows-only package contracts.
- Root packaging audit found a frozen-windowed false failure: PyInstaller
  `--windowed` may expose `sys.stdout`/`sys.stderr` as `None`, while hidden
  import children and runtime smoke used `print()`. Replaced console output
  with best-effort writes because exit codes and JSON are the evidence; added
  a no-console regression. Focused result: `9 passed in 1.75s`.
- Final integration and the remaining two independent audits are in progress;
  Windows W1/W2 and physical gates remain BLOCKED, not inferred from macOS.
- A2L/selection audit fixed real `phys_unit.unit` extraction, ReviewModal
  selection freeze, identical-transport no-op behavior, and the parsed-A2L
  checklist fact. Its focused/adjacent result was `118 passed, 1 skipped`.
- DTO follow-up added the real `640 * 0.015625 = 10.0 V` decode regression and
  `BUS_ERROR_UNKNOWN` summary semantics. Its expanded result was `93 passed`.
- Packaging follow-up made W2 build the default windowed artifact and forbids
  substituting a `-Console` PASS. Packaging result was `24 passed`.
- Root final focused integration: `202 passed, 4 skipped in 22.02s`.
- Root broad Acquisition/Cockpit integration: `711 passed, 4 skipped in
  67.13s`. Full collection: `3216/3219 collected (3 deselected) in 4.67s`.
- Remaining skips/gates are intentionally external: exact Windows W1, default
  windowed W2, opt-in real A2L, and physical Vector/ECU evidence.
- The first final `MagicMock()` scan matched two legitimate callable spies in
  `test_vector_probe_stages.py`, not an unrestricted fake external module.
  Inspected both sites and narrowed the static guard instead of deleting useful
  call assertions.
- Inspected existing surface spec and plan under `docs/superpowers`.
- Confirmed old docs described a snow/flush-panel direction that no longer matched the user-approved porcelain tray mockup.
- Read relevant lessons for visual parity screenshots, rounded child-widget pixel checks, QSettings isolation, shared ViewTabBar styling, and plan/spec literal evidence.
- Rewrote `docs/superpowers/specs/2026-06-19-surface-system-redesign-design.md`.
- Rewrote `docs/superpowers/plans/2026-06-19-surface-system-redesign.md`.
- Created `task_plan.md`, `findings.md`, and `progress.md` for this planning-with-files workflow.
- Dispatched Pauli for Task 0/1. Pauli reported baseline `313 passed` and new tests failing for expected unimplemented shell/QSS reasons.
- Tightened `tests/ui/test_chart_stack.py::test_time_controls_spacer_has_toolbar_background_rule` and the plan snippet so the transparent background assertion is scoped to `QWidget#chartToolbar QWidget#chartTimeControlsSpacer`.
- Applied Galileo review fixes: `test_surface_layering.py` now uses regex block extraction instead of brittle split, guards against a second `QStatusBar`, and spec/plan now explicitly preserve the `self.statusBar` attribute API rather than `MainWindow.statusBar()` callable compatibility.
- Newton completed Task 2 in `mf4_analyzer/ui/main_window/window.py` and `mf4_analyzer/ui/toolbar.py`. Shell status test passed; plan test id was corrected from the stale view-switch name to `test_main_window_mounts_view_tabbar`.
- Nietzsche completed Task 3 in `mf4_analyzer/ui_kit/style.qss`: no `#e8ecf2` or generic `QStatusBar {` hits remain; `Toolbar#surfaceTopBar`, `QStatusBar#surfaceStatusBar`, and `QWidget#centralTray` are present. `tests/ui/test_surface_layering.py` now fails only on the deferred chart toolbar flat contract.
- Ampere completed Task 4: `fileScroll` and `channelCard` are styled-background inner cards; focused left-panel tests passed (`21 passed`).
- Plato completed Task 5 in `style.qss`: chart toolbar is transparent/flat, Inspector body/cards use porcelain tokens, and the focused suite passed (`179 passed`).
- Task 6 exposed the exact rounded-corner backing bug: all five surfaces initially rendered opaque corner pixels. Added a pixel probe to `tests/ui/test_surface_layering.py`; fixed by adding transparent/no-system-background shell attributes to topbar/statusbar/FileNavigator/ChartStack/Inspector and transparent ChartStack internal containers while keeping the existing toolbar layout margins. Rounded-corner suite passed, with corner alpha `[0, 0, 0, 0]` for all five surfaces.
- Final focused UI suite passed: `324 passed in 16.13s` for surface layering, toolbar, file navigator, channel widget, chart stack, inspector, view tabbar, and view-switch integration tests.
- `git diff --check -- mf4_analyzer tests docs/superpowers task_plan.md findings.md progress.md` passed.
- Regenerated final screenshots for all four modes under `docs/surface-redesign-after/`.
- Surface radius alignment pass completed: compact radii `8/7/6/5`, transparent version affordance, shell/child backing fixes, focused UI tests passed, and screenshots regenerated.

---

## 2026-07-24 Channel Configuration Manager V2 Plan

- Started a documentation-only implementation-planning pass from the approved
  interactive HTML prototype.
- Loaded the file-based planning workflow, channel-config lessons, prior
  focused-suite/publish evidence, and current dirty-worktree state.
- Preserved the three existing uncommitted channel-tree alignment files and
  the untracked approved HTML prototype; no Qt source edits are authorized in
  this planning pass.
- Traced the QSettings store, current immediate manager signals, MainWindow
  mutation handlers, exact-name apply resolver, QSS ownership, and focused UI
  tests.
- Wrote the V2 implementation plan with a draft/atomic-save foundation,
  migration-compatible unit hints, portable JSON transfer, explicit batch
  state, red-first tests, and offscreen plus live Qt acceptance gates.
- Cross-checked every existing source/test path, marked planned new modules
  explicitly, passed `git diff --check`, and confirmed the lessons gate does
  not require a new lesson for this documentation-only pass.
- Executed the V2 plan: added the draft/atomic Store contract and transfer
  module, rebuilt the manager UI, wired MainWindow Save, and retained the
  legacy bottom-bar apply behavior.
- Added focused regression coverage and ran the configuration plus navigator
  suite: `96 passed in 3.17s`.
- Superseded during the final HTML-parity pass: the earlier generic-table
  manager did not faithfully reproduce the approved sidebar/detail operation
  model. The final isolated offscreen set is default, channel-selected,
  dirty/batch, and import-preview at 1180×790 / 940×680; it confirms the
  310 px sidebar, 36 px controls, 49 px rows, full selected-row fill, visible
  `×` actions, and no stacked cards in batch mode. Focused result: `72 passed
  in 2.81s`.

## 2026-07-10 Cockpit In-Place Focus

- Began a documentation-only spec/plan task from the user-approved interactive HTML model.
- Read the existing Cockpit governing spec/plan, project lessons, current report/prototype direction, and the stale root planning files without replacing their prior surface-redesign record.
- Recorded the final interaction constraints: single expanded trace, no top slot strip or left management pane in this view, vertical scroll retention, adjacent-card context, and a hard laptop-viewport budget.
- Wrote `docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-card-inplace-focus-spec.md` and its paired implementation plan. Both retain Replay isolation, prescribe a 78% focus target / 80% hard cap, and replace the duplicate-curve / isolated-card behavior with a single-Sparkline in-place Focus contract.
- Cross-checked headings, artifact links, document routing, Focus presentation boundaries, and `git diff --check`. Corrected the plan so Replay retains the existing hidden-by-default `liveFocusShell` rather than losing its isolated Focus UI.

---

## 2026-07-26 HDF Time-Domain Interaction Performance

### Phase 1: Regression report and architecture plan

- **Status:** in_progress
- **Started:** 2026-07-26
- Actions taken:
  - Loaded the project lessons and file-based planning workflow.
  - Preserved the completed prior planning records and added a scoped current-task addendum.
  - Reused the live same-HDF historical probes only after verifying isolated module paths.
  - Confirmed the two main historical facts: resize was partially optimized in June, while raw X-union scanning entered pan/resize only in `5a565fcf`.
- Files modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`

## Current Test Baseline

| Test | Expected | Actual | Status |
|---|---|---|---|
| Same-HDF historical Cocoa probe | Resolve each historical module from its isolated export | Verified module paths under `/private/tmp/tracelab-version-probe.*` | PASS |
| Eight settled pan windows | Historical union scans 0; current exposes regression | v7.5/v7.6/v7.7/pre-5a `0`; current `8`, about `280 ms` | RED baseline captured |

- Loaded the focused performance/cache/dense-raster/channel-state lessons.
- Converted their requirements into consumer call-count, generation invalidation, first-paint, and real Cocoa acceptance gates.
- Corrected the first stale BLF/CRC artifact path lookup before reading the governing spec/plan.
- Read the July 23 selection-delta plan against the current implementation and
  confirmed a contract gap: common multi-subplot checkbox changes still take
  the explicit full-rebuild fallback.
- Audited the existing dense-raster backend. It is structurally reusable for
  dense continuous HDF rows, but only behind a narrow candidate policy and
  only if the cache/quiet-window fixes leave Cocoa paint above budget.
- Added red-first raw-X and resize quiet-window tests, observed the intended
  two failures, implemented the generation cache and one-stage resize settle,
  then passed the focused compatibility set: `8 passed`.
- First ad-hoc real-HDF benchmark assumed a lowercase `time` column and failed
  with `KeyError: 'time'`; inspected the live group schema and reran with the
  real `Time` column and `units` mapping.
- Post-fix Cocoa result: one raw-X scan total, pan p50/p95 `123.6/132.1 ms`,
  resize p50/p95 `207.0/240.8 ms`. This is a large recovery but still above a
  fluid interaction budget, so the plan's conditional continuous-raster stage
  is now authorized by measurement.

### Phase 2–6: Implemented and Verified

- **Status:** complete for source/macOS Cocoa; Windows packaged EXE pending.
- Implemented raw-X finite-bound generation caching, a 150 ms resize quiet
  window with one synchronous final settle, and retained ordinary subplot rows
  for hide/restore/append selection deltas.
- Tested and rejected the direct dense-discrete pixmap reuse for continuous
  HDF: six DPR2 images made pan/resize slower, so no such production change
  remains and a negative test prevents accidental reintroduction.
- Added the standards document and `benchmark_timedomain_interaction.py`;
  it splits callback, forced paint, held frames and final settle and emits a
  machine-readable JSON record with deterministic counts.
- Final real-HDF Cocoa gate passed: initial `981.5 ms`, pan p95 `84.5 ms`,
  resize p95 `128.5 ms`, callback p95 `13.1 ms`, paint p95 `101.0 ms`,
  raw-X scans `1`, held-pan setData `0`.
- Verification passed: hotpath `16 passed in 7.61s`, dense-raster `23 passed
  in 8.74s`, pg-canvas `362 passed, 1 deselected in 90.65s`.

## 2026-08-01 TimeDomain Per-Source Custom X-Axis Execution

- Reconnected after the parallel Batch session completed. Live Git state shows
  `26e422b` (Batch) followed by `4db876b` (custom-X) and local-main merge
  `4d88457`; both commits are ancestors of HEAD and the workstreams do not
  overlap Batch-owned source/test files.
- Updated the formal plan's baseline and final verification commands: integrated
  checks now run from local `main`, include the previously omitted pure resolver
  test file, and add a dedicated `26e422b` Batch protection suite.
- The first refreshed invocation reproduced an already-recorded command defect:
  inserting root-level `tests/test_project_io.py` into the UI list prevented
  later UI files from receiving their local fixtures (`819 passed`, `4 failed`,
  `43 errors`). The formal plan now separates UI and project-I/O invocations;
  this mixed-path result is diagnostic only and is not used as a product gate.
- Two additional UI test owners were missing from the reviewed directed list:
  compute-progress and overlay-risk tests still faked the retired list return
  from `_build_time_plot_data()`. Their fakes now use the authoritative
  `TimePlotBuildResult`, and both files are included in the formal gate.
- Independent merge-boundary review returned P0/P1 PASS and found one P2:
  all-failed custom-X Apply overwrote truthful `0/N` diagnostics with a success
  toast. A RED-first regression now drives the render result back to the apply
  handler; all-failed keeps the empty hint, pill, and `0/N` status without the
  contradictory toast.
- Integrated verification is green: custom-X resolver/render/state/project and
  producer-consumer tests total `85 passed`; the Batch UI and core protection
  suites total `457 passed`. `py_compile`, `git diff --check`, ancestry, and the
  lesson gate passed.
- Foreground macOS acceptance was attempted with real MF4 files. TraceLab v7.9
  launched, but confirming the first file triggered SIGSEGV before custom-X
  selection. `Python-2026-08-01-213130.ips` records EXC_BAD_ACCESS on the main
  thread in `sipQGraphicsWidget::resizeEvent` / Qt graphics-layout geometry.
  Foreground acceptance therefore remains UNVERIFIED; it is not replaced by
  the offscreen suite.
- Reviewed the Claude-updated plan with independent state/persistence and
  render/diagnostics passes, patched every P1 ambiguity, then dispatched three
  non-overlapping implementation workstreams.
- Implemented the pure resolver, tagged Inspector payload, View/project legacy
  migration, per-source plot assembly, post-range finite eligibility, unit
  cohort selection, and expandable chart-card diagnostics.
- Follow-up review found two P1s (early unit voting and blank-unit fallback)
  plus missing range/subplot regressions. They were repaired and the same
  reviewer returned PASS with no new P0/P1.
- Verification passed: focused custom-X/state `39 passed`; project I/O
  `15 passed`; critical closure `14 passed`; compile and diff checks clean.
- The complete directed UI set reached `831 passed, 1 deselected, 20 failed`.
  A pristine `git archive HEAD` probe reproduced both FFT dB-reference failures
  and the representative split-focus helper failure, establishing those groups
  as pre-existing baseline failures rather than this feature's regressions.
- Full-repository pytest was attempted and reached 54%, then exited 139 after
  `db_reference_dialog.py:117` handled an already deleted
  `ScientificReferenceSpinBox`. Full-suite status remains UNVERIFIED.
- Promoted `custom-x-unit-cohort-after-eligibility`; the lesson gate now reports
  `lesson_required: False`. No Batch or requirements 1–3 source was touched.
- Remaining acceptance: foreground macOS TraceLab interaction and visual check
  with real unequal-length files; offscreen Qt evidence is not a substitute.

## 2026-08-02 — Batch Compact UI Redesign

- User authorized implementation on a new branch, following the approved
  compact-UI Spec/Plan.
- Loaded the HTML operation-parity, rendered-visual, dynamic-scroll,
  output-validation, and runtime-state lessons.
- Recovered current base `main` at `c1b3cef`; the worktree already contains
  unrelated untracked Playwright artifacts and the user-provided HTML/render
  migration documentation. No product code or tests have been changed yet.
- Added compact-UI contract tests and ran them red: `4 failed` for legacy
  heatmap `time_range`, hardcoded batch preset names, CSV output defaults, and
  time-mode dB visibility. These are intended RED results, not a baseline pass.
- Added the shared preset-slot reader/change bus, routed Inspector writes through
  it, rebuilt batch spectral cards on the same persisted slots, and implemented
  explicit dirty deselection. Added method-aware time-range normalization and
  compact fixed output values/dB visibility. The first contract pass is now
  green: `4 passed in 0.69s`.
- The first implementation pass keeps runner/task-list state as an internal
  compatibility model while removing it from the visible product layout. The
  next pass projects only status and progress into the fixed footer, preserving
  the existing QThread.finished unlock boundary.
- Completed the visible compact layout: a 54 px data-source summary opens the
  modal manager, time-domain grouping uses three annotated waveform cards,
  output has fixed XLSX + PNG 1920×1080/auto-number choices, and the footer is
  a 48 px aggregate status/progress bar. The internal `TaskListWidget` remains
  event-only, so runner lifecycle and artifact facts are preserved without a
  visible lower section.
- Added XLSX worksheet splitting at the physical Excel data-row boundary and a
  small-limit regression test; empty dataframes retain one header worksheet.
- Final directed verification: `181 passed in 7.88s`, `git diff --check`, and
  the lesson gate (`lesson_required: False`) pass. The full batch test cluster
  is `723 passed, 1 failed`; the failure is confirmed against pristine HEAD,
  not introduced by this branch.
- Rendered and visually inspected actual-QSS offscreen proof states in
  `/tmp/tracelab-batch-compact-ui-proof-output`: FFT 1080×760, time grouping
  1080×760, FFT 1440×900, and the data-source manager. The proof asserts fixed
  export values, hidden time dB/source interval, hidden task list, and footer
  height; it remains offscreen evidence, not foreground macOS acceptance.
- Inspector preset-bar regression coverage is also green: `211 passed in
  9.90s`; a live shared-slot update now clears an affected batch-card
  selection, preventing it from claiming an old parameter snapshot is current.
- A user edit in the output/axis panel now also clears an applied analysis card
  when its output snapshot changes; this extends the same no-misleading-state
  rule beyond the analysis-form fields.

### Visual-Parity Remediation Restart

- Reopened the current 1080×760 and 1440×900 Qt renders against the approved
  HTML source and the user's prototype screenshots. Marked the prior visual
  completion claim invalid; no source was changed during that audit.
- Loaded the exact HTML-operation, rendered-screenshot, dynamic-scroll,
  QSettings-isolation, and superseded-plan lessons, plus the frontend design
  and file-planning workflows.
- Preserved the 2026-08-01 plan as historical evidence and created
  `docs/superpowers/plans/2026-08-02-batch-compact-ui-visual-parity-remediation.md`.
  The new plan protects the completed behavior wiring but reopens all visible
  surfaces and the offscreen matrix.
- Current phase: add RED-first geometry/content contracts for the HTML shell,
  cards, modal, axis card, and footer before changing the Qt widgets.
- Added the visual contracts and ran the focused RED gate: `8 passed, 8
  failed`. Every failure is one intended HTML-parity gap (header/pipeline/footer
  geometry, flat pipeline, grouping semantics, preset summaries, axis card,
  modal shell); existing behavior contracts in the same file remained green.
- Current phase: implement the shell/pipeline/continuous-pane geometry, then
  render the first 1080×760 and 1440×900 screenshots before deeper panels.
- Rebuilt `PipelineStrip` as flat 01/02/03 stage cells, added the 50 px toolbar
  host, removed root/pane gutters, applied 29:39:32 continuous scroll panes,
  and changed the footer to the approved 54 px order.
- Focused shell verification passed: `4 passed in 0.82s`.
- Generated and opened the Phase 1 1080×760 and 1440×900 images under
  `/tmp/tracelab-batch-compact-ui-phase1`. Shell geometry is PASS; deeper
  Input/Analysis/Output surfaces remain expected FAIL and are not called done.
- Replaced the abstract grouping strokes with semantic F/S waveform painters,
  dynamic real-count formulas, and applied/compact states. Replaced generic
  preset buttons with 61 px two-level cards using the shared slot names and
  parameter summaries. Focused result: `39 passed in 1.63s`.
- Opened Phase 3A images under `/tmp/tracelab-batch-compact-ui-phase3a`.
  Wave/preset cards are improved, but the old form label column overlaps them;
  next step is the two-column parameter renderer, not more QSS padding.
- Completed the HTML visual-parity remediation across the shell, Input,
  Analysis, Output, modal, and footer while retaining the batch runner and
  validation authorities. Compatibility-only controls remain hidden rather
  than participating in layout.
- Generated and directly inspected the final isolated-QSettings render matrix:
  24 PNGs covering 22 sheet states and 2 modal states at 1080×760/1440×900 in
  `/tmp/tracelab-batch-compact-ui-final-matrix`. The last pass found and fixed
  raw `rpm_channel`/`outputs` validation text in the visible pipeline, then
  regenerated and reopened the affected images.
- Final offscreen regressions: complete Batch cluster `735 passed, 1 failed`
  (the same legacy logical-source migration failure reproduced from pristine
  HEAD); Inspector cluster `221 passed`; targeted presentation tests are part
  of those totals. Foreground macOS acceptance remains not executed.
