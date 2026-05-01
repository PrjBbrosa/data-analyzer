# Chart Options Dialog Code Review

Verdict: PASS

## Scope Reviewed

- Spec and plan: `docs/superpowers/specs/2026-05-01-chart-options-dialog-design.md`, `docs/superpowers/plans/2026-05-01-chart-options-dialog.md`
- Implementation: `mf4_analyzer/ui/dialogs.py`, `mf4_analyzer/ui/_axis_interaction.py`, `mf4_analyzer/ui/canvases.py`, `mf4_analyzer/ui/chart_stack.py`, `mf4_analyzer/ui/style.qss`
- Tests: `tests/ui/test_dialogs.py`, `tests/ui/test_axis_interaction.py`, `tests/ui/test_chart_stack.py`, `tests/ui/test_canvas_compactness.py`

## Findings

No blocking findings.

## Evidence

- Requirements are captured in the spec: double-click graph face and toolbar button open the same Chinese `图表选项` flow, and multi-axes canvases must target the clicked axes (`docs/superpowers/specs/2026-05-01-chart-options-dialog-design.md:22`, `docs/superpowers/specs/2026-05-01-chart-options-dialog-design.md:35`, `docs/superpowers/specs/2026-05-01-chart-options-dialog-design.md:43`).
- The implementation plan tracks the intended files and completed TDD steps through toolbar entry and regression checks (`docs/superpowers/plans/2026-05-01-chart-options-dialog.md:13`, `docs/superpowers/plans/2026-05-01-chart-options-dialog.md:40`, `docs/superpowers/plans/2026-05-01-chart-options-dialog.md:73`, `docs/superpowers/plans/2026-05-01-chart-options-dialog.md:114`, `docs/superpowers/plans/2026-05-01-chart-options-dialog.md:143`).
- `ChartOptionsDialog` is a Chinese, Inspector-styled dialog with `图表选项`, `基础信息`, `X 轴`, `Y 轴`, `图例`, and `重置 / 取消 / 应用 / 确定` actions (`mf4_analyzer/ui/dialogs.py:283`, `mf4_analyzer/ui/dialogs.py:309`, `mf4_analyzer/ui/dialogs.py:317`, `mf4_analyzer/ui/dialogs.py:326`, `mf4_analyzer/ui/dialogs.py:376`, `mf4_analyzer/ui/dialogs.py:394`).
- Applying the dialog writes title, ranges, labels, scale, grid and optional legend back to the target axes, then schedules a canvas redraw (`mf4_analyzer/ui/dialogs.py:477`, `mf4_analyzer/ui/dialogs.py:496`, `mf4_analyzer/ui/dialogs.py:503`, `mf4_analyzer/ui/dialogs.py:510`).
- Axes targeting now prefers `event.inaxes` and falls back to the existing gutter hit-test, preserving axis-label/tick double-click behavior while enabling graph-face double-click (`mf4_analyzer/ui/_axis_interaction.py:62`, `mf4_analyzer/ui/canvases.py:86`).
- `TimeDomainCanvas`, `SpectrogramCanvas`, and `PlotCanvas` all route double-clicks through the shared chart-options opener (`mf4_analyzer/ui/canvases.py:1065`, `mf4_analyzer/ui/canvases.py:1597`, `mf4_analyzer/ui/canvases.py:2103`).
- Each canvas exposes `open_chart_options_dialog()` with a preferred/default axes list, including FFT-vs-Time main/slice axes and heatmap axes (`mf4_analyzer/ui/canvases.py:486`, `mf4_analyzer/ui/canvases.py:1348`, `mf4_analyzer/ui/canvases.py:1844`).
- `_ChartCard` installs an icon-only `图表选项` toolbar button and delegates the click to the current canvas (`mf4_analyzer/ui/chart_stack.py:231`, `mf4_analyzer/ui/chart_stack.py:381`).
- QSS styles the new dialog surface, tabs, and grouped panels to match the existing light Inspector visual language (`mf4_analyzer/ui/style.qss:663`, `mf4_analyzer/ui/style.qss:682`, `mf4_analyzer/ui/style.qss:706`).
- Tests cover dialog field reads/apply/reset, double-click graph/gutter targeting, FFT-vs-Time slice targeting and remembered axes, toolbar button installation/delegation, and the updated hit-margin source guard (`tests/ui/test_dialogs.py:21`, `tests/ui/test_dialogs.py:44`, `tests/ui/test_axis_interaction.py:50`, `tests/ui/test_axis_interaction.py:88`, `tests/ui/test_axis_interaction.py:283`, `tests/ui/test_chart_stack.py:49`, `tests/ui/test_canvas_compactness.py:77`).

## Tests Run

- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py -q -k chart_options` -> 3 passed
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_axis_interaction.py tests/ui/test_chart_stack.py tests/ui/test_dialogs.py -q -k "chart_options or dblclick"` -> 12 passed, 34 deselected
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_axis_interaction.py tests/ui/test_chart_stack.py tests/ui/test_canvases.py tests/ui/test_inspector.py -q` -> 162 passed, 81 warnings
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_canvas_compactness.py -q -k axis_hit_margin` -> 2 passed, 7 deselected
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q` -> 485 passed, 81 warnings
- `git diff --check` -> no output
- `rg -n "_update_combos|fft_time_signal_changed|_fft_time_cache_key|SpectrogramResult" mf4_analyzer tests/ui/test_inspector.py tests/ui/test_nonuniform_fft_full_flow.py` -> inspected; no chart-options implementation touched the DSP/cache result shape code.

## Residual Risks

- The PyQt dialog styling was validated by widget-level tests and stylesheet inspection, not by a rendered screenshot in a live desktop session.
- Log-scale validation still relies on Matplotlib behavior; the dialog does not yet show a custom warning if a user enters non-positive limits for a log axis.
