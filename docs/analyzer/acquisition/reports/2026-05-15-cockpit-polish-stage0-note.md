---
date: 2026-05-15
stage: 0
plan: docs/analyzer/acquisition/plans/2026-05-15-cockpit-polish-wave-implementation.md
spec: docs/analyzer/acquisition/specs/2026-05-15-cockpit-polish-wave-spec.md
verdict: GREEN
author: codex
---

# Acquisition Cockpit Polish Wave — Stage 0 Note

## Inputs Verified

- `mf4_analyzer/acquisition_capture/thresholds.py` exposes every threshold
  constant required by the Settings dialog field list.
- `mf4_analyzer.acquisition.manifest` exposes `load_manifest`,
  `Mf4DatasetEntry`, and `resolve_entry_path`.
- `mf4_analyzer.acquisition_capture.backends.ReplayRecorderBackend` exists and
  keeps the current synthetic/source-samples replay path. MF4-path replay is
  still an expected Stage 4 implementation gap, per the tightened polish spec.
- PyInstaller spec path exists at `build/spec/MF4DataAnalyzer.spec`.

## Baseline Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
```

Result: `192 passed, 1 skipped in 8.28s`.

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
```

Result: `494 passed, 81 warnings in 23.89s`.

The warnings are existing matplotlib/Qt font glyph warnings and do not block
this polish wave.

## Doc Routing Scan

```bash
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs/analyzer/acquisition docs/analyzer/README.md docs/README.md
```

Hits were limited to `docs/analyzer/acquisition/reports/2026-05-15-cockpit-execute-report.md`
quoting the earlier doc-routing lesson and explicitly saying those stale paths
were not added. No new polish-wave reference was routed to an old docs path.

## Verdict

GREEN to dispatch and integrate the polish-wave workers. The live checkout is
green before this wave's implementation begins; any later failures should be
attributed to the polish changes unless proven otherwise.
