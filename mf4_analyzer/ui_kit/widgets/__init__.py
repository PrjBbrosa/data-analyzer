"""Lightweight reusable widgets shared by Analyzer and Cockpit.

Only widgets that have **no Analyzer-specific dependency** belong here.
Anything coupled to ``mf4_analyzer.ui`` internals (FileData, Inspector
panels, etc.) must stay in ``mf4_analyzer/ui/widgets/``.
"""
from .searchable_combo import SearchableComboBox
from .search_field import SearchField

__all__ = ["SearchableComboBox", "SearchField"]
