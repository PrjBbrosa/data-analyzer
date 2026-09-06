---
id: listwidget-on-white-needs-dark-highlighted-text
status: active
owners: [codex]
keywords: [qss, qlistwidget, selection, highlightedtext, channel-editor, cocoa]
paths:
  - mf4_analyzer/ui/dialogs/channel_editor.py
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/test_channel_editor_export.py
checks:
  - rg -n "channelExportList::item:selected|HighlightedText" mf4_analyzer/ui_kit/style.qss mf4_analyzer/ui/dialogs/channel_editor.py
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_channel_editor_export.py::test_export_list_selected_row_keeps_readable_label tests/ui_kit/test_qss_border_shorthand.py -q
---

# ListWidget On White Needs Dark Highlighted Text

Trigger: Styling a QListWidget (or similar item view) on a white Analyzer
surface, especially Channel Editor 导出/删除.

Past failure: Clicking an export-list channel used Cocoa
`QPalette.HighlightedText` (white). The list background stayed `#ffffff`,
so the selected label vanished. QSS `::item { padding }` without
`selection-color` / `::item:selected { color }` looked complete in source.

Rule: On white lists, set both QSS `selection-color` plus `::item:selected`
ink, and `QPalette.HighlightedText` on the widget and viewport. Do not
assume native highlight fill will appear. Do not use `border:` shorthand
in the selected-item rule.

Verification: `test_export_list_selected_row_keeps_readable_label` samples
selected-row pixels and HighlightedText lightness; run the QSS
border-shorthand lint.
