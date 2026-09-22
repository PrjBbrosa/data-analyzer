"""Persisted, already authenticated revocation facts shared without TUF imports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contract import ExtensionError, ReasonCode

REVOCATION_STORE_NAME = "observed-revocations.json"


def revocation_store_path(app_root: Path) -> Path:
    return Path(app_root) / "extensions/cache/metadata" / REVOCATION_STORE_NAME


def load_revocation_records(path: Path) -> list[dict[str, Any]]:
    """Missing is empty; unreadable or malformed observations fail closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtensionError(ReasonCode.COMPONENT_CORRUPT,
                             "observed revocation cache is unreadable") from exc
    if (not isinstance(payload, dict)
            or payload.get("schema") not in (None, "observed-revocations-v1")
            or not isinstance(payload.get("items"), list)):
        raise ExtensionError(ReasonCode.COMPONENT_CORRUPT,
                             "observed revocation cache has an invalid schema")
    for item in payload["items"]:
        digest = item.get("sha256") if isinstance(item, dict) else None
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in digest)):
            raise ExtensionError(ReasonCode.COMPONENT_CORRUPT,
                                 "observed revocation cache contains an invalid item")
    return payload["items"]
