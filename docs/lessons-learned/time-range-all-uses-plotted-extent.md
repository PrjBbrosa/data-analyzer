---
id: time-range-all-uses-plotted-extent
status: active
owners: [codex]
keywords: [时间范围, 全部, plotted, extent, channel-tree, analysis-canvas]
paths:
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/inspector_sections/persistent_top.py
  - mf4_analyzer/ui/analysis_section_page.py
checks: []
tests:
  - tests/ui/test_inspector.py::test_max_range_button_uses_plotted_not_longest_loaded
  - tests/ui/test_inspector.py::test_max_range_button_lives_on_chk_range_row
  - tests/ui/test_analysis_scope_and_xframe.py::test_max_range_in_analysis_mode_uses_attached_short_file
---

# 「全部」按模式分流：时域用已绘时长，分析页回 full

Trigger: Changing Inspector「全部」/ time-range max, `_plotted_time_extent`,
`_time_data_extent`, analysis-mode framing, or Home/reset-to-full-extent.

Past failure: 「全部」walked every loaded file in the channel tree and framed
to the longest time base, even when only shorter channels were plotted.
A later analysis-mode path still treated「全部」as view-all / plotted
extent, so an enabled or drafted compute range survived.

Rule: Split by mode. Time-domain「全部」and Home still resolve max extent
via `_plotted_time_extent` (analysis page focused canvas, not
`chart_stack.focused_canvas()`), then canvas data union → checked plotted
channels → attached sources → `_time_data_extent`. Do not enable the
filter. Analysis「全部」cancels the checkbox, clears the controller draft,
and projects the current source full span (`convert_to_full`). Do not
reuse plotted-extent Home as analysis compute intent.

Verification: Run
`tests/ui/test_inspector.py -k max_range`,
`tests/ui/test_main_window_smoke.py -k max_range`, and
`tests/ui/test_analysis_scope_and_xframe.py`.
