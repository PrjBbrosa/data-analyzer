"""Channel editor as a left-anchored slide-in drawer (v1 baseline: fixed panel)."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QVBoxLayout

from ...ui_kit.dialog_geometry import (
    SCREEN_MARGIN,
    clamp_frame_rect,
    fit_window,
    frame_insets_of,
    resolve_available_rect,
)
from ..dialogs import ChannelEditorDialog
from ..widgets.toast import Toast


class ChannelEditorDrawer(QDialog):
    """
    Wraps ChannelEditorDialog's content in a window anchored to the LEFT edge
    of the parent — right next to the channel/file navigator dock — so the
    editor opens close to the channels it affects (the old build anchored to
    the right edge, which the user found too far away). v1: modal QDialog,
    no slide-in animation.
    """

    # (fid, new_channels, removed_channels). The fid is whichever file the
    # user had selected in the dialog's top file combo at accept time — NOT
    # necessarily the originally-active file, since the dialog lets the user
    # switch files before applying.
    applied = pyqtSignal(str, dict, set)
    export_requested = pyqtSignal(str, list, bool, bool, str)

    # Width matches the narrow "方案 A" layout; the inner dialog scrolls when
    # content overflows, so a modest height is fine.
    PANEL_WIDTH = 336
    LEFT_OFFSET = 12  # px gap from the parent's left edge / navigator dock
    # Toast clearance inside the drawer — no MainWindow status/tab chrome here.
    _TOAST_BOTTOM_MARGIN = 16

    def __init__(self, parent, files, active_fid):
        super().__init__(parent)
        self.setObjectName("DrawerSurface")
        self._inner = ChannelEditorDialog(self, files, active_fid)
        title = self._inner.windowTitle() or "通道编辑"
        self.setWindowTitle(title.replace("通道编辑 - ", "通道编辑 — "))
        self.setModal(True)
        self._inner.setWindowFlags(Qt.Widget)
        # Bookkeeping for headless assertions (BatchSheet toast pattern).
        self._last_toast_text: str = ""
        self._last_toast_kind: str = ""
        self._own_toast: Toast | None = None
        self._forwarding = False
        self.is_closing = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
        self._inner.accepted.connect(self._on_applied)
        self._inner.rejected.connect(self.reject)
        self._inner.export_requested.connect(self.export_requested)
        self._inner.setMinimumWidth(0)
        preferred_h = (parent.height() - 80) if parent is not None else 520
        fit_window(
            self,
            (self.PANEL_WIDTH, max(preferred_h, 240)),
            parent=parent,
            content_minimum=(240, 240),
            clamp_width_to_parent=False,
        )

    def showEvent(self, event):
        parent = self.parent()
        if parent is not None:
            pr = parent.geometry()
            available = resolve_available_rect(widget=self, parent=parent)
            insets = frame_insets_of(self)
            x = pr.left() + self.LEFT_OFFSET
            y = pr.top() + 40
            frame = clamp_frame_rect(
                (x, y, self.width() + insets.horizontal, self.height() + insets.vertical),
                available,
                SCREEN_MARGIN,
            )
            self.resize(frame.width - insets.horizontal, frame.height - insets.vertical)
            self.move(frame.x, frame.y)
        super().showEvent(event)

    def toast(self, text: str, kind: str = "info") -> None:
        """Show a toast on the surface the user is looking at.

        ``MainWindow._toast`` is a child of the main window, so forwarding
        there while this modal drawer is up painted the message *underneath*
        it (export keeps the drawer open on purpose). While visible the drawer
        owns its toast; after close — or while apply is closing us — fall
        back to the parent. ``_forwarding`` lets that fallback happen once.
        """
        self._last_toast_text = text
        self._last_toast_kind = kind
        if self._forwarding:
            return
        if self.isVisible() and not self.is_closing:
            try:
                if self._own_toast is None:
                    self._own_toast = Toast(
                        self, bottom_margin=self._TOAST_BOTTOM_MARGIN,
                    )
                self._own_toast.show_message(text, level=kind)
                return
            except Exception:  # noqa: BLE001
                # Toast is purely informational — fall through to the parent
                # rather than letting a paint bug break the action.
                pass
        parent = self.parent()
        if parent is not None and hasattr(parent, "toast"):
            self._forwarding = True
            try:
                parent.toast(text, kind)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._forwarding = False

    def _on_applied(self):
        # Drop toast-host eligibility before emit: apply feedback must land
        # on the main window, because ``accept()`` immediately closes us.
        self.is_closing = True
        self.applied.emit(
            self._inner.current_fid,
            self._inner.new_channels,
            self._inner.removed_channels,
        )
        self.accept()
