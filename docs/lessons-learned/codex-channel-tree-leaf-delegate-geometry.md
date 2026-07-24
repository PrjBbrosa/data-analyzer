---
id: codex-channel-tree-leaf-delegate-geometry
status: active
owners: [codex]
keywords: [pyqt, qtreewidget, delegate, selection, checkbox, eye-icon, detach-icon, rendered-screenshot]
paths: [mf4_analyzer/ui/widgets/__init__.py, tests/ui/test_file_navigator.py]
checks: [git diff --check]
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_file_navigator.py -q
---

# Channel Tree Leaf Delegate Geometry

Trigger: Changing selected-state presentation or action icons in the channel
tree.

Past failure: Styling the native branch gutter did not change the macOS tree
style's separate checkbox and decoration placement. A selected channel still
showed a shifted checkbox while its colour swatch and eye stayed on different
anchors. A later leaf-only delegate fix aligned channel eyes but left the
file/raster detach icon on the native left decoration inset, so the red x sat
off the display-column centerline.

Rule: Keep the checkbox, colour swatch, text, and display-column actions on
explicit fixed geometry. Channel leaves own their full three-column paint; a
file/raster parent may keep its native row paint, but its column-2 detach icon
must suppress the native decoration and reuse the same centered action rect as
channel eyes. Do not claim the fix from QSS tokens or geometry helpers alone;
render the actual icons and inspect their painted pixels.

Verification: Run the focused navigator test and inspect an offscreen capture
with a checked selected channel next to a checked unselected channel and a
file-row detach icon. Confirm the column-0 checkbox/swatch/text x positions
match, and both the eye and red x are centered in the display column.
