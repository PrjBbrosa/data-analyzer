---
id: pyqt-ui/2026-08-14-ultraview-stale-means-digest-sync-recaptures
status: active
owners: [codex]
keywords: [ultraview, stale, 源已变化, digest, sync, recapture, PreviewStore]
paths:
  - mf4_analyzer/ui/ultraview_state.py
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - tests/ui/test_ultraview_capture.py
  - tests/ui/test_ultraview_page.py
checks:
  - rg -n "user-sync|sync_preview|STATUS_STALE" mf4_analyzer/ui/main_window/ultraview_coordinator.py mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - rg -n "do_fft|do_fft_time|do_frf|do_order_time" mf4_analyzer/ui/main_window/ultraview_coordinator.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_page.py::test_stale_card_sync_button_emits_page_intent tests/ui/test_ultraview_capture.py::test_user_sync_recaptures_stale_preview_without_recompute tests/ui/test_ultraview_capture.py::test_user_sync_hidden_canvas_toasts_without_navigate -q
---

# UltraView Stale Means Digest Mismatch; Sync Recaptures

Trigger: Changing UltraView card status, `derive_preview_status`, presentation digest, idle recapture, or adding a Board sync/refresh control.

Past failure: 「源已变化」looks like a file-on-disk warning. It is a presentation-digest mismatch (pan/zoom, dual cursor, pill text, markup, analysis generation). Users saw the amber badge with no obvious data change and had no way to refresh except opening the source View and waiting for idle grab. Forcing `STATUS_FRESH` without a grab hid real staleness behind old pixels.

Rule: Stale keeps the last valid preview. Sync (`user-sync`) recaptures the live visible canvas and never recomputes DSP. Hidden source canvases must navigate-then-grab or toast; do not mark fresh when `current_digest` is missing. Orphaned cards use rebind, not sync.

Verification: `test_stale_card_sync_button_emits_page_intent`, `test_user_sync_recaptures_stale_preview_without_recompute`, `test_user_sync_hidden_canvas_toasts_without_navigate`.
