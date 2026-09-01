---
id: wwt-initial-axis-groups-stay-ordinary-editable
status: active
owners: [codex]
keywords: [wwt, initial-view, axis-group, channel-tree, ordinary-canvas]
paths:
  - mf4_analyzer/ui/widgets/channel_tree.py
  - mf4_analyzer/ui/view_bridge.py
  - mf4_analyzer/ui/wwt_view_import.py
checks:
  - git diff --check
tests:
  - tests/ui/test_channel_axis_groups.py::TestAxisGroupModel::test_restored_group_uses_normal_badge_and_split_action
---

# WWT Initial Axis Groups Stay Ordinary And Editable

Trigger: Importing or restoring WWT-derived initial axis groups in the shared
TimeDomain channel tree.

Past failure: The initial group was stored in a separate restored projection.
Rendering consumed it, but the normal badge lookup and split menu only read the
interactive group model, leaving an invisible persistent group the user could
not change through ordinary Canvas controls.

Rule: WWT may seed an initial group, but badge lookup, merge, split, removal,
and effective-group precedence must all honor normal user edits. The imported
seed must never override or bypass an explicit ordinary interaction.

Verification: Run the focused channel-axis-group test above and the WWT initial
view contract tests offscreen.
