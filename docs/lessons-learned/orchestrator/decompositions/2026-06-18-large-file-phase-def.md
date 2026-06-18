# Decomposition Audit — 2026-06-18-large-file-phase-def

**Task:** 退役 matplot 然后进行 EF 的优化 — phases D (retire matplotlib/canvases.py), E (main_window.py → package+mixins), F (acquisition_ui/main_window.py → package+mixins). Continuing on branch `refactor/large-file-decomp-abc`.

## Subtask table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| D — retire matplotlib (canvases.py helper extraction + class deletion) | refactor-architect | — | Pure file relocation, deletion of dead matplotlib classes, and shim maintenance. No Qt widget behaviour, no DSP computation. Includes test teardown for obsolete mpl tests. |
| E — main_window.py → main_window/ package + mixins | pyqt-ui-engineer | D completed and pytest green | Qt God class split; six domain mixins share `self`; Qt signal/slot wiring and Qt lifecycle methods are the dominant surface. FFT/Order/STFT numeric cluster carries brief note that signal-processing-expert review is available for numeric seams if needed. |
| F — acquisition_ui/main_window.py → main_window/ package + mixins | pyqt-ui-engineer | E completed and pytest green | Qt God class split; mixin clusters are connection, polling, toolbar, settings — all Qt domain. Must be serialised after E because both touch the git index on the same branch. |

## Lessons consulted

- `docs/lessons-learned/refactor/2026-06-18-monkeypatch-anchor-survives-module-to-package.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-06-18-large-file-phase-abc.md` (context, sibling decomposition)

## Routing notes

- D routed to `refactor-architect`: both sub-steps are relocation + deletion + shim. No widget behaviour.
- E routed to `pyqt-ui-engineer` (not `refactor-architect`): the 4754-line file is a Qt God class (`QMainWindow` subclass), and the dominant risk is mixin field-init-order safety — a Qt lifecycle concern, not a pure module-move concern. The spec §3.4 explicitly says "pyqt-ui-engineer + signal-processing-expert available if any FFT/order/STFT numeric seam needs review".
- F routed to `pyqt-ui-engineer`: same mixin pattern, Qt domain, acquisition cockpit window.
- D→E→F chained strictly: same-branch mutators must serialize.

## Missed trigger recorded

Incoming message contained "优化" (optimize) but not a current trigger token. Routing was correct (entails `.py` source edits). Lesson written to `orchestrator/2026-06-18-optimize-verb-missed-trigger.md`.
