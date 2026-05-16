---
id: codex-acquisition-threshold-defaults-use-current-values
status: active
owners: [codex]
keywords: [acquisition, thresholds, settings, SessionConfig, default-args]
paths:
  - mf4_analyzer/acquisition_capture/
  - mf4_analyzer/acquisition_ui/
  - tests/test_acquisition_settings_overrides.py
checks:
  - rg -n "thresholds\\.[A-Z0-9_]+|from .*thresholds import" mf4_analyzer/acquisition_capture mf4_analyzer/acquisition_ui
tests:
  - PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_settings_overrides.py -v
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_right_panel.py -v
---

# Acquisition Threshold Defaults Use Current Values

Trigger: Touching Acquisition Cockpit editable thresholds, settings auto-load, `SessionConfig` defaults, health helper defaults, or preflight UI defaults.

Past failure: User settings were loaded into `thresholds`, but import-time
defaults kept stale values. `SessionConfig` copied bitrate, health poll
interval, and connection timeout at class definition time; `level_hw()` and the
right-panel CAN preflight path also froze editable thresholds in default
arguments.

Rule: Editable acquisition thresholds must be read at construction or call time,
not frozen in dataclass field values, function default arguments, or by-value
imports. Use `field(default_factory=...)`, `None` sentinels, or module imports
that dereference `thresholds.KEY` when the value is needed.

Verification: Add a regression that changes an editable threshold after import
and proves the default-consuming path uses the new value. Run the settings
override tests and the right-panel UI tests.
