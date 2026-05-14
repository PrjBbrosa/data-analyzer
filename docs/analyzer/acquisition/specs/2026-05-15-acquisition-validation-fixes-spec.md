# Acquisition Validation Fixes Spec

Date: 2026-05-15
Status: Approved for staged implementation after plan corrections
Plan: `docs/analyzer/acquisition/plans/2026-05-15-acquisition-validation-fixes.md`
Primary review input: `docs/analyzer/acquisition/reviews/2026-05-14-acquisition-docs-code-review.md`

## Goal

Close the 2026-05-14 acquisition-validation gaps without starting production
DAQ UI work. The result must make the offline validation track trustworthy,
make P0 resume paths truthful, and keep all acquisition work isolated from the
existing MF4 loader, UI, batch, FFT, and order-analysis surfaces.

## Scope

In scope:

- Regression snapshots fail loudly when requested channels are absent.
- Preflight converts loader failures into `PreflightResult(ok=False)` instead
  of uncaught exceptions.
- Snapshot comparisons treat `NaN`/`NaN` as equal and report new channels in
  the current snapshot.
- Sample hashes are pinned to explicit little-endian float64 bytes.
- P0 Vector and XCP probe modules exist, import on macOS, and keep hardware
  dependencies lazy.
- Alias runbook commands are runnable in a clean checkout using
  `X04C.example`, with local real mappings documented as untracked files.
- Required local/LFS manifest entries require `sha256`; optional examples and
  external paths remain exempt.
- Smoke runner, stale reports, dataclass immutability polish, A2L address
  handling, manifest id validation, and CLI friendliness are completed as
  Stage 3 polish.

Out of scope:

- No production DAQ UI, streaming tab, or live acquisition service.
- No changes to `mf4_analyzer.io.loader.DataLoader.load_mf4`.
- No loader-level standard-signal remapping.
- No hardware PASS claim for Vector/XCP without a Windows Vector workstation
  and powered ECU evidence.
- No confidential MF4, A2L, or vehicle-local signal mappings committed.

## Architecture Decisions

- Keep acquisition validation as a sidecar layer under
  `mf4_analyzer/acquisition/`, `scripts/`, `can_logger/p0/`, tests, and
  analyzer docs.
- Keep raw MF4 channel names visible; standard-signal aliases are metadata used
  by preflight, not a replacement for loader output.
- Split execution by stage:
  1. Stage 1: correctness gates.
  2. Stage 2: truth-up and explicit policy decisions.
  3. Stage 3: docs, tests, and polish.
- Stage 2 must not begin until Stage 1 tests are green. Stage 3 must not begin
  until Stage 2 is green.

## Acceptance Gates

- Stage 1 passes:
  `PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py tests/test_acquisition_preflight.py -v`
- Stage 2 passes:
  `PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_vector_probe.py tests/test_p0_xcp_probe.py tests/test_acquisition_signals.py tests/test_acquisition_manifest.py tests/test_acquisition_preflight.py -v`
- Stage 3 passes:
  `PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v`
- Final smoke passes:
  `.venv/bin/python scripts/acquisition_smoke.py --skip-regression`
- Non-MF4 preflight CLI returns controlled failure JSON, not a traceback:
  `python scripts/preflight.py docs/analyzer/acquisition/templates/issue_capture.md --require-exists`
  exits 1 with `ok=false` and a `loader failed` problem.

## Execution Notes

- Treat the updated plan as the source of truth for exact test names, code
  snippets, and per-task commit messages.
- If a plan step conflicts with this spec, stop and surface the conflict before
  editing code.
- Use the repo verification entrypoint with `PYTHONPATH=.` and `.venv/bin/python`.
- Do not use shell write shortcuts for file creation; create/edit source with
  normal patching.
