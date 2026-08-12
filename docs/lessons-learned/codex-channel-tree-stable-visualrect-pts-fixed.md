---
id: codex-channel-tree-stable-visualrect-pts-fixed
status: active
owners: [codex]
keywords: [pyqt, qtreewidget, delegate, selection, checkbox, pts, option.rect, resizetocontents, projection-role]
paths:
  - mf4_analyzer/ui/widgets/channel_tree.py
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/test_file_navigator.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_file_navigator.py -q
---

# Channel Tree Stable Content Rect And Fixed Pts Width

Trigger: Changing channel-tree selection chrome, checkbox painting, Pts column
sizing, QSS item padding, or projection-role presentation.

Past failure: Selected checkable rows on macOS shifted the checkbox and channel
name because paint geometry followed QSS/selection-mutated `option.rect` while
tests only compared helpers. Switching paint to raw `visualRect` then hid
top-level file checkboxes under the expander. Pts also jumped because
`QHeaderView.ResizeToContents` remeasured on selection. Candidate mode stripped
`ItemIsUserCheckable` on parents but channel leaves still painted decorative
boxes, so file checkboxes looked "gone".

Rule: Paint from the view's content `option.rect` after clearing native
check/decoration features; keep horizontal `::item` padding at 0; keep Pts
`Fixed`. Only UserCheckable rows paint a checkbox (parents and channels stay
in sync). Assert painted pixel anchors for selected vs normal rows and for
time-mode file parents.

Verification: Run `tests/ui/test_file_navigator.py` including checkbox border,
Pts right-edge, and file-row checkbox tests across projection roles.
