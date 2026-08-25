---
id: ultraview-live-editor-suppresses-persisted-text
status: active
owners: [codex]
keywords: [ultraview, author, text, editor, ghosting, double-paint, QPlainTextEdit]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/author_layer.py
  - mf4_analyzer/ui/chart_stack/ultraview/author_render.py
  - mf4_analyzer/ui/chart_stack/ultraview/author_widgets.py
  - mf4_analyzer/ui/chart_stack/ultraview/free_grid_author_controller.py
  - tests/ui/test_ultraview_author_layer.py
  - tests/ui/test_ultraview_author_integration.py
checks:
  - rg -n "hidden_text_object_ids|editing_state_changed" mf4_analyzer/ui/chart_stack/ultraview tests/ui
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_author_render.py tests/ui/test_ultraview_author_layer.py tests/ui/test_ultraview_author_integration.py tests/ui/test_ultraview_author_text_slice.py tests/ui/test_ultraview_author_shape_slice.py tests/ui/test_ultraview_author_connector_slice.py -q
---

# UltraView Live Editor Suppresses Persisted Text

Trigger: Editing an existing UltraView text object, shape label, or connector
label shows doubled, offset, or ghosted glyphs.

Past failure: The live `QPlainTextEdit` used a transparent background while
`AuthorPaintLayer` continued to render the persisted object beneath it. A
font-pixel-size repair addressed collapsed glyph advance inside the editor but
did not remove that second paint source.

Rule: Treat editor metrics and duplicate ink as separate failures. While the
direct editor is active, project its object id into the paint layer and suppress
only that object's text. Do not hide shape or connector geometry, add another
transparent overlay, or rely on `raise_()`/repaint timing.

Verification: Assert that the active editor id is projected and cleared after
cancel/commit, and render the transparent author layer with the active id to
prove it leaves no persisted text ink. Run the focused author rendering and
interaction tests.
