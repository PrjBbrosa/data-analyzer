---
id: project-open-recomputes-every-analysis-view
status: active
owners: [codex]
keywords: [project-restore, analysis-view, view-id, fft, pane-sources]
paths:
  - mf4_analyzer/ui/main_window/_project_io_mixin.py
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
  - mf4_analyzer/ui/main_window/_fft_mixin.py
checks:
  - rg -n "_recompute_restored_analysis_view|_dispatch_pending_analysis_restore" mf4_analyzer/ui/main_window
tests:
  - tests/ui/test_project_session.py
  - tests/ui/test_frf_main_window.py
---

# Project Open Recomputes Every Analysis View

Trigger: Changing project save/open, analysis View restore, FFT pane.sources capture, or any path that used to call `do_fft` / `do_order_time` / `do_fft_time` / `do_frf` after loading a `.tlproj`.

Past failure: `.tlproj` does not store numeric results, which is correct, but open only queued the active analysis tab. Inactive Views stayed empty until the user clicked them. FFT computed from the Inspector 单信号 dropdown never wrote `pane.sources`, so reopen did not even queue a recompute and showed an empty chart with 「未选通道，使用单信号」.

Rule: After `open_project` finishes, dispatch every source-bearing `(section, view_id)` through `_recompute_restored_*_view`. Build from persisted pane state and overlay params; do not `apply_params` onto the shared Inspector or call `do_*` (those capture live controls). FFT capture: navigator ticks if present, otherwise the Inspector combo when its `(fid, ch)` is a real loaded file. Plot only the currently visible View; others fill the cache so a later tab switch renders without 计算. UltraView stays a display of already-drawn canvases.

Verification: `tests/ui/test_project_session.py` asserts both FFT Views dispatch on open, an inactive FFT View shows curves after tab switch without 计算, and Inspector-only FFT persists `pane.sources`. FRF restore tests keep `view_id` identity across reorder.
