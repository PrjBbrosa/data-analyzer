"""Persistence for Cockpit per-project config and per-user recent list.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Persistence Contract.

Two artifacts:

1. **``acquisition_config.yaml``** (per-project) — favorites, selected
   measurements with raster, filter state. Looked up in this order:

      1. ``--config`` CLI flag.
      2. ``${A2L_DIR}/acquisition_config.yaml``.
      3. ``${PROJECT_ROOT}/acquisition_config.yaml``.
      4. None — in-memory default, ``pinned = False``.

2. **``~/.acquisition-cockpit/recent.json``** (per-user) — last 50
   selected measurements, pruned by ``max_age_days`` on every write.

This module is intentionally pure-Python (no PyYAML dependency). The
YAML reader/writer here is a deliberate constrained subset: it accepts
exactly the spec schema and rejects everything else with a clear
``ConfigSchemaError``. Adding PyYAML would change deployment posture for
zero feature gain — the schema is small enough that hand-rolling is
safer than depending on a library that handles a thousand shapes we
don't allow.

All file IO uses explicit ``encoding="utf-8"`` per
``docs/lessons-learned/signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md``.
Chinese channel names (e.g. ``转速``, ``振动``) are routine in this
project and would otherwise round-trip through cp936 on Windows.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Per-project config schema.
# ---------------------------------------------------------------------------

# Top-level keys allowed in acquisition_config.yaml. Anything else
# raises ConfigSchemaError.
ALLOWED_TOP_LEVEL = frozenset({
    "version",
    "a2l_path",
    "favorites",
    "selected",
    "filter_state",
    "threshold_overrides",
})

CONFIG_FILENAME = "acquisition_config.yaml"
CONFIG_VERSION = 1


class ConfigSchemaError(ValueError):
    """Raised when ``acquisition_config.yaml`` violates the spec schema."""


@dataclass(frozen=True)
class ConfigStore:
    """Snapshot of the loaded per-project config.

    ``pinned`` is True when an on-disk config was found (CLI / A2L dir /
    project root), False when the loader fell through to the in-memory
    default. The status bar reads ``pinned`` to surface
    "no project pinned" mode per spec §Persistence Contract.

    ``source_path`` is the file that was loaded, or ``None`` for the
    in-memory default.
    """

    pinned: bool
    source_path: Path | None
    version: int = CONFIG_VERSION
    a2l_path: str = ""
    favorites: list[dict[str, Any]] = field(default_factory=list)
    selected: list[dict[str, Any]] = field(default_factory=list)
    filter_state: dict[str, Any] = field(default_factory=dict)
    threshold_overrides: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public load entry point.
# ---------------------------------------------------------------------------


def load_or_default(
    *,
    project_root: Path,
    a2l_dir: Path | None = None,
    cli_config_path: Path | None = None,
) -> ConfigStore:
    """Return a ``ConfigStore`` per the spec 4-step lookup order."""
    candidates: list[Path] = []
    if cli_config_path is not None:
        candidates.append(Path(cli_config_path))
    if a2l_dir is not None:
        candidates.append(Path(a2l_dir) / CONFIG_FILENAME)
    if project_root is not None:
        candidates.append(Path(project_root) / CONFIG_FILENAME)

    for path in candidates:
        if path.exists() and path.is_file():
            return _load_config_file(path)

    return ConfigStore(
        pinned=False,
        source_path=None,
        version=CONFIG_VERSION,
        a2l_path="",
        favorites=[],
        selected=[],
        filter_state={
            "has_daq": True,
            "show_selected_only": False,
            "group": None,
            "datatype": None,
        },
        threshold_overrides={},
    )


def _load_config_file(path: Path) -> ConfigStore:
    text = path.read_text(encoding="utf-8")
    parsed = _parse_yaml(text)
    if not isinstance(parsed, dict):
        raise ConfigSchemaError(f"{path}: top-level must be a mapping")

    extra = set(parsed.keys()) - ALLOWED_TOP_LEVEL
    if extra:
        raise ConfigSchemaError(
            f"{path}: unknown top-level key(s) {sorted(extra)!r}; "
            f"allowed keys are {sorted(ALLOWED_TOP_LEVEL)!r}"
        )

    version = parsed.get("version")
    if version != CONFIG_VERSION:
        raise ConfigSchemaError(
            f"{path}: version must be {CONFIG_VERSION}, got {version!r}"
        )

    return ConfigStore(
        pinned=True,
        source_path=path.resolve(),
        version=CONFIG_VERSION,
        a2l_path=str(parsed.get("a2l_path") or ""),
        favorites=list(parsed.get("favorites") or []),
        selected=list(parsed.get("selected") or []),
        filter_state=dict(parsed.get("filter_state") or {}),
        threshold_overrides=dict(parsed.get("threshold_overrides") or {}),
    )


# ---------------------------------------------------------------------------
# Per-user recent list.
# ---------------------------------------------------------------------------


DEFAULT_MAX_AGE_DAYS = 14
DEFAULT_MAX_ENTRIES = 50


def default_recent_path() -> Path:
    return Path.home() / ".acquisition-cockpit" / "recent.json"


def read_recent(path: Path | None = None) -> dict[str, Any]:
    """Read the recent.json file, or return the default empty shape."""
    p = path if path is not None else default_recent_path()
    if not p.exists():
        return {
            "version": 1,
            "max_age_days": DEFAULT_MAX_AGE_DAYS,
            "max_entries": DEFAULT_MAX_ENTRIES,
            "entries": [],
        }
    return json.loads(p.read_text(encoding="utf-8"))


def write_recent(
    path: Path,
    *,
    new_entry: Mapping[str, Any],
    now_ts: float | None = None,
) -> None:
    """Insert ``new_entry``, prune by ``max_age_days``, cap by
    ``max_entries``, write back UTF-8 JSON.

    ``now_ts`` is injectable for tests; production callers leave it as
    ``None`` so ``time.time()`` is used.
    """
    if now_ts is None:
        now_ts = time.time()

    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "version": 1,
            "max_age_days": DEFAULT_MAX_AGE_DAYS,
            "max_entries": DEFAULT_MAX_ENTRIES,
            "entries": [],
        }

    max_age_days = int(payload.get("max_age_days", DEFAULT_MAX_AGE_DAYS))
    max_entries = int(payload.get("max_entries", DEFAULT_MAX_ENTRIES))
    cutoff_ts = now_ts - max_age_days * 86400.0

    entries: list[dict[str, Any]] = list(payload.get("entries") or [])
    # Remove any existing entry with the same name (dedupe by name).
    new_name = new_entry.get("name")
    entries = [e for e in entries if e.get("name") != new_name]
    # Append new entry.
    entries.append(dict(new_entry))
    # Prune by age.
    entries = [e for e in entries if float(e.get("added_ts", 0.0)) >= cutoff_ts]
    # Enforce max_entries cap (drop oldest).
    if len(entries) > max_entries:
        entries.sort(key=lambda e: float(e.get("added_ts", 0.0)))
        entries = entries[-max_entries:]

    payload["entries"] = entries
    payload.setdefault("version", 1)
    payload.setdefault("max_age_days", DEFAULT_MAX_AGE_DAYS)
    payload.setdefault("max_entries", DEFAULT_MAX_ENTRIES)

    # ``ensure_ascii=False`` keeps Chinese characters as themselves on
    # disk; paired with ``encoding="utf-8"`` so the round-trip is sound
    # on Windows (lessons-learned pin).
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Constrained YAML reader.
#
# Spec schema is small enough that hand-rolling beats pulling pyyaml. The
# parser accepts ONLY shapes the spec lists; anything else raises
# ``ConfigSchemaError`` with a line number. Comments (``# ...``) are
# stripped. Flow mappings/lists (``{}``, ``[]``) are recognized but only
# as empty literals.
#
# Indentation is space-only; tabs are an error.
# ---------------------------------------------------------------------------


_SCALAR_INT = re.compile(r"^-?\d+$")
_SCALAR_FLOAT = re.compile(r"^-?\d+\.\d+$")


def _parse_yaml(text: str) -> Any:
    lines = _preprocess_lines(text)
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, 0)
    if idx != len(lines):
        raise ConfigSchemaError(
            f"line {lines[idx][0] + 1}: unexpected content"
        )
    return value


def _preprocess_lines(text: str) -> list[tuple[int, int, str]]:
    """Strip comments and blank lines; return (orig_lineno, indent, content)."""
    out: list[tuple[int, int, str]] = []
    for i, raw in enumerate(text.splitlines()):
        # Strip trailing whitespace; preserve indent.
        if "\t" in raw[:len(raw) - len(raw.lstrip(" \t"))]:
            raise ConfigSchemaError(
                f"line {i + 1}: tab in indentation; YAML reader requires spaces only"
            )
        stripped = raw.rstrip()
        # Strip comments (anything from unescaped # to EOL). Spec schema
        # has no quoted strings containing #.
        if "#" in stripped:
            # Only treat # as comment when it's whitespace-preceded or
            # at start of trimmed content. This is conservative; the
            # spec schema never embeds # in scalars.
            cleaned = _strip_comment(stripped)
            stripped = cleaned.rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        out.append((i, indent, stripped[indent:]))
    return out


def _strip_comment(line: str) -> str:
    in_double = False
    in_single = False
    for i, ch in enumerate(line):
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == "#" and not in_double and not in_single:
            return line[:i]
    return line


def _parse_block(
    lines: list[tuple[int, int, str]],
    idx: int,
    parent_indent: int,
) -> tuple[Any, int]:
    """Parse a mapping or list block starting at ``lines[idx]``."""
    if idx >= len(lines):
        return {}, idx

    _, indent, content = lines[idx]
    if indent <= parent_indent and parent_indent > 0:
        return {}, idx

    if content.startswith("- "):
        return _parse_list(lines, idx, indent)
    return _parse_mapping(lines, idx, indent)


def _parse_mapping(
    lines: list[tuple[int, int, str]],
    idx: int,
    block_indent: int,
) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while idx < len(lines):
        lineno, indent, content = lines[idx]
        if indent < block_indent:
            break
        if indent > block_indent:
            raise ConfigSchemaError(
                f"line {lineno + 1}: unexpected indent {indent} > {block_indent}"
            )
        if content.startswith("- "):
            raise ConfigSchemaError(
                f"line {lineno + 1}: list item under mapping context"
            )
        key, sep, value_text = content.partition(":")
        if not sep:
            raise ConfigSchemaError(
                f"line {lineno + 1}: mapping entry missing ':'"
            )
        key = key.strip()
        value_text = value_text.strip()
        idx += 1
        if value_text:
            out[key] = _parse_scalar(value_text)
        else:
            # Nested block — peek the next line.
            if idx >= len(lines) or lines[idx][1] <= block_indent:
                out[key] = None
            else:
                child, idx = _parse_block(lines, idx, block_indent)
                out[key] = child
    return out, idx


def _parse_list(
    lines: list[tuple[int, int, str]],
    idx: int,
    block_indent: int,
) -> tuple[list[Any], int]:
    out: list[Any] = []
    while idx < len(lines):
        lineno, indent, content = lines[idx]
        if indent < block_indent or not content.startswith("- "):
            break
        item_text = content[2:].strip()
        idx += 1
        if ":" in item_text and not (item_text.startswith('"') or item_text.startswith("'")):
            # Inline mapping like "- name: foo" — fold sibling keys at
            # one deeper indent into the same mapping.
            item_dict: dict[str, Any] = {}
            key, _, value_text = item_text.partition(":")
            item_dict[key.strip()] = _parse_scalar(value_text.strip()) if value_text.strip() else None
            # Pull continuation lines indented past block_indent.
            child_indent = block_indent + 2  # "- " takes two columns
            while idx < len(lines):
                _, sub_indent, sub_content = lines[idx]
                if sub_indent < child_indent:
                    break
                if sub_content.startswith("- "):
                    break
                if ":" not in sub_content:
                    raise ConfigSchemaError(
                        f"line {lines[idx][0] + 1}: list-item continuation missing ':'"
                    )
                sk, _, sv = sub_content.partition(":")
                item_dict[sk.strip()] = _parse_scalar(sv.strip()) if sv.strip() else None
                idx += 1
            out.append(item_dict)
        else:
            out.append(_parse_scalar(item_text))
    return out, idx


def _parse_scalar(text: str) -> Any:
    if not text:
        return None
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if text == "null" or text == "~":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    if _SCALAR_INT.match(text):
        return int(text)
    if _SCALAR_FLOAT.match(text):
        return float(text)
    return text
