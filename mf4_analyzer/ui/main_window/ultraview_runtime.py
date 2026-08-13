"""Per-ref UltraView runtime facts that cannot be rebuilt from ViewState.

Qt-free. The coordinator is the only owner; project files never persist this
ledger. Keys are ``UltraViewRef`` only.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ultraview_state import UltraViewRef


@dataclass(frozen=True)
class PresentationRuntimeFacts:
    markup_revision: int | tuple = 0
    visible_pane_count: int | None = None


class PresentationRuntimeLedger:
    """Process-local last-known runtime facts keyed by ``UltraViewRef``."""

    def __init__(self) -> None:
        self._facts: dict[UltraViewRef, PresentationRuntimeFacts] = {}

    def get(self, ref: UltraViewRef) -> PresentationRuntimeFacts | None:
        return self._facts.get(ref)

    def commit(self, ref: UltraViewRef, facts: PresentationRuntimeFacts) -> None:
        self._facts[ref] = facts

    def clear(self) -> None:
        self._facts.clear()
