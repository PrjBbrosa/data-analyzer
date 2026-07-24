---
id: codex-channel-tree-refresh-preserves-view-state
status: active
owners: [codex]
keywords: [pyqt, channel-editor, file-navigator, viewstate, attachment, refresh, hdf]
paths:
  - mf4_analyzer/ui/widgets/__init__.py
  - mf4_analyzer/ui/file_navigator.py
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/main_window/_channel_scope_mixin.py
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_channel_widget.py tests/ui/test_channel_axis_groups.py tests/ui/test_file_navigator.py tests/ui/test_view_channel_scope.py tests/ui/test_project_session.py -q
tests:
  - tests/ui/test_channel_widget.py::test_refresh_file_preserves_view_attachment_and_tree_interactions
  - tests/ui/test_head_hdf_rail.py::test_refresh_hdf_raster_keeps_other_rasters_and_view_state
  - tests/ui/test_main_window_smoke.py::test_channel_editor_apply_keeps_attached_tree_display_state
  - tests/ui/test_view_channel_scope.py::test_channel_editor_removal_cleans_deleted_channel_from_every_view
---

# Channel Tree Refresh Must Not Detach A View File

Trigger: Refreshing channel rows after a channel-editor add/remove operation,
including grouped HDF rasters.

Past failure: The editor rebuilt an existing source through
`navigator.remove_file()` then `add_file()`. Removal correctly cleared the
current View attachment, so the channel tree showed its empty state after a
derivative channel was confirmed. It also discarded display color, hidden,
axis-group, selection, and expansion state.

Rule: Use the dedicated in-place channel-tree refresh path for an existing
fid; reserve `remove_file()` for actual source closure/detachment. Preserve
the attached-file list and surviving tree interactions. When a channel is
deleted, prune that channel from every TimeDomain View's checked/hidden/color,
overlay-primary, and custom-X state before replotting.

Verification: Run the focused widget/View/project suites and direct channel
editor/HDF refresh regressions. Keep the existing TimeDomain X-limit regression
green.
