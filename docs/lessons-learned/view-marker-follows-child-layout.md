---
id: view-marker-follows-child-layout
status: active
owners: [codex]
keywords: [viewtabbar, marker, resize, geometry, cocoa]
paths: [mf4_analyzer/ui/view_tabbar.py]
checks: []
tests:
  - tests/ui/test_view_tabbar.py::test_adding_views_keeps_marker_on_final_tab_geometry
  - tests/ui/test_view_tabbar.py::test_marker_follows_fast_a_b_c_from_current_displayed_value
  - tests/ui/test_view_tabbar.py::test_resize_snaps_in_flight_marker_to_confirmed_tab
---

# View Marker Must Follow The Child Strip Layout

Trigger: A cached selection marker uses QTabBar tabRect while labels, tab count, or visible widths change.

Past failure: Adding View updated the marker before the QHBoxLayout resized the child QTabBar. The outer rail width stayed fixed, so its resize handler never corrected the cached coordinates. Cocoa left the marker across two tabs while offscreen passed the same action.

Rule: Reconcile cached geometry after the actual child strip resize, using confirmed manager identity. Preserve animations for ordinary same-layout selection and snap when geometry changes. Do not infer child layout completion from the outer widget dimensions.

Verification: Run the tests above on offscreen and Cocoa; render the real MainWindow Time/FFT/FFT-Time/Order rails after repeated plus-button actions and compare marker geometry to the selected tab. A passing offscreen run alone is insufficient for this failure.
