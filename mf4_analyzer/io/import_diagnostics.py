"""UI-neutral, serializable facts about one completed source import.

Missing metadata is unknown, not a successful validation. Parsers retain their
public return shapes and own recovery decisions; this module only carries facts.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import math
from numbers import Integral, Real


_STATES = {"complete": 0, "warning": 1, "partial": 2}


def _plain(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    raise TypeError(f"unsupported import diagnostic value: {type(value).__name__}")


def make_import_issue(code, message, *, severity="warning", action="retained", **details):
    if severity not in {"warning", "partial"}:
        raise ValueError(f"invalid import issue severity: {severity}")
    return {"code": str(code), "message": str(message), "severity": severity,
            "action": str(action), **_plain(details)}


def _issue_key(issue):
    return json.dumps(issue, ensure_ascii=False, sort_keys=True, allow_nan=False)


def set_import_diagnostics(metadata, issues, *, source_kind=None, **counts):
    unique = []
    seen = set()
    for raw in issues:
        issue = _plain(raw)
        if issue.get("severity") not in {"warning", "partial"}:
            raise ValueError("import issue requires warning or partial severity")
        key = _issue_key(issue)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    state = max((item["severity"] for item in unique), key=_STATES.get,
                default="complete")
    payload = {
        "schema": 1, "state": state,
        "source_kind": str(source_kind or metadata.get("source_kind") or ""),
        "counts": _plain(counts), "issues": unique,
    }
    metadata["import_diagnostics"] = payload
    return payload


def get_import_diagnostics(metadata):
    if not isinstance(metadata, Mapping):
        return None
    payload = metadata.get("import_diagnostics")
    if (not isinstance(payload, Mapping) or payload.get("schema") != 1
            or payload.get("state") not in _STATES
            or not isinstance(payload.get("issues"), (list, tuple))):
        return None
    return deepcopy(dict(payload))


def aggregate_import_diagnostics(source_metadatas):
    """Aggregate a file card's logical sources, never summing shared counts."""
    payloads = []
    issues = []
    seen = set()
    unknown = 0
    for metadata in source_metadatas:
        payload = get_import_diagnostics(metadata)
        if payload is None:
            unknown += 1
            continue
        payloads.append(payload)
        identity = str(metadata.get("source_path") or metadata.get("source_filename") or "")
        for issue in payload["issues"]:
            key = (identity, _issue_key(issue))
            if key not in seen:
                seen.add(key)
                issues.append(issue)
    if not payloads:
        return None
    counts = payloads[0].get("counts", {})
    if any(payload.get("counts", {}) != counts for payload in payloads[1:]):
        counts = {}
    kinds = {payload.get("source_kind", "") for payload in payloads}
    return {
        "schema": 1,
        "state": max((payload["state"] for payload in payloads), key=_STATES.get),
        "source_kind": next(iter(kinds)) if len(kinds) == 1 else "",
        "counts": deepcopy(counts), "issues": issues, "unknown_sources": unknown,
    }


def format_import_summary(metadata):
    payload = get_import_diagnostics(metadata)
    if payload is None or payload["state"] == "complete":
        return ""
    messages = list(dict.fromkeys(str(issue.get("message") or "").strip()
                                 for issue in payload["issues"]))
    messages = [message for message in messages if message]
    prefix = "部分导入" if payload["state"] == "partial" else "导入提示"
    text = "；".join(messages[:3])
    if len(messages) > 3:
        text += f"；另有 {len(messages) - 3} 项，详见导入详情"
    return f"{prefix}：{text}" if text else prefix


def uncovered_legacy_metadata(metadata):
    """Retain legacy facts unless a structured issue explicitly covers them."""
    result = dict(metadata or {})
    payload = get_import_diagnostics(result)
    if payload is None:
        return result
    issues = payload["issues"]

    def covered(entry):
        fields = entry if isinstance(entry, Mapping) else {}
        name = str(fields.get("name", "") if fields else entry)
        name = name.split(" (公式:", 1)[0]
        for issue in issues:
            if issue.get("action") != "skipped":
                continue
            channel = str(issue.get("channel") or "")
            names = {channel}
            if issue.get("group"):
                names.add(f"{issue['group']}.{channel}")
            if not name or name not in names:
                continue
            identities = ("record_index", "column_index", "group_index", "channel_index")
            if all(fields[key] == issue.get(key) for key in identities if key in fields):
                return True
        return False

    for key in ("skipped_channels", "skipped_vars", "dropped_channels"):
        if key in result:
            result[key] = [entry for entry in result[key] or () if not covered(entry)]
    if "warnings" in result:
        messages = {str(issue.get("message") or "").strip() for issue in issues}
        result["warnings"] = [entry for entry in result["warnings"] or ()
                              if str(entry).strip() not in messages]
    return result
