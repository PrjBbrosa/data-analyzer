---
id: page-transition-empty-target-completion
status: active
owners: [codex]
keywords: [page-transition, empty, watchdog, time-domain, camera]
paths: [mf4_analyzer/ui/chart_stack/page_transition.py, mf4_analyzer/ui/main_window/window.py]
checks: []
tests:
  - tests/ui/test_page_transition.py::test_armed_target_without_paint_request_releases_cover
  - tests/ui/test_section_page_transition.py::test_return_to_empty_time_finishes_and_channel_selection_draws
  - tests/ui/test_section_page_transition.py::test_empty_time_entry_redirect_does_not_cover_new_section
  - tests/ui/test_section_page_transition.py::test_e2_time_to_fft_and_back_user_navigation
---

# Empty Target Must Complete Its Page Transition

Trigger: A chart transition holds the outgoing image while the destination may skip rendering because its selection is empty.

Past failure: Time entry scheduled target acknowledgement only for checked channels. Returning from a computed heatmap to empty Time kept the heatmap cover forever; later checkbox changes drew real curves underneath it. The timeout was armed only after requesting target paint, so it never ran. Unconditionally redrawing the empty target then erased retained camera ranges.

Rule: Separate render eligibility from presentation completion. An empty or retained target must still acknowledge its natural paint or cancel the cover. Bound the cover lifetime when the target is armed, before render callbacks can skip the paint request. Keep timeout cleanup token-scoped and preserve existing camera/retained-view semantics.

Verification: Run the focused tests above. Assert cover visibility and retained image bytes, not only active/pending flags; exercise empty return, subsequent channel selection, rapid redirect, and retained zoom. Verify the real widget on Cocoa separately from offscreen; this lifecycle fix does not prove continuous-frame flicker acceptance.
