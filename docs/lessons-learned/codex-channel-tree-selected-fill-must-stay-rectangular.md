---
id: codex-channel-tree-selected-fill-must-stay-rectangular
status: active
owners: [codex]
keywords: [channel-tree, selection, qss, border-radius, expander, detach-icon, pill]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/widgets/channel_tree.py
  - tests/ui_kit/test_qss_border_shorthand.py
  - tests/ui/test_channel_widget.py
checks:
  - rg -n "channelTree::(item|branch):selected" -A 8 mf4_analyzer/ui_kit/style.qss
  - rg -n "test_channel_tree_selected_does_not_round_per_cell" tests/ui_kit/test_qss_border_shorthand.py 
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_channel_widget.py::test_selected_file_parent_selection_is_a_continuous_bar tests/ui_kit/test_qss_border_shorthand.py::test_channel_tree_selected_does_not_round_per_cell -q
---

# Channel Tree Selected Fill Must Stay Rectangular

Trigger: Changing channel-tree selected-row QSS, `drawBranches`, or the
display-column close/eye paint path.

Past failure: E1 restated `border-radius` on `::item:selected` and
`::branch:selected` so first/last rows would not square-over the tree's 9px
arc. Qt applies those rules per cell and per branch slot, so a selected file
row became a circle around the expander (square slot corners showing the tree
background) and a detached pill around the red x.

Rule: Do not set `border-radius` on `QTreeWidget#channelTree::item:selected`
or `::branch:selected`. Keep the selected fill a continuous rectangle. The
tree widget still owns the 9px frame radius. Darwin selected parents must
`fillRect` the branch slot with `SELECTED_BG` before the vector chevron;
file-row column-2 actions must use that same rectangular fill, not
`CE_ItemViewItem`. Prove it by sampling rendered corner pixels, not QSS
tokens.

Verification: Run the continuous-bar pixel test and the QSS guard that forbids
per-cell selected radius.
