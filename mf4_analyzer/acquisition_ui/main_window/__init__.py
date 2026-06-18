"""main_window package: re-exports CockpitMainWindow from window.py.

This ``__init__.py`` is the monkeypatch anchor for all names that tests
patch via ``monkeypatch.setattr('mf4_analyzer.acquisition_ui.main_window.<Symbol>', ...)``.

The anchored names are:

  - ``QMessageBox``  — patched in ``test_dropped_frame_prompt.py:102``
    and ``test_pick_a2l_warnings.py:112`` as
    ``mf4_analyzer.acquisition_ui.main_window.QMessageBox.open``.

Methods in the mixin files that call ``QMessageBox(...)`` at execution
time use a ``sys.modules.get('mf4_analyzer.acquisition_ui.main_window')``
runtime lookup so patches applied here are visible at call time (not
captured at import time).  See lesson:
``docs/lessons-learned/refactor/2026-06-18-monkeypatch-anchor-survives-module-to-package.md``
"""

from PyQt5.QtWidgets import QMessageBox  # monkeypatch anchor

from .window import CockpitMainWindow, _PlaceholderReviewModal
from ._defs import (  # re-export module-level constants (tests import these from old path)
    DBC_DISABLED_TOOLTIP,
    REPLAY_TAB_TITLE,
    HISTORY_TAB_TITLE,
    DROPPED_FRAMES_PROMPT_TITLE,
    DROPPED_FRAMES_PROMPT_TEXT,
    MODE_SEGMENTS,
)

__all__ = [
    "CockpitMainWindow",
    "_PlaceholderReviewModal",
    "DBC_DISABLED_TOOLTIP",
    "REPLAY_TAB_TITLE",
    "HISTORY_TAB_TITLE",
    "DROPPED_FRAMES_PROMPT_TITLE",
    "DROPPED_FRAMES_PROMPT_TEXT",
    "MODE_SEGMENTS",
]
