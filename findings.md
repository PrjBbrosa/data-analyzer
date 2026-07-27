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

---

## 2026-07-24 Channel Configuration Manager V2 Planning Findings

- Approved prototype: `docs/analyzer/ui-prototypes/2026-07-23-channel-config-manager-v2.html`.
- The target separates single-config editing from explicit batch-config mode;
  the right pane exposes every saved channel with single and batch removal.
- Current-View match/missing state is a preview and must be recomputed, not
  persisted or transferred.
- Transfer files use a versioned JSON envelope and carry only portable facts:
  configuration name, channel name, and optional unit.
- Import remains a draft until the user confirms the manager's primary Save
  action; same-name policy is explicit: keep both, replace, or skip.
- Relevant durable checks: structured configuration rows, host-width rendered
  geometry, and screenshot proof beyond QSS/object-name assertions.
- Existing publish memory identifies the focused configuration suite and the
  need to isolate config work from unrelated dirty checkout changes.
- Current `ChannelConfigManagerDialog` emits immediate create/rename/copy/delete
  requests, and `_channel_scope_mixin.py` commits each request directly to the
  QSettings-backed store. A truthful Save/Discard UI therefore requires a
  draft snapshot and atomic commit before the visual rebuild.
- The existing persisted record is schema v1 and stores names only. The plan
  keeps `channel_names` authoritative, retains the current settings key, reads
  v1/v2, and uses optional persisted unit hints only for display/transfer.
- The implementation plan is
  `docs/analyzer/plans/2026-07-24-channel-config-manager-v2-implementation.md`.
- Implementation now uses `commit_snapshot()` as the manager-only write
  boundary. The old manager-specific immediate mutation helpers were removed;
  the existing bottom-bar save/apply flow remains a separate compatibility path.
- During offscreen review, `QTableWidgetItem` check-state rendering read like a
  destructive red cross under the live stylesheet. Both batch/config and
  channel selection cells now use real `QCheckBox` widgets, and the rendered
  batch screenshot confirms the two independent selected states are legible.
- Offscreen evidence is stored under
  `docs/analyzer/verify/2026-07-24-channel-config-manager-v2/`; the final
  HTML-parity images prove 36px control geometry, the fixed 310px sidebar,
  selected-channel fill, batch-card cleanup, visible `×` actions, import
  preview, and the 940×680 footer/channel-width contract. It is not a
  substitute for a foreground TraceLab session.

---

## 2026-07-26 HDF Time-Domain Performance Findings

- Reproduction file: `/Users/donghang/Downloads/260417-ripple-PK2C-电机加热-1.hdf`, 24 kHz raster, 1,188,000 samples per selected channel, six subplot rows.
- Isolated historical Cocoa comparison with the same file showed current v7.8 pan p50/p95 `213/222 ms` versus v7.5 `184/195 ms` and v7.6 `178/195 ms`; resize p50/p95 was current `271/296 ms` versus v7.5 `214/251 ms` and v7.6 `224/277 ms`.
- Pure HDF parse stayed near `0.26 s`; the loader is not the recent regression.
- Before `5a565fcf`, `_data_x_union()` was used for build/Home only. The new buffered settle path calls it for every settled/coarse refresh.
- Eight settled pan windows called `_data_x_union()` zero times in v7.5/v7.6/v7.7/pre-`5a565fcf`, but eight times in current v7.8, costing about `280 ms` total in the isolated probe.
- The six HDF rows share one 1,188,000-point time array, yet current `_data_x_union()` repeats `isfinite` plus finite-copy/min/max for every channel.
- Resize optimization already exists: `816c2083` moved label/axis rework to a 40 ms settle pass. It is incomplete, because a slow paint lets the timer expire during a live resize and current settle then enters `_buffered_xlim()` and the raw union scan.
- Current continuous HDF channels classify as `general`, so they pay the new coverage/settle management but do not receive the dense-discrete cached-raster benefit.
- Existing tests prove synthetic setData/call-count contracts but do not bound raw-union scans, six-row million-sample resize behavior, or Cocoa end-to-end latency.

### Current Technical Direction

| Decision | Rationale |
|---|---|
| Cache raw X bounds at the canvas data-generation boundary and deduplicate identical time-array identities | Bounds are immutable for one plot generation; pan/resize must be O(1), and shared HDF axes must not be scanned six times. |
| Make resize a real quiet window that cancels pending coarse/settled refresh work on every resize event | The existing 40 ms label debounce is defeated when a frame itself exceeds 40 ms. |
| Keep the dense-discrete raster path unchanged in the first implementation pass | The confirmed regression can be removed with lower risk; a continuous raster backend is a separate fidelity/performance decision. |
| Add deterministic default regressions plus an opt-in Cocoa threshold benchmark | Call counts are stable in CI; Cocoa paint latency is the user-visible truth. |

### Existing July 23 Contract Gap

- The July 23 spec and implementation plan require add/remove/show/hide channel
  deltas while preserving unchanged `PlotDataItem`/`ViewBox` identities.
- Current `try_apply_selection_delta()` deliberately rejects a changed active
  set in multi-row `subplot` or `overlay` mode with a topology-change reason.
  The MainWindow then falls back to `plot_channels()`, whose `clear()` destroys
  the whole chart. The prior plan is therefore not proof that checkbox latency
  was implemented.
- The existing dense-raster layer already provides the correct raw/display
  separation and transform-only interaction model, but only accepts
  `dense_discrete` profiles. The 1,188,000-point HDF waveforms are `general`,
  so their interactive-quality transition clears native curve caches and
  makes six vector envelopes repaint on each frame.
- Extending the raster candidate policy to every `general` channel would be
  too broad. Any reuse must be restricted by raw density, subplot mode,
  finiteness/linear-axis compatibility, memory caps, and a native fallback;
  low-density smooth curves must retain their current native-AA behavior.
- The best-risk sequence is now explicit: (1) O(1) raw-X bounds, (2) a true
  resize quiet window, (3) measure, (4) only if paint remains above budget,
  admit dense continuous subplot rows to the already-tested raster backend,
  and (5) separately replace full chart rebuilds with object-preserving
  topology relayout.

### Post Stage 1-2 Cocoa Measurement

- Same real HDF, six rows, 1900×1100 Cocoa: raw-X scan count is now `1` for
  the full plot generation and stays `1` across ten pan windows plus eight
  resizes.
- Settled pan after warmup improved to p50/p95 `123.6/132.1 ms` from the
  pre-fix current baseline `213/222 ms`.
- Resize improved to p50/p95 `207.0/240.8 ms` from `271/296 ms`.
- This restores or beats the historical v7.5/v7.6 relative level, but a
  124 ms settled pan still visibly stalls. The remaining cost is therefore
  sufficient evidence to execute the conditional dense-continuous raster
  stage rather than stop at the union-cache micro-optimization.

### Loaded Lesson Constraints

- The raw-X cache must be proven at the consumer: tests must count the uncached finite-bound scan across multiple pan/resize refreshes, not merely assert that a cache field exists.
- End-to-end `set_xlim/resize → settle → viewport.repaint()` numbers remain authoritative; an isolated union-scan speedup cannot claim the plot SLA by itself.
- Cache invalidation is generation/state conditional: clear cached bounds when channel data is rebuilt or mutated, never on every handler replay.
- Keep `dense_discrete` raster DPR, one-device-pixel stroke, AA-blocking, and Cocoa `<16 ms` transform / `<25 ms` settle contracts intact.
- Dense subplot first-paint cost must still be measured with `viewport.repaint()`; a cached `grab()` is not evidence.
- Channel-tree performance edits must not detach the file from its View or lose colors, hidden state, axis groups, selection, or expansion state.
- The July 23 BLF/CRC governing artifacts live under `docs/analyzer/specs`, `docs/analyzer/plans`, and `docs/analyzer/reviews`, not `docs/superpowers`.

### Executed Architecture Decision and Final Evidence

- The conditional continuous-raster experiment was executed, then rejected:
  six DPR2 pixmaps produced held-pan p50/p95 `176.6/179.9 ms` and resize
  p50/p95 `271.4/359.8 ms`, worse than native-vector probes. No experiment
  production code remains; a negative test keeps ordinary `general` continuous
  rows out of that backend.
- The accepted third layer is ordinary-subplot retained-row delta. Compatible
  hide/re-show keeps the original PlotItem/ViewBox and collapses the hidden
  layout row; a compatible append builds one new row. Complex topology and
  insertion-order changes deliberately return an auditable full-rebuild reason.
- Final real HDF Cocoa benchmark (1900×1100, six selected channels) passed:
  initial plot `981.5 ms`; held-pan p50/p95 `74.8/84.5 ms`; pan settle
  `119.2 ms`; resize p50/p95 `125.5/128.5 ms`; resize settle `120.7 ms`;
  checkbox callback p95 `13.1 ms`; checkbox paint p95 `101.0 ms`; raw-X
  scans `1`; held-pan setData `0`.
- Regression evidence: `16 passed in 7.61s` hotpath, `23 passed in 8.74s`
  dense-raster, and `362 passed, 1 deselected in 90.65s` full pg-canvas.
- This is source plus real Cocoa-canvas evidence, not packaged Windows proof.
  Windows EXE remains pending under the same scenario and relative-baseline
  rules in the performance standards.
