"""Chart-options dialog dispatch for pyqtgraph axis handles."""

from PyQt5.QtWidgets import QDialog

from ._axis_handle import make_handle


def edit_chart_options_dialog(parent_widget, handle, *, color_policy_restore_callback=None):
    """Open the chart options dialog for an existing pyqtgraph axis handle.

    Returns True when the dialog accepted or when the user clicked Apply before
    closing it, so callers can refresh for both paths.
    """
    from .dialogs import ChartOptionsDialog

    axis_handle = make_handle(handle)
    kwargs = {}
    if color_policy_restore_callback is not None:
        kwargs['color_policy_restore_callback'] = color_policy_restore_callback
    dlg = ChartOptionsDialog(parent_widget, axis_handle, **kwargs)
    accepted = dlg.exec_() == QDialog.Accepted
    return accepted or dlg.was_applied()
