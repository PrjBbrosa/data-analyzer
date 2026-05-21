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
| [Codex Publish Flow Lightweight](codex-publish-flow-lightweight.md) | Publish already-local changes: commit, push, open/write PR. | Bounded git status/diff/checks; no audit-style exploration |
| [Codex Lessons System Maintenance](codex-lessons-system-maintenance.md) | Codex lessons system changes, hook tuning, master-kit sync, or `scripts/lessons/*` edits. | `scripts/lessons/check.py --doctor --verbose` |
| [Confirmed Issue List Means Remaining Scope](codex-confirmed-issue-list-means-remaining-scope.md) | Numbered issue follow-ups where the user approves some items and asks a design question about another. | `git status --short`, `git diff --stat`, explicit checklist |
| [Chart Toolbar Label Order](pyqt-ui/2026-05-12-chart-toolbar-label-order.md) | Chart toolbar layout, Matplotlib locLabel, in-toolbar hint text, or per-card controls. | `tests/ui/test_chart_stack.py` |
| [Matplotlib Resize And Modal Nav State](pyqt-ui/2026-05-13-matplotlib-resize-and-modal-nav-state.md) | Touching Matplotlib-backed PyQt canvases, splitter/inspector resize behavior, chart-options double-click flows, or chart toolbar navigation actions. | See lesson |
| [Codex Analyzer Doc Routing](codex-analyzer-doc-routing.md) | Creating, moving, or referencing analyzer-facing documentation and review artifacts. | See lesson |
| [Acquisition Validation Evidence Gates](codex-acquisition-validation-evidence-gates.md) | Acquisition validation docs, preflight/regression tooling, smoke runners, or P0 probe evidence. | See lesson |
| [Acquisition Threshold Defaults Use Current Values](codex-acquisition-threshold-defaults-use-current-values.md) | Acquisition Cockpit editable thresholds, settings auto-load, `SessionConfig` defaults, health helper defaults, or preflight UI defaults. | See lesson |
| [Visual Parity Requires Rendered Screenshot](codex-visual-parity-rendered-screenshot.md) | Touching PyQt visual parity, QSS, toolbar controls, compact chips, or a UI implementation that is supposed to match an HTML prototype or screenshot. | See lesson |
| [Codex MF4 Source Path Alias Dedupe](codex-mf4-source-path-alias-dedupe.md) | Touching MF4 channel enumeration, analyzer channel lists, batch MF4 | See lesson |
| [Windows Native Imports Need Isolated Probe](codex-windows-native-import-guard.md) | Touching Windows acquisition backends, Cockpit startup/import paths, or optional native dependencies such as `pya2l`, `pyxcp`, or Vector `python-can`. | See lesson |
| [Phantom API Surface Guards](codex-phantom-api-surface-guards.md) | Mocking external library surfaces for acquisition probes or optional native dependencies. | Structured fakes/autospec; focused Vector probe tests |
| [Owned Backend Invalidation](codex-owned-backend-invalidation.md) | Touching Acquisition Cockpit backend swapping, transport/A2L settings, | See lesson |

## Selection Rules

- Use keywords, file paths, failing test names, and user prompt terms to select
  at most 1-5 relevant lessons.
- Prefer lessons with executable checks over prose-only lessons.
- If a task creates a new durable rule, add or update one lesson and update this
  table.
