---
date: 2026-05-17
stage: 8
pr: PR-1
plan: docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md
spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md
verdict: GREEN_WITH_LIMITS
author: codex
---

# Stage 8 PR-1 Report

## Verdict

**GREEN_WITH_LIMITS.** PR-1 is logically self-consistent after the follow-up
fixes in this report. It establishes the backend prerequisites for Stage 8:
Windows-only Vector/XCP optional dependencies, IF_DATA XCP parsing,
measurement-to-DAQ-event extraction, A2L summary enrichment, and v2
transport config persistence. It does not claim the live Vector/pyXCP backend
implementation or Windows hardware validation; those remain PR-2/PR-4 gates.

## Scope Reviewed

- Spec and plan: `docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md`, `docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md`
- Parser and A2L integration: `can_logger/p0/ifdata_xcp.py`, `can_logger/p0/a2l_probe.py`
- Transport persistence: `mf4_analyzer/acquisition_capture/transport_config.py`, `mf4_analyzer/acquisition_capture/config_store.py`, `mf4_analyzer/acquisition_capture/session.py`
- Tests and fixtures: `tests/test_ifdata_xcp_parser.py`, `tests/test_acquisition_a2l_events.py`, `tests/test_transport_config.py`, `tests/test_config_store_migration.py`, `tests/fixtures/ifdata_xcp/`

## Implemented

- Added the frozen IF_DATA XCP model and parser with CAN/CAN FD transport
  extraction, timestamp metadata, DAQ processor info, DAQ events, and
  measurement event references (`can_logger/p0/ifdata_xcp.py:17`,
  `can_logger/p0/ifdata_xcp.py:303`, `can_logger/p0/ifdata_xcp.py:325`).
- Enriched A2L summaries with parsed DAQ event capacity and per-measurement
  compatible events, using the same latin-1 tolerant A2L read path used by
  the parser file entrypoint (`can_logger/p0/a2l_probe.py:73`,
  `can_logger/p0/a2l_probe.py:122`).
- Added `TransportConfig` and wired it into `SessionConfig` plus
  `acquisition_config.yaml` v2 migration/persistence
  (`mf4_analyzer/acquisition_capture/transport_config.py:10`,
  `mf4_analyzer/acquisition_capture/session.py:72`,
  `mf4_analyzer/acquisition_capture/config_store.py:154`).
- Added Windows-only dependency markers for Vector/CAN and XCP packages so
  macOS/Linux installs do not attempt to install hardware-specific packages
  (`requirements.txt:11`).

## Review Fixes Applied

1. **A2L file encoding bug fixed.** `parse_ifdata_xcp_file()` now reads A2L
   files with `encoding="latin-1", errors="replace"` instead of hard UTF-8,
   matching the existing `a2l_probe` raw-text path
   (`can_logger/p0/ifdata_xcp.py:333`, `can_logger/p0/a2l_probe.py:122`).
   Regression coverage was added with a latin-1 comment byte that would fail
   under UTF-8 (`tests/test_ifdata_xcp_parser.py:95`).

2. **Transport config schema tightened.** `TransportConfig.from_dict()` now
   rejects unknown nested keys, non-bool booleans, stringified ints, invalid
   positive-number fields, and out-of-range sample points instead of silently
   dropping unknown keys (`mf4_analyzer/acquisition_capture/transport_config.py:23`).
   The config loader wraps these failures as `ConfigSchemaError` so project
   config files fail loudly (`mf4_analyzer/acquisition_capture/config_store.py:157`).
   Regression coverage checks both direct validation and YAML load rejection
   (`tests/test_transport_config.py:58`, `tests/test_config_store_migration.py:66`).

3. **Plan drift fixed.** The plan snippet no longer uses only
   `ifdata_blocks[0]`; it now walks every parsed IF_DATA block, matching the
   live implementation in `_fill_ifdata_events()`
   (`docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:895`,
   `can_logger/p0/a2l_probe.py:84`).

## Validation Evidence

- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_ifdata_xcp_parser.py tests/test_transport_config.py tests/test_config_store_migration.py tests/test_acquisition_config_store.py -v`
  - Result: **34 passed in 0.49s**
- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition* tests/test_ifdata_xcp_parser.py tests/test_transport_config.py tests/test_config_store_migration.py -v`
  - Result: **228 passed in 7.88s**
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test`
  - Result: exit 0; Qt printed `This plugin does not support propagateSizeHints()`
- Legacy-drift grep over the Stage 8 plan/spec/report for stale bare
  command examples, stale identifiers, old UI smoke flags, and the old
  first-IF_DATA-block snippet
  - Result: no matches
- `rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" ...`
  - Result: no matches
- `git diff --check`
  - Result: no whitespace errors
- `/usr/bin/python3 scripts/lessons/check.py --status`
  - Result: `lesson_required: False`, `candidate_exists: False`

## Remaining Gates

- **PR-2:** implement the actual `python-can` Vector transport facade and
  backend wiring against the PR-1 transport/config contracts.
- **PR-3:** add protocol grouping/fallback behavior if the selected A2L
  metadata is incomplete or incompatible across measurements.
- **PR-4:** run Windows + Vector XL hardware validation with real CAN/CAN FD
  and XCP targets. Current PR-1 proof is macOS/unit/UI-self-test only.

## Notes

- `scripts/probe_a2l_dbc.py` is currently untracked and was left outside this
  PR-1 report scope.
