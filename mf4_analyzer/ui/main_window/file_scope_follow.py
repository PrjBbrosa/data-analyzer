"""File-scope follow preferences and pure decision helpers (Stage 1.1).

No Qt widgets / MainWindow. Callers own projection, toast, and attach writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# Reuse the historical auto-attach key so existing user prefs migrate as item 1.
ATTACH_ON_LOAD_KEY = "channel_selection/auto_attach_current_view"
INHERIT_ON_NEW_VIEW_KEY = "channel_selection/follow_new_view_inherit_files"
FILL_ON_MODE_ENTRY_KEY = "channel_selection/follow_fill_empty_on_mode_entry"


def _coerce_bool(raw: Any, *, default: bool) -> bool:
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off", ""}


def _normalize_fids(
    values: Iterable[Any] | None,
    files: Mapping[str, Any] | Iterable[str] | None,
) -> list[str]:
    """Deduplicate, preserve order, drop fids absent from ``files`` when given."""
    if files is None:
        loaded = None
    elif isinstance(files, Mapping):
        loaded = {str(fid) for fid in files}
    else:
        loaded = {str(fid) for fid in files}
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        fid = str(value)
        if not fid or fid in seen:
            continue
        if loaded is not None and fid not in loaded:
            continue
        seen.add(fid)
        out.append(fid)
    return out


@dataclass(frozen=True)
class FollowPrefs:
    attach_on_load: bool = True
    inherit_on_new_view: bool = False
    fill_on_mode_entry: bool = False

    def any_enabled(self) -> bool:
        return (
            self.attach_on_load
            or self.inherit_on_new_view
            or self.fill_on_mode_entry
        )

    def enabled_count(self) -> int:
        return sum(
            (
                self.attach_on_load,
                self.inherit_on_new_view,
                self.fill_on_mode_entry,
            )
        )


def load_follow_prefs(settings) -> FollowPrefs:
    """Read prefs from QSettings-like object; item 1 reuses the legacy key."""
    return FollowPrefs(
        attach_on_load=_coerce_bool(
            settings.value(ATTACH_ON_LOAD_KEY, True), default=True
        ),
        inherit_on_new_view=_coerce_bool(
            settings.value(INHERIT_ON_NEW_VIEW_KEY, False), default=False
        ),
        fill_on_mode_entry=_coerce_bool(
            settings.value(FILL_ON_MODE_ENTRY_KEY, False), default=False
        ),
    )


def save_follow_prefs(settings, prefs: FollowPrefs) -> None:
    settings.setValue(ATTACH_ON_LOAD_KEY, bool(prefs.attach_on_load))
    settings.setValue(INHERIT_ON_NEW_VIEW_KEY, bool(prefs.inherit_on_new_view))
    settings.setValue(FILL_ON_MODE_ENTRY_KEY, bool(prefs.fill_on_mode_entry))
    sync = getattr(settings, "sync", None)
    if callable(sync):
        sync()


def resolve_new_view_template(
    section_attachment: Sequence[Any] | None,
    time_attachment: Sequence[Any] | None,
    files: Mapping[str, Any] | Iterable[str] | None,
) -> list[str]:
    """Fids to copy into a brand-new View (item 2).

    Priority: same-section template → time-focus View → empty.
    """
    primary = _normalize_fids(section_attachment, files)
    if primary:
        return primary
    return _normalize_fids(time_attachment, files)


def resolve_mode_entry_fill(
    target_attachment: Sequence[Any] | None,
    time_attachment: Sequence[Any] | None,
    files: Mapping[str, Any] | Iterable[str] | None,
) -> list[str] | None:
    """Fids to write when entering an analysis mode (item 3).

    Returns ``None`` when the target already has any attachment (do not touch).
    Returns ``[]`` when the target is empty and the time template is also empty.
    """
    existing = _normalize_fids(target_attachment, files=None)
    if existing:
        return None
    return _normalize_fids(time_attachment, files)
