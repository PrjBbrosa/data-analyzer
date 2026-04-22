# Move-then-tighten across specialists causes file-level rework

**Cause:** rework
**Tags:** [decomposition][rework][cross-specialist][import-hygiene][move-pattern]
**Detected by:** main Claude (executor) Phase 3 rework scan
**Run:** modular restructure of `MF4 Data Analyzer V1.py` → `mf4_analyzer/` package, 2026-04-22

## Symptom

Two ordered subtask pairs landed file-level overlap with different specialists
on either side:

| Earlier subtask | Later subtask | Overlapping files | Earlier expert | Later expert |
|---|---|---|---|---|
| S1 `scaffold-package` | S6 `tighten-ui-imports` | `mf4_analyzer/ui/{canvases,dialogs,widgets,main_window}.py` | refactor-architect | pyqt-ui-engineer |
| S4 `move-ui-and-app`  | S6 `tighten-ui-imports` | `mf4_analyzer/ui/{canvases,dialogs,widgets,main_window}.py` | refactor-architect | pyqt-ui-engineer |

The S1↔S6 overlap is mechanically present but trivial (S1 created empty
modules; S6 added import hygiene). The S4↔S6 overlap is the substantive one:
S4 populated UI module bodies AND deliberately preserved the inherited
`from PyQt5.QtWidgets import *` wildcard, then S6 came right behind to
replace those wildcards with explicit name lists.

## Why it happened

The decomposition split a single coherent UI-file edit ("create the file
with explicit imports") across two specialists by domain:

- refactor-architect owns file relocation and import wiring (S4).
- pyqt-ui-engineer owns Qt-specific import hygiene (S6).

Each specialist's brief was correct in isolation; the rework is a consequence
of the boundary, not a planning defect. The spec
(`docs/superpowers/specs/2026-04-22-mf4-analyzer-modular-restructure-design.md`,
section "Rework detection — expected hits") explicitly predicted these S4↔S6
hits and accepted them as the cost of clean specialist boundaries.

## Was the boundary worth it?

Arguably yes for this run, because:

- pyqt-ui-engineer reading 4 freshly-created files cold has UI domain
  context that refactor-architect would not bring; the explicit name lists
  are non-trivial (canvases 2/2, dialogs 15/15, widgets 12/12, main_window
  22/22 names — see S6 return).
- Asking refactor-architect to BOTH move the bodies AND derive explicit Qt
  import lists in one pass would have inflated S4's scope (already the
  largest subtask) and mixed two distinct concerns in one specialist
  envelope.

But it would also have been defensible to fold the import hygiene into S4
(one extra grep + one extra import block per file, refactor-architect could
do it). The rework cost was 4 files re-edited; the boundary clarity cost
saved is harder to measure.

## Prevention / when to re-decide

When a future plan would create a "first specialist creates file body, second
specialist of a different domain immediately edits the same file's
imports/headers/typing-only metadata", consider:

1. **Fold the metadata edit into the body-creator's brief** when the
   metadata is mechanically derivable (grep `Q*` symbols → explicit list IS
   mechanical). Score: lower rework, slight scope creep on the body
   creator.
2. **Keep the split** when the metadata derivation requires domain expertise
   the body creator lacks. Score: rework lesson written (this lesson),
   higher confidence in the metadata.
3. **Move the metadata edit BEFORE the body creation** when the metadata is
   just imports — i.e., have the metadata specialist write the import block
   first, then hand off to the body creator. Generally not workable here
   because S6 needs to grep the bodies to know which imports.

For this codebase, default to option 1 (fold) unless the import list is
genuinely non-mechanical. The Qt wildcard cleanup is mechanical → next
similar refactor should pre-derive the explicit lists in the move step.

## Note on a non-hit that was predicted

The spec also predicted rework on `tests/test_fft_amplitude_normalization.py`
between S2 (refactor-architect) and S5 (signal-processing-expert). Actual
files_changed showed no overlap: S2 deliberately did NOT touch the test (it
preserved the monolith class definitions so the AST-extract test kept
working until S4); S5 then rewrote the test to use a direct import. This is
a coordinated handoff via a shared invariant (the AST-extract continues to
locate `FFTAnalyzer` until S4 collapses the monolith), not rework. The
literal rework rule (file intersection) correctly recognized this as
non-rework. Spec's prediction was overcautious.

## Index entry (to be written into `LESSONS.md`)

`- [move-then-tighten-causes-cross-specialist-rework](orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md) [decomposition][rework][cross-specialist] — Splitting "create file body" and "tighten file imports" across two specialists causes file-level rework; fold mechanical metadata edits into the body creator's brief unless domain expertise is required.`
