from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


_EMPTY_ALIAS_MAP: Mapping[str, tuple[str, ...]] = MappingProxyType({})


@dataclass(frozen=True)
class VehicleSignalMapping:
    vehicle: str
    aliases: Mapping[str, tuple[str, ...]] = _EMPTY_ALIAS_MAP


def _coerce_aliases(raw: dict) -> Mapping[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for standard, raw_channels in raw.items():
        if not isinstance(raw_channels, list):
            raise ValueError(f"aliases.{standard} must be a list")
        out[str(standard)] = tuple(str(ch) for ch in raw_channels)
    return MappingProxyType(out)


def load_vehicle_mapping(root: str | Path, vehicle: str) -> VehicleSignalMapping:
    path = Path(root) / "vehicles" / f"{vehicle}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    aliases = _coerce_aliases(raw.get("aliases", {}))
    return VehicleSignalMapping(vehicle=str(raw.get("vehicle", vehicle)), aliases=aliases)


def resolve_standard_signals(
    raw_channels: list[str] | tuple[str, ...],
    mapping: VehicleSignalMapping,
) -> dict[str, str]:
    raw_set = set(raw_channels)
    resolved: dict[str, str] = {}
    for standard, candidates in mapping.aliases.items():
        for raw in candidates:
            if raw in raw_set:
                resolved[standard] = raw
                break
    return resolved
