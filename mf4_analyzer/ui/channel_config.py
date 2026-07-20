"""Named, user-level channel selection configurations.

The module is deliberately widget-free: it owns the versioned QSettings JSON
shape and resolves raw channel names against files attached to one TimeDomain
View. Dialogs and View mutation live in the main-window layer.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1


def normalize_channel_names(values: Iterable[str]) -> tuple[str, ...]:
    """Return exact channel names in first-seen order without duplicates."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value)
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return tuple(out)


def _normalize_config_name(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError("config name must not be blank")
    return name


@dataclass(frozen=True)
class ChannelSelectionConfig:
    schema_version: int
    config_id: str
    name: str
    channel_names: tuple[str, ...]
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        config_id: str,
        name: str,
        channel_names: Iterable[str],
        *,
        now: str | None = None,
    ) -> "ChannelSelectionConfig":
        normalized_names = normalize_channel_names(channel_names)
        if not normalized_names:
            raise ValueError("channel config must contain at least one channel")
        timestamp = now or datetime.now(timezone.utc).isoformat()
        return cls(
            schema_version=SCHEMA_VERSION,
            config_id=str(config_id),
            name=_normalize_config_name(name),
            channel_names=normalized_names,
            created_at=str(timestamp),
            updated_at=str(timestamp),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config_id": self.config_id,
            "name": self.name,
            "channel_names": list(self.channel_names),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChannelSelectionConfig":
        if int(data["schema_version"]) != SCHEMA_VERSION:
            raise ValueError("unsupported channel config schema")
        config_id = str(data["config_id"])
        if not config_id:
            raise ValueError("config id must not be blank")
        channel_names = data["channel_names"]
        if not isinstance(channel_names, list):
            raise ValueError("channel_names must be a list")
        created_at = str(data["created_at"])
        updated_at = str(data["updated_at"])
        if not created_at or not updated_at:
            raise ValueError("config timestamps must not be blank")
        return cls.create(
            config_id,
            str(data["name"]),
            channel_names,
            now=created_at,
        )._with_updated_at(updated_at)

    def _with_updated_at(self, value: str) -> "ChannelSelectionConfig":
        return replace(self, updated_at=str(value))


class ConfigNameConflict(ValueError):
    """Raised when a trimmed, case-folded config name is already in use."""

    def __init__(self, existing: ChannelSelectionConfig):
        super().__init__(f"channel config name already exists: {existing.name}")
        self.existing = existing


@dataclass(frozen=True)
class ChannelConfigResolution:
    matched: tuple[tuple[str, str], ...]
    missing_names: tuple[str, ...]
    target_file_count: int


class ChannelSelectionConfigStore:
    """Versioned JSON persistence for named channel configurations."""

    SETTINGS_KEY = "channel_selection/configs_v1"

    def __init__(self, settings, *, now=None, id_factory=None):
        self._settings = settings
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.had_corruption = False
        self._configs = self._load()

    def list(self) -> list[ChannelSelectionConfig]:
        return list(self._configs)

    def get(self, config_id: str) -> ChannelSelectionConfig | None:
        wanted = str(config_id)
        return next((item for item in self._configs if item.config_id == wanted), None)

    def create(
        self, name: str, channel_names: Iterable[str]
    ) -> ChannelSelectionConfig:
        normalized_name = _normalize_config_name(name)
        self._ensure_name_available(normalized_name)
        timestamp = str(self._now())
        config = ChannelSelectionConfig.create(
            str(self._id_factory()),
            normalized_name,
            channel_names,
            now=timestamp,
        )
        self._configs.append(config)
        self._flush()
        return config

    def overwrite(
        self, config_id: str, channel_names: Iterable[str]
    ) -> ChannelSelectionConfig:
        idx, existing = self._require(config_id)
        normalized_names = normalize_channel_names(channel_names)
        if not normalized_names:
            raise ValueError("channel config must contain at least one channel")
        replacement = replace(
            existing,
            channel_names=normalized_names,
            updated_at=str(self._now()),
        )
        self._configs[idx] = replacement
        self._flush()
        return replacement

    def rename(self, config_id: str, name: str) -> ChannelSelectionConfig:
        idx, existing = self._require(config_id)
        normalized_name = _normalize_config_name(name)
        self._ensure_name_available(normalized_name, exclude_id=existing.config_id)
        replacement = replace(
            existing,
            name=normalized_name,
            updated_at=str(self._now()),
        )
        self._configs[idx] = replacement
        self._flush()
        return replacement

    def delete(self, config_id: str) -> ChannelSelectionConfig:
        idx, existing = self._require(config_id)
        del self._configs[idx]
        self._flush()
        return existing

    def _load(self) -> list[ChannelSelectionConfig]:
        raw = self._settings.value(self.SETTINGS_KEY, "[]")
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            self.had_corruption = True
            return []
        if not isinstance(payload, list):
            self.had_corruption = True
            return []

        valid: list[ChannelSelectionConfig] = []
        ids: set[str] = set()
        names: set[str] = set()
        for entry in payload:
            try:
                if not isinstance(entry, dict):
                    raise ValueError("config entry must be an object")
                config = ChannelSelectionConfig.from_dict(entry)
                folded = config.name.casefold()
                if config.config_id in ids or folded in names:
                    raise ValueError("duplicate config identity")
            except (KeyError, TypeError, ValueError):
                self.had_corruption = True
                continue
            valid.append(config)
            ids.add(config.config_id)
            names.add(folded)
        return valid

    def _flush(self) -> None:
        payload = [config.to_dict() for config in self._configs]
        self._settings.setValue(
            self.SETTINGS_KEY,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        self._settings.sync()

    def _require(self, config_id: str) -> tuple[int, ChannelSelectionConfig]:
        wanted = str(config_id)
        for idx, config in enumerate(self._configs):
            if config.config_id == wanted:
                return idx, config
        raise KeyError(wanted)

    def _ensure_name_available(self, name: str, *, exclude_id: str | None = None):
        folded = name.casefold()
        for config in self._configs:
            if config.config_id != exclude_id and config.name.casefold() == folded:
                raise ConfigNameConflict(config)


def resolve_channel_config(
    config: ChannelSelectionConfig,
    attached_file_ids: Iterable[str],
    files: Mapping[str, Any],
) -> ChannelConfigResolution:
    """Resolve exact raw names across existing attached files in View order."""
    wanted = set(config.channel_names)
    matched: list[tuple[str, str]] = []
    matched_keys: set[tuple[str, str]] = set()
    seen_names: set[str] = set()
    seen_fids: set[str] = set()
    target_file_count = 0

    for value in attached_file_ids:
        fid = str(value)
        if fid in seen_fids:
            continue
        seen_fids.add(fid)
        fd = files.get(fid)
        if fd is None:
            continue
        target_file_count += 1
        for value in fd.get_signal_channels():
            channel = str(value)
            key = (fid, channel)
            if channel not in wanted or key in matched_keys:
                continue
            matched.append(key)
            matched_keys.add(key)
            seen_names.add(channel)

    return ChannelConfigResolution(
        matched=tuple(matched),
        missing_names=tuple(
            name for name in config.channel_names if name not in seen_names
        ),
        target_file_count=target_file_count,
    )
