---
id: toolbar-mirrored-hosts-own-chrome
status: active
owners: [codex]
keywords: [toolbar, layout, mode-zone, centering, compact, left_widget]
paths: [mf4_analyzer/ui/toolbar.py, tests/ui/test_toolbar.py]
checks:
  - Put new toolbar chrome inside `_left_layout` / `_left_widget`, not the outer `QHBoxLayout`
  - Keep mode-zone centering tests green after adding left-side labels
tests:
  - tests/ui/test_toolbar.py::test_toolbar_project_name_lives_inside_mirrored_left_host
  - tests/ui/test_toolbar.py
---

# Main Toolbar Chrome Belongs In The Mirrored Left Host

Trigger: Adding a label, chip, or other chrome to the main Analyzer toolbar, especially beside 打开 / 保存 / 批处理, or changing `_mode_zone_budget` / left-right mirroring.

Past failure: The project-name `QLabel` was inserted on the outer toolbar layout between `left_widget` and the centering stretch. Mode-zone centering uses `left_widget.width() * 2`, so the extra outer width shifted the five-mode segment 32–45 px off center and delayed compact-at-980px.

Rule: New left-side toolbar chrome must live inside `_left_layout` so the mirrored right host can match its width. Do not place widgets on the outer layout between the left host and the stretch. Keep the name chip compact (`Maximum` width) so 1440 px still has labeled modes.

Verification: Assert `lbl_project_session.parent() is tb._left_widget`, then run `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar.py -q`.
