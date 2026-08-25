"""Runtime policy for activating a newly created View."""

from __future__ import annotations

import sys


def defer_new_view_activation_after_pointer_release() -> bool:
    """Whether a new View must activate on the next Qt event-loop turn.

    A frozen Windows executable uses the qwindows platform plugin.  Rebuilding
    a pyqtgraph canvas synchronously from a ``QPushButton.clicked`` handler can
    expose a short-lived native surface while the pointer release is still in
    flight.  Keep the state mutation synchronous, but let that input event
    complete before the active-view render starts.  Development runs and other
    platforms preserve their established immediate interaction timing.
    """
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))
