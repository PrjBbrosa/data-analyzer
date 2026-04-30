#!/usr/bin/env python3
"""Codex lessons gate and event recorder."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT_MARKERS = (".git", "AGENTS.md", "pyproject.toml", "package.json")
FAILURE_PATTERNS = re.compile(
    r"(Traceback|AssertionError|FAILED|ERROR|command not found|No such file|Permission denied)",
    re.IGNORECASE,
)
LESSON_REQUIRED_PATTERN = re.compile(r"(?m)^\s*LESSON_REQUIRED\s*:")


def find_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return current


def state_dir(root: Path) -> Path:
    path = root / ".state"
    path.mkdir(exist_ok=True)
    return path


def append_event(root: Path, event: dict[str, Any]) -> None:
    event = {
        "time": dt.datetime.now(dt.timezone.utc).isoformat(),
        **event,
    }
    path = state_dir(root) / "lesson-events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(root: Path) -> list[dict[str, Any]]:
    path = state_dir(root) / "lesson-events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def post_tool_hook(root: Path, data: dict[str, Any]) -> None:
    response = stringify(data.get("tool_response", ""))
    tool_name = data.get("tool_name", "")
    if not response:
        return
    explicit_requirement = LESSON_REQUIRED_PATTERN.search(response)
    if explicit_requirement or FAILURE_PATTERNS.search(response):
        severity = "lesson_required" if explicit_requirement else "observe"
        append_event(
            root,
            {
                "kind": "tool_signal",
                "severity": severity,
                "tool": tool_name,
                "summary": response[:1000],
            },
        )


def requirement_reason(root: Path) -> str | None:
    required_file = state_dir(root) / "lesson-required"
    if required_file.exists() and required_file.read_text(encoding="utf-8").strip():
        return required_file.read_text(encoding="utf-8").strip()

    relevant_events = [
        event for event in read_events(root)
        if event.get("severity") == "lesson_required"
        or event.get("kind") in {"lesson_promoted", "requirement_cleared"}
    ]
    if relevant_events and relevant_events[-1].get("severity") == "lesson_required":
        return str(
            relevant_events[-1].get("summary")
            or relevant_events[-1].get("reason")
            or "lesson_required event"
        )
    return None


def stop_hook(root: Path) -> None:
    reason = requirement_reason(root)
    if not reason:
        return

    candidate = state_dir(root) / "lesson-candidate.md"
    if candidate.exists() and candidate.read_text(encoding="utf-8").strip():
        message = (
            "Lessons gate: a lesson is required and .state/lesson-candidate.md exists. "
            "Promote it with `/usr/bin/python3 scripts/lessons/promote.py`, or explain why "
            "the durable lesson is unnecessary and run `/usr/bin/python3 scripts/lessons/check.py --clear`."
        )
    else:
        message = (
            "Lessons gate: a durable lesson is required before finalizing. "
            f"Reason: {reason}\n"
            "Create `.state/lesson-candidate.md` from `docs/lessons-learned/_template.md`, "
            "fill in trigger/past failure/rule/verification, then promote it with "
            "`/usr/bin/python3 scripts/lessons/promote.py`. If this is a false alarm, "
            "explain why and run `/usr/bin/python3 scripts/lessons/check.py --clear`."
        )

    print(json.dumps({"decision": "block", "reason": message}, ensure_ascii=False))


def mark_required(root: Path, reason: str) -> None:
    path = state_dir(root) / "lesson-required"
    path.write_text(reason.strip() + "\n", encoding="utf-8")
    append_event(root, {"kind": "manual_requirement", "severity": "lesson_required", "reason": reason})


def clear(root: Path) -> None:
    required = state_dir(root) / "lesson-required"
    if required.exists():
        required.unlink()
    append_event(root, {"kind": "requirement_cleared", "severity": "info"})


def status(root: Path) -> None:
    selected = state_dir(root) / "selected-lessons.json"
    candidate = state_dir(root) / "lesson-candidate.md"
    reason = requirement_reason(root)
    print(f"root: {root}")
    print(f"lesson_required: {bool(reason)}")
    if reason:
        print(f"reason: {reason}")
    print(f"candidate_exists: {candidate.exists()}")
    print(f"selected_lessons_state: {selected.exists()}")
    print(f"event_count: {len(read_events(root))}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook", action="store_true", help="Run as Codex Stop hook.")
    parser.add_argument("--post-tool-hook", action="store_true", help="Run as Codex PostToolUse hook.")
    parser.add_argument("--require", help="Mark this task as requiring a lesson.")
    parser.add_argument("--clear", action="store_true", help="Clear the current lesson requirement.")
    parser.add_argument("--status", action="store_true", help="Print lesson gate status.")
    parser.add_argument("--cwd", default=os.getcwd())
    args = parser.parse_args()

    hook_data: dict[str, Any] = {}
    if args.hook or args.post_tool_hook:
        raw = sys.stdin.read().strip()
        hook_data = json.loads(raw) if raw else {}

    root = find_root(Path(hook_data.get("cwd") or args.cwd))

    if args.post_tool_hook:
        post_tool_hook(root, hook_data)
    elif args.hook:
        stop_hook(root)
    elif args.require:
        mark_required(root, args.require)
    elif args.clear:
        clear(root)
    elif args.status:
        status(root)
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
