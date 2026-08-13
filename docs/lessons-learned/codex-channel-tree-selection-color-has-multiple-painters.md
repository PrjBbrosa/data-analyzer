---
id: codex-channel-tree-selection-color-has-multiple-painters
status: active
owners: [codex]
keywords: [channel-tree, selection, qss, delegate, qt-render, windows]
paths: [mf4_analyzer/ui/widgets/channel_tree.py, mf4_analyzer/ui_kit/style.qss, tests/ui/test_channel_widget.py]
checks: [rg -n "SELECTED_BG|channelTree::(item|branch):selected|drawBranches" mf4_analyzer/ui/widgets/channel_tree.py mf4_analyzer/ui_kit/style.qss]
tests: [tests/ui/test_channel_widget.py, tests/ui/test_file_navigator.py]
---

# Channel Tree Selection Color Has Multiple Painters

Trigger: Changing the selected-row color or painting behavior of the Analyzer
channel tree.

Past failure: The channel tree QSS selected color was changed, but channel
leaves still rendered the old color because `_ChannelLeafDelegate` paints the
leaf body and `_CheckTolerantTree.drawBranches` repaints its indent gutter.
Source inspection of QSS alone would have declared the visual change complete
even though the actual screen pixels were unchanged.

Rule: Keep all three selected-row paths synchronized: the generic channel-tree
QSS item/branch rules, `_ChannelLeafDelegate.SELECTED_BG`, and the custom
branch-gutter fill. Reuse the delegate constant inside Python painting code,
and verify the result by rendering a selected real channel row and sampling
both its body and gutter pixels.

Verification: Run
`.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_channel_widget.py tests/ui/test_file_navigator.py`
with `QT_QPA_FONTDIR=C:\\Windows\\Fonts`; confirm the selected-row render test
and channel geometry tests pass.
