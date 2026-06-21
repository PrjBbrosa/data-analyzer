"""Bundled HTML help/usage decks + a single open-in-browser entry point.

All help documents live next to this module under ``mf4_analyzer/help/`` and
are shipped as PyInstaller ``datas`` so the same path-resolution works in the
dev tree and in a frozen build. Documents are opened with the system default
browser via ``QDesktopServices.openUrl`` — zero new dependencies, no
QWebEngine / QTextBrowser.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Logical guide name -> HTML filename inside the help directory.
_GUIDE_FILES = {
    'order': 'order-analysis-guide.html',
    'fft': 'fft-guide.html',
    'fft_time': 'ffttime-guide.html',
    'time': 'time-domain-guide.html',
    'manual': 'TraceLab-使用说明.html',
}


def help_dir() -> Path:
    """Absolute path to the bundled help directory (dev + frozen).

    Dev: the directory containing this module (``mf4_analyzer/help/``).
    Frozen (PyInstaller): ``<_MEIPASS>/mf4_analyzer/help`` — the .spec datas
    place the tree there so this resolves to the unpacked copy. Falls back to
    the source-tree location when ``_MEIPASS`` is unset.
    """
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled = Path(meipass) / 'mf4_analyzer' / 'help'
        if bundled.is_dir():
            return bundled
    return Path(__file__).resolve().parent


def guide_path(name: str) -> Path:
    """Resolve a logical guide ``name`` to its on-disk HTML path."""
    filename = _GUIDE_FILES.get(name, _GUIDE_FILES['manual'])
    return help_dir() / filename


def open_guide(name: str) -> bool:
    """Open the guide ``name`` in the system default browser.

    Returns True when the file exists and the open was dispatched, False when
    the file is missing (caller may surface a toast). Never raises for a
    missing file — degrades silently so a broken bundle cannot crash the UI.
    """
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices

    path = guide_path(name)
    if not path.exists():
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
