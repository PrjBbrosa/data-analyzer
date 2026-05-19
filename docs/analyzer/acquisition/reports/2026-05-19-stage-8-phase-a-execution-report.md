# Stage 8 Phase-A Execution Report

- Date: 2026-05-19
- Branch: `stage8/real-a2l-followup`
- Trigger: User asked "打开 A2L 一个变量名都不显示" → 链路扫描发现 6 处生产入口断点 → 8 项 Phase-A 落地。
- Companion artifact: `docs/analyzer/acquisition/runbooks/2026-05-19-stage-8-vn1630-vehicle-test-action-board.html` (live status board)

## Why this exists

The Stage-8 `VectorXcpRecorderBackend` class shipped with PR-1/2/3 but never had a production entry point. The cockpit always constructed `FakeRecorderBackend()`; the CLI's `--backend` accepted only `fake/replay`; `set_transport` stored configuration that nothing read back; an open A2L never filled the left pane; `daq_timestamp_size=0` collapsed the MF4 time axis. The user's "A2L 变量名一个都不显示" report became the surface symptom of a much deeper chain-disconnect.

Phase A is the Mac-side ceiling on what can be fixed without Vector hardware. Eight items, all landed in this session, all behind regression tests. Vector real-hardware verification is the next phase (Phase B / PR-4 bench runbook).

## The 8 Phase-A items

| # | Task | Files touched | Tests added |
|---|---|---|---|
| T1-1 + T1-2 | Pick A2L populates left pane; remove silent `limit=20` | `can_logger/p0/a2l_probe.py`, `mf4_analyzer/acquisition_ui/main_window.py` | `tests/acquisition_ui/test_pick_a2l_populates_left_pane.py` (4) |
| T1-5 | `ts_size=0` per-frame arrival timestamp | `mf4_analyzer/acquisition_capture/dto_decode.py`, `backends.py` | `tests/test_dto_decode.py` (+4) |
| T1-3 + T1-4 | Cockpit + CLI wire `VectorXcpRecorderBackend` | `mf4_analyzer/acquisition_capture/__main__.py`, `mf4_analyzer/acquisition_ui/main_window.py` | `tests/test_cli_vector_backend.py` (4), `tests/acquisition_ui/test_record_backend_swap.py` (5) |
| T1-6 | Cockpit hydrate + persist `acquisition_config.yaml` | `mf4_analyzer/acquisition_capture/config_store.py`, `mf4_analyzer/acquisition_ui/main_window.py` | `tests/acquisition_ui/test_config_path_persistence.py` (6) |
| T2-2 + T2-3 | A2L parse failure: modal warn + clear stale `_ifdata_xcp` | `mf4_analyzer/acquisition_ui/main_window.py` | `tests/acquisition_ui/test_pick_a2l_warnings.py` (3) |
| T3-1 + T3-2 | Extract PR-4 bench runbook + evidence dir | `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md`, `docs/analyzer/acquisition/evidence/stage-8/README.md` | n/a (docs) |
| T3-3 | `vector_probe` layered exit codes (1/2/3/4 + 9/10) | `can_logger/p0/vector_probe.py` | `tests/test_vector_probe_stages.py` (9) |
| Phase-A gate | Full Mac pytest sweep | n/a | n/a |

**Final pytest run:** `983 passed, 2 skipped` (the 2 skips are `P0_A2L_PATH` real-A2L env-gated test and a vector-hardware-only smoke).

## Production-relevant subtleties

### Cockpit backend swap respects caller injection
`_maybe_swap_to_vector_backend()` only replaces `self._backend` when it is currently an `isinstance(_, FakeRecorderBackend)`. Tests and replay flows that inject a non-Fake backend at construction time are never overwritten. This keeps the existing dependency-injection contract intact while still letting production swap to Vector when all preconditions hold.

### `[FAKE backend]` is loud on purpose
When transport / IF_DATA / pool preconditions are missing or Vector construction fails (non-Windows, missing python-can, etc.), the status bar shows `[FAKE backend] 不录真实 ECU: <reason>`. The reason is appended verbatim so the operator can fix the exact precondition. This is the operator's guard against a vehicle test that quietly records synthetic sines.

### `limit: int | None` is the public default
`load_measurement_summary` now defaults to `limit=None` (every measurement returned). Callers that previously relied on the implicit cap (`tests/test_p0_a2l_probe.py`, `scripts/probe_a2l_dbc.py`, the module's own CLI) all pass an explicit `limit` and keep working. The UI consumer that *needed* the full pool gets it.

### `daq_timestamp_size=0` resolution order
`decode_dto` now resolves the per-sample timestamp in three tiers:
1. `timestamp_size > 0` → ECU clock (XCP canonical path).
2. `timestamp_size == 0` and `frame_arrival_monotonic_s` given → host `time.monotonic()` at frame arrival.
3. Otherwise → `base_monotonic_s` (legacy fallback so the pre-T1-5 test suite stays green without modification).

The Vector capture loop unconditionally passes (2); only the pure-decode tests fall through to (3).

### Settings save reuses existing yaml structure
`config_store.save_transport()` loads the existing yaml (or builds an empty store), replaces only the `transport` block, and writes back. Favorites, selected measurements, filter state, and threshold overrides are preserved. This avoids the "Settings save nuked my favorites" footgun.

### A2L warning dialog is window-modal but non-blocking
Static `QMessageBox.warning()` blocks the offscreen test runner indefinitely (we hit this hang mid-implementation). Switched to `QMessageBox.open()` with `Qt.WindowModal`: the operator still can't dismiss the cockpit without acknowledging, but the test harness returns immediately. See companion lesson `pyqt-ui/2026-05-19-qmessagebox-static-warning-hangs-offscreen.md`.

### `vector_probe` failure-triage codes are part of the action board contract
The action board's "Common errors" table references exit codes 1/2/3/4 by number. Renaming them would break operator-facing docs. The codes are documented in the module docstring and the test suite asserts each one stays at its declared number.

## What did NOT change

- **State machine** — no changes to `CockpitStateMachine`. The bug was in the *wiring* between transport/A2L/backend, not in the state model.
- **MF4 writer** — the `Mf4Writer` was already correct; only the upstream sample stream was broken (T1-5).
- **Spec docs** — `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md` was untouched. All Phase-A items are wiring fixes; none require spec amendments.
- **Squad routing** — the user's messages did not contain squad keywords, so this was executed by main Claude directly per the CLAUDE.md escape-hatch / out-of-scope rules. The decomposition was driven by the chain-scan analysis in turn 3 of the conversation; that analysis is captured in the action board's "链路扫描" callout for any future re-execution.

## Open items handed to Phase B (Windows / VN1630 离车预检)

Operator follows `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md` §Pre-flight, then §Test sequence Step 1 (cold connection). The expected `vector_probe` output for a healthy box is documented in the runbook §0; failure exit codes map back to action-board rows by number.

## Open items handed to Phase C (车上 ECU)

`stage-8-pr4-bench.md` §Test sequence Steps 3–6. Acceptance criteria + ts_size=0 cross-check are in §Acceptance gate.

## Files changed (commit-ready summary)

```
modified:
  can_logger/p0/a2l_probe.py                (limit: int | None)
  can_logger/p0/vector_probe.py             (full rewrite — layered stages + exit codes)
  mf4_analyzer/acquisition_capture/__main__.py
  mf4_analyzer/acquisition_capture/backends.py
  mf4_analyzer/acquisition_capture/config_store.py  (+save_transport)
  mf4_analyzer/acquisition_capture/dto_decode.py
  mf4_analyzer/acquisition_ui/main_window.py
  tests/test_dto_decode.py

added:
  docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md
  docs/analyzer/acquisition/runbooks/2026-05-19-stage-8-vn1630-vehicle-test-action-board.html
  docs/analyzer/acquisition/evidence/stage-8/README.md
  tests/acquisition_ui/test_config_path_persistence.py
  tests/acquisition_ui/test_pick_a2l_populates_left_pane.py
  tests/acquisition_ui/test_pick_a2l_warnings.py
  tests/acquisition_ui/test_record_backend_swap.py
  tests/test_cli_vector_backend.py
  tests/test_vector_probe_stages.py
  docs/analyzer/acquisition/reports/2026-05-19-stage-8-phase-a-execution-report.md  (this file)

lessons added:
  docs/lessons-learned/pyqt-ui/2026-05-19-qmessagebox-static-warning-hangs-offscreen.md
  docs/lessons-learned/signal-processing/2026-05-19-branch-reached-is-not-behavior-correct.md
  docs/lessons-learned/refactor/2026-05-19-default-fallback-must-be-observable.md
```

No git commit was created by this session — that's the user's call.
