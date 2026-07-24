---
id: codex-approved-html-operation-parity
status: active
owners: [codex]
keywords: [html-prototype, visual-parity, operation-model, pyqt, offscreen]
paths:
  - docs/analyzer/ui-prototypes/**
  - mf4_analyzer/ui/widgets/**
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/**
  - tools/render_*.py
checks:
  - Compare the approved HTML DOM actions with the PyQt controls before implementation.
  - Render every changed primary state with the shared stylesheet and inspect it.
tests:
  - tests/ui/test_channel_config_manager.py
---

# Approved HTML Requires Operation Parity

Trigger: A user supplies or approves an HTML prototype as the implementation
target for a PyQt surface.

Past failure: The configuration manager kept its data features but was rebuilt
as a generic toolbar-and-table workflow. It omitted the prototype's sidebar
cards, detail action placement, batch footer, selected-row treatment, and
import-review hierarchy. The first screenshot made the mismatch obvious.

Rule: Before changing widgets, map every visible HTML action and state to a
specific PyQt widget/state transition. Preserve the prototype's information
architecture and operations; only adapt for real Qt constraints such as font
metrics or native window chrome. Do not call the work complete until normal,
selected/dirty, batch, and modal/import states have rendered screenshots.

Verification: Add interaction tests for each mapped state, run the focused UI
suite, run the screen-size render probe using the shared stylesheet, and
inspect the produced images for stacked widgets, missing icon labels, clipped
controls, and selected-row fill.
