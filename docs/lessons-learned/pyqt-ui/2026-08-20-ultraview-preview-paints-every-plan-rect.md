---
id: pyqt-ui/2026-08-20-ultraview-preview-paints-every-plan-rect
status: active
owners: [codex]
keywords: [ultraview, ghost, overlay, drag preview, coalescer, collision, displaced, reentrancy]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - mf4_analyzer/ui/chart_stack/ultraview/gesture.py
checks:
  - rg -n "ref in mover_refs else None|setUpdatesEnabled\\(False\\)|_gesture_presenting.*, False\\):\\s*$" mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - rg -n "PREVIEW_DISPLACED_WARNING|_ingest_pointer_sample|_latest_pointer_sample" mf4_analyzer/ui/chart_stack/ultraview/widgets.py
tests:
  - tests/ui/test_ultraview_gesture_preview.py
  - tests/ui/test_ultraview_gesture_coalesce.py
---

# UltraView Preview Paints Every Plan Rect

Trigger: Changing UltraView free-grid drag/resize preview, `GhostOverlay.set_move_previews`, pointer coalescing, or collision/safety paint.

Past failure: `a4035287` sent `image=None` for displaced neighbours, so avoidance showed an empty outline. `0cbe6ffb` left `_queue_pointer_sample` unused and presented every mouse move. Per-frame `setUpdatesEnabled(False/True)` plus `_image.clear()` raced the overlay. A single `_legal` flag painted displaced cards blue. Re-entrant extent/edge-pan refresh returned while presenting and dropped the latest sample. Tests asserted overlay fields, not pixels.

Rule: Keep `plan_layout` and the commit/undo path. Overlay paints a fast preview image for every `plan.preview_rects()` item. Roles are per item (`mover_valid`, `displaced_warning`, `collision_reject`, `safety_wall`); legal avoidance keeps the mover blue and the displaced neighbour red. Origin wash lives on the overlay — do not freeze or clear live cards during drag. Pointer events overwrite `latest_sample`; the first threshold crossing paints immediately; later events coalesce on the 0 ms timer; release flushes. A present already in flight stores the newest sample and schedules the next frame instead of dropping it. The translucent overlay must full-`update()` and stay raised; a clipped `update(QRect)` or skipped paint on an identical candidate blanks the Cocoa backing store so the preview flashes once and vanishes. Never `CompositionMode_Source`-clear the whole sibling overlay or set `WA_NoSystemBackground` on it: that punches the parent canvas through and whites out the cards on click. Pixel tests must cover mover and displaced images, red collision paint, origin rebase, overlay restore after hide, and one undo.

Verification: `tests/ui/test_ultraview_gesture_preview.py` and `tests/ui/test_ultraview_gesture_coalesce.py`.
