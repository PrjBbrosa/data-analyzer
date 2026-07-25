---
id: codex-channel-config-manager-taskbar-height
status: active
owners: [codex]
keywords: [pyqt, dialog, channel-config, geometry, height, taskbar, footer]
paths:
  - mf4_analyzer/ui/widgets/channel_config_manager.py
  - tests/ui/test_channel_config_manager.py
checks:
  - QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_channel_config_manager.py -q
tests:
  - tests/ui/test_channel_config_manager.py
---

# Channel Configuration Manager Must Open Above the Taskbar

Trigger: Changing the default geometry or fixed-height regions of the Channel
Configuration Manager dialog.

Past failure: The manager opened at 790px high, which extended behind the
Windows taskbar on a 768px display and hid its bottom save controls.

Rule: Keep the default size at 1180x680 and the minimum size at 940x680.
When changing this dialog's geometry, retain scrollable lists and verify that
the save control remains visible at the minimum size.

Verification: Run the focused geometry regression and the complete
`tests/ui/test_channel_config_manager.py` module with Qt offscreen.
