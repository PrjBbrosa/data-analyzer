"""Rendered application stylesheet must parse — whole-sheet death guard.

One malformed declaration (e.g. an unquoted ``qproperty-alignment: A | B``)
makes Qt drop the ENTIRE application stylesheet: every widget silently falls
back to platform-default chrome (grey fills gone, text colors gone, default
rounded buttons). Unit suites never catch it because Qt parses the app sheet
lazily — only when a live widget gets polished — and most tests style widgets
directly. This guard renders ``style.qss`` exactly like
``ui_kit.stylesheet.load_stylesheet`` and forces an eager parse against a real
widget. Red here means a syntax error in the template or a token, not a
styling decision.
"""
from __future__ import annotations

import re
from pathlib import Path

from PyQt5.QtCore import qInstallMessageHandler
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui_kit.control_style import CONTROL_QSS_TOKENS
from mf4_analyzer.ui_kit.icons import render_qss_template

_QSS_PATH = (
    Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"
)


def _rendered_sheet() -> str:
    """Render the template the way load_stylesheet does.

    Icon placeholders get a dummy path — ``url(...)`` with a missing file
    parses fine; what must never survive rendering is a bare ``{{...}}``.
    """
    template = _QSS_PATH.read_text(encoding="utf-8")
    placeholders = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", template))
    dummy_icons = {
        name: "/nonexistent/guard-dummy.png"
        for name in placeholders
        if name not in CONTROL_QSS_TOKENS
    }
    return render_qss_template(template, {**CONTROL_QSS_TOKENS, **dummy_icons})


def test_rendered_stylesheet_has_no_leftover_placeholders():
    rendered = _rendered_sheet()
    assert "{{" not in rendered and "}}" not in rendered, (
        "unresolved {{TOKEN}} left in rendered style.qss — it would fail the "
        "whole application stylesheet parse"
    )


def test_rendered_stylesheet_parses_with_a_live_widget(qapp):
    messages: list[str] = []
    qInstallMessageHandler(lambda _mode, _ctx, text: messages.append(text))
    old_sheet = qapp.styleSheet()
    probe = QWidget()
    try:
        probe.show()  # a polished widget forces the otherwise-lazy parse
        qapp.setStyleSheet(_rendered_sheet())
        qapp.processEvents()
        parse_errors = [m for m in messages if "parse" in m.lower()]
        assert parse_errors == [], (
            "application stylesheet failed to parse — every widget would "
            f"fall back to platform defaults: {parse_errors}"
        )
    finally:
        qInstallMessageHandler(None)
        qapp.setStyleSheet(old_sheet)
        probe.deleteLater()
        qapp.processEvents()
