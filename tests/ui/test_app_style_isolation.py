"""Regression for the root QApplication appearance-isolation fixture.

This test writes a temporary child test outside ``tests/ui`` and explicitly
loads the real ``tests/conftest.py`` fixture as a plugin.  Therefore the first
child item begins with no QApplication, creates one in its body, and the
second item observes the state only after the first item's full teardown.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    # ``tests`` is intentionally not a regular package.  Import the actual
    # root test fixture by the unique module name ``conftest`` from this path.
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(_REPO_ROOT / "tests"), str(_REPO_ROOT), env.get("PYTHONPATH"))
        if part
    )
    env["TMPDIR"] = "/tmp"
    env["MPLCONFIGDIR"] = "/tmp"
    return env


def _write_child(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            from PyQt5.QtGui import QColor, QFont, QPalette
            from PyQt5.QtWidgets import QApplication, QStyleFactory


            APP = None
            ORIGINAL = None


            def test_style_child_creates_and_mutates_application():
                global APP, ORIGINAL
                APP = QApplication.instance() or QApplication([])
                ORIGINAL = (
                    APP.styleSheet(),
                    APP.style().objectName(),
                    QPalette(APP.palette()),
                    QFont(APP.font()),
                )
                alternate = next(
                    key for key in QStyleFactory.keys()
                    if key.lower() != ORIGINAL[1].lower()
                )
                APP.setStyle(alternate)
                palette = QPalette(APP.palette())
                palette.setColor(QPalette.Window, QColor("#325a88"))
                APP.setPalette(palette)
                font = QFont(APP.font())
                font.setPointSize(max(1, font.pointSize() + 2))
                APP.setFont(font)
                APP.setStyleSheet("QWidget { background: #325a88; }")
                assert APP.styleSheet() != ORIGINAL[0]
                assert APP.style().objectName() != ORIGINAL[1]
                assert APP.palette() != ORIGINAL[2]
                assert APP.font() != ORIGINAL[3]


            def test_style_child_observes_prior_item_after_full_teardown():
                assert APP is not None and ORIGINAL is not None
                sheet, style_name, palette, font = ORIGINAL
                assert APP.styleSheet() == sheet
                assert APP.style().objectName() == style_name
                assert APP.palette() == palette
                assert APP.font() == font
            """
        ),
        encoding="utf-8",
    )


def test_root_style_fixture_restores_app_created_during_prior_item(tmp_path):
    child = tmp_path / "test_style_child.py"
    _write_child(child)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "conftest",
            str(child),
        ],
        cwd=tmp_path,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout, result.stdout


def _write_neutral_then_create_child(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            import sys


            APP = None
            ORIGINAL = None


            def test_neutral_item_does_not_import_qt():
                assert "PyQt5.QtWidgets" not in sys.modules


            def test_body_creates_and_mutates_application():
                global APP, ORIGINAL
                from PyQt5.QtGui import QColor, QFont, QPalette
                from PyQt5.QtWidgets import QApplication, QStyleFactory

                APP = QApplication.instance() or QApplication([])
                ORIGINAL = (
                    APP.styleSheet(),
                    APP.style().objectName(),
                    QPalette(APP.palette()),
                    QFont(APP.font()),
                )
                alternate = next(
                    key for key in QStyleFactory.keys()
                    if key.lower() != ORIGINAL[1].lower()
                )
                APP.setStyle(alternate)
                palette = QPalette(APP.palette())
                palette.setColor(QPalette.Window, QColor("#325a88"))
                APP.setPalette(palette)
                font = QFont(APP.font())
                font.setPointSize(max(1, font.pointSize() + 2))
                APP.setFont(font)
                APP.setStyleSheet("QWidget { background: #325a88; }")
                assert APP.styleSheet() != ORIGINAL[0]
                assert APP.style().objectName() != ORIGINAL[1]


            def test_later_item_sees_restored_style():
                from PyQt5.QtWidgets import QApplication

                assert APP is not None and ORIGINAL is not None
                sheet, style_name, palette, font = ORIGINAL
                app = QApplication.instance()
                assert app is APP
                assert app.styleSheet() == sheet
                assert app.style().objectName() == style_name
                assert app.palette() == palette
                assert app.font() == font
            """
        ),
        encoding="utf-8",
    )


def test_root_style_fixture_does_not_import_qt_until_body_creates_app(tmp_path):
    """Neutral items must not pay a Qt import; a later body-created app still restores."""
    child = tmp_path / "test_style_lazy_child.py"
    _write_neutral_then_create_child(child)
    env = _child_env()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "conftest",
            str(child),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout, result.stdout
