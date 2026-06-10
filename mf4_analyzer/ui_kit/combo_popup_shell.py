"""Give every ``QComboBox`` dropdown the rounded-popup translucent shell.

Background
----------
``style.qss`` rounds the *inner* list of every combo::

    QComboBox QAbstractItemView { border-radius: 8px; background: #fff; ... }

but a combo popup is shown inside a **top-level window** —
``QComboBoxPrivateContainer`` (a ``QFrame``). That window is, by default,
an opaque, square, natively shadowed rectangle. The rounded QSS then
paints *inside* it, so the square corners and the rectangular native
shadow leak out behind the rounded list — the "矩形框叠在圆角框后面"
users see on every dropdown.

Fix / prevention
----------------
Every other rounded popup in the app (markup style menu, pyqtgraph
context menus, ``RebuildTimePopover``, ``SignalPickerPopup`` …) pairs its
rounded QSS with ``Qt.WA_TranslucentBackground`` + ``FramelessWindowHint
| NoDropShadowWindowHint`` on the popup window. Combos are created at ~30
call sites across Analyzer and Cockpit, so patching each one is both
tedious and fragile — the next ``QComboBox(...)`` would forget again.

Instead we install a single application-level event filter (from the
shared ``load_stylesheet`` chokepoint that both processes already call).
It configures the popup window of *every* combo — present and future —
the first time the combo is shown, while its container is still hidden,
so there is no re-show flicker. This is the structural guard that keeps
the bug from recurring; see
``docs/lessons-learned/codex-rounded-qt-popups-need-translucent-shell.md``.
"""
from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QComboBox


# The native-shadow flags that kill the rectangular backing/shadow. Paired
# with WA_TranslucentBackground (set in _apply_shell) for parity with the
# rest of the app's rounded popups.
_SHELL_FLAGS = Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint


def _apply_shell(window):
    """Apply the translucent rounded-popup shell to ``window`` once.

    Returns ``True`` only when the shell was newly applied (used by the
    fallback path to decide whether a re-show is needed). Idempotent: a
    window that already carries ``WA_TranslucentBackground`` is left
    untouched, so repeated Show events are cheap no-ops.
    """
    if window is None or window.testAttribute(Qt.WA_TranslucentBackground):
        return False
    window.setWindowFlags(window.windowFlags() | _SHELL_FLAGS)
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    # Translucency alone removes the opaque square *fill*, but
    # QComboBoxPrivateContainer also paints a 1px square *frame* in its
    # own paintEvent (via the style, independent of frameShape) — that is
    # the leftover gray rectangle outside the rounded inner list. A global
    # QSS rule does not reach this private top-level popup window, so the
    # border must be cleared on the container directly.
    window.setStyleSheet(
        "QComboBoxPrivateContainer { border: none; background: transparent; }"
    )
    return True


class _ComboPopupShellFilter(QObject):
    """Application event filter that rounds every combo dropdown.

    Catching it centrally — rather than at each ``QComboBox(...)`` call
    site — means no current or future combo can forget the shell.
    """

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show:
            if isinstance(obj, QComboBox):
                # Primary path: a combo is shown long before its popup
                # opens, so we force-create and configure the (still
                # hidden) container with zero re-show flicker.
                _apply_shell(obj.view().window())
            elif obj.metaObject().className() == "QComboBoxPrivateContainer":
                # Fallback: a popup whose owning combo we never observed
                # being shown. The window is already mapped, so changing
                # its flags hides it — re-show the now-translucent popup.
                if _apply_shell(obj):
                    obj.show()
        return False


# One filter per process. Kept module-global so a second load_stylesheet
# call (or a test re-invoking install) does not stack duplicate filters.
_filter_ref = []


def install_combo_popup_shell(app):
    """Install the combo-popup shell filter on ``app`` (idempotent).

    Returns the active filter instance. Call once, after ``QApplication``
    construction — ``load_stylesheet`` does this for both Analyzer and
    Cockpit.
    """
    if _filter_ref:
        return _filter_ref[0]
    filt = _ComboPopupShellFilter(app)
    app.installEventFilter(filt)
    _filter_ref.append(filt)
    return filt
