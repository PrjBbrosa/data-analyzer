---
id: ultraview-selection-chrome-follows-bounds
status: active
owners: [codex]
keywords: [ultraview, selection-toolbar, chrome, geometry, y=56, classify_press, card-hover, flyout]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/chart_stack/ultraview/author_chrome.py
  - mf4_analyzer/ui/chart_stack/ultraview/author_selection.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
checks:
  - rg -n "setGeometry\\(.*56" mf4_analyzer/ui/chart_stack/ultraview
  - rg -n "RELEASE_AUTHOR_TOOLS" mf4_analyzer/ui/chart_stack/ultraview/chrome.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_selection_toolbar_contract.py tests/ui/test_ultraview_board_hit_routing.py -q
---

# UltraView Selection Chrome Follows Bounds

Trigger: Changing UltraView selection toolbar placement, Signal Spine, author hit routing, or release-rail tool visibility.

Past failure: Seven authoring-tool commits were test-green while the selection toolbar stayed pinned at `y=56`, card actions were dead shells, Spine always said `FFT`, and Select could not hit Connector/Stroke. Intent/commit slice tests did not prove chrome followed the prototype.

Rule: Assert chrome geometry and hit routing on the real widget path. Two selections at different bounds must produce different toolbar `y` values; hide the toolbar when bounds are missing instead of pinning `y=56`. Card/card_author selections never show the author toolbar — Card uses the existing hover/focus action bar. Sticky/Shapes/Draw first click must open an anchored flyout. `classify_press` is the only Select-tool hit owner. Merging Connector into Shapes must keep `L` and persisted objects.

Verification: Run `tests/ui/test_ultraview_selection_toolbar_contract.py` and `tests/ui/test_ultraview_board_hit_routing.py`. Offscreen screenshots are structure evidence only; Cocoa remains a separate gate.
