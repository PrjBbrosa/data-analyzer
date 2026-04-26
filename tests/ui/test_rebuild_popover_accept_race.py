"""Regression tests for the accept/WindowDeactivate race in
``RebuildTimePopover`` (2026-04-26).

Production bug sequence (macOS Cocoa):

1. ``btn_ok.clicked → self.accept() → done(Accepted)`` sets the result
   code to ``Accepted`` and calls ``hide()``.
2. ``hide()`` synchronously dispatches ``QEvent.WindowDeactivate`` to
   the dialog while ``isVisible()`` is still ``True`` (the visibility
   flag hasn't been flushed yet).
3. The dialog's custom ``event()`` handler sees
   ``WindowDeactivate && self.isVisible()`` and calls ``self.reject()``.
4. ``reject() → done(Rejected)`` overwrites the prior ``done(Accepted)``.
5. ``exec_()`` returns ``Rejected`` and the host
   (``MainWindow._show_rebuild_popover``) skips
   ``fd.rebuild_time_axis``.
6. The user clicks compute again, the time axis is still non-uniform,
   the same toast pops, and the loop never breaks.

The fix adds an ``_is_closing`` flag so the deactivate auto-reject is
suppressed once an explicit ``accept`` or ``reject`` is already in
flight; the focus-out auto-close path (deactivate while NO explicit
close is pending) is preserved.

Reproduction strategy under offscreen Qt + pytest-qt
====================================================

The race is timing-dependent: under ``QT_QPA_PLATFORM=offscreen`` with
``qtbot.addWidget(pop)`` the platform plugin does NOT synthesize a
deactivate during ``hide()`` while ``isVisible()`` is still ``True``,
so a literal ``btn_ok.click()`` followed by ``exec_()`` cannot
reproduce the bug deterministically. Per
``docs/lessons-learned/pyqt-ui/2026-04-26-popover-accept-deactivate-race.md``
we lock the timing by:

* Setting the result code directly via ``setResult(Accepted)`` (the
  first half of what ``done`` does in production).
* While the popover is still visible (the second half of ``done`` —
  ``hide()`` — has NOT run yet), invoking the ``event()`` handler with
  a constructed ``QEvent.WindowDeactivate``.

This faithfully recreates the macOS Cocoa sequence (result already
``Accepted``, ``isVisible()`` still ``True``, deactivate fires) without
depending on platform-specific synchronization.

Lessons consumed
================
* ``docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md``
  — offscreen Qt is reliable for geometry and event dispatch when the
  test feeds events explicitly rather than relying on platform-level
  generation.
* ``docs/lessons-learned/pyqt-ui/2026-04-26-popover-accept-deactivate-race.md``
  — ``QDialog.done()`` is not idempotent; a second ``done`` call
  silently overwrites the result code, so any post-accept reject path
  must be guarded.
"""
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QDialog

from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover


def test_clean_accept_survives_deactivate_during_hide(qapp, qtbot):
    """User clicks 确定: result must remain ``Accepted`` even when a
    ``WindowDeactivate`` event fires while ``isVisible()`` is still
    ``True``.

    Reproduces the macOS Cocoa race. With OLD popover code the OLD
    ``event()`` handler calls ``reject() → done(Rejected)`` which
    overwrites the result; ``pop.result()`` ends up ``Rejected``.
    With the fix, ``_is_closing`` is set during ``accept`` so the
    deactivate auto-reject branch is skipped and the result stays
    ``Accepted``.
    """
    pop = RebuildTimePopover(parent=None, target_filename="x.mf4",
                             current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show()
    qtbot.waitExposed(pop)

    # Run the production accept path — sets _is_closing in the fixed
    # code, sets result = Accepted, calls hide(). After accept returns
    # the dialog's isVisible() is False on this platform; restoring
    # it to the production "deactivate fires while still visible"
    # state requires a re-show, which would itself reset state. So we
    # split the sequence below into the two pieces of done() and
    # inject the deactivate between them.
    #
    # accept() in production = done(Accepted) which is roughly
    # setResult(Accepted) + hide() + emit finished + exit_loop.
    # We want to recreate the moment AFTER setResult(Accepted) but
    # BEFORE hide() flips isVisible — that is when the OLD bug fires.
    #
    # Manually call accept() to flip the _is_closing flag (no-op on
    # OLD code), then re-show to restore isVisible(), then inject the
    # deactivate to exercise event(). On OLD code event() will call
    # reject() and overwrite the result; on the fix _is_closing
    # short-circuits the auto-reject.
    pop.accept()
    pop.show()
    qtbot.waitExposed(pop)
    # After re-show, accept's done() already ran once and set result
    # to Accepted. We must re-establish the "result = Accepted, dialog
    # visible" state because show() itself does NOT reset the result.
    assert pop.result() == QDialog.Accepted
    assert pop.isVisible()

    # Inject a WindowDeactivate. OLD code path:
    #   isVisible() == True  → self.reject() → done(Rejected) → result=0
    # NEW code path:
    #   _is_closing is True (set by accept above) → skip reject() →
    #   result stays Accepted.
    pop.event(QEvent(QEvent.WindowDeactivate))

    assert pop.result() == QDialog.Accepted, (
        f"after explicit accept, a WindowDeactivate must NOT flip the "
        f"result; got {pop.result()}. The OLD event() handler is "
        "overriding the user's accept with an auto-reject."
    )


def test_explicit_cancel_returns_rejected(qapp, qtbot):
    """User clicks 取消: result must be ``Rejected``.

    Locks the second half of the contract: the fix's _is_closing flag
    must NOT prevent a user-initiated reject from reaching the
    QDialog state machine.
    """
    pop = RebuildTimePopover(parent=None, target_filename="x.mf4",
                             current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show()
    qtbot.waitExposed(pop)

    pop.reject()
    assert pop.result() == QDialog.Rejected, (
        f"explicit reject must yield Rejected, got {pop.result()}"
    )


def test_focus_out_auto_close_still_rejects(qapp, qtbot):
    """Deactivate while NO explicit close is in flight must still call
    reject (focus-out auto-close intent preserved).

    This guards the original purpose of ``event()``: when the user
    clicks outside the popover, the window manager fires
    ``WindowDeactivate`` and the popover should self-close as a
    rejection. The fix's _is_closing flag must NOT block this path
    when no accept/reject has run yet.
    """
    pop = RebuildTimePopover(parent=None, target_filename="x.mf4",
                             current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show()
    qtbot.waitExposed(pop)

    # Initial state: result code is 0 (the Rejected sentinel that
    # QDialog uses by default). To verify that reject() actually
    # fires from the event handler we observe done() being called.
    fired = []
    _orig_done = pop.done

    def traced_done(r):
        fired.append(r)
        _orig_done(r)

    pop.done = traced_done

    pop.event(QEvent(QEvent.WindowDeactivate))

    assert fired, (
        "event(WindowDeactivate) on a still-visible popover with no "
        "pending accept/reject must trigger an auto-close via reject"
    )
    assert fired[-1] == QDialog.Rejected, (
        f"focus-out auto-close must call done(Rejected); got {fired}"
    )
    assert pop.result() == QDialog.Rejected
