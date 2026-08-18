"""Versioned internal MIME for a single channel drag. Qt-free."""
from __future__ import annotations

import json

INTERNAL_CHANNEL_MIME = "application/x-tracelab-channel-v1"
_CHANNEL_KIND = "channel"
_CHANNEL_VERSION = 1


def encode_channel_drag(fid, channel) -> bytes:
    """Encode one composite channel key. No arrays, paths, or display names."""
    return json.dumps(
        {
            "version": _CHANNEL_VERSION,
            "kind": _CHANNEL_KIND,
            "fid": str(fid or "").strip(),
            "channel": str(channel or "").strip(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_channel_drag(payload) -> tuple[str, str] | None:
    """Return ``(fid, channel)`` or ``None`` for unknown/malformed payloads."""
    try:
        if isinstance(payload, bytes):
            text = payload.decode("utf-8")
        else:
            text = str(payload)
        data = json.loads(text)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != _CHANNEL_VERSION:
        return None
    if data.get("kind") != _CHANNEL_KIND:
        return None
    fid = str(data.get("fid") or "").strip()
    channel = str(data.get("channel") or "").strip()
    if not fid or not channel:
        return None
    return fid, channel
