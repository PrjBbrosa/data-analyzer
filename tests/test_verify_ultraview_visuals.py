"""UltraView visual harness: geometry assertions, contact sheet, default output."""
from __future__ import annotations

import ast
from pathlib import Path

from tools.verify_ultraview_visuals import (
    DEFAULT_OUTPUT,
    REQUIRED_SHOTS,
    generate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "verify_ultraview_visuals.py"


def test_default_output_is_gitignored_state_dir():
    assert DEFAULT_OUTPUT.parts[-2:] == (".state", "ultraview-p0")
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".state/" in gitignore


def test_harness_does_not_import_main_window():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "main_window" not in alias.name
                assert alias.name != "mf4_analyzer.ui.main_window"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "main_window" not in node.module
            assert node.module != "mf4_analyzer.ui"


def test_ultraview_visual_harness_geometry_and_contact_sheet(qapp, tmp_path):
    manifest = generate(tmp_path)
    for name in REQUIRED_SHOTS:
        info = manifest["shots"][name]
        path = tmp_path / info["path"]
        assert path.is_file(), name
        assert path.stat().st_size > 100, name
        assert info["width"] >= 10 and info["height"] >= 10
    contact = tmp_path / manifest["contact_sheet"]
    assert contact.is_file()
    assert contact.stat().st_size > 1000
    assert (tmp_path / "manifest.json").is_file()
    statuses = {
        card["status"]
        for card in manifest["geometry"]["four_status_1600"]["cards"]
        if not card.get("empty")
    }
    assert {"fresh", "stale", "missing", "orphaned"} <= statuses
    assert manifest["geometry"]["toolbar_1100"]["overlap_pairs"] == []
    assert manifest["geometry"]["show_flags_1600"]["show_titles"] is False
    assert manifest["geometry"]["presentation_1600"]["library_visible"] is False
