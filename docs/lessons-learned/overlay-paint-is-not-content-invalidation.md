---
id: overlay-paint-is-not-content-invalidation
status: active
owners: [codex]
keywords: [page-transition, overlay, paint, invalidation, qwidget]
paths: [mf4_analyzer/ui/chart_stack/page_transition.py, mf4_analyzer/ui/chart_stack/stack.py, mf4_analyzer/ui/pg_canvas/canvas.py]
checks: [rg -n "QEvent.Paint" mf4_analyzer/ui/chart_stack/page_transition.py]
tests:
  - tests/ui/test_page_transition_integration.py::test_section_switch_keeps_outgoing_cover_above_new_stacked_page
  - tests/ui/test_page_transition.py::test_target_capture_keeps_cover_visible_and_preserves_child_composition
  - tests/ui/test_page_transition.py::test_live_fade_waits_for_target_snapshot_and_rejects_duplicate_ack
  - tests/ui/test_page_transition.py::test_queued_capture_cannot_prepare_a_ready_successor
  - tests/ui/test_page_transition.py::test_ordinary_ready_paint_does_not_cancel_live_fade
  - tests/ui/test_page_transition_integration.py::test_live_widget_natural_paint_completes_fade_without_manual_clock
  - tests/ui/test_page_transition_integration.py::test_ready_content_replacement_cancels_live_fade
  - tests/ui/test_page_transition.py::test_identical_dark_live_endpoints_never_reveal_host_background
  - tests/ui/test_page_transition.py::test_two_endpoint_composite_is_opaque_and_blends_only_endpoints
  - tests/ui/test_page_transition_integration.py::test_real_heatmap_repeat_fade_keeps_dark_plot_pixels
---

# Overlay Paint Is Not Content Invalidation

Trigger: A translucent Qt overlay composites over a live chart, or a page-transition / cover widget watches the target's `QEvent.Paint`.

Past failure: Time-domain View fades armed correctly, then cancelled within one expose as `target-surface-invalidated`. QObject paint fences and manual animation-clock jumps never saw the production GraphicsView paint path. The subsequent freeze optimization caused repeat heatmap white flashes: a source-only overlay faded over skipped target widgets. A second SourceOver error gave two fractional-alpha endpoints only 75% opacity at the midpoint. Windows foreground video later exposed a target/old-source reversal before the fade: target capture used hide/grab/show, and the animation clock started before the queued target capture. A later fix still missed QStackedLayout raising the incoming page above the cover: the regression pumped events before checking pixels, letting deferred pin reflow hide the exposed intermediate frame.

Rule: Treat ordinary expose/paint and overlay compositing as presentation. Cancel only on owner-signalled content replacement, identity/lifecycle, geometry, or input. Do not infer data change from `QEvent.Paint`. Freeze duplicate exposes only after caching the admitted target outside its paint callback. Disabled children do not preserve backing pixels below a translucent sibling. Composite an opaque target first, then fade the source over it; thaw on finish/cancel. Never hide the visible cover to capture a target: render the host background and visible direct children in stacking order into the target pixmap, excluding only the cover. Start the fade clock after the snapshot is complete, bind queued preparation to its request token, and reject duplicate acknowledgements. Switch the stacked page and restore the cover stacking order before re-enabling host updates; preserve an already-disabled update state. Check outgoing pixels immediately after set_mode returns, before deferred reflow. Never treat low paint counts as proof of correct visible pixels.

Verification: Run the tests above with `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`. Confirm `_input_invalidation_events` does not include `QEvent.Paint`.

Pixel evidence: identical black endpoints must remain black at every fade step; real heatmap repeats must retain dark plot pixels. Compare the captured target against the ordinary widget pixels, including translucent children and DPR; assert the cover receives no Hide event during capture. Verify native QWidget composition separately from offscreen and desktop screen recordings.
