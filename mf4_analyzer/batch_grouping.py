"""Pure task-to-render-group planning for batch output previews and runs."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from .batch_output import (
    GroupOutputIdentity,
    TaskOutputIdentity,
    build_group_output_identity,
)
from .batch_recipe import TIME_RENDER_DEFAULTS


@dataclass(frozen=True)
class RenderTask:
    source_key: object
    channel: str
    identity: TaskOutputIdentity


@dataclass(frozen=True)
class RenderGroup:
    identity: GroupOutputIdentity
    group_by: str
    group_key: str
    display_name: str
    layout: str
    members: tuple[RenderTask, ...]


def _task_sort_key(task: RenderTask) -> tuple[str, str, str, str]:
    identity = task.identity
    return (
        identity.source_identity,
        identity.group_identity,
        identity.channel_identity,
        identity.task_id,
    )


def _member_identity(task: RenderTask) -> tuple[str, str, str]:
    identity = task.identity
    return (
        identity.source_identity,
        identity.group_identity,
        identity.channel_identity,
    )


def _source_group_key(source_identity: str, group_identity: str) -> str:
    return json.dumps(
        [source_identity, group_identity],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _source_basename(source_identity: str) -> str:
    """Return a display-safe basename for POSIX or Windows identities."""

    value = str(source_identity or "").strip()
    if not value:
        return "source"
    if "\\" in value:
        name = PureWindowsPath(value).name
    else:
        name = PurePosixPath(value).name
    return name or "source"


# Group identities that exist for the runner's benefit, never for a reader's:
# ``default`` is the fallback every plain file gets (batch_output._group_identity)
# and ``unresolved-source:<key>`` is the placeholder a not-yet-loaded source
# carries (batch.py). Neither belongs in a title beside the file name.
#
# This is the single source of truth for the rule.  It used to live only in
# ``batch_render_qt/_page.py``, so chart titles were clean while every other
# reader-facing surface (preview dialog, task list) leaked
# ``unresolved-source:hdf:3af2470…`` through ``_source_display_name``.  The
# rule belongs here because ``batch_grouping`` is GUI-free and sits below both
# consumers.
MACHINE_GROUP_IDENTITIES = ("default",)
MACHINE_GROUP_PREFIXES = ("unresolved-source:", "file_id:")


def is_human_group(group: Any) -> bool:
    """True when *group* is a group name a reader should actually see."""

    text = str(group or "").strip()
    if not text:
        return False
    folded = text.casefold()
    if folded in MACHINE_GROUP_IDENTITIES:
        return False
    return not folded.startswith(MACHINE_GROUP_PREFIXES)


def _source_display_name(source_identity: str, group_identity: str) -> str:
    source_name = _source_basename(source_identity)
    group_name = str(group_identity or "").strip()
    if is_human_group(group_name):
        return f"{source_name} · {group_name}"
    return source_name


def group_render_tasks(
    tasks: Sequence[RenderTask], params: Mapping[str, Any],
) -> tuple[RenderGroup, ...]:
    """Return deterministic singleton, source, or channel render groups."""

    group_by = str(params.get(
        "render_group_by", TIME_RENDER_DEFAULTS["render_group_by"],
    ) or "").strip().lower()
    if group_by not in {"none", "source", "channel"}:
        raise ValueError(f"unsupported render grouping: {group_by!r}")
    layout = str(params.get(
        "render_layout", TIME_RENDER_DEFAULTS["render_layout"],
    ) or "").strip().lower()
    if group_by == "none":
        layout = TIME_RENDER_DEFAULTS["render_layout"]
    elif layout not in {"overlay", "subplot"}:
        raise ValueError(f"unsupported render layout: {layout!r}")

    ordered = tuple(sorted(tasks, key=_task_sort_key))
    if group_by == "none":
        return tuple(
            RenderGroup(
                identity=GroupOutputIdentity(
                    group_id=task.identity.task_id,
                    stem=task.identity.stem,
                    members=(_member_identity(task),),
                ),
                group_by="none",
                group_key=task.identity.task_id,
                display_name=(
                    f"{_source_display_name(task.identity.source_identity, task.identity.group_identity)}"
                    f" · {task.channel}"
                ),
                layout=layout,
                members=(task,),
            )
            for task in ordered
        )

    buckets: dict[object, list[RenderTask]] = {}
    for task in ordered:
        identity = task.identity
        key = (
            (identity.source_identity, identity.group_identity)
            if group_by == "source"
            else identity.channel_identity
        )
        buckets.setdefault(key, []).append(task)

    groups = []
    for key in sorted(buckets):
        members = tuple(sorted(buckets[key], key=_task_sort_key))
        identity = build_group_output_identity(
            tuple(_member_identity(member) for member in members),
            method="time",
            params=params,
            group_by=group_by,
        )
        group_key = (
            _source_group_key(*key)
            if group_by == "source"
            else str(key)
        )
        display_name = (
            _source_display_name(*key)
            if group_by == "source"
            else str(key)
        )
        groups.append(RenderGroup(
            identity=identity,
            group_by=group_by,
            group_key=group_key,
            display_name=display_name,
            layout=layout,
            members=members,
        ))
    return tuple(groups)


__all__ = [
    "MACHINE_GROUP_IDENTITIES",
    "MACHINE_GROUP_PREFIXES",
    "RenderGroup",
    "RenderTask",
    "group_render_tasks",
    "is_human_group",
]
