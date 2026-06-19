# Findings: TraceLab Porcelain Surface Layering

## Relevant Current Code

- `MainWindow._init_ui` owns `QWidget#centralTray`, root margins `5px`, and root spacing currently `8px`.
- `MainWindow._init_ui` creates `self.statusBar = QStatusBar()` and registers it with `setStatusBar`.
- `Toolbar` is a `QWidget` subclass and needs explicit styled-background ownership for rounded topbar QSS.
- `FileNavigator`, `ChartStack`, and `Inspector` already set `WA_StyledBackground`.
- `MultiFileChannelWidget` currently has no objectName and no styled-background ownership.
- `QWidget#chartToolbar` is currently styled with white background; user selected annotation says it should not be a rounded/bordered card.

## Relevant Tests / Risks

- Many tests and app paths call `self.statusBar.showMessage`, `currentMessage`, `clearMessage`, `insertPermanentWidget`, and `addPermanentWidget`.
- `tests/ui/test_view_switch_integration.py` expects the hint bar parent to be `w.statusBar`.
- `tests/ui/test_chart_stack.py::test_chart_choice_checked_qss_uses_visible_blue_selection_tokens` requires checked chart choice buttons to keep blue selection tokens.
- `tests/ui/test_chart_stack.py::test_time_controls_spacer_has_toolbar_background_rule` currently expects a white spacer and must change with the flat toolbar contract.
- Lessons require rendered screenshots and pixel-level rounded-corner checks for this class of UI work.

## Visual Decisions

- Default theme: porcelain tray (`#f2f4f7`).
- Topbar: white rounded surface, 50px.
- Bottombar: white rounded surface, 40px, still a `QStatusBar`.
- Vertical spacing: 5px.
- Main panel radius: 10px.
- Chart toolbar: flat transparent tool row; no border/radius/card background.
