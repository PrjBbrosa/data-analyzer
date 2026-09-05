"""E3 follow-up: acquisition_ui QMessageBox sites must fit button text.

The analyzer package already routed long Chinese confirm labels through
``fit_message_box_buttons_to_text`` (lesson ``codex-qmessagebox-qss-content-width``).
Cockpit dialogs were a whole-package miss — F6 closes it.
"""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.review_modal import ReviewModal
from mf4_analyzer.ui_kit.message_box_buttons import fit_message_box_buttons_to_text

from tests.acquisition_ui.test_dropped_frame_prompt import (
    _arm_dropped_prompt,
    _walk_to_recording,
)
from tests.acquisition_ui.test_review_handoff import _finalize_and_make_context

_PACKAGE = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "acquisition_ui"
_CTOR_NAMES = {"QMessageBox", "_QMessageBox"}


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_every_message_box_constructor_fits_buttons():
    offenders: list[str] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            constructs = False
            fits = False
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                name = _call_name(child)
                if name in _CTOR_NAMES:
                    constructs = True
                if name == "fit_message_box_buttons_to_text":
                    fits = True
            if constructs and not fits:
                rel = path.relative_to(_PACKAGE.parents[1]).as_posix()
                offenders.append(f"{rel}:{node.name}")
    assert offenders == [], (
        "acquisition_ui QMessageBox constructors must call "
        f"fit_message_box_buttons_to_text: {offenders}"
    )


def test_discard_confirm_fits_delete_button(qtbot, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    qtbot.addWidget(modal)
    modal.do_discard()
    box = modal._discard_confirm_box
    assert box is not None
    labels = {btn.text(): btn for btn in box.buttons()}
    assert "确认删除" in labels
    delete = labels["确认删除"]
    text_width = delete.fontMetrics().horizontalAdvance(delete.text())
    assert delete.minimumWidth() >= text_width + 8 + 20 + 2
    assert "min-width:" not in (delete.styleSheet() or "")
    box.done(0)


def test_dropped_frames_prompt_fits_action_buttons(qapp):
    window = CockpitMainWindow()
    try:
        _walk_to_recording(window)
        _arm_dropped_prompt(window)
        prompt = window._dropped_prompt
        assert prompt is not None
        for btn in prompt.buttons():
            text_width = btn.fontMetrics().horizontalAdvance(btn.text())
            assert btn.minimumWidth() >= text_width + 8 + 20 + 2, btn.text()
            assert "min-width:" not in (btn.styleSheet() or ""), btn.text()
        prompt.done(0)
        qapp.processEvents()
    finally:
        window.close()


def test_fit_helper_expands_stop_and_review_label(qapp):
    box = QMessageBox()
    try:
        stop = box.addButton("停止并复盘", QMessageBox.DestructiveRole)
        box.addButton("继续录制", QMessageBox.AcceptRole)
        fit_message_box_buttons_to_text(box)
        assert "min-width:" not in (stop.styleSheet() or "")
        text_width = stop.fontMetrics().horizontalAdvance(stop.text())
        assert stop.minimumWidth() >= text_width + 8 + 20 + 2
    finally:
        box.deleteLater()
