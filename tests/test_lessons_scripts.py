from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_lesson_gate_unblocks_after_promotion_or_clear(tmp_path):
    check = _load_script("scripts/lessons/check.py")

    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    check.mark_required(tmp_path, "publish flow was too heavy")
    assert check.requirement_reason(tmp_path) == "publish flow was too heavy"

    check.append_event(
        tmp_path,
        {
            "kind": "lesson_promoted",
            "severity": "info",
            "path": "docs/lessons-learned/codex-publish-flow-lightweight.md",
        },
    )
    (tmp_path / ".state" / "lesson-required").unlink()
    assert check.requirement_reason(tmp_path) is None

    check.mark_required(tmp_path, "another requirement")
    assert check.requirement_reason(tmp_path) == "another requirement"
    check.clear(tmp_path)
    assert check.requirement_reason(tmp_path) is None


def test_post_tool_hook_requires_only_explicit_lesson_marker(tmp_path):
    check = _load_script("scripts/lessons/check.py")

    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    check.post_tool_hook(
        tmp_path,
        {
            "tool_name": "Bash",
            "tool_response": 'FAILURE_PATTERNS = r"(Traceback|LESSON_REQUIRED)"',
        },
    )
    assert check.requirement_reason(tmp_path) is None

    check.post_tool_hook(
        tmp_path,
        {
            "tool_name": "Bash",
            "tool_response": "lesson_required: False",
        },
    )
    assert check.requirement_reason(tmp_path) is None

    check.post_tool_hook(
        tmp_path,
        {
            "tool_name": "Bash",
            "tool_response": "LESSON_REQUIRED: durable publish-flow correction",
        },
    )
    assert check.requirement_reason(tmp_path) == "LESSON_REQUIRED: durable publish-flow correction"


def test_promote_updates_index_inside_active_lessons_table(tmp_path):
    promote = _load_script("scripts/lessons/promote.py")
    index = tmp_path / "INDEX.md"
    index.write_text(
        "# Lessons Learned Index\n\n"
        "## Active Lessons\n\n"
        "| Lesson | Trigger | Checks |\n"
        "| --- | --- | --- |\n"
        "| [Existing](existing.md) | Existing trigger. | Existing check |\n\n"
        "## Selection Rules\n\n"
        "- Keep the table compact.\n",
        encoding="utf-8",
    )

    promote.update_index(
        index,
        "codex-publish-flow-lightweight.md",
        "Codex Publish Flow Lightweight",
        "Publish already-local changes.",
    )

    text = index.read_text(encoding="utf-8")
    row = "| [Codex Publish Flow Lightweight](codex-publish-flow-lightweight.md) | Publish already-local changes. | See lesson |"
    assert row in text
    assert text.index(row) < text.index("## Selection Rules")
