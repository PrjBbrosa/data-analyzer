---
id: codex-markup-group-child-normalization
status: active
owners: [codex]
keywords: [markup, QGraphicsItemGroup, scene.items, childItems, undo, crop, paste]
paths: [mf4_analyzer/ui/markup/editor.py, tests/ui/test_markup_editor.py]
checks: [rg -n "_as_markup_item|_markup_items|QGraphicsItemGroup|beginMacro" mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py]
tests: [tests/ui/test_markup_editor.py]
---

# Markup Group Child Normalization

Trigger: Editing or reviewing the markup editor's scene traversal, selection,
copy/paste, crop, or undo behavior when `QGraphicsItemGroup` annotations are
present.

Past failure: `QGraphicsScene.items()` returns both a `QGraphicsItemGroup` and
its child ellipse/text items. Treating those child items as independent markup
annotations led to risky duplicate crop position snapshots, missing number
copy/paste support, and empty paste undo macros.

Rule: Normalize scene hits and traversals to the top-level markup item before
selection, serialization, hit testing, or crop snapshots. Filter editor handles
and crop overlays, deduplicate normalized items, and cover grouped number
annotations with tests whenever changing shared scene traversal.

Verification: Run
`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q`.
Keep targeted coverage for grouped number children, crop overlay filtering,
number copy/paste, and empty paste undo behavior.
