# Progress: TraceLab Porcelain Surface Layering

## 2026-06-19

- Inspected existing surface spec and plan under `docs/superpowers`.
- Confirmed old docs described a snow/flush-panel direction that no longer matched the user-approved porcelain tray mockup.
- Read relevant lessons for visual parity screenshots, rounded child-widget pixel checks, QSettings isolation, shared ViewTabBar styling, and plan/spec literal evidence.
- Rewrote `docs/superpowers/specs/2026-06-19-surface-system-redesign-design.md`.
- Rewrote `docs/superpowers/plans/2026-06-19-surface-system-redesign.md`.
- Created `task_plan.md`, `findings.md`, and `progress.md` for this planning-with-files workflow.
- Dispatched Pauli for Task 0/1. Pauli reported baseline `313 passed` and new tests failing for expected unimplemented shell/QSS reasons.
- Tightened `tests/ui/test_chart_stack.py::test_time_controls_spacer_has_toolbar_background_rule` and the plan snippet so the transparent background assertion is scoped to `QWidget#chartToolbar QWidget#chartTimeControlsSpacer`.
- Applied Galileo review fixes: `test_surface_layering.py` now uses regex block extraction instead of brittle split, guards against a second `QStatusBar`, and spec/plan now explicitly preserve the `self.statusBar` attribute API rather than `MainWindow.statusBar()` callable compatibility.
- Newton completed Task 2 in `mf4_analyzer/ui/main_window/window.py` and `mf4_analyzer/ui/toolbar.py`. Shell status test passed; plan test id was corrected from the stale view-switch name to `test_main_window_mounts_view_tabbar`.
- Nietzsche completed Task 3 in `mf4_analyzer/ui_kit/style.qss`: no `#e8ecf2` or generic `QStatusBar {` hits remain; `Toolbar#surfaceTopBar`, `QStatusBar#surfaceStatusBar`, and `QWidget#centralTray` are present. `tests/ui/test_surface_layering.py` now fails only on the deferred chart toolbar flat contract.
- Ampere completed Task 4: `fileScroll` and `channelCard` are styled-background inner cards; focused left-panel tests passed (`21 passed`).
- Plato completed Task 5 in `style.qss`: chart toolbar is transparent/flat, Inspector body/cards use porcelain tokens, and the focused suite passed (`179 passed`).
- Task 6 exposed the exact rounded-corner backing bug: all five surfaces initially rendered opaque corner pixels. Added a pixel probe to `tests/ui/test_surface_layering.py`; fixed by adding transparent/no-system-background shell attributes to topbar/statusbar/FileNavigator/ChartStack/Inspector and transparent ChartStack internal containers while keeping the existing toolbar layout margins. Rounded-corner suite passed, with corner alpha `[0, 0, 0, 0]` for all five surfaces.
- Final focused UI suite passed: `324 passed in 16.13s` for surface layering, toolbar, file navigator, channel widget, chart stack, inspector, view tabbar, and view-switch integration tests.
- `git diff --check -- mf4_analyzer tests docs/superpowers task_plan.md findings.md progress.md` passed.
- Regenerated final screenshots for all four modes under `docs/surface-redesign-after/`.
- Surface radius alignment pass completed: compact radii `8/7/6/5`, transparent version affordance, shell/child backing fixes, focused UI tests passed, and screenshots regenerated.
