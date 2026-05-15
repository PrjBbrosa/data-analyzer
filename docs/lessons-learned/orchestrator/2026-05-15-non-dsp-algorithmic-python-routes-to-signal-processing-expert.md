---
cause: decomposition
role: orchestrator
date: 2026-05-15
tags: [routing, decomposition, signal-processing-expert, refactor-architect, agent-roster, body-vs-shape]
status: active
---

# Non-DSP algorithmic Python belongs to signal-processing-expert, not refactor-architect

## Observed in

`docs/analyzer/acquisition/reports/2026-05-15-cockpit-execute-report.md` Stage 3 of the Acquisition Cockpit execution wave. Orchestrator decomposition at
`docs/lessons-learned/orchestrator/decompositions/2026-05-15-acquisition-cockpit-execute.md` originally routed S3 to `refactor-architect` with the rationale "non-FFT/non-filter algorithmic Python → refactor-architect, NOT signal-processing-expert."

`refactor-architect` correctly refused via the agent's pre-Write self-check: every S3 deliverable was new module body, new dataclass fields with parsing logic, new numeric formulas, or new persistence I/O — none of which fits `refactor-architect`'s scope of "file move / rename / re-export shim / import-statement update / entry-point wiring." The agent flagged `signal-processing-expert` as the proper owner. Main Claude re-dispatched, and `signal-processing-expert` delivered S3 with TDD-first discipline (59 new tests, all green, no regressions).

## Why orchestrator got the routing wrong

The original rationale conflated two distinct boundaries:

1. **Signal-domain boundary** — FFT / order analysis / filtering / windowing. This is a real specialization on `signal-processing-expert`.
2. **Body-vs-shape boundary** — writing new function bodies, new algorithm logic, new persistence I/O. This belongs to `signal-processing-expert` regardless of whether the algorithm is DSP. The `refactor-architect` only relocates / re-shapes existing code.

The agent description for `signal-processing-expert` says "FFT, order analysis, windowing, filtering, **numerical correctness for the MF4 Data Analyzer**." That last phrase — numerical correctness — covers any numeric algorithm, including:

- Preflight estimators (CAN bus load formula, throughput, record duration).
- Token-scoring search with explicit scoring weights.
- Band-classification helpers against threshold tables.
- A2L parsing with structured field defaults.
- Config-store I/O with UTF-8 round-trip and schema validation.

None of these is signal DSP, but all need TDD-first numeric correctness and live in `mf4_analyzer/acquisition_capture/`. They fit `signal-processing-expert`.

## Rule

When decomposing a stage that creates new module bodies, default to `signal-processing-expert` for any of these shapes, regardless of signal-domain content:

- New `*.py` file with functions/classes that have non-trivial logic in their body.
- New dataclass fields that require parsing/extraction code (not just type extension).
- Numeric formulas / scoring tables / band classifiers / thresholds.
- Persistence layer (JSON / YAML / hash / atomicity) with explicit schema and TDD.

Route to `refactor-architect` only when the brief is:

- File moves between packages.
- New `__init__.py` re-export shims.
- Import-statement updates triggered by relocations.
- Entry-point wiring (`__main__.py`, `setup.py` console_scripts) where the body is one-shot delegation.
- Cross-module relocation under an existing public API.

If the brief mixes both shapes (e.g. "move module X **and** add a new algorithm to it"), split into two nodes — `refactor-architect` for the move, `signal-processing-expert` for the algorithm.

## How `refactor-architect` defended the boundary

The agent's pre-Write self-check enumerates allowed edit categories:

> `(a) file move / rename, (b) new __init__.py or re-export shim, (c) import-statement update, (d) entry-point wiring`

When the brief asked for `MeasurementSummary` field extension with `IF_DATA XCP DAQ_EVENT` parsing, the agent classified that as "function-body change + new feature" and refused. This refusal is the correct behavior; do not overrule it by re-issuing the same brief.

## How to fix when this happens mid-execution

1. Read the refusal and the agent's `flagged[]` entry — it usually nominates the correct specialist.
2. Re-dispatch with a brief that explicitly acknowledges the re-routing ("originally routed to X; X refused per their roster; you are the correct owner").
3. Preserve all original constraints (forbidden files, owned-file list, TDD requirement).
4. After completion, write a decomposition lesson (this file) so the next orchestrator plan avoids the misroute.

## Cost paid this time

- One extra round trip (~78 s of refactor-architect time) before re-dispatch.
- No code rework — `refactor-architect` correctly stopped before any file write.
- Net loss: ~5 minutes of wall clock. Net gain: TDD-discipline-first execution under the right owner, 59 new tests with red-phase proof.

## See also

- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — adjacent rule: bundle mechanical metadata edits with the body creator, don't split.
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md` — adjacent rule: bundle paired callsite updates with the contract change.
