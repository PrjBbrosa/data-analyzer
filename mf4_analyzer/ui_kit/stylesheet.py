"""Apply the shared ``style.qss`` template to a ``QApplication``.

This module is the only path Analyzer (``mf4_analyzer.app``) and
Cockpit (``mf4_analyzer.acquisition_ui``) use to install the shared
stylesheet. Keeping it in ``ui_kit`` ensures the two upper packages
do not need to know about icon-cache plumbing or the QSS file's
location on disk.

Extracted from ``mf4_analyzer.app._load_stylesheet`` during Stage 1 of
``docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md``.
"""
from pathlib import Path

from .combo_popup_shell import install_combo_popup_shell
from .control_style import CONTROL_QSS_TOKENS
from .icons import ensure_icon_cache, render_qss_template
from .message_box_buttons import install_message_box_button_roles
from .ultraview_style import ULTRAVIEW_QSS_TOKENS


def load_stylesheet(app):
    """Load ``style.qss`` with subcontrol-arrow icon-cache substitution.

    ``style.qss`` is a template containing ``{{ICON_*}}`` placeholders
    for QComboBox / QSpinBox arrow glyphs. :func:`ensure_icon_cache`
    renders the PNGs into ``~/.mf4-analyzer-cache/icons/`` on first run
    (or after a qtawesome / palette change) and returns a
    placeholder→path map. :func:`render_qss_template` substitutes them;
    placeholder-free QSS for older / external ``setStyleSheet`` callers
    continues to load fine since Qt silently drops unresolved
    ``image: url(...)`` rules.

    Must run AFTER ``QApplication`` construction — qtawesome lazy-loads
    its icon font and the device-pixel-ratio that drives PNG resolution
    is read from the ``QApplication`` primary screen. The icon cache
    helper raises ``RuntimeError`` if invoked pre-app.
    """
    qss = Path(__file__).resolve().parent / "style.qss"
    if not qss.exists():
        return
    template = qss.read_text(encoding="utf-8")
    try:
        icon_paths = ensure_icon_cache()
        stylesheet = render_qss_template(
            template,
            {**CONTROL_QSS_TOKENS, **ULTRAVIEW_QSS_TOKENS, **icon_paths},
        )
    except Exception as exc:
        # Defensive: if qtawesome import or icon rendering fails (e.g.
        # an unusual install), fall back to the raw template. Spinbox
        # arrows will be invisible (the original bug) but the rest of
        # the app remains styled. Log so it surfaces in the console.
        print(
            f"[mf4_analyzer.ui_kit.stylesheet] icon cache generation failed "
            f"({exc!r}); loading stylesheet without subcontrol arrow glyphs.",
        )
        # Control tokens do not depend on icon rendering, so retain the shared
        # action-control contract even when the optional icon cache is absent.
        stylesheet = render_qss_template(
            template, {**CONTROL_QSS_TOKENS, **ULTRAVIEW_QSS_TOKENS}
        )
    app.setStyleSheet(stylesheet)
    # The QSS above rounds the inner QComboBox list, but the popup's
    # top-level window stays a square, natively shadowed rectangle that
    # leaks behind the rounded corners. Install the shared event filter
    # that gives every combo dropdown — present and future — the
    # translucent rounded shell, so no call site has to remember to.
    install_combo_popup_shell(app)
    # Static QMessageBox helpers build transient boxes; tag their buttons
    # centrally so QSS can style Yes/confirm differently from No/cancel.
    install_message_box_button_roles(app)
