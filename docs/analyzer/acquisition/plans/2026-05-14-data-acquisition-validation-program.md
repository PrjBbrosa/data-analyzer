# Data Acquisition Validation Program — Master Index

**Goal:** Turn historical MF4 data, synthetic signal checks, P0 XCP feasibility evidence, bench checks, and vehicle quick checks into a repeatable acquisition verification workflow. The program is split into independently-shippable modules; this document is the index.

**Architecture invariant (applies to every module):** Keep the existing XCP P0 plan as the hardware feasibility gate and add the offline validation track first. New offline code lives under `mf4_analyzer/acquisition/` plus thin scripts under `scripts/`; it uses the existing `mf4_analyzer.io.loader.DataLoader.load_mf4` instead of changing the loader contract. Standard signal mapping is a **sidecar** alias layer (Module B) so raw MF4 channel names remain visible and existing UI, search, batch presets, and reports do not break.

**Format invariant:** Manifests and signal mappings are JSON, not YAML. Where the roadmap shows YAML it is conceptual — JSON keeps the runtime stdlib-only.

---

## Source Inputs

This program consolidates:

- `docs/analyzer/acquisition/CAN_Logger_Integration_Report.md`
- `docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md`
- `docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md`

---

## Module Map

| ID | Module | File | Status |
| --- | --- | --- | --- |
| A | Offline foundation — manifest, preflight, regression, synthetic | [`2026-05-14-acquisition-offline-foundation.md`](2026-05-14-acquisition-offline-foundation.md) | Ready |
| B | Standard signal alias sidecar | [`2026-05-14-acquisition-signal-aliases.md`](2026-05-14-acquisition-signal-aliases.md) | Ready, depends on A |
| C | Validation workflow & docs (templates, runbook, smoke runner) | [`2026-05-14-acquisition-validation-workflow.md`](2026-05-14-acquisition-validation-workflow.md) | Ready, depends on A |
| P0 | XCP / Vector hardware feasibility | [`2026-05-13-xcp-acquisition-p0.md`](2026-05-13-xcp-acquisition-p0.md) | Pre-existing, independent of A/B/C |
| D (future) | CI integration — pre-commit + PR gates (roadmap §14) | `2026-05-14-acquisition-ci-integration.md` | Not yet drafted |
| E (future) | Bad-case synthetic MF4 corpus (roadmap L3) | `2026-05-14-acquisition-badcase-corpus.md` | Not yet drafted |

---

## Dependency Graph

```text
A (offline foundation)
  ├── B (signal aliases)       → adds standard-signal resolution to preflight
  ├── C (workflow & docs)      → consumes A's scripts; templates Bug→Regression loop
  └── D (CI integration)*      → wires A/B/C into pre-commit and PR CI
       (* future)

P0 (XCP feasibility) — independent track; its PASS gate unblocks production DAQ work
E (bad-case corpus)* — feeds A's regression with deliberate failure fixtures
       (* future)
```

A is the unblocker. B and C can ship in parallel once A is merged. P0 runs on its own branch and feeds the Validation Runbook in C without depending on A's code.

---

## Acceptance Gate Matrix

Roll-up of each module's gates plus the program-level gate.

| Gate | Source | Required evidence |
| --- | --- | --- |
| A1 Manifest | Module A | `tests/test_acquisition_manifest.py` PASS, JSON schema rejects malformed entries |
| A2 Preflight | Module A | `tests/test_acquisition_preflight.py` PASS, CLI exit codes correct |
| A3 Regression | Module A | `tests/test_acquisition_regression.py` PASS, snapshot create-then-compare loop works |
| A4 Synthetic | Module A | `tests/synthetic/` PASS without GUI deps |
| B1 Alias module | Module B | `tests/test_acquisition_signals.py` PASS |
| B2 Preflight integration | Module B | `analyze_mf4` reports `resolved_signals` when configured |
| B3 Legacy parity | Module B | `analyze_mf4` with no signal config matches Module A behavior — test enforced |
| B4 Configs | Module B | `standard_signals.json` parses, X04C example resolves |
| C1 Templates | Module C | 4 templates present, referenced from runbook |
| C2 Smoke runner | Module C | `python scripts/acquisition_smoke.py` correct exit codes |
| C3 Workflow rule | Module C | Change-type matrix encoded in Validation_Runbook.md |
| C4 Bug→Regression | Module C | `templates/issue_capture.md` encodes roadmap §12 |
| P0 | Existing P0 plan | `P0_Runbook.md` verdict ∈ {PASS, PARTIAL} with documented next action |
| G★ Program | This file | All of A1–A4, B1–B4, C1–C4, P0 met |

---

## Execution Order (Recommended)

1. **Module A** end-to-end. Foundation is small; ship it first.
2. **Modules B and C** in parallel branches off `feat/acquisition-offline-foundation` (or `main` after A merges).
3. **P0** runs whenever Windows + Vector hardware is available; not blocked by A/B/C.
4. **Production DAQ work (UI tab, streaming, hardware-dependent imports)** is deferred until **both** the program gate G★ is met **and** P0 verdict is PASS or a documented narrow PARTIAL.

---

## Deferred Until P0 PASS

Do not implement these until the existing XCP P0 plan has a PASS verdict (or a narrow documented PARTIAL):

- Production DAQ streaming.
- DAQ UI tab or dock.
- Realtime plotting of live acquisition values.
- `requirements.txt` additions for `python-can[vector]`, `pyxcp`, `pya2ldb`, or `pyelftools`.
- Any change that makes acquisition hardware dependencies required for normal analyzer startup.

If P0 is BLOCKED because the ECU requires seed/key handshake before SHORT_UPLOAD (a common gating condition not currently exercised by the P0 probes), treat it as PARTIAL pending a follow-up that adds seed/key — and keep working only on:

- manifest coverage,
- regression snapshots,
- synthetic tests,
- standard signal sidecar,
- bench/vehicle documentation,
- resolving the specific P0 blocker.

---

## Notes vs Roadmap

Where this program intentionally diverges from `2026-05-14-data-acquisition-validation-roadmap.md`:

| Roadmap section | Program decision | Reason |
| --- | --- | --- |
| §3, §6 (YAML manifests / mapping) | JSON | stdlib only; no PyYAML in runtime |
| §6 (loader emits standard signals) | Sidecar via Module B | Avoid breaking existing UI/batch/search; revisit after Module B ships |
| §4 (Git LFS for `data/golden/`) | Documented in `data/golden/.gitkeep`; LFS install deferred to the first golden file | Module A can run with zero LFS dependency |
| §14 (CI hookups) | Deferred to future Module D | Keep A/B/C self-contained; CI work is its own spec |
| L3 bad-case corpus | Deferred to future Module E | Synthetic positive correctness (L1.5) lands first |

---

## Branch Strategy

One feature branch per module (each module's spec spells out its branch). Do **not** bundle A + B + C in a single branch — the whole point of the split is independent review and rollback.

Module P0 has its own branch (`feat/xcp-acquisition-p0`) per its own plan and does not mix into the offline branches.

---

## Final Verification (Program Level)

Run after each module's own final verification:

```bash
git status --short
PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_acquisition_manifest.py \
    tests/test_acquisition_preflight.py \
    tests/test_acquisition_regression.py \
    tests/test_acquisition_signals.py \
    tests/synthetic -v
python scripts/acquisition_smoke.py
```

Expected:

- All four acquisition test files plus the synthetic suite pass.
- Cross-platform smoke runner exits 0 with the local manifest either valid or absent.
- P0 runbook verdict is recorded under `docs/analyzer/acquisition/P0_Runbook.md` independently of the offline track.
