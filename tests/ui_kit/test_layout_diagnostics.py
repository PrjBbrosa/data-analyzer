"""Layout diagnostics collect UI facts without blocking the app."""
from __future__ import annotations

import json
import logging
import os

import pytest
from PyQt5.QtWidgets import QApplication, QDialog, QPushButton

from mf4_analyzer.ui_kit.layout_diagnostics import (
    collect_environment_facts,
    collect_widget_layout_facts,
    emit_layout_facts,
    qss_identity,
    reset_environment_emission_for_tests,
)


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_emission():
    reset_environment_emission_for_tests()
    yield
    reset_environment_emission_for_tests()


def test_environment_facts_include_qt_and_qss_not_user_paths(qapp):
    facts = collect_environment_facts()
    assert "qt" in facts
    assert "pyqt" in facts
    assert "screens" in facts
    identity = qss_identity()
    assert identity["qss_sha256"]
    dumped = json.dumps(facts)
    assert "MF4Analyzer" not in dumped
    assert "/Users/" not in dumped or "qss_path" in facts


def test_widget_facts_use_prompt_id_not_body_copy(qapp, qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.setObjectName("probeBox")
    button = QPushButton("保存很长的业务文案 /secret/user/path.mf4", dialog)
    button.setObjectName("saveBtn")
    facts = collect_widget_layout_facts(dialog, prompt_id="unsaved_project")
    assert facts["prompt_id"] == "unsaved_project"
    blob = json.dumps(facts)
    assert "secret/user/path" not in blob
    assert facts["buttons"][0]["label_len"] == len(button.text())


def test_collect_none_widget_is_a_programming_error(qapp):
    with pytest.raises(TypeError):
        collect_widget_layout_facts(None)


def test_emit_serialization_failure_does_not_raise(qapp, caplog):
    class _Boom:
        pass

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        emit_layout_facts({"prompt_id": "x", "bad": _Boom()}, detailed=True)
    assert "serialization failed" in caplog.text


def test_emit_rejects_empty_facts(qapp):
    with pytest.raises(TypeError):
        emit_layout_facts({})
