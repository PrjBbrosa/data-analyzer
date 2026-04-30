#!/usr/bin/env python3
"""Select a small set of relevant project lessons for a Codex turn."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_MARKERS = (".git", "AGENTS.md", "pyproject.toml", "package.json")
SKIP_FILES = {"INDEX.md", "LESSONS.md", "README.md", "_template.md"}


def find_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return current


def git_files(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.append(path)
    return files


def parse_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [
        item.strip().strip("'\"")
        for item in raw.split(",")
        if item.strip().strip("'\"")
    ]


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = parse_list(value)
        else:
            data[key] = value.strip("'\"")
    return data


def title_from(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def lesson_records(root: Path) -> list[dict[str, Any]]:
    lessons_dir = root / "docs" / "lessons-learned"
    if not lessons_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(lessons_dir.glob("*.md")):
        if path.name in SKIP_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        status = str(meta.get("status", "active")).lower()
        if status not in {"active", "always"}:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "id": meta.get("id") or path.stem,
                "title": title_from(text, path.stem),
                "keywords": [str(x).lower() for x in meta.get("keywords", [])],
                "paths": [str(x) for x in meta.get("paths", [])],
                "status": status,
            }
        )
    return records


def score_record(record: dict[str, Any], prompt: str, changed: list[str]) -> int:
    prompt_l = prompt.lower()
    changed_l = [p.lower() for p in changed]
    score = 0

    if record["status"] == "always":
        score += 100

    for token in [record["id"], record["title"]]:
        token_l = str(token).lower()
        if token_l and token_l in prompt_l:
            score += 15

    for keyword in record["keywords"]:
        if keyword and keyword in prompt_l:
            score += 10
        if keyword and any(keyword in path for path in changed_l):
            score += 6

    for pattern in record["paths"]:
        if any(fnmatch.fnmatch(path, pattern) for path in changed):
            score += 12
        if pattern.strip("*").strip("/") and pattern.strip("*").strip("/").lower() in prompt_l:
            score += 4

    return score


def select(root: Path, prompt: str, limit: int) -> list[dict[str, Any]]:
    changed = git_files(root)
    scored = []
    for record in lesson_records(root):
        score = score_record(record, prompt, changed)
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["path"]))
    return [record for _, record in scored[:limit]]


def write_state(root: Path, selected: list[dict[str, Any]]) -> None:
    state = root / ".state"
    state.mkdir(exist_ok=True)
    (state / "selected-lessons.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def hook_output(selected: list[dict[str, Any]]) -> None:
    if not selected:
        return
    lines = ["Codex selected these project lessons for this turn. Read only these unless the user asks for a full lessons audit:"]
    for item in selected:
        lines.append(f"- {item['path']}: {item['title']}")
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(lines),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook", action="store_true", help="Read Codex hook JSON from stdin.")
    parser.add_argument("--prompt", default="", help="Prompt text for manual selection.")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--max", type=int, default=5)
    args = parser.parse_args()

    hook_data: dict[str, Any] = {}
    if args.hook:
        raw = sys.stdin.read().strip()
        hook_data = json.loads(raw) if raw else {}

    cwd = Path(hook_data.get("cwd") or args.cwd)
    root = find_root(cwd)
    prompt = str(hook_data.get("prompt") or args.prompt or "")
    selected = select(root, prompt, args.max)
    write_state(root, selected)

    if args.hook:
        hook_output(selected)
    else:
        for item in selected:
            print(f"{item['path']}\t{item['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
