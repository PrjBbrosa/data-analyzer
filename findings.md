# Findings: Vector/XCP Readiness Review Remediation

## Baseline

- Branch: `codex/vector-xcp-readiness` at `04591e57`.
- Worktree was clean before remediation.
- Focused macOS suite: `132 passed, 1 skipped in 18.34s` using the main
  checkout venv. The skip is the real Windows package contract.
- No generated Windows `api-contract.json`, `build-api-contract.json`, or
  `packaged-runtime-smoke.json` exists; the evidence directory contains only a
  template.

## Review Findings To Close

1. `test_xcp_connection()` coerces pyxcp 0.29.10's structured CONNECT
   `ResourceType` to `int`; real hardware can fail after CONNECT.
2. Test Connection runs GET_STATUS only when a Seed&Key DLL is configured,
   allowing locked DAQ to appear green.
3. DAQ Seed&Key resource is encoded as `0x02`; pyxcp 0.29.10 defines DAQ as
   `0x04`.
4. `diagnostics()` landed on `FakeRecorderBackend`, while the real Vector
   backend returns no queue/decode/unknown-PID evidence.
5. DTO decoding silently drops unknown/short/unsupported frames without
   separate counters.
6. `MeasurementSummary` defaults for address extension and linear conversion
   are never populated by the A2L parser, so MF4 may store plausible-looking
   raw values under physical units.
7. Measurement changes after connection do not invalidate/reconfigure the
   attached Vector stream, so backend DAQ layout and writer schema can differ.
8. Windows verifier does not prove the required isolated PyQt-loaded pyxcp
   import context.
9. Frozen build dependency/metadata closure is not evidenced; runbook exe name
   differs from the build script default.
10. No source/package/bench evidence supports a `PROCEED TO BENCH` handoff.

## Initial Packaging Evidence Details (Resolved In This Remediation)

- Initially, `verify_windows_acquisition_runtime.py` imported pyxcp directly in its own
  process and never executes the production `_run_pyxcp_import_probe()` path,
  so it cannot prove the PyQt-loaded crash boundary used by Cockpit.
- Initially, `runtime_smoke.py` verified distribution metadata and `Master`, but did not
  prove policy construction, adapter construction, or an isolated import.
- Initially, the frozen entrypoint did not expose a child-only import-probe
  flag. Calling the production `sys.executable -c ...` probe from an onedir
  executable would not have normal CPython `-c` semantics and therefore needs
  an explicit frozen-safe probe entrypoint.
- Initially, `build_windows_folder.ps1` copied only the `pyxcp/` directory. It did not
  copy `pyxcp-0.29.10.dist-info`, yet packaged smoke calls
  `importlib.metadata.version("pyxcp")`; it also does not explicitly vendor
  pyxcp's dependency closure.
- The build's authoritative default is now consistently documented as
  `dist\\TraceLab7.5\\TraceLab7.5.exe`.

Resolution: source and frozen probes now use the production child boundary;
runtime smoke checks pinned metadata and API surfaces without opening hardware;
the build vendors the pinned acquisition requirements with `pip --target`,
including dist-info and dependencies; and the runbook/evidence paths match.
Actual Windows W1/W2 JSON remains absent and therefore BLOCKED.

## Integration Review Additions

- `BackendStatus.bus_error_count` is not observable from the current
  pyxcp-owned transport: pyxcp 0.29.10 catches `python-can CanError` inside its
  CAN wrapper and returns `None` before the application policy sees it.
  Diagnostics must therefore expose `bus_error_observable=False`; zero cannot
  be described as a measured absence of bus errors.
- The initial Seed&Key implementation inherited a stale four-argument custom
  `ASAP1A_XCP_ComputeKeyFromSeed` ABI from the historical Stage 8 plan. The
  pinned pyxcp runtime already owns the supported `Master.cond_unlock("DAQ")`
  flow and its five-argument `dllif.getKey` adapter, multi-part seed/key logic,
  privilege byte, and bitness loader. The remediation must delegate to that
  pinned surface instead of maintaining a guessed ctypes ABI.
- The source-safe A2L crash boundary used
  `sys.executable -m can_logger.p0._a2l_subprocess`. In a frozen onedir app,
  `sys.executable` is `TraceLab7.5.exe`, not CPython, so `-m` is not an
  interpreter command and can launch the GUI instead of returning a pickle.
  Frozen acquisition therefore needs its own hidden A2L child entrypoint.
- The initial build copied only `pya2l/`; dynamically imported parser
  dependencies and `pya2ldb` metadata were not guaranteed in the onedir
  package. The build must vendor the exact installed `pya2ldb` distribution
  with its dependency closure, just as the pyxcp closure is vendored.
- `PyXcpRuntime._build_application()` initially passed and assigned Python
  `None` for an absent Seed&Key DLL. pyxcp 0.29.10 declares
  `General.seed_n_key_dll` as `Unicode('', allow_none=False)`, so the normal
  unprotected/no-provider path could fail with a trait error before Master
  construction. Hardware-free `SimpleNamespace` tests did not enforce this
  real config contract; absence must be normalized to `""`.
- Connected-idle transport/A2L changes initially stopped and replaced an owned
  Vector backend without clearing connection/first-frame facts or leaving
  `CONNECTED_IDLE`. Record could then remain enabled and start the Fake
  fallback. During RECORDING/REVIEW, the same mutation path could stop the
  backend still owned by `CaptureController` while the UI remained in the old
  state. Configuration mutations must be rejected during active/review states
  and must fully disconnect/reset an idle real connection.
- Backend unknown-PID/decode/policy counters initially did not feed Cockpit
  `DaqHealth`; a bad DTO followed by one valid sample could satisfy the
  first-frame predicate and enable Record. These nonzero facts must keep DAQ
  red/NO-GO even though the decoder correctly continues processing later
  frames.
- Transport settings exposed editable arbitration/data sample-point
  percentages, but the runtime never propagated them. pyxcp Vector accepts
  explicit clock-dependent `BitTiming`/tseg facts, not a bare percentage. With
  no hardware clock contract, the truthful remediation is driver-automatic,
  disabled controls plus fail-closed legacy overrides—not an invented timing
  calculation.
- Packaged runtime smoke initially checked only that `PyXcpRuntime.open` was
  callable and intentionally did not construct config/policies. That could not
  detect the no-DLL trait failure. A no-hardware smoke can and must construct
  the real pyxcp application config and policy objects while still avoiding
  Master/Vector channel creation.
- ASAM MCD-2 MC confirms that RAT_FUNC is the exception whose direction is
  physical-to-internal. The implemented affine subset therefore correctly
  inverts `internal=(b*physical+c)/f` to
  `physical=(f/b)*internal-c/b`; all non-affine cases remain unsupported.

## Durable Constraints From Lessons

- Optional Windows/native imports require a subprocess probe; `try/except` is
  not a sufficient crash boundary.
- External API tests must use structured fakes matching the real response
  shape.
- Cockpit-owned backends must be invalidated after transport, A2L, vehicle, or
  selected-measurement changes.
- A2L DTO imports must remain safe without importing `pya2l` at module load.
- Acquisition evidence commands and output artifacts are executable contracts;
  missing evidence is `UNKNOWN`, never PASS.

## Final Closure

- Independent adversarial closure review marked all seven discovered P0/P1
  groups code-level `RESOLVED`; no new P0/P1 remained.
- Frozen A2L smoke now exercises the actual child command, binary stdout,
  pickle, pya2l DB/parser/dependency path, and measurement facts with a real
  one-signal A2L. Windows onedir execution itself remains `UNKNOWN` until W2.
- Final focused integration: `204 passed, 4 skipped in 19.27s`.
- Final broad Acquisition/Cockpit suite: 700 tests, exit 0
  (`699 passed, 1 skipped`).
- Full repository collection: `3211/3214 tests collected (3 deselected)`.
- `git diff --check`, lesson gate, eager-native-import scan, and retired ABI/
  stale identifier scans passed.

## Independent Agent Audit Closure

- The pinned pyxcp 0.29.10 contract was independently rechecked against the
  official wheel and needs no further source correction: structured RESOURCE,
  GET_STATUS, `cond_unlock("DAQ")`, and the empty-string config trait agree.
- Real pya2l exposes `phys_unit` as a relationship node; extracting its `.unit`
  avoids persisting an ORM repr as the MF4 unit.
- ReviewModal must keep measurement/event selection frozen, and an identical
  transport save must not invalidate a healthy connection. Both now have
  regression coverage; true configuration changes still disconnect and
  require a rebuilt DAQ layout.
- A filename alone is not A2L proof. The checklist now requires successful
  parsed summary facts before displaying A2L parsed.
- `bus_error_count=0` is not usable PASS evidence when pyxcp cannot expose bus
  errors. SessionSummary keeps its integer schema but carries the explicit
  `BUS_ERROR_UNKNOWN` warning in that case.
- Frozen hidden children and runtime smoke cannot depend on console streams:
  production `--windowed` may set stdout/stderr to `None`. Text output is now
  best-effort, and W2 explicitly validates the default windowed artifact;
  `-Console` is diagnostic only.
- Default theme: porcelain tray (`#f2f4f7`).
- Topbar: white rounded surface, 50px.
- Bottombar: white rounded surface, 40px, still a `QStatusBar`.
- Vertical spacing: 5px.
- Main panel radius: 10px.
- Chart toolbar: flat transparent tool row; no border/radius/card background.

---

## 2026-07-10 Cockpit In-Place Focus Findings

- The approved direction is not a separate Focus page: a selected live card expands within the existing vertical `QScrollArea` stream, while adjacent cards remain visible but de-emphasized.
- The expanded card must contain exactly one trace. The compact trace is resized/repainted into the expanded plot rect; a second overview trace plus detail trace is forbidden.
- Laptop-height efficiency is a first-order constraint: the selected card uses at most 80% of the card-stream viewport; the remainder exposes adjacent card context. No dedicated top slot strip or left-side management surface belongs in the Focus view.
- Current `LiveCardGrid` already has a vertical scroll area, `focus_channel`, a focus shell, and cached cards. The next spec must refine those mechanisms rather than introduce a separate TimeDomain view.
- Current governing `2026-07-10-cockpit-live-preview-first-principles-spec.md` explicitly leaves zoom/cursor/manual-axis Focus mechanics out of scope. This follow-up must preserve that boundary while defining the compact in-place expansion.
- `liveFocusShell` cannot be globally removed: it remains required for the default isolated Focus used by Replay. Cockpit `inplace` hides it without layout height instead.
