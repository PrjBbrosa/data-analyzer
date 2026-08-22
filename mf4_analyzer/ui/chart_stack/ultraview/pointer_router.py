"""Canonical import path for UltraView ``PointerRouter``.

Implementation lives in ``board_pointer.py`` so existing relative imports keep
working. This module re-exports the composed router; it does not install a
QApplication event filter.
"""
from __future__ import annotations

from .board_pointer import PointerHitFacts, PointerRouter

__all__ = ["PointerHitFacts", "PointerRouter"]
