---
id: channel-menu-actions-follow-target-cardinality
status: active
owners: [codex]
keywords: [channel-tree, context-menu, selection, axis]
paths: [mf4_analyzer/ui/widgets/channel_tree.py, tests/ui/test_channel_name_copy.py]
checks: [git diff --check]
tests: [tests/ui/test_channel_name_copy.py, tests/ui/test_channel_axis_groups.py]
---

# Channel Menu Actions Follow Target Cardinality

Trigger: Adding or changing channel-tree context-menu actions.

Past failure: A multi-channel selection still offered Set Left Axis, but the action only changed the right-clicked channel, misleading users about its target.

Rule: Build menu availability from the effective target selection. Single-channel actions require one target; multi-channel menus contain axis-group actions only. Right-clicking outside the selection retains the existing clicked-row fallback.

Verification: Test single and multiple targets in all tree projection roles, including grouped channels and clicks outside the selection. Check a real Cocoa menu and preserve full channel identity.
