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


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid json: {exc}"
    if not isinstance(data, dict):
        return None, "json root is not an object"
    return data, None


def active_hook_names(root: Path) -> tuple[list[str], str | None]:
    data, error = read_json(root / ".codex" / "hooks.json")
    if error:
        return [], error
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return [], "hooks field is not an object"
    return sorted(str(name) for name in hooks), None


def count_index_lessons(index: Path) -> int:
    if not index.exists():
        return 0
    count = 0
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.startswith("| [") and "](" in line:
            count += 1
    return count


def status(root: Path, verbose: bool = False) -> None:
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
    if verbose:
        hooks, hook_error = active_hook_names(root)
        print(f"active_hooks: {hooks if not hook_error else hook_error}")
        print(f"audit_hooks_config: {(root / '.codex' / 'hooks.audit.json').exists()}")
        print(f"index_lesson_count: {count_index_lessons(root / 'docs' / 'lessons-learned' / 'INDEX.md')}")


def doctor(root: Path, verbose: bool = False) -> int:
    failures = 0
    warnings = 0

    def report(level: str, message: str) -> None:
        nonlocal failures, warnings
        if level == "FAIL":
            failures += 1
        elif level == "WARN":
            warnings += 1
        print(f"{level}: {message}")

    print(f"root: {root}")

    config = root / ".codex" / "config.toml"
    if not config.exists():
        report("FAIL", "missing .codex/config.toml; Codex hooks may not be enabled")
    elif "codex_hooks = true" in config.read_text(encoding="utf-8"):
        report("OK", ".codex/config.toml enables codex_hooks")
    else:
        report("FAIL", ".codex/config.toml does not enable codex_hooks")

    hooks, hook_error = active_hook_names(root)
    if hook_error:
        report("FAIL", f".codex/hooks.json {hook_error}")
    else:
        missing = [name for name in ("UserPromptSubmit", "Stop") if name not in hooks]
        if missing:
            report("FAIL", f".codex/hooks.json missing required hooks: {', '.join(missing)}")
        else:
            report("OK", f".codex/hooks.json has required hooks: {', '.join(hooks)}")
        if "PostToolUse" in hooks:
            report("WARN", "PostToolUse is active; keep it in .codex/hooks.audit.json unless intentionally auditing")

    audit_hooks = root / ".codex" / "hooks.audit.json"
    audit_data, audit_error = read_json(audit_hooks)
    if audit_error:
        report("WARN", f".codex/hooks.audit.json {audit_error}; optional audit mode is unavailable")
    else:
        audit_names = sorted(str(name) for name in audit_data.get("hooks", {}))
        if "PostToolUse" in audit_names:
            report("OK", ".codex/hooks.audit.json preserves optional PostToolUse auditing")
        else:
            report("WARN", ".codex/hooks.audit.json exists but does not include PostToolUse")

    required_files = [
        ".agents/skills/project-lessons/SKILL.md",
        "docs/lessons-learned/INDEX.md",
        "docs/lessons-learned/_template.md",
        "scripts/lessons/select.py",
        "scripts/lessons/check.py",
        "scripts/lessons/promote.py",
    ]
    for rel in required_files:
        if (root / rel).exists():
            report("OK", f"{rel} exists")
        else:
            report("FAIL", f"{rel} is missing")

    index = root / "docs" / "lessons-learned" / "INDEX.md"
    lesson_count = count_index_lessons(index)
    if lesson_count:
        report("OK", f"INDEX.md routes {lesson_count} active lesson(s)")
    elif index.exists():
        report("WARN", "INDEX.md exists but has no active lesson rows")

    selected = state_dir(root) / "selected-lessons.json"
    if selected.exists():
        try:
            json.loads(selected.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report("WARN", f".state/selected-lessons.json is invalid: {exc}")
        else:
            report("OK", ".state/selected-lessons.json is valid JSON")
    elif verbose:
        report("OK", ".state/selected-lessons.json is absent; it will be created by the selector hook")

    reason = requirement_reason(root)
    candidate = state_dir(root) / "lesson-candidate.md"
    if reason:
        report("WARN", f"outstanding lesson requirement: {reason}")
    if candidate.exists():
        report("WARN", ".state/lesson-candidate.md exists; promote or clear it before finalizing")

    events = read_events(root)
    if verbose:
        required_events = sum(1 for event in events if event.get("severity") == "lesson_required")
        report("OK", f"lesson event log has {len(events)} event(s), {required_events} requirement signal(s)")

    print(f"summary: {failures} failure(s), {warnings} warning(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook", action="store_true", help="Run as Codex Stop hook.")
    parser.add_argument("--post-tool-hook", action="store_true", help="Run as Codex PostToolUse hook.")
    parser.add_argument("--require", help="Mark this task as requiring a lesson.")
    parser.add_argument("--clear", action="store_true", help="Clear the current lesson requirement.")
    parser.add_argument("--status", action="store_true", help="Print lesson gate status.")
    parser.add_argument("--doctor", action="store_true", help="Run a lessons-system self-check.")
    parser.add_argument("--verbose", action="store_true", help="Print extra status or doctor details.")
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
        status(root, verbose=args.verbose)
    elif args.doctor:
        return doctor(root, verbose=args.verbose)
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
