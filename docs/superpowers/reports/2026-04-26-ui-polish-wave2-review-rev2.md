# Wave-2 Rev 2 Review — 2026-04-26

## Rev 1 Finding Disposition
Rev 1 found an executable bare `fig.tight_layout()` in `mf4_analyzer/batch.py`; commit `7302ddba` fixed that call. Evidence: `grep -n "tight_layout()" mf4_analyzer/batch.py` returned no output, and `grep -n "CHART_TIGHT_LAYOUT_KW" mf4_analyzer/batch.py` returned `22:from ._chart_kw import CHART_TIGHT_LAYOUT_KW` and `351:            fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)`.

## Hoisted-Module Verification
`nl -ba mf4_analyzer/_chart_kw.py` shows `CHART_TIGHT_LAYOUT_KW = dict(pad=0.4, h_pad=0.6, w_pad=0.4)` at line 26, `SPECTROGRAM_SUBPLOT_ADJUST = dict(left=0.07, right=0.93, top=0.97, bottom=0.09)` across lines 27-29, and `AXIS_HIT_MARGIN_PX = 45` at line 30; `grep -n "from.*ui" mf4_analyzer/_chart_kw.py` returned no output, and `grep -nE "^[[:space:]]*(from|import)[[:space:]]" mf4_analyzer/_chart_kw.py` returned no output. `nl -ba mf4_analyzer/ui/canvases.py | sed -n '1,80p'` shows the re-export import from `.._chart_kw` for all three constants at lines 48-52. `grep -rn "from .canvases import CHART_TIGHT_LAYOUT_KW" mf4_analyzer/` returned `mf4_analyzer/ui/main_window.py:26:from .canvases import CHART_TIGHT_LAYOUT_KW`; `grep -rn "from mf4_analyzer.ui.canvases import" tests/` returned multiple test imports, including `tests/ui/test_canvas_compactness.py:35` and `:55`, and `nl -ba tests/ui/test_canvas_compactness.py | sed -n '30,65p'` confirms those import `CHART_TIGHT_LAYOUT_KW`.

## Regression Spot-Check
Dependency direction is clean: `grep -n "from.*ui" mf4_analyzer/batch.py` returned no output, and `grep -n "import" mf4_analyzer/_chart_kw.py` only returned docstring line `7:\`ui/\` would force \`batch.py\` to import "up" into \`ui\`, violating the`. Constant values match the Wave-2 values moved by `git show --unified=30 7302ddba`: the diff removes the same three definitions from `mf4_analyzer/ui/canvases.py` and adds them to `mf4_analyzer/_chart_kw.py`. Exact `grep -rn "tight_layout()" mf4_analyzer/` returned `mf4_analyzer/ui/canvases.py:764` plus a binary `__pycache__` match; source-only `grep -rn "tight_layout()" mf4_analyzer/ --include="*.py"` returned only `mf4_analyzer/ui/canvases.py:764`, a docstring line. RPM scan is not clean under the requested broad pattern: `grep -rni "rpm" mf4_analyzer/ --include="*.py" | wc -l` returned `164`, non-comment count returned `159`, distributed as `44 batch.py`, `43 signal/order.py`, `44 ui/main_window.py`, `13 ui/inspector_sections.py`, `13 ui/drawers/batch_sheet.py`, and `2 ui/canvases.py`; first-page evidence includes non-comment uses such as `mf4_analyzer/ui/main_window.py:100`, `:1013`, and `:1477`.

## Independent Observations
`git show --name-status --oneline 7302ddba` lists only `A mf4_analyzer/_chart_kw.py`, `M mf4_analyzer/batch.py`, and `M mf4_analyzer/ui/canvases.py`; no unexpected files were changed. The broad RPM grep caveat appears pre-existing to this rev-2 fix because commit `7302ddba` did not touch the RPM-heavy files outside `batch.py`, but it still does not satisfy the requested "0 non-comment hits or only legacy variable names" spot-check literally.

## Verdict
`approved with minor revisions`
Rev 1's chart-layout finding and dependency direction are fixed; reconcile or narrow the Wave-1 RPM-removal grep criterion before treating the regression spot-check as fully clean.
