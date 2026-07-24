"""Named, user-level channel selection configurations.

This module deliberately has no QWidget dependency.  It owns the versioned
QSettings representation, draft-safe commits, portable unit hints, and exact
raw-name resolution against one TimeDomain View.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 2
_SUPPORTED_SCHEMA_VERSIONS = {1, SCHEMA_VERSION}


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


def normalize_channel_unit_hints(
    values: Mapping[str, str] | Iterable[tuple[str, str]] | None,
    channel_names: Iterable[str],
) -> tuple[tuple[str, str], ...]:
    """Normalize display-only units in channel order.

    Names remain the sole identity.  Hints for absent names and empty units are
    omitted so an old v1 record remains compact after the first real save.
    """
    if values is None:
        raw: dict[str, str] = {}
    elif isinstance(values, Mapping):
        raw = {str(name): str(unit).strip() for name, unit in values.items()}
    else:
        raw = {str(name): str(unit).strip() for name, unit in values}
    return tuple(
        (name, raw[name])
        for name in channel_names
        if raw.get(name, "")
    )


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
    channel_unit_hints: tuple[tuple[str, str], ...] = ()

    @classmethod
    def create(
        cls,
        config_id: str,
        name: str,
        channel_names: Iterable[str],
        *,
        now: str | None = None,
        channel_unit_hints: Mapping[str, str]
        | Iterable[tuple[str, str]]
        | None = None,
    ) -> "ChannelSelectionConfig":
        normalized_names = normalize_channel_names(channel_names)
        if not normalized_names:
            raise ValueError("channel config must contain at least one channel")
        identifier = str(config_id)
        if not identifier:
            raise ValueError("config id must not be blank")
        timestamp = now or datetime.now(timezone.utc).isoformat()
        return cls(
            schema_version=SCHEMA_VERSION,
            config_id=identifier,
            name=_normalize_config_name(name),
            channel_names=normalized_names,
            created_at=str(timestamp),
            updated_at=str(timestamp),
            channel_unit_hints=normalize_channel_unit_hints(
                channel_unit_hints, normalized_names
            ),
        )

    def unit_hint(self, channel_name: str) -> str:
        return dict(self.channel_unit_hints).get(str(channel_name), "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "config_id": self.config_id,
            "name": self.name,
            "channel_names": list(self.channel_names),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "channel_unit_hints": dict(self.channel_unit_hints),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChannelSelectionConfig":
        version = int(data["schema_version"])
        if version not in _SUPPORTED_SCHEMA_VERSIONS:
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
        raw_hints = data.get("channel_unit_hints", {}) if version >= 2 else {}
        if not isinstance(raw_hints, Mapping):
            raise ValueError("channel_unit_hints must be an object")
        return cls.create(
            config_id,
            str(data["name"]),
            channel_names,
            now=created_at,
            channel_unit_hints=raw_hints,
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


@dataclass(frozen=True)
class ChannelConfigPreview:
    """Read-only current-View facts used by the configuration editor."""

    target_file_count: int
    available_names: frozenset[str]
    unit_hints: tuple[tuple[str, str], ...]
    inconsistent_unit_names: frozenset[str]

    def unit_for(self, channel_name: str) -> str:
        return dict(self.unit_hints).get(str(channel_name), "")

    def matches(self, channel_name: str) -> bool:
        return str(channel_name) in self.available_names


def build_channel_config_preview(
    attached_file_ids: Iterable[str], files: Mapping[str, Any]
) -> ChannelConfigPreview:
    """Collect name/unit facts from attached files without changing any View."""
    names: set[str] = set()
    units: dict[str, str] = {}
    inconsistent: set[str] = set()
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
        channel_units = getattr(fd, "channel_units", None) or {}
        for value in fd.get_signal_channels():
            name = str(value)
            names.add(name)
            unit = str(channel_units.get(name, "") or "").strip()
            prior = units.get(name, "")
            if unit and prior and prior != unit:
                inconsistent.add(name)
            if unit and not prior:
                units[name] = unit
    return ChannelConfigPreview(
        target_file_count=target_file_count,
        available_names=frozenset(names),
        unit_hints=tuple((name, units[name]) for name in sorted(units)),
        inconsistent_unit_names=frozenset(inconsistent),
    )


class ChannelSelectionConfigStore:
    """Versioned JSON persistence for named channel configurations."""

    SETTINGS_KEY = "channel_selection/configs_v1"

    def __init__(self, settings, *, now=None, id_factory=None):
        self._settings = settings
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.had_corruption = False
        self._configs = self._load()
        self._reserved_draft_ids: set[str] = {config.config_id for config in self._configs}

    def list(self) -> list[ChannelSelectionConfig]:
        return list(self._configs)

    def get(self, config_id: str | None) -> ChannelSelectionConfig | None:
        wanted = str(config_id or "")
        return next((item for item in self._configs if item.config_id == wanted), None)

    def new_draft_id(self) -> str:
        """Return an ID reserved for a dialog-local draft, not a persisted row."""
        while True:
            candidate = str(self._id_factory())
            if candidate and candidate not in self._reserved_draft_ids:
                self._reserved_draft_ids.add(candidate)
                return candidate

    def create(
        self,
        name: str,
        channel_names: Iterable[str],
        *,
        channel_unit_hints: Mapping[str, str]
        | Iterable[tuple[str, str]]
        | None = None,
    ) -> ChannelSelectionConfig:
        normalized_name = _normalize_config_name(name)
        self._ensure_name_available(normalized_name)
        draft = ChannelSelectionConfig.create(
            self.new_draft_id(),
            normalized_name,
            channel_names,
            now="draft",
            channel_unit_hints=channel_unit_hints,
        )
        return next(
            config
            for config in self.commit_snapshot([*self._configs, draft])
            if config.config_id == draft.config_id
        )

    def overwrite(
        self,
        config_id: str,
        channel_names: Iterable[str],
        *,
        channel_unit_hints: Mapping[str, str]
        | Iterable[tuple[str, str]]
        | None = None,
    ) -> ChannelSelectionConfig:
        idx, existing = self._require(config_id)
        names = normalize_channel_names(channel_names)
        draft = replace(
            existing,
            channel_names=names,
            channel_unit_hints=normalize_channel_unit_hints(
                channel_unit_hints, names
            ),
        )
        if not draft.channel_names:
            raise ValueError("channel config must contain at least one channel")
        drafts = self.list()
        drafts[idx] = draft
        return next(
            config
            for config in self.commit_snapshot(drafts)
            if config.config_id == existing.config_id
        )

    def rename(self, config_id: str, name: str) -> ChannelSelectionConfig:
        idx, existing = self._require(config_id)
        drafts = self.list()
        drafts[idx] = replace(existing, name=_normalize_config_name(name))
        return next(
            config
            for config in self.commit_snapshot(drafts)
            if config.config_id == existing.config_id
        )

    def delete(self, config_id: str) -> ChannelSelectionConfig:
        _idx, existing = self._require(config_id)
        self.commit_snapshot(
            [config for config in self._configs if config.config_id != existing.config_id]
        )
        return existing

    def commit_snapshot(
        self, configs: Iterable[ChannelSelectionConfig]
    ) -> list[ChannelSelectionConfig]:
        """Validate then persist a complete dialog snapshot with one sync.

        The caller may freely discard its draft.  No store state changes until
        every identity/name/channel invariant has been checked.
        """
        candidates = list(configs)
        existing_by_id = {config.config_id: config for config in self._configs}
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        validated: list[tuple[ChannelSelectionConfig, str, tuple[str, ...], tuple[tuple[str, str], ...]]] = []

        for candidate in candidates:
            if not isinstance(candidate, ChannelSelectionConfig):
                raise ValueError("channel config snapshot contains an invalid item")
            config_id = str(candidate.config_id)
            if not config_id or config_id in seen_ids:
                raise ValueError("channel config snapshot has duplicate identity")
            name = _normalize_config_name(candidate.name)
            folded = name.casefold()
            if folded in seen_names:
                conflict = next(
                    (item for item, prior_name, _names, _hints in validated if prior_name.casefold() == folded),
                    candidate,
                )
                raise ConfigNameConflict(conflict)
            names = normalize_channel_names(candidate.channel_names)
            if not names:
                raise ValueError("channel config must contain at least one channel")
            hints = normalize_channel_unit_hints(candidate.channel_unit_hints, names)
            validated.append((candidate, name, names, hints))
            seen_ids.add(config_id)
            seen_names.add(folded)

        timestamp = str(self._now())
        normalized: list[ChannelSelectionConfig] = []
        for candidate, name, names, hints in validated:
            config_id = candidate.config_id
            existing = existing_by_id.get(config_id)
            if existing is None:
                normalized.append(
                    ChannelSelectionConfig.create(
                        config_id,
                        name,
                        names,
                        now=timestamp,
                        channel_unit_hints=hints,
                    )
                )
            elif (
                existing.name == name
                and existing.channel_names == names
                and existing.channel_unit_hints == hints
            ):
                normalized.append(existing)
            else:
                normalized.append(
                    replace(
                        existing,
                        schema_version=SCHEMA_VERSION,
                        name=name,
                        channel_names=names,
                        channel_unit_hints=hints,
                        updated_at=timestamp,
                    )
                )

        self._persist_snapshot(normalized)
        return self.list()

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

    def _persist_snapshot(self, configs: list[ChannelSelectionConfig]) -> None:
        old_configs = self._configs
        old_raw = self._settings.value(self.SETTINGS_KEY, "[]")
        payload = json.dumps(
            [config.to_dict() for config in configs],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            self._settings.setValue(self.SETTINGS_KEY, payload)
            self._settings.sync()
            status = self._settings.status()
            if int(status) != 0:
                raise OSError(f"channel config settings sync failed: {int(status)}")
        except Exception:
            self._configs = old_configs
            try:
                self._settings.setValue(self.SETTINGS_KEY, old_raw)
                self._settings.sync()
            except Exception:
                pass
            raise
        self._configs = list(configs)
        self._reserved_draft_ids.update(config.config_id for config in configs)

    def _require(self, config_id: str) -> tuple[int, ChannelSelectionConfig]:
        wanted = str(config_id)
        for idx, config in enumerate(self._configs):
            if config.config_id == wanted:
                return idx, config
        raise KeyError(wanted)

    def _ensure_name_available(self, name: str, *, exclude_id: str | None = None) -> None:
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
