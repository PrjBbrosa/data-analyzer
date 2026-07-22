---
id: codex-channel-tree-leaf-delegate-geometry
status: active
owners: [codex]
keywords: [pyqt, qtreewidget, delegate, selection, checkbox, eye-icon, rendered-screenshot]
paths: [mf4_analyzer/ui/widgets/__init__.py, tests/ui/test_file_navigator.py]
checks: [git diff --check]
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_file_navigator.py -q
---

# Channel Tree Leaf Delegate Geometry

Trigger: Changing selected-state presentation or icons in the channel tree.

Past failure: Styling the native branch gutter did not change the macOS tree
style's separate checkbox and decoration placement. A selected channel still
showed a shifted checkbox while the colour swatch and eye stayed on different
anchors.

Rule: For channel leaves, keep the checkbox, colour swatch, text, and display
icon in one explicit item delegate with fixed column geometry. Leave file and
raster parents on the native delegate. Do not claim the fix from QSS tokens;
render a selected and unselected neighbouring row and assert the geometry.

Verification: Run the focused navigator test and inspect an offscreen capture
with a checked selected channel next to a checked unselected channel. Confirm
the column-0 checkbox/swatch/text x positions match and the eye is centered in
the display column.
