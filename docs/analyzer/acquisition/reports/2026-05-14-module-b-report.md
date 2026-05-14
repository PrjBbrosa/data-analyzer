# Module B Work Report — Standard Signal Alias Sidecar

- Branch: `feat/acquisition-validation-program`
- HEAD at report time: `616b5d5`
- Module status: **done**

## Summary

Module B introduced a sidecar alias layer that translates standard signal
names (e.g. `vehicle_speed`) into per-vehicle raw MF4 channel names without
modifying the loader, batch, FFT, or order-cot pipelines. A new
`mf4_analyzer/acquisition/signals.py` module owns the immutable
`VehicleSignalMapping`, mapping loader, and resolver, and Module A's
`analyze_mf4` was extended with three optional kwargs (`signal_config_root`,
`vehicle`, plus the existing `expected_signals`) so the preflight CLI can
opt into alias resolution. A legacy-parity regression test was added FIRST
to lock in the Module A contract — calls without a `signal_config_root`
behave identically to Module A, byte-for-byte. Operationally noteworthy:
Module B's first specialist disconnected mid-flight during Task 2; a second
specialist resumed from the preserved dirty working tree, completed the
remaining Task 2 steps verbatim from the plan, and committed `616b5d5`
with the planned commit message — full Module A + B regression stayed
green across the handoff.

## Acceptance gates

| Gate | Status | Evidence |
| --- | --- | --- |
| B1 — Alias module loads + validates | PASS | `tests/test_acquisition_signals.py` was 4/4 green at Module B handoff; current checkout has 5 test definitions after the checked-in `X04C.example` config guard. Malformed alias rejection still uses `ValueError`. |
| B2 — Preflight reports resolved + unresolved aliases | PASS | `tests/test_acquisition_preflight.py` was 6/6 green at Module B handoff; current checkout has 8 test definitions after loader-failure and sha256-skip polish, including the resolved + missing alias tests. |
| B3 — Module A legacy parity preserved | PASS | `test_analyze_mf4_without_signal_config_keeps_legacy_behavior` green; `analyze_mf4` with no signal config behaves identically to Module A. |
| B4 — Config files parse and resolve | PASS | `configs/signals/standard_signals.json` parses; `configs/signals/vehicles/X04C.example.json` resolves a synthetic raw-channel list end-to-end. |

## Commits

| Task | SHA | Title |
| --- | --- | --- |
| Task 1 — Signal alias module | `3d7d0f4` | feat: add standard signal alias sidecar |
| Task 2 — Preflight integration | `616b5d5` | feat: connect preflight to standard signal aliases |

## Tests

Combined Module A + Module B + P0 hardware-free run at Module B handoff: **22 passed, 1 skipped**
(5 manifest + 6 preflight + 4 regression + 4 signals + 2 synthetic + 1 P0
mf4 = 22 passed; the 1 P0 a2l test is env-gated and skipped).

**Post-execution correction (2026-05-15):** do not reuse the 22/1 count as a
current branch total. Current test-definition inventory after fix stages is
manifest 10 + preflight 8 + regression 11 + signals 5 + smoke 3 + synthetic 2
plus P0 hardware-free 8. Fresh pytest output is still required for PASS/FAIL.

Module B added **7 new tests** total:

- 4 new tests in `tests/test_acquisition_signals.py` (alias load, resolve,
  partial-miss, malformed rejection).
- 3 new tests in `tests/test_acquisition_preflight.py`:
  - `test_analyze_mf4_without_signal_config_keeps_legacy_behavior` — the
    legacy-parity regression guard, added FIRST per plan Task 2 Step 1 to
    pin the Module A contract.
  - `test_analyze_mf4_reports_resolved_standard_signals` — positive path
    for a resolved alias.
  - `test_analyze_mf4_reports_unresolved_standard_signal_as_missing` —
    positive path for a missing alias reported through
    `resolved_signals`.

The legacy-parity test is a deliberate Module A-contract regression guard:
any future change that breaks the no-config code path will fail this test
loudly, even before any alias logic runs.

## Files changed

- `configs/signals/standard_signals.json`
- `configs/signals/vehicles/X04C.example.json`
- `mf4_analyzer/acquisition/signals.py`
- `tests/test_acquisition_signals.py`
- `mf4_analyzer/acquisition/preflight.py`
- `scripts/preflight.py`
- `tests/test_acquisition_preflight.py`

## Symbols touched

New symbols: `VehicleSignalMapping` (frozen dataclass), `load_vehicle_mapping`,
and `resolve_standard_signals` — all in `mf4_analyzer/acquisition/signals.py`.
Modified symbols: `PreflightResult` (added a `resolved_signals` field),
`analyze_mf4` (added `signal_config_root` + `vehicle` kwargs and an
alias-resolution block), and `scripts/preflight.py`'s `main` (added
`--vehicle` and `--signal-config-root` CLI flags). All edits stay inside the
acquisition module boundary; the loader, batch, FFT, order-cot, manifest,
regression, P0, templates, and the UI surfaces remain untouched. The
boundary-respecting approach was chosen explicitly to honor the
silent-boundary-leak lesson at
`docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`.

## Cross-specialist handoff event

During Task 2 the first specialist's socket dropped after it had already
written the correct edits to `mf4_analyzer/acquisition/preflight.py` and
`tests/test_acquisition_preflight.py` — including the legacy-parity test
added FIRST (plan Task 2 Step 1). The dirty working tree was preserved
intact (no `git reset --hard`, no `git stash`, no `git checkout --`),
which was the critical decision that made recovery possible. A second
specialist resumed by inspecting the tree, adding the two positive tests
(`test_analyze_mf4_reports_resolved_standard_signals` and
`test_analyze_mf4_reports_unresolved_standard_signal_as_missing`) verbatim
from plan §Task 2 Step 4, adding the two CLI flags to `scripts/preflight.py`
per plan §Task 2 Step 5, and running the full Module A + B regression
(clean). The commit was made as `616b5d5` with the plan's exact commit
message. Working-tree continuity is the load-bearing lesson here:
destructive recovery would have lost the legacy-parity test ordering and
the test-FIRST discipline trail.

## Residual risk and follow-up

- Loader-level sinking of standard signals (roadmap §6 original intent) is
  deferred to a follow-up spec. The sidecar approach was chosen so UI,
  batch, and search continue to operate on raw channel names — anything
  that lowers aliases into the loader would touch all four surfaces and
  trigger a much larger boundary expansion.
- Vehicle mapping is currently per-file JSON under
  `configs/signals/vehicles/`. If the mapping count grows beyond roughly
  10 vehicles, an index file or directory-scan loader should be considered
  to avoid CLI argument sprawl.
- `VehicleSignalMapping` uses `types.MappingProxyType` for immutability —
  consumers must not assume the underlying alias dict is mutable. Any
  caller that needs to mutate should construct a new mapping instead.

## Lessons learned

- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`
- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
