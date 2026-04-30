#!/usr/bin/env python3
"""Promote .state/lesson-candidate.md into docs/lessons-learned."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path


ROOT_MARKERS = (".git", "AGENTS.md", "pyproject.toml", "package.json")


def find_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return current


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = text.strip("-")
    return text[:80] or dt.datetime.now().strftime("lesson-%Y%m%d-%H%M%S")


def parse_id(text: str) -> str | None:
    match = re.search(r"^id:\s*([^\n]+)$", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().strip("'\"")
    if not value or value == "replace-with-stable-id":
        return None
    return value


def title_from(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if title and title != "Replace With Lesson Title":
                return title
    return "Untitled Lesson"


def trigger_from(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("trigger:"):
            return line.split(":", 1)[1].strip() or "See lesson"
    return "See lesson"


def ensure_id(text: str, lesson_id: str) -> str:
    if re.search(r"^id:\s*", text, re.MULTILINE):
        return re.sub(r"^id:\s*.*$", f"id: {lesson_id}", text, count=1, flags=re.MULTILINE)
    if text.startswith("---\n"):
        return text.replace("---\n", f"---\nid: {lesson_id}\n", 1)
    return f"---\nid: {lesson_id}\nstatus: active\n---\n\n{text}"


def update_index(index: Path, lesson_path: str, title: str, trigger: str) -> None:
    if not index.exists():
        index.write_text("# Lessons Learned Index\n\n## Active Lessons\n\n| Lesson | Trigger | Checks |\n| --- | --- | --- |\n", encoding="utf-8")
    text = index.read_text(encoding="utf-8")
    if lesson_path in text:
        return
    text = text.replace("| _none yet_ | Add project-specific lessons with `scripts/lessons/promote.py`. | |\n", "")
    row = f"| [{title}]({lesson_path}) | {trigger} | See lesson |\n"
    selection = "\n## Selection Rules"
    if "| Lesson | Trigger | Checks |" in text and selection in text:
        before, after = text.split(selection, 1)
        text = before.rstrip() + "\n" + row + selection + after
    elif "| Lesson | Trigger | Checks |" in text:
        text = text.rstrip() + "\n" + row
    else:
        text = text.rstrip() + "\n\n## Active Lessons\n\n| Lesson | Trigger | Checks |\n| --- | --- | --- |\n" + row
    index.write_text(text, encoding="utf-8")


def append_event(root: Path, event: dict[str, str]) -> None:
    state = root / ".state"
    state.mkdir(exist_ok=True)
    path = state / "lesson-events.jsonl"
    event = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default=".state/lesson-candidate.md")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = find_root(Path(args.cwd))
    candidate = root / args.candidate
    if not candidate.exists():
        raise SystemExit(f"Missing candidate: {candidate}")

    text = candidate.read_text(encoding="utf-8")
    title = title_from(text)
    lesson_id = parse_id(text) or slugify(title)
    text = ensure_id(text, lesson_id)

    lessons_dir = root / "docs" / "lessons-learned"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    target = lessons_dir / f"{lesson_id}.md"
    if target.exists() and not args.force:
        raise SystemExit(f"Lesson already exists: {target}. Use --force to replace.")

    target.write_text(text, encoding="utf-8")
    update_index(
        lessons_dir / "INDEX.md",
        f"{lesson_id}.md",
        title,
        trigger_from(text),
    )

    required = root / ".state" / "lesson-required"
    if required.exists():
        required.unlink()
    candidate.unlink()

    append_event(root, {"kind": "lesson_promoted", "severity": "info", "path": str(target.relative_to(root))})
    print(f"Promoted lesson: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
