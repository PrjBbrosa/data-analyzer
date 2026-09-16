---
id: layout-derived-x-titles-are-auto-origin
status: active
owners: [codex]
keywords: [wwt, custom-xaxis, label_origin, inspector, winwert]
paths: [mf4_analyzer/ui/wwt_view_import.py, mf4_analyzer/ui/time_xaxis.py, tests/ui/test_wwt_view_import.py, tests/ui/test_wwt_import_flow.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_view_import.py::test_ordinary_x_axis_opts_mark_layout_title_auto_even_when_it_differs tests/ui/test_wwt_import_flow.py::test_wwt_layout_import_first_time_switch_clears_auto_draft_then_apply_uses_time -q]
tests: [tests/ui/test_wwt_view_import.py::test_ordinary_x_axis_opts_mark_layout_title_auto_even_when_it_differs, tests/ui/test_wwt_import_flow.py::test_wwt_layout_import_first_time_switch_clears_auto_draft_then_apply_uses_time]
---

# Layout-Derived X Titles Are Auto Origin

Trigger: Constructing `CustomXAxisSpec` in a file or layout importer, especially WWT/WinWert ordinary channel X.

Past failure: `_x_axis_opts` wrote the WinWert display title without `label_origin`. The dataclass defaults to `user`, so Inspector kept `Steering Angle [deg]` on the first switch to 自动(时间).

Rule: Layout-derived X titles are bound to the current X source. Pass `label_origin=LABEL_ORIGIN_AUTO`. Only real `textEdited` user titles are `user`. Do not rely on the dataclass default, and do not infer origin from whether the title equals the channel name.

Verification: Ordinary WWT proposals persist `auto`; first Auto-Time switch clears the draft; applying uses source time arrays and `Time (s)`. Existing user-title tests still keep handwritten labels.
