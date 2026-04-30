# Lessons Learned Index

This index routes Codex to a small set of relevant lessons. Do not read every
lesson by default.

## Active Lessons

| Lesson | Trigger | Checks |
| --- | --- | --- |
| [Codex Review Report Contract](codex-review-report-contract.md) | Review-only code/plan/spec/commit reports with citations or fixed verdicts. | `git show`, `rg -n`, `nl -ba`, report heading check |
| [Codex Plan And Spec Literal Evidence](codex-plan-spec-literal-evidence.md) | Plan/spec rev verification, checklists, proceed/no-go reviews. | Full-artifact read, retired-identifier grep, checklist pass |
| [Codex Runtime Verification Entrypoints](codex-runtime-verification-entrypoints.md) | Running pytest, Qt/offscreen checks, Matplotlib-backed validation. | `.venv/bin/python -m pytest`, `TMPDIR=/tmp`, `MPLCONFIGDIR=/tmp` |
| [Codex Order Batch Boundaries](codex-order-batch-boundaries.md) | Order-analysis, batch runner, batch presets, current/free config flows. | Grep canonical FFT helpers and GUI-free `BatchRunner`; focused tests |
| [Codex FFT Time Review Shields](codex-fft-time-review-shields.md) | FFT-vs-Time wiring, cache/worker/export, validation reports. | Grep signal plumbing, cache keys, `SpectrogramResult`; reconcile fresh tests |
| [Codex Performance And UI Audit Flow](codex-performance-ui-audit-flow.md) | Performance research before edits; read-only UI audits. | Report-first flow; grep toast/modal paths and related tests |
| [Codex Order Canvas Wave Review](codex-order-canvas-wave-review.md) | Order-canvas wave reviews, stale-generation tests, strict scope. | `git status`, `git diff`, `git show HEAD:<file>`, scoped pytest |

## Selection Rules

- Use keywords, file paths, failing test names, and user prompt terms to select
  at most 1-5 relevant lessons.
- Prefer lessons with executable checks over prose-only lessons.
- If a task creates a new durable rule, add or update one lesson and update this
  table.
