---
id: time-range-all-uses-plotted-extent
status: active
owners: [codex]
keywords: [时间范围, 全部, plotted, extent, channel-tree]
paths:
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/inspector_sections/persistent_top.py
checks: []
tests:
  - tests/ui/test_inspector.py::test_max_range_button_uses_plotted_not_longest_loaded
  - tests/ui/test_inspector.py::test_max_range_button_lives_on_chk_range_row
---

# 「全部」用图面已绘制通道时长，不用通道树最长加载文件

Trigger: Changing Inspector「全部」/ time-range max, `_time_data_extent`, or
Home/reset-to-full-extent behavior.

Past failure: 「全部」walked every loaded file in the channel tree and framed to
the longest time base, even when only shorter channels were plotted. Spinboxes
and the X-axis jumped past the drawn curves.

Rule: Resolve max extent via `_plotted_time_extent` (canvas data union → checked
plotted channels → fallback `_time_data_extent`). Do not use all-files longest
as the primary source for「全部」or draft-local checks when curves are on screen.

Verification: Run
`tests/ui/test_inspector.py -k max_range` and
`tests/ui/test_main_window_smoke.py -k max_range`.
