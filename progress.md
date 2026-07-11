# Progress: Vector/XCP Readiness Review Remediation

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
