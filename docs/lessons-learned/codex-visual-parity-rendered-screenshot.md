---
id: codex-visual-parity-rendered-screenshot
status: active
owners: [codex]
keywords: [visual-parity, screenshot, qss, pyqt, geometry, acquisition-ui]
paths:
  - mf4_analyzer/acquisition_ui/**
  - mf4_analyzer/ui_kit/style.qss
  - docs/analyzer/ui-prototypes/**
checks:
  - render a representative window screenshot after QSS/widget changes
  - inspect fixed heights/widths for toolbar chips, selectors, and compact controls
tests:
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui -v
---

# Visual Parity Requires Rendered Screenshot

Trigger: Touching PyQt visual parity, QSS, toolbar controls, compact chips, or a UI implementation that is supposed to match an HTML prototype or screenshot.

Past failure: Structural tests asserted object names and state properties, but
the rendered Acquisition Cockpit still had oversized toolbar selectors, a gray
spacer block, and filter chips collapsed into checkbox squares/ellipsis. The
tests were green while the UI was visibly wrong.

Rule: After visual-parity changes, render or inspect an actual screenshot and
add at least one geometry/size assertion for the controls that define the
reference layout. Do not call visual work done from object-name/QSS-token tests
alone.

Verification: Run the targeted UI tests plus a rendered screenshot pass for the
changed screen. When compact controls are involved, assert fixed heights/widths
or visible chip text so Qt default sizing cannot silently drift.
