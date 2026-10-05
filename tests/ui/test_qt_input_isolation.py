"""A failed mouse test must not leak a pressed button into the next item."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

_CHILD = "TRACELAB_MOUSE_ISOLATION_CHILD"


@pytest.mark.skipif(os.environ.get(_CHILD) != "1", reason="bounded child only")
def test_mouse_child_leaves_button_pressed(qapp, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QWidget

    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.mousePress(widget, Qt.LeftButton)
    assert qapp.mouseButtons() & Qt.LeftButton
    pytest.fail("intentional failure before mouse release")


@pytest.mark.skipif(os.environ.get(_CHILD) != "1", reason="bounded child only")
def test_mouse_child_next_item_starts_released(qapp):
    from PyQt5.QtCore import Qt

    assert qapp.mouseButtons() == Qt.NoButton


def test_failed_mouse_test_preserves_failure_and_releases_input():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve()),
         "-k", "mouse_child", "--tb=short"],
        cwd=root,
        env={**os.environ, _CHILD: "1", "QT_QPA_PLATFORM": "offscreen",
             "PYTHONPATH": str(root), "TMPDIR": "/tmp"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "intentional failure before mouse release" in result.stdout
    assert "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr
