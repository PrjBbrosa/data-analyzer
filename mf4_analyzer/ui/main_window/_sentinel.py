"""Shared sentinel for mixin-based MainWindow methods.

``_INSPECTOR_TIME_RANGE`` is a default-argument sentinel used by FFT,
Order, and FFT-vs-Time method families so callers can distinguish
"use the inspector's current range" from "use no range (None)" from
"use this explicit range".

Defined here (not in window.py) to avoid circular imports when mixin
files that use this sentinel are imported before window.py finishes
initialising its class body.
"""

_INSPECTOR_TIME_RANGE = object()
