# MF4 Data Analyzer Modular Restructure — Work Report

**Date:** 2026-04-22
**Branch:** `claude/fft-remarks-chart-ui-sJ410`
**Spec:** `docs/superpowers/specs/2026-04-22-mf4-analyzer-modular-restructure-design.md`
**Squad runbook:** 4 phases, 6 specialist subtasks, fully serial.

## Outcome (one paragraph)

Collapsed the 2199-line monolith `MF4 Data Analyzer V1.py` into a 4-line
launcher that delegates to a new `mf4_analyzer/` package split across three
internal subpackages (`io/`, `signal/`, `ui/`) plus an application entry
(`app.py`), font helper (`_fonts.py`), and a shared color palette
(`_palette.py`). Behavior is preserved; numeric algorithms (`FFTAnalyzer`,
`OrderAnalyzer`, `ChannelMath`) moved byte-for-byte. Test count went from 8
passed (6 FFT + 2 quick_build) before refactor to **9 passed** after — the
extra test is a new guard verifying the signal layer never imports PyQt5 or
matplotlib.pyplot. Two new permanent lessons were written, plus one rework
lesson auto-detected by the executor's Phase 3 scan.

## What landed

### New package
```
mf4_analyzer/
├── __init__.py
├── app.py              # main(): font setup → matplotlib backend → QApplication → MainWindow
├── _fonts.py           # setup_chinese_font() (now called from main(), not at import time)
├── _palette.py         # FILE_PALETTES (mid-flight promotion to package root)
├── io/
│   ├── __init__.py
│   ├── loader.py       # DataLoader (mf4/csv/xlsx loading)
│   └── file_data.py    # FileData (in-memory data container)
├── signal/
│   ├── __init__.py
│   ├── fft.py          # FFTAnalyzer
│   ├── order.py        # OrderAnalyzer
│   └── channel_math.py # ChannelMath
└── ui/
    ├── __init__.py     # re-exports MainWindow only
    ├── canvases.py     # TimeDomainCanvas, PlotCanvas
    ├── dialogs.py      # ChannelEditorDialog, ExportDialog, AxisEditDialog
    ├── widgets.py      # StatisticsPanel, MultiFileChannelWidget
    └── main_window.py  # MainWindow (~877 lines, future spec to decompose)
```

### Root launcher (preserved path for PyInstaller spec)
`MF4 Data Analyzer V1.py` is now exactly:
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from mf4_analyzer.app import main

if __name__ == "__main__":
    main()
```

### Tests
- `tests/test_fft_amplitude_normalization.py` — rewrote `_load_fft_analyzer()`
  AST extraction with `from mf4_analyzer.signal.fft import FFTAnalyzer`. All
  6 test method bodies and assertions are byte-identical to the prior
  version.
- `tests/test_signal_no_gui_import.py` — NEW. Spawns a child process,
  poisons `sys.modules['PyQt5']` and `sys.modules['matplotlib.pyplot']` with
  `None` (which makes CPython raise `ModuleNotFoundError` on subsequent
  `import <name>`), then imports `mf4_analyzer.signal.fft` and asserts
  success. Includes a meta-sanity check that intentionally tries to import
  the poisoned names after poisoning to verify the poisoning idiom actually
  blocks.
- `pytest -q tests/` final state: **9 passed, 0 failed** (≈ 0.46s).

## Squad execution trace

| # | Subtask | Specialist | Outcome | tests_before → tests_after |
|---|---|---|---|---|
| S1 | scaffold-package | refactor-architect | done | 8 → 8 |
| S2 | move-signal | refactor-architect | done | 8 → 8 |
| S3 | move-io | refactor-architect | done | 8 → 8 |
| S4 | move-ui-and-app | refactor-architect | done | 8 → 2 (transient, AST collection error) |
| S5 | rewire-tests-and-guard | signal-processing-expert | done | 2 → 9 |
| S6 | tighten-ui-imports | pyqt-ui-engineer | done | 9 → 9 |

**top_level_status: done.** No `blocked` or `partial` outcomes.

## Mid-flight design corrections

### FILE_PALETTES dependency violation
The original spec located `FILE_PALETTES` in `ui/_palette.py`. S3 surfaced
that `FileData` (io layer) calls `get_color_palette()` which uses
`FILE_PALETTES` — putting the constant in `ui/` would force `io/` to import
from `ui/`, violating the dependency rule. S3 worked around by inlining the
constant in `io/file_data.py`. S4 received the corrected brief: promote the
constant to `mf4_analyzer/_palette.py` (package root, sibling of `_fonts.py`),
delete the now-redundant pre-scaffolded `ui/_palette.py`. Both io and ui
import via `from .._palette import FILE_PALETTES`. S4 also wrote a refactor
lesson capturing the pattern.

### Test count off by one
Spec said baseline 7 tests (5 FFT + 2 quick_build). S1's actual baseline run
showed 8 (6 FFT + 2 quick_build) — the FFT test file has 6 methods, not 5.
All subsequent specialist briefs were corrected mid-flight to use 8 as the
invariant.

### Matplotlib backend selection
The original monolith called `matplotlib.use('Qt5Agg')` at line 20 (import
time). S4 moved this into `app.py`, called inside `main()` BEFORE
`from .ui import MainWindow`. This both (a) keeps the signal layer
backend-agnostic and (b) avoids backend-already-selected races if `signal/`
is imported in headless tests.

## Phase 3 — Rework detection results

Per CLAUDE.md rule (different specialists + non-empty `files_changed`
intersection on an ordered pair):

| Pair | Overlap | Rework? | Notes |
|---|---|---|---|
| S1 → S6 | 4 ui/*.py files | yes (mechanically) | Trivial: S1 created empty scaffolds, S6 added explicit imports. Same root cause as S4→S6. |
| S4 → S6 | 4 ui/*.py files | yes (substantive) | S4 populated bodies preserving wildcard import; S6 replaced wildcards with explicit name lists. The boundary between "create body" and "tighten Qt imports" cost 4 file re-edits. |
| All other pairs | ∅ | no | The spec predicted S2↔S5 rework on `tests/test_fft_amplitude_normalization.py`, but S2 deliberately did NOT touch that test (preserved monolith for ast-extract continuity); S5 then rewrote it. Coordinated handoff via shared invariant, not rework. |

One consolidated rework lesson written:
`docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`.
The lesson recommends folding mechanical metadata edits (like Qt name-list
derivation) into the body creator's brief unless domain expertise makes a
separate specialist pass valuable. For the wildcard cleanup the next similar
refactor should pre-derive the explicit lists in the move step.

## Phase 4 — State

`docs/lessons-learned/.state.yml`: `top_level_completions: 2 → 3`.
`last_prune_at: 0`. Distance to prune threshold (20): 17 runs. No prune
cycle this run.

## Lessons added this run

- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
  (auto-detected by Phase 3 rework scan; pattern across S1↔S6 and S4↔S6).
- `docs/lessons-learned/refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md`
  (written by S4 specialist for the FILE_PALETTES mid-flight correction).
- `docs/lessons-learned/orchestrator/decompositions/2026-04-22-mf4-analyzer-modular-restructure.md`
  (decomposition audit by squad-orchestrator; not a behavior lesson but
  recorded for traceability).

## Acceptance criteria (from spec)

| Criterion | Status |
|---|---|
| `pytest -q tests/` reports green | ✅ 9 passed (spec said 8; baseline correction explained above) |
| `python -c "from mf4_analyzer.app import main; print('ok')"` prints `ok` | ⚠️ Could not exercise in this env — PyQt5 Qt DLLs fail to load on the workstation independently of this refactor. Static import-graph verified clean by S4 and S6. |
| `python -c "from mf4_analyzer.signal.fft import FFTAnalyzer; ..."` prints `clean` | ✅ Verified by S2/S4/S6 specialists; also enforced as the new test guard. |
| `MF4 Data Analyzer V1.py` is the 4-line launcher | ✅ |
| Package layout matches spec | ✅ (with the mid-flight `_palette.py` correction documented above) |
| `.state.yml` shows `top_level_completions: 3` | ✅ |
| Rework lessons written for all detected file overlaps | ✅ (one consolidated lesson covering both pairs) |

## Known environment caveat

The workstation cannot import `PyQt5.QtWidgets` directly (Qt DLL load
failure pre-existing this refactor, reproduces with bare PyQt5 import).
Specialists relied on AST-level / static verification for UI changes; the
runtime smoke (`from mf4_analyzer.ui import MainWindow`) and a manual GUI
launch were not exercised. PyInstaller-built artifact would not be affected
because it bundles its own Qt runtime. End user should sanity-launch
`python "MF4 Data Analyzer V1.py"` once on a working environment before
shipping.

## Next step (per spec post-runbook hook)

Dispatch `codex:rescue` for an independent review of the refactored
package. Address any concrete defects it surfaces in a follow-up dispatch
(specialist chosen by defect domain). Then ship.
