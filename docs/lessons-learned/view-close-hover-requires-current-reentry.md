---
id: view-close-hover-requires-current-reentry
status: active
owners: [codex]
keywords: [viewtabbar, close, hover, currentchanged, destructive-target, pointer-reentry]
paths:
  - mf4_analyzer/ui/view_tabbar.py
  - tests/ui/test_view_tabbar.py
checks:
  - rg -n "_pointer_slot_view_id|_close_slot_actionable|current_index_changed" mf4_analyzer/ui/view_tabbar.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_tabbar.py -k "inactive_swatch or switched_swatch" -q
---

# View Close Hover Requires Current Re-entry

Trigger: Changing a tab color-swatch hover action, current-View switching, or
another destructive control that can appear under a pointer after selection.

Past failure: Every View swatch became an immediately actionable close target,
so sweeping to an inactive View and clicking its leading slot deleted instead
of switching; green geometry and event-isolation tests encoded the unsafe path.

Rule: A destructive tab hover target is actionable only when the pointer enters
while that View is already current. Switching through the same slot locks the
press/release to normal selection, and the close target stays suppressed until
the pointer leaves and re-enters.

Verification: Run the listed inactive-switch and re-entry tests, then the full
`tests/ui/test_view_tabbar.py` owner file.
