"""Shared persisted analysis-preset slots for Inspector and batch UI.

The Inspector remains the owner of the editing experience.  This small module
only centralises the existing QSettings wire format and publishes in-process
changes so a visible batch sheet never keeps a second copy of preset names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from PyQt5.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class StoredAnalysisPresetSlot:
    """One persisted slot, or ``None`` when the slot has no saved override."""

    name: str
    params: dict


class _PresetSlotBus(QObject):
    changed = pyqtSignal(str, int)


_BUS = _PresetSlotBus()


def preset_slot_bus() -> _PresetSlotBus:
    return _BUS


def slot_key(kind: str, slot: int, *, builtin: bool, custom: bool) -> str:
    """Return the current Inspector key without changing its persistence ABI."""

    if builtin:
        return f"{kind}/preset_override/{slot}"
    if custom:
        return f"{kind}/preset_custom/{slot}"
    return f"{kind}/preset/{slot}"


def _settings():
    # Resolve through the helpers module at call time so the UI test fixture's
    # temporary QSettings factory is honoured by both consumers.
    from .inspector_sections import _helpers

    return _helpers._preset_settings()


def read_slot(
    kind: str,
    slot: int,
    *,
    default_name: str,
    builtin: bool,
    custom: bool,
) -> StoredAnalysisPresetSlot | None:
    """Read the Inspector's envelope or its legacy flat-dict representation."""

    raw = _settings().value(
        slot_key(kind, slot, builtin=builtin, custom=custom), "",
    )
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("params"), dict):
        return StoredAnalysisPresetSlot(
            str(payload.get("name") or default_name),
            dict(payload["params"]),
        )
    # Earlier slots contained the parameter mapping directly.
    return StoredAnalysisPresetSlot(default_name, dict(payload))


def notify_slot_changed(kind: str, slot: int) -> None:
    preset_slot_bus().changed.emit(str(kind), int(slot))


__all__ = [
    "StoredAnalysisPresetSlot",
    "notify_slot_changed",
    "preset_slot_bus",
    "read_slot",
    "slot_key",
]
