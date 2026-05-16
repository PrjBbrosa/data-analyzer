"""Shared UI primitives for Analyzer and Cockpit.

This package is the lowest layer of the UI dependency graph: it must not
import from ``mf4_analyzer.ui`` (Analyzer) or
``mf4_analyzer.acquisition_ui`` (Cockpit). Both upper packages may
depend on ``ui_kit``; the import boundary is enforced by
``tests/ui/test_import_boundaries.py``.

Public surface (re-exported for convenience; deep imports also work):

* :func:`load_stylesheet` — apply the shared QSS template to a
  ``QApplication`` with icon-cache substitution.
* :func:`setup_chinese_font` — configure matplotlib's Chinese font.
* :class:`Icons` — programmatic QIcon factory (line/glyph icons used
  across both Analyzer toolbar and Cockpit chrome).
* :class:`SearchableComboBox` — drop-in QComboBox with fuzzy-match
  completer.
"""
from .fonts import setup_chinese_font
from .icons import Icons, ensure_icon_cache, render_qss_template
from .stylesheet import load_stylesheet
from .widgets.searchable_combo import SearchableComboBox

__all__ = [
    "Icons",
    "SearchableComboBox",
    "ensure_icon_cache",
    "load_stylesheet",
    "render_qss_template",
    "setup_chinese_font",
]
