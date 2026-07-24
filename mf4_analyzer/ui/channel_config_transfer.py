"""Portable JSON import/export for saved channel configurations.

The functions here are intentionally QWidget- and filesystem-free.  The
dialog owns file pickers and confirmation UI; this module owns only bytes,
validation, and deterministic conflict handling.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .channel_config import (
    ChannelSelectionConfig,
    normalize_channel_names,
    normalize_channel_unit_hints,
)


TRANSFER_FORMAT = "tracelab.channel-configs"
TRANSFER_VERSION = 1
TRANSFER_SUFFIX = ".tracelab-config.json"
MAX_TRANSFER_BYTES = 2 * 1024 * 1024
MAX_CONFIGS = 100
MAX_CHANNELS_PER_CONFIG = 2_000
MAX_CONFIG_NAME_CHARS = 80
MAX_CHANNEL_NAME_CHARS = 180
MAX_UNIT_CHARS = 32


@dataclass(frozen=True)
class TransferConfig:
    name: str
    channel_names: tuple[str, ...]
    channel_unit_hints: tuple[tuple[str, str], ...] = ()

    def unit_hint(self, channel_name: str) -> str:
        return dict(self.channel_unit_hints).get(str(channel_name), "")


@dataclass(frozen=True)
class ParsedTransfer:
    configs: tuple[TransferConfig, ...]


@dataclass(frozen=True)
class ImportMergeResult:
    drafts: tuple[ChannelSelectionConfig, ...]
    imported_count: int
    replaced_count: int
    skipped_count: int


def _validate_name(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    if len(normalized) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return normalized


def _validate_unit(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("channel unit must be a string")
    unit = value.strip()
    if len(unit) > MAX_UNIT_CHARS:
        raise ValueError(f"channel unit exceeds {MAX_UNIT_CHARS} characters")
    return unit


def _transfer_config_from_object(raw: object) -> TransferConfig:
    if not isinstance(raw, Mapping):
        raise ValueError("config entry must be an object")
    name = _validate_name(raw.get("name"), label="config name", limit=MAX_CONFIG_NAME_CHARS)
    channels = raw.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ValueError("config channels must be a non-empty list")
    if len(channels) > MAX_CHANNELS_PER_CONFIG:
        raise ValueError(f"config channels exceeds {MAX_CHANNELS_PER_CONFIG}")
    names: list[str] = []
    hints: dict[str, str] = {}
    for raw_channel in channels:
        if not isinstance(raw_channel, Mapping):
            raise ValueError("channel entry must be an object")
        channel_name = _validate_name(
            raw_channel.get("name"), label="channel name", limit=MAX_CHANNEL_NAME_CHARS
        )
        unit = _validate_unit(raw_channel.get("unit", ""))
        if channel_name in hints or channel_name in names:
            continue
        names.append(channel_name)
        if unit:
            hints[channel_name] = unit
    normalized_names = normalize_channel_names(names)
    if not normalized_names:
        raise ValueError("config must contain at least one channel")
    return TransferConfig(
        name=name,
        channel_names=normalized_names,
        channel_unit_hints=normalize_channel_unit_hints(hints, normalized_names),
    )


def parse_transfer(payload: bytes | bytearray | str) -> ParsedTransfer:
    """Validate portable JSON without touching local storage."""
    if isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    else:
        raw_bytes = bytes(payload)
    if len(raw_bytes) > MAX_TRANSFER_BYTES:
        raise ValueError("file cannot exceed 2 MiB")
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("file is not valid UTF-8 JSON") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("transfer root must be an object")
    if raw.get("format") != TRANSFER_FORMAT:
        raise ValueError("unsupported channel configuration format")
    if raw.get("version") != TRANSFER_VERSION:
        raise ValueError("unsupported channel configuration version")
    configs = raw.get("configs")
    if not isinstance(configs, list) or not configs:
        raise ValueError("transfer must contain at least one config")
    if len(configs) > MAX_CONFIGS:
        raise ValueError(f"transfer contains more than {MAX_CONFIGS} configs")
    parsed = tuple(_transfer_config_from_object(item) for item in configs)
    return ParsedTransfer(configs=parsed)


def serialize_transfer(
    configs: Iterable[ChannelSelectionConfig], *, exported_at: str | None = None
) -> bytes:
    """Return deterministic portable UTF-8 JSON, excluding local-only facts."""
    items = list(configs)
    if not items:
        raise ValueError("at least one config is required for export")
    if len(items) > MAX_CONFIGS:
        raise ValueError(f"transfer contains more than {MAX_CONFIGS} configs")
    payload_configs = []
    for config in items:
        name = _validate_name(config.name, label="config name", limit=MAX_CONFIG_NAME_CHARS)
        if len(config.channel_names) > MAX_CHANNELS_PER_CONFIG:
            raise ValueError(f"config channels exceeds {MAX_CHANNELS_PER_CONFIG}")
        channels = []
        for channel_name in config.channel_names:
            checked = _validate_name(
                channel_name, label="channel name", limit=MAX_CHANNEL_NAME_CHARS
            )
            channels.append({"name": checked, "unit": _validate_unit(config.unit_hint(checked))})
        payload_configs.append({"name": name, "channels": channels})
    export_time = exported_at or datetime.now(timezone.utc).isoformat()
    return json.dumps(
        {
            "format": TRANSFER_FORMAT,
            "version": TRANSFER_VERSION,
            "exported_at": export_time,
            "configs": payload_configs,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _import_name(base: str, taken: set[str]) -> str:
    candidate = f"{base}（导入）"
    sequence = 2
    while candidate.casefold() in taken:
        candidate = f"{base}（导入 {sequence}）"
        sequence += 1
    return candidate


def merge_import(
    drafts: Iterable[ChannelSelectionConfig],
    incoming: Iterable[TransferConfig],
    *,
    conflict_mode: str,
    id_factory,
) -> ImportMergeResult:
    """Merge parsed imports into drafts, preserving IDs for replacement."""
    if conflict_mode not in {"keep", "replace", "skip"}:
        raise ValueError("unsupported import conflict mode")
    result = list(drafts)
    index_by_name = {config.name.casefold(): idx for idx, config in enumerate(result)}
    taken = set(index_by_name)
    imported = replaced = skipped = 0
    for item in incoming:
        existing_index = index_by_name.get(item.name.casefold())
        if existing_index is not None and conflict_mode == "skip":
            skipped += 1
            continue
        if existing_index is not None and conflict_mode == "replace":
            existing = result[existing_index]
            result[existing_index] = replace(
                existing,
                channel_names=item.channel_names,
                channel_unit_hints=item.channel_unit_hints,
            )
            replaced += 1
            continue
        name = item.name if existing_index is None else _import_name(item.name, taken)
        candidate = ChannelSelectionConfig.create(
            str(id_factory()),
            name,
            item.channel_names,
            now="draft",
            channel_unit_hints=item.channel_unit_hints,
        )
        result.append(candidate)
        index_by_name[name.casefold()] = len(result) - 1
        taken.add(name.casefold())
        imported += 1
    return ImportMergeResult(
        drafts=tuple(result),
        imported_count=imported,
        replaced_count=replaced,
        skipped_count=skipped,
    )
