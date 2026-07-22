---
id: codex-channel-config-picker-structured-rows
status: active
owners: [codex]
keywords: [channel-config, qcombobox, item-delegate, popup, configuration-manager, rendered-screenshot]
paths:
  - mf4_analyzer/ui/widgets/channel_config_bar.py
  - mf4_analyzer/ui/widgets/channel_config_manager.py
  - mf4_analyzer/ui_kit/combo_popup_shell.py
  - mf4_analyzer/ui_kit/style.qss
checks:
  - Render the config picker popup and the management dialog with the shared stylesheet.
  - Confirm names and channel counts remain in separate popup item roles.
tests:
  - tests/ui/test_channel_config_bar.py
  - tests/ui/test_channel_config_manager.py
  - tests/ui/test_view_channel_scope.py
---

# Channel Config Picker Uses Structured Rows

Trigger: Changing the TimeDomain saved-channel configuration picker or its
management dialog.

Past failure: The picker rendered each saved configuration as a compact plain
text row such as `name · count`, which made labels feel crowded and counts
visually misalign. Management then required a sequence of unrelated native
prompts, so users could not inspect or batch-manage saved configurations.

Rule: Keep picker item data structured: the delegate owns the fixed row
geometry and draws the name on the left and channel count on the right. Keep
the popup shell in the shared combo-popup helper. Manage configurations in the
single list/detail dialog; selection may batch-delete, while rename and copy
must remain single-item actions.

Verification: Run the focused picker, manager, and view-scope tests, then
render both the popup and dialog with the live stylesheet and inspect their
row height, column alignment, and action states.
