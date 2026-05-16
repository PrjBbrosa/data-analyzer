---
date: 2026-05-15
stage: 0
plan: docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md
spec: docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md
verdict: GREEN
author: refactor-architect (Stage 0 doc-only scan)
---

# Acquisition Cockpit — Stage 0 Gap Note

This note pins the implementation starting state against the actual files
in the repo so downstream stages (S1–S8) do not regress on stale-report
assumptions. Stage 0 is documentation-only — no `.py` files were edited
and no new tests were added.

## Inputs Verified

### 1. Prototype HTML files live under `docs/analyzer/ui-prototypes/`

Confirmed. Files present (verbatim `ls`):

- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-options.html` (73 890 B, 2026-05-14 12:29)
- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v2.html` (65 685 B, 2026-05-14 12:40)
- `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html` (68 478 B, 2026-05-14 15:20) — **the approved v3 implementation source per the design report.**

No prototype HTML lives outside `docs/analyzer/ui-prototypes/`. Stages
2–5 may reference the v3 file as the rendering ground truth.

### 2. MainWindow has NO public file-load wrapper today

Confirmed via `grep -n "def load_file\b\|def load_files\b\|def _load_one\b"
mf4_analyzer/ui/main_window.py`:

```
576:    def load_files(self):
580:    def _load_one(self, fp):
```

- `load_files(self)` (line 576) is the **toolbar/file-dialog** entry —
  it pops a `QFileDialog.getOpenFileNames(...)` and iterates results
  through `_load_one`. It is NOT a single-path public API; Cockpit
  cannot call it without spawning a dialog.
- `_load_one(self, fp)` (line 580) is the **private** per-path loader.
  Its signature is `_load_one(fp)` (positional path, untyped). Body
  handles `.mf4` / `.xlsx` / `.xls` / `.csv` via `DataLoader`.

**Gap:** there is no `MainWindow.load_file(path: str | Path) -> None`
public wrapper. Cockpit Stages 2–4 MUST NOT reference `_load_one`
directly; the wrapper is created in Stage 5 ("Owned files" §Stage 5)
and is the only Analyzer-side .py modification the plan permits.

### 3. P0 status — Vector/XCP PARTIAL ⇒ Stage 8 hardware-gated

Confirmed against `docs/analyzer/acquisition/P0_Runbook.md`:

- L51 — MF4 gate: **PASS** (`test_p0_written_mf4_loads_through_existing_loader` PASSED, 0.23 s).
- L74 — A2L gate: **SKIPPED (acceptable)** under `P0_A2L_PATH` env gate.
- L152 — Vector / XCP: **PARTIAL** ("Resume path verified to import on macOS; full PASS requires Vector hardware on Windows").
- L185 — Overall: **PARTIAL**.
- L193 — Narrow PARTIAL with named/bounded blocker ("Vector hardware
  not present on macOS host"). Hardware-wired UI work (= Stage 8) is
  NOT authorized until the Vector CONNECT and XCP SHORT_UPLOAD gates
  run on Windows + Vector + powered ECU.

Stage 8 stays hardware-gated. Stages 0–7 proceed against
`FakeRecorderBackend` / `ReplayRecorderBackend` per plan.

### 4. Executable doc commands use `.venv/bin/python` or `PYTHONPATH=. .venv/bin/python`

Confirmed for this plan and the spec. Two contextual one-liners in
sibling docs use bare `python`:

- `docs/analyzer/acquisition/plans/2026-05-14-acquisition-validation-workflow.md:226`
- `docs/analyzer/acquisition/templates/issue_capture.md:22`

Both are intra-document copy-paste examples for users (a `python -c
"..."` SHA helper), not part of this plan's verification ladder. The
remaining `python` hits in the workflow doc (L448/476/484/497) are
Python source code (`env_python`, `python = _python_executable()`,
etc.), not shell invocations. No action required for Stage 0.

## Gap List — Four Green-Field Scopes Introduced By This Plan

Verified absent on disk (`ls` checks):

1. **`mf4_analyzer/acquisition_capture/health.py`** — owned by Stage 2.
   Hosts `HwHealth`, `CanHealth`, `XcpHealth`, `DaqHealth`, `RecHealth`
   dataclasses with `level()` helpers plus `HealthAggregator`. Does
   NOT exist today; `mf4_analyzer/acquisition_capture/` directory does
   not exist.
2. **`mf4_analyzer/acquisition_capture/preflight_estimates.py`** —
   owned by Stage 3. Four pure functions:
   `estimate_can_bus_load`, `daq_slot_usage`,
   `estimate_throughput_bps`, `estimate_record_duration_s`. Does NOT
   exist today.
3. **`mf4_analyzer/acquisition_ui/`** — owned by Stage 4. Whole
   package (`__init__.py`, `__main__.py`, `main_window.py`, `state.py`,
   `widgets/`, `widgets/live_downsampler.py`). Directory does NOT
   exist today. Distinct from existing `mf4_analyzer/acquisition/`
   (manifest/preflight/regression/signals — NOT to be renamed).
4. **Stage 5 Analyzer handoff method: `MainWindow.load_file(path: str | Path) -> None`** —
   public wrapper around private `_load_one` at
   `mf4_analyzer/ui/main_window.py:580`. Does NOT exist today (see
   Input 2 above). Only Analyzer-side .py modification the plan
   permits.

Future stages cross-check against this list. If any of these four
appears unexpectedly (added by another stage out-of-order), surface as
a flagged item.

### Adjacent name to NOT confuse

- `mf4_analyzer/acquisition/` exists today and contains
  `manifest.py`, `preflight.py`, `regression.py`, `signals.py`. This
  is the post-record diagnostics module from the validation program.
  It is NOT the same package as `acquisition_capture/` or
  `acquisition_ui/`. Stage 2 must not move or rename these files.

## Test Suite Status

Command (verbatim from plan Stage 0 Verification):

```
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
```

Result: **52 passed, 1 skipped in 1.40 s** (pytest 9.0.3, PyQt5 5.15.11
/ Qt 5.15.18, Python 3.12.13 on Darwin).

- `tests/test_acquisition_manifest.py` — 16 PASSED
- `tests/test_acquisition_preflight.py` — 8 PASSED
- `tests/test_acquisition_regression.py` — 11 PASSED
- `tests/test_acquisition_signals.py` — 5 PASSED
- `tests/test_acquisition_smoke.py` — 3 PASSED
- `tests/test_p0_a2l_probe.py` — 1 PASSED, 1 SKIPPED
  (`test_p0_real_a2l_has_measurements` — documented `P0_A2L_PATH` skip,
  per P0 Runbook L74 acceptable).
- `tests/test_p0_mf4_probe.py` — 1 PASSED
- `tests/test_p0_vector_probe.py` — 2 PASSED (hardware-free portion)
- `tests/test_p0_xcp_probe.py` — 3 PASSED (hardware-free portion)
- `tests/synthetic/test_cot_known_order.py` — 1 PASSED
- `tests/synthetic/test_fft_known_tone.py` — 1 PASSED

No failures. The one skip is documented and unrelated to capture /
cockpit work.

## Verdict

**GREEN** for downstream stages (S1–S8).

- Prototype source-of-truth file is present and dated 2026-05-14.
- The MainWindow load-path gap is real and matches the plan's claim
  exactly — `_load_one(fp)` at `mf4_analyzer/ui/main_window.py:580`,
  no public `load_file` today.
- P0 PARTIAL is documented narrowly enough to authorize Stages 0–7
  but keeps Stage 8 hardware-gated.
- Executable verification ladder runs on `.venv/bin/python` with
  `PYTHONPATH=.` consistently.
- Stage 0 baseline pytest suite is green; capture / cockpit work
  starts from a clean tree, not a broken one.

## Notes For S1 / S2 / S3

- **S1 (`ui_kit` extraction):** sources to migrate are confirmed to
  exist:
  - `mf4_analyzer/ui/icons.py` (18 168 B) — present.
  - `mf4_analyzer/_fonts.py` (1 768 B, top-level, NOT under `ui/`) —
    present at top-level as plan states. Do NOT look in `ui/_fonts.py`.
  - `mf4_analyzer/ui/style.qss` (24 156 B) — present.
  - `mf4_analyzer/ui/widgets/searchable_combo.py` — `widgets/` dir is
    present; the file's existence at that exact name should be
    re-verified by S1 before move.
  - `mf4_analyzer/app.py` (3 602 B, with `_load_stylesheet`) — present.
  - S1's first edit is the import-boundary AST test
    (`tests/ui/test_import_boundaries.py`); Stage 0 does NOT preempt it.

- **S2 (`acquisition_capture/`):** package directory does not exist;
  S2 owns its creation. The adjacent `mf4_analyzer/acquisition/`
  (manifest/preflight/regression/signals) MUST be left alone — do not
  consolidate, rename, or hoist symbols across the two packages
  without a separate refactor brief. Channel-naming contract
  (`MF4 channel name == A2L measurement name` verbatim) is load-bearing
  for Stage 5 `expected_channels`; the writer-spike test
  `tests/test_acquisition_capture_writer.py::test_channel_names_match_a2l`
  enforces it.

- **S3 (`acquisition_capture/a2l_events.py`, `search.py`,
  `config_store.py`, `preflight_estimates.py`):** four pure modules,
  no Qt. The plan freezes the `SearchHit(measurement, score,
  match_spans)` shape — `match_spans` is a `list[tuple[int, int]]` of
  half-open ranges that the UI consumes directly without re-matching.
  S3 also owns
  `tests/test_acquisition_preflight_estimates.py`; band thresholds
  must be unit-tested per spec §Threshold Contract.

- **Boundary reminder for all stages:** Stage 0 confirmed that the
  Analyzer-side change in the plan is exactly one public wrapper at
  Stage 5 (`MainWindow.load_file`). Stages 1–4 / 6–7 MUST NOT edit
  `mf4_analyzer/ui/main_window.py`. The private `_load_one` body stays
  unchanged across the whole plan.

- **Lesson citation:** Task absence is expected, not a blocker — see
  `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`.
  This Stage 0 artifact was produced directly without dispatching
  further specialists; downstream stages are dispatched by main
  Claude, not by this report.
