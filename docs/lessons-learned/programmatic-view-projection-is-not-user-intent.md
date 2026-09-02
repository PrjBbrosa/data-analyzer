---
id: programmatic-view-projection-is-not-user-intent
status: active
owners: [codex]
keywords: [view-restore, signal, reentrancy, custom-x, axis-group]
paths:
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/view_bridge.py
  - mf4_analyzer/ui/widgets/channel_tree.py
checks:
  - git diff --check
tests:
  - tests/ui/test_view_switch_reentrancy.py::test_channel_change_signal_is_ignored_while_applying_a_view
  - tests/ui/test_wwt_initial_view_contract.py::test_mixed_initial_axis_groups_do_not_overwrite_wwt_custom_x_on_open
---

# Programmatic View Projection Is Not User Intent

Trigger: Changing View restore/application, a widget model projected from
ViewState, or a signal connected to a user-edit capture/replot handler.

Past failure: Restoring a WWT initial axis-group projection emitted
``axis_groups_changed`` before the Inspector Custom-X control was restored.
``_ch_changed`` treated that programmatic signal as a user edit, captured the
half-applied time-axis controls back into ViewState, and changed otherwise
valid angle-X curves into Time-Y plots.

Rule: Apply a View as one transaction. Programmatic projection setters must
refresh their presentation without publishing user intent, and capture/replot
handlers must reject signals while the View render/application guard is
active. Interactive merge/split operations still emit their normal signal.

Verification: Exercise a synthetic WWT that combines ordinary channel-backed
Custom-X curves with record-only curves in imported axis groups. Assert that
open keeps ``PER_SOURCE_NAME`` Custom-X and exact X arrays, while restore-time
signals cause no capture or replot and later user split still emits once.
