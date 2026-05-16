# Module A Work Report — Acquisition Validation Foundation

- Date: 2026-05-14
- Branch: `feat/acquisition-validation-program`
- Head commit: `df0a63e`
- Specialist: `signal-processing-expert`

## Summary

Module A landed the acquisition-validation foundation in four sequenced
commits on `feat/acquisition-validation-program`, ending at
`df0a63e`. The work introduced a manifest schema and loader
(`mf4_analyzer/acquisition/manifest.py`), a preflight channel/path
checker (`acquisition/preflight.py`) with a CLI front-end
(`scripts/preflight.py`), a regression-snapshot harness
(`acquisition/regression.py`) with a CLI front-end
(`scripts/regression.py`), and synthetic-signal tests that pin FFT and
COT order extraction against analytically-known inputs. All four
acceptance gates A1–A4 are green: manifest validation, preflight CLI
exits, regression snapshot round-trip, and synthetic FFT/COT tone
agreement within tolerance. Module A is the unblocker for Modules B
(real-world golden MF4 capture) and Module C (CI-side regression
enforcement), both of which depend on the manifest, preflight, and
regression primitives shipped here.

## Acceptance gates

| Gate | Status | Evidence |
|------|--------|----------|
| A1 — Manifest schema + loader | green | `tests/test_acquisition_manifest.py` had 5 tests at Module A handoff; current checkout has 10 test definitions after later required-`sha256` and manifest-id polish. `data/manifest.example.json` doubles as a fixture and human-readable template. |
| A2 — Preflight check (channel + path) | green | `tests/test_acquisition_preflight.py` had 3 tests at Module A handoff; current checkout has 8 test definitions after alias, loader-failure, and sha256-skip polish. CLI smoke covered `preflight_valid` exit=0, `preflight_missing_channel` exit=1, `preflight_missing_path_default` exit=0 (skip-note), `preflight_missing_path_require_exists` exit=2. |
| A3 — Regression snapshot harness | green | `tests/test_acquisition_regression.py` had 4 tests at Module A handoff; current checkout has 11 test definitions after missing-channel, new-channel, NaN, CLI-failure, and endian-stability polish. `data/snapshots/.gitkeep` reserves the on-disk path. |
| A4 — Synthetic signal pin (FFT + COT) | green | `tests/synthetic/test_fft_known_tone.py` and `tests/synthetic/test_cot_known_order.py` (2 tests) pin FFT against a synthetic single-tone input and COT against a known-order synthetic ramp; COT ratio threshold (5×) passed first try. |

## Commits

| Task | SHA | Title |
|------|-----|-------|
| Task 1 — Manifest foundation | `b010a5a` | feat: add acquisition mf4 manifest foundation |
| Task 2 — Preflight CLI | `70e26ce` | feat: add mf4 acquisition preflight check |
| Task 3 — Regression snapshots | `2d4e254` | feat: add mf4 dataset regression snapshots |
| Task 4 — Synthetic checks | `df0a63e` | test: add acquisition synthetic signal checks |

## Tests

- Baseline before Module A: **517** tests passing.
- After Module A: **531** tests passing (`tests_after = 531`).
- New tests per task: Task 1 +5, Task 2 +3, Task 3 +4, Task 4 +2 — total +14 (5+3+4+2 = 14).
- **Post-execution correction (2026-05-15):** the three counts above are historical Module A handoff counts, not current branch totals. Current inventory by test definition is manifest 10 + preflight 8 + regression 11 + synthetic 2; use fresh pytest output for current PASS/FAIL.
- CLI smoke coverage on `scripts/preflight.py` exercised four distinct
  exit codes: `0` (valid manifest), `1` (missing channel), `0` (missing
  path, default skip), and `2` (missing path under `--require-exists`).
- 0 GUI / Qt imports introduced. The acquisition package is import-safe
  in headless contexts, which is a prerequisite for Module C (CI).

## Files changed

- `.gitignore`
- `data/golden/.gitkeep`
- `data/manifest.example.json`
- `data/snapshots/.gitkeep`
- `mf4_analyzer/acquisition/__init__.py`
- `mf4_analyzer/acquisition/manifest.py`
- `mf4_analyzer/acquisition/preflight.py`
- `mf4_analyzer/acquisition/regression.py`
- `scripts/preflight.py`
- `scripts/regression.py`
- `tests/test_acquisition_manifest.py`
- `tests/test_acquisition_preflight.py`
- `tests/test_acquisition_regression.py`
- `tests/synthetic/__init__.py`
- `tests/synthetic/test_fft_known_tone.py`
- `tests/synthetic/test_cot_known_order.py`

## Symbols touched

16 new symbols across `manifest.py`, `preflight.py`, `regression.py`
plus 2 CLI `main()` entrypoints plus 14 test functions. Full list in
the specialist's return JSON (commit `df0a63e` HEAD). Symbol-level
tracking is deliberate per the
`2026-04-25-silent-boundary-leak-bypasses-rework-detection` lesson —
file-level diffs alone hide cross-expert overlaps that the rework
detector needs to flag, so each new public symbol is recorded against
its task. `forbidden_symbols_check` is clean: 0 edits to Qt/UI/loader/
batch/FFT internals.

## Residual risk and follow-up

- **Module D (CI integration, roadmap §14) — deferred.** The
  regression and preflight CLIs are CI-ready (exit codes documented,
  no Qt imports), but no GitHub Actions / pre-commit wiring landed in
  Module A. Tracked for Module D.
- **Module E (bad-case synthetic corpus, roadmap L3) — deferred.** The
  synthetic suite currently pins only the *good* path (single tone,
  known order). Pathological inputs (clipping, NaN injection, sample-
  rate drift, dropped frames) are deferred to Module E.
- **Git LFS install — deferred** until the first real golden MF4 lands.
  `data/golden/.gitkeep` documents the deferral inline so the next
  contributor adding a binary golden file knows to install LFS first
  before committing.
- **5× COT ratio threshold passed first try.** If a future asammdf
  upgrade changes resampling internals, or if `COTOrderAnalyzer` is
  refactored, the synthetic COT test should be re-validated — the 5×
  margin is comfortable today but is not a deep safety factor.

## Lessons learned

Merged (read before/during Module A):

- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md`

No new lessons authored in Module A (`lessons_added: []`) — the
existing corpus covered the failure modes encountered.
