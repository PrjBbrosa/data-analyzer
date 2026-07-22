---
id: codex-channel-config-host-geometry-render
status: active
owners: [codex]
keywords: [channel-config, qcombobox, qmessagebox, popup, offscreen, geometry]
paths:
  - mf4_analyzer/ui/widgets/channel_config_bar.py
  - mf4_analyzer/ui/main_window/_project_io_mixin.py
  - mf4_analyzer/ui_kit/style.qss
checks:
  - render the config bar in a production-width navigator rail, not standalone
  - render every new batch-DBC message box and inspect button text bounds
  - assert popup scrollbar and visible action rows explicitly
tests:
  - tests/ui/test_channel_config_bar.py
  - tests/ui/test_blf_batch_import.py
  - tests/ui/test_combo_popup_shell.py
---

# Channel Config UI Needs Host-Width Render Proof

Trigger: Changing the channel configuration rail, its combo popup, or the
batch-BLF DBC confirmation dialog.

Past failure: A standalone offscreen bar appeared acceptable, but the real
navigator-width render stretched the side buttons and clipped long batch-DBC
button labels. The configuration popup also hid its management action behind a
one-pixel vertical scrollbar.

Rule: Render the changed control inside a representative navigator-width host
with the shared stylesheet. Use fixed side-action widths, give the selector
the layout stretch, route combo width through `popupMinWidth`, and assert that
the intended visible rows fit without a scrollbar. For message boxes, use
short action labels and compare every label's text width with its button
contents rectangle.

Verification: Run the listed focused tests and inspect the offscreen dialog,
rail, and popup screenshots with four saved configurations.
