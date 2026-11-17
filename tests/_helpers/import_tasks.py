"""Explicit completion waits for tests consuming asynchronous GUI imports."""
from time import monotonic

from PyQt5.QtTest import QTest


def wait_for_imports(window, *, timeout_ms=30_000):
    """Pump Qt until this window's queued imports finish, or fail the test.

    This only waits; callers retain their real broker or explicitly installed
    stub and must assert the expected import outcome themselves.
    """
    deadline = monotonic() + timeout_ms / 1000
    while window._imports.busy:
        if monotonic() >= deadline:
            raise AssertionError(f"Import tasks did not finish within {timeout_ms} ms")
        QTest.qWait(10)
