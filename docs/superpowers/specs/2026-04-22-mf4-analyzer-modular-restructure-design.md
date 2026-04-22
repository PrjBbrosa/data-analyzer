# MF4 Data Analyzer — Modular Package Restructure

**Date:** 2026-04-22
**Status:** Approved (user opted out of post-write review; runbook proceeds directly)
**Owner:** main Claude (executor) + squad-orchestrator (planner) + three specialists

## Goal

Break the 2199-line monolith `MF4 Data Analyzer V1.py` into a layered package
`mf4_analyzer/` with three internal subpackages (`io/`, `signal/`, `ui/`) plus
an `app.py` entry. Behavior stays equivalent; the existing two test files
remain green throughout. The exercise also serves as a stress test of the
agent squad's rework-detection mechanism.

## Non-goals (explicit YAGNI)

- **Not** restructuring `MainWindow` internally. It stays an 877-line class
  in `ui/main_window.py`; further decomposition is a future spec.
- **Not** changing any numeric algorithm in `FFTAnalyzer`, `OrderAnalyzer`,
  `ChannelMath`. Function bodies move byte-for-byte.
- **Not** changing PyInstaller spec or `quick_build.py`.
- **Not** introducing a new dependency, build system, or package manager.

## Final package layout

```
mf4_analyzer/
├── __init__.py                  # empty placeholder
├── app.py                       # main(), wires QApplication + MainWindow
├── _fonts.py                    # setup_chinese_font() (was line 24-64)
├── io/
│   ├── __init__.py              # re-export DataLoader, FileData
│   ├── loader.py                # class DataLoader        (was 96-179)
│   └── file_data.py             # class FileData          (was 180-226)
├── signal/
│   ├── __init__.py              # re-export FFTAnalyzer, OrderAnalyzer, ChannelMath
│   ├── fft.py                   # class FFTAnalyzer       (was 227-296)
│   ├── order.py                 # class OrderAnalyzer     (was 297-412)
│   └── channel_math.py          # class ChannelMath       (was 413-432)
└── ui/
    ├── __init__.py              # re-export MainWindow
    ├── canvases.py              # TimeDomainCanvas + PlotCanvas        (637-870, 915-1121)
    ├── dialogs.py               # ChannelEditor + Export + AxisEdit    (433-608, 609-636, 871-914)
    ├── widgets.py               # StatisticsPanel + MultiFileChannelWidget (1122-1147, 1148-1313)
    └── main_window.py           # class MainWindow                       (1314-2190)
```

Repository root after refactor:

- `MF4 Data Analyzer V1.py` — kept at original path, reduced to a 4-line
  launcher that calls `mf4_analyzer.app.main()`. PyInstaller spec & double-click
  flow stay intact.
- `MF4_Analyzer.spec`, `quick_build.py`, `requirements.txt` — untouched.
- Existing tests untouched in location; one test file gets its import logic
  rewritten in S5.

## Dependency rules (enforced by code review, not by tooling)

```
app          → ui, _fonts
ui           → signal, io
signal       → (numpy/scipy only — NO matplotlib, NO PyQt5)
io           → (numpy/pandas/asammdf/openpyxl only — NO matplotlib, NO PyQt5)
```

- `signal/*` imports **must not** include `PyQt5`, `matplotlib.pyplot`, or any
  GUI module. A guard test (added in S5) enforces this for `signal/fft.py`.
- All cross-subpackage imports use **relative** form: `from ..signal import FFTAnalyzer`.
- `__init__.py` files re-export only the public API:
  - `io/__init__.py` exposes `DataLoader`, `FileData`.
  - `signal/__init__.py` exposes `FFTAnalyzer`, `OrderAnalyzer`, `ChannelMath`.
  - `ui/__init__.py` exposes `MainWindow` only (canvases/dialogs/widgets stay UI-internal).
- `FILE_PALETTES` (currently a module-level constant at line 87) moves into
  `ui/_palette.py` (new private module) and is imported by canvases/widgets
  that need it. It is not exported from the package.

## Application startup

`mf4_analyzer/app.py` (final content):

```python
"""Application entry point."""
import sys
from PyQt5.QtWidgets import QApplication

from .ui import MainWindow
from ._fonts import setup_chinese_font


def main():
    setup_chinese_font()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
```

**Key migration decision:** `setup_chinese_font()` moves from import-time
(currently runs at line 64 of the monolith on `import`) to `main()`-time
(called once before `QApplication` is constructed). This keeps `signal/*`
clean — importing `mf4_analyzer.signal.fft` in a headless test no longer
triggers a matplotlib font scan. Trade-off: any future code that creates
PyQt widgets outside `main()` and needs Chinese rendering would have to call
`setup_chinese_font()` itself. There is no such caller today.

`MF4 Data Analyzer V1.py` (root launcher, final content, 4 lines):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from mf4_analyzer.app import main

if __name__ == "__main__":
    main()
```

## Test strategy

### Existing tests

| File | Action | Owner |
|---|---|---|
| `tests/test_fft_amplitude_normalization.py` | Replace `_load_fft_analyzer()` AST-extraction logic with `from mf4_analyzer.signal.fft import FFTAnalyzer`. All five test method bodies and assertions stay byte-identical. | signal-processing-expert (S5) |
| `tests/test_quick_build.py` | No change — references `MF4 Data Analyzer V1.py` which is preserved as the launcher. | — |

### New guard test (S5)

`tests/test_signal_no_gui_import.py` — verifies the "signal layer has no GUI
deps" rule by importing `mf4_analyzer.signal.fft` in a child process whose
`sys.modules` has `PyQt5` and `matplotlib.pyplot` poisoned. If the import
succeeds, the rule holds.

### Test count expectations

The AST-extract test reads `MF4 Data Analyzer V1.py` to locate the
`FFTAnalyzer` ClassDef. To keep this test green throughout the multi-phase
move, S2/S3 **copy** class bodies into the new package while leaving the
originals in the monolith. The originals are deleted only in S4 when the
monolith is collapsed to the 4-line launcher. S5 rewrites the test to use a
direct import in the same dispatch round that empties the monolith — so the
test never reaches a broken state across phase boundaries.

| Phase | Expected `pytest -q tests/` |
|---|---|
| Before refactor | 5 (FFT) + 2 (quick_build) = **7 passed** |
| After S2 (signal copied to package, originals retained) | **7 passed** (AST extract still finds class in monolith) |
| After S3 (io copied) | **7 passed** |
| After S4 (monolith emptied) | **2 passed** (AST test red — class no longer in monolith). Acceptable as a transient state because S5 ships in the same runbook. |
| After S5 (test rewritten + guard added) | 5 + 2 + 1 = **8 passed** |
| After S6 (UI imports tightened) | **8 passed** (S6 edits no test files) |

## Migration phases (squad decomposition)

Six subtasks executed strictly serially. Each specialist returns the standard
JSON envelope with `tests_before`, `tests_after`, `files_changed`, plus
specialist-specific fields (`files_moved` for refactor-architect,
`ui_verified` for pyqt-ui-engineer).

| # | subtask slug | expert | depends_on | summary |
|---|---|---|---|---|
| 1 | `scaffold-package` | refactor-architect | — | Create empty `mf4_analyzer/` skeleton: 16 new files (`__init__.py` + `app.py` + `_fonts.py` + `io/{__init__,loader,file_data}.py` + `signal/{__init__,fft,order,channel_math}.py` + `ui/{__init__,canvases,dialogs,widgets,main_window,_palette}.py`), all empty or with one-line docstring + `__all__ = []`. No code moved. |
| 2 | `move-signal` | refactor-architect | [1] | Copy `FFTAnalyzer`/`OrderAnalyzer`/`ChannelMath` bodies verbatim into `signal/{fft,order,channel_math}.py`. **Leave originals in monolith** (deleted in S4) so the AST-extract test still finds them. Add re-exports in `signal/__init__.py`. |
| 3 | `move-io` | refactor-architect | [2] | Copy `DataLoader`/`FileData` bodies verbatim into `io/{loader,file_data}.py`. Leave originals in monolith. Add re-exports in `io/__init__.py`. |
| 4 | `move-ui-and-app` | refactor-architect | [3] | Move 8 UI classes into `ui/{canvases,dialogs,widgets,main_window}.py`. Move `setup_chinese_font` to `_fonts.py`. Move `FILE_PALETTES` to `ui/_palette.py`. Write `app.py`. **Empty the monolith** down to the 4-line launcher. Wire all internal imports to `mf4_analyzer.{io,signal,ui}` paths. |
| 5 | `rewire-tests-and-guard` | signal-processing-expert | [4] | Rewrite `test_fft_amplitude_normalization.py` to use direct import. Add `test_signal_no_gui_import.py` guard. Run full test suite — expect 8 passed. |
| 6 | `tighten-ui-imports` | pyqt-ui-engineer | [5] | Replace `from PyQt5.QtWidgets import *` in 4 ui/*.py files with explicit name lists derived from actual usage. Verify via `python -c "from mf4_analyzer.ui import MainWindow; print('ok')"` smoke; report in `ui_verified`. |

### Why serial and not parallel

S2 and S3 both edit the monolith (adding new packages doesn't conflict, but
both also need to keep the monolith stable). Running them serially is simpler
and avoids merge conflicts on the same source file. The cost is small (~1
extra dispatch round). S5 and S6 must wait for S4 because they need the
empty-monolith state.

### Specialist allocation rationale

- **refactor-architect** owns S1-S4: pure file relocation and import wiring.
  No algorithmic changes, no UI semantics changes.
- **signal-processing-expert** owns S5: tests are the safety net for numeric
  correctness; rewriting the import-strategy of the FFT test belongs to the
  signal-numerics specialist who understands what the test is asserting.
- **pyqt-ui-engineer** owns S6: choosing the explicit `QtWidgets` name list
  requires knowing which Qt classes each UI module actually uses. UI domain.

## Rework detection — expected hits

The squad runbook (Phase 3) detects rework when two different specialists
edit overlapping files. Expected hits this run:

| File | First editor | Second editor | Triggers rework lesson |
|---|---|---|---|
| `tests/test_fft_amplitude_normalization.py` | S2 (refactor-architect, indirectly via monolith) | S5 (signal-processing-expert) | Yes — direct edit by S5 |
| `mf4_analyzer/signal/fft.py` | S2 (refactor-architect created it) | S5 (signal-processing-expert may add docstring or verify-touch) | Conditional |
| `mf4_analyzer/ui/canvases.py` | S4 (refactor-architect) | S6 (pyqt-ui-engineer) | Yes |
| `mf4_analyzer/ui/dialogs.py` | S4 (refactor-architect) | S6 (pyqt-ui-engineer) | Yes |
| `mf4_analyzer/ui/widgets.py` | S4 (refactor-architect) | S6 (pyqt-ui-engineer) | Yes |
| `mf4_analyzer/ui/main_window.py` | S4 (refactor-architect) | S6 (pyqt-ui-engineer) | Yes |

Expected output: **5–6 rework lessons** auto-written to
`docs/lessons-learned/orchestrator/`, dual-written into `LESSONS.md` index
under `## orchestrator`. Most are not "bad rework" — they are a natural
consequence of the move-then-tighten pattern. The lessons document this
pattern so future plans can pre-allocate edits to one specialist when
appropriate.

## State counter

`docs/lessons-learned/.state.yml` will be incremented from `top_level_completions: 2`
to `3` when this run completes with `done` or `partial` status. Distance to
prune threshold (20) remains comfortable; no prune cycle this run.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| AST-extract test breaks mid-run between S2 and S5 | S2-S4 leave the original class definitions in the monolith until S4 fully empties it; S5 rewrites the test in the same dispatch sequence. The window where the test could break is bounded by the runbook's serial execution. |
| Hidden import in MainWindow that wasn't grepped | refactor-architect must `grep -n "^import\|^from"` the full monolith before S4 and migrate every line, not just the obvious ones. |
| `from PyQt5.QtWidgets import *` hides a needed name S6 misses | S6's import smoke (`from mf4_analyzer.ui import MainWindow`) will surface NameError at module load time, not at runtime — so a missed import is caught immediately, not when the user clicks a button. |
| Font setup moved to main()-time breaks an unforeseen widget creation path | No such path exists today (verified: the only widget creator is `MainWindow.__init__` called from `main()`). If the user later adds a script-mode widget, they call `setup_chinese_font()` themselves. |
| Specialist accidentally edits `.py` outside its assigned files | Each specialist's return JSON includes `files_changed`; main Claude (executor) checks these against the brief and surfaces deviations. |

## Acceptance criteria

- `pytest -q tests/` reports 8 passed.
- `python -c "from mf4_analyzer.app import main; print('ok')"` prints `ok`.
- `python -c "from mf4_analyzer.signal.fft import FFTAnalyzer; print('ok')"` prints `ok` and does NOT import PyQt5.
- `MF4 Data Analyzer V1.py` is exactly the 4-line launcher.
- `mf4_analyzer/` matches the layout in "Final package layout" above, including all `__init__.py` files.
- `.state.yml` shows `top_level_completions: 3`.
- All `files_changed` overlaps between specialists have a corresponding
  rework lesson in `docs/lessons-learned/orchestrator/`.

## Post-runbook step

After Phase 4 completes, main Claude dispatches `codex:rescue` to perform an
independent review of the refactored package. Any concrete defects it
surfaces are addressed in a follow-up dispatch (specialist chosen by defect
domain). This is outside the squad runbook proper but recorded here so the
intent is explicit.
