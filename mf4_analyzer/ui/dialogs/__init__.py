"""Modal dialogs: ChannelEditor, Export, ChartOptions."""
# ``QMessageBox`` stays reachable as ``mf4_analyzer.ui.dialogs.QMessageBox`` because
# tests patch it through this package path (tests/ui/test_dialogs.py).
from PyQt5.QtWidgets import QMessageBox

from .channel_editor import ChannelEditorDialog
from .chart_options import ChartOptionsDialog
from .export import ExportDialog

__all__ = [
    "ChannelEditorDialog",
    "ChartOptionsDialog",
    "ExportDialog",
    "QMessageBox",
]
