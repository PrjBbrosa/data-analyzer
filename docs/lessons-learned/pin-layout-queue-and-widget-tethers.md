---
id: pin-layout-queue-and-widget-tethers
status: active
owners: [codex]
keywords: [pinned-cursor, layout-queue, collection-snapshot, tether, QWidget, z-order]
paths:
  - mf4_analyzer/ui/chart_stack/pinning/presentation.py
  - mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py
  - mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py
checks: [git diff --check]
tests:
  - tests/ui/test_pinned_cursor_geometry.py
  - tests/ui/test_pinned_cursor_interaction.py
---

# Pin layout queues current collection; tethers stay outside QWidget panels

Trigger: Changing pinned-panel layout timers, user-placed anchors, or
panel-to-line tether routing.

Past failure: A coalesced reflow stored the collection object in the pending
queue, so a later 0 ms layout reapplied the pre-drag anchor after the user had
already committed a new position. Separately, tether polylines lived in the
chart scene and started on the panel interior; raising item z-order could not
draw them above the sibling CursorPill QWidget, so the association line
disappeared under the card.

Rule: Pending layout holds owner identity only and reads the live collection at
apply time. Skip auto-anchor while a pill is dragging. Route tethers from ports
outside the panel rect onto a visible point on the real cursor line; never treat
scene z-order as a way to paint over a QWidget.

Verification: Run `tests/ui/test_pinned_cursor_geometry.py` and
`tests/ui/test_pinned_cursor_interaction.py` with the production style, then
`git diff --check`.
