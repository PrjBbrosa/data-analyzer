"""Neutral CAN frame result retaining read diagnostics across processes."""


class CanFrameBatch(list):
    """Keep the existing frame-list API and immutable warning text."""

    def __init__(self, frames=(), *, warnings=()):
        super().__init__(frames)
        self.warnings = tuple(warnings)


class _CanFrameBudget:
    """One retained-frame peak, reused when ASC discards a fast-path prefix."""

    def __init__(self):
        from .import_limits import get_import_budget

        self.budget = get_import_budget()
        self.peak_bytes = 0

    def admit(self, total_bytes):
        self.budget.reserve(max(0, total_bytes - self.peak_bytes), label="CAN retained frames")
        self.peak_bytes = max(self.peak_bytes, total_bytes)
