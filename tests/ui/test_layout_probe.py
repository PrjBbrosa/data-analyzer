"""Layout probe stays on synthetic data and out of acquisition_ui."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest
from PyQt5.QtCore import QSettings

from mf4_analyzer.ui.layout_probe import run_layout_probe


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_SRC = REPO_ROOT / "mf4_analyzer" / "ui" / "layout_probe.py"


def test_layout_probe_module_does_not_import_acquisition_ui():
    tree = ast.parse(PROBE_SRC.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = [
        name
        for name in imported
        if name == "mf4_analyzer.acquisition_ui"
        or name.startswith("mf4_analyzer.acquisition_ui.")
    ]
    assert forbidden == []


def test_batch_helper_does_not_rebreak_budget(qapp, qtbot, monkeypatch):
    from PyQt5.QtWidgets import QDialog

    from mf4_analyzer.ui.drawers.batch._geometry import fit_dialog_to_available_screen
    from mf4_analyzer.ui_kit.dialog_geometry import FrameInsets, IntRect, SCREEN_MARGIN

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    qtbot.addWidget(dialog)
    fit_dialog_to_available_screen(dialog, None, 1040, 720, min_w=640, min_h=420)
    assert dialog.width() <= 640 - 2 * SCREEN_MARGIN
    assert dialog.height() <= 360 - 2 * SCREEN_MARGIN


def test_run_layout_probe_writes_json_and_isolates_qsettings(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TRACELAB_LAYOUT_PROBE_DIR", str(tmp_path))
    monkeypatch.delenv("TRACELAB_LAYOUT_PROBE", raising=False)
    code = run_layout_probe(qapp)
    assert code == 0
    summary = tmp_path / "layout-probe.json"
    assert summary.is_file()
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["environment"]["qt"]
    ids = {demo["prompt_id"] for demo in payload["demos"]}
    assert "probe_synthetic_dialog" in ids
    assert "probe_batch_preview_30" in ids
    assert "unsaved_project" in ids
    settings_file = QSettings().fileName()
    assert "MF4Analyzer" not in settings_file
    assert "DataAnalyzer" not in settings_file
