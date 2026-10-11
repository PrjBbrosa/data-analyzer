"""Bundled HTML help/usage decks + a single open-in-browser entry point.

All help documents live next to this module under ``mf4_analyzer/help/`` and
are shipped as PyInstaller ``datas`` so the same path-resolution works in the
dev tree and in a frozen build. Documents open in the system default browser.
No QWebEngine or QTextBrowser.

On macOS the browser is a different process from the app. A checkout under
``~/Downloads``, ``~/Desktop``, or ``~/Documents`` is readable by Terminal but
not by Chrome or Safari, so a ``file://`` URL there paints a blank page.
Publishing a real copy under the user temp directory gives the browser a path
it is allowed to read. A symlink would still resolve back into the protected
directory.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Logical guide name -> HTML filename inside the help directory.
_GUIDE_FILES = {
    'order': 'order-analysis-guide.html',
    'fft': 'fft-guide.html',
    'fft_time': 'ffttime-guide.html',
    'frf': 'frf-guide.html',
    'time': 'time-domain-guide.html',
    'ultraview': 'ultraview-guide.html',
    'manual': 'TraceLab-使用说明.html',
    'acquisition': 'acquisition-cockpit-guide.html',
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


# stamp -> temp directory that holds one published copy of the help tree.
_PUBLISHED_HELP: dict[str, Path] = {}
_STAMP_DIR = re.compile(r"^[0-9a-f]{16}$")


def _help_file_worth_copying(path: Path) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.suffix != ".pyc"
        and "__pycache__" not in path.parts
    )


def _published_tree_complete(root: Path, dest_root: Path) -> bool:
    if not dest_root.is_dir():
        return False
    for path in root.rglob("*"):
        if not _help_file_worth_copying(path):
            continue
        published = dest_root / path.relative_to(root)
        if published.is_symlink() or not published.is_file():
            return False
    return True


def _remove_older_help_stamps(parent: Path, stamp: str) -> None:
    help_parent = parent / "tracelab-help"
    if not help_parent.is_dir():
        return
    for child in list(help_parent.iterdir()):
        if child.name == stamp or not child.is_dir():
            continue
        if _STAMP_DIR.fullmatch(child.name) is None:
            continue
        try:
            shutil.rmtree(child)
        except OSError:
            # A stale copy still open in a browser should not block the new one.
            continue


def _help_tree_stamp(root: Path) -> str:
    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if not path.is_file() or path.is_symlink():
            continue
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        parts.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def publish_help_for_browser(
    path: Path,
    *,
    root: Path | None = None,
    dest_parent: Path | None = None,
) -> Path:
    """Copy ``path`` and its help siblings to a browser-readable directory.

    ``path`` must live inside ``root`` (the bundled help directory by default).
    The copy preserves relative asset names. Callers on macOS open the copy.
    """
    path = path.resolve()
    root = (root if root is not None else help_dir()).resolve()
    relative = path.relative_to(root)
    stamp = _help_tree_stamp(root)
    parent = dest_parent if dest_parent is not None else Path(tempfile.gettempdir())
    dest_root = _PUBLISHED_HELP.get(stamp)
    if dest_root is None or dest_parent is not None:
        dest_root = parent / "tracelab-help" / stamp
    published = dest_root / relative
    if (
        published.is_symlink()
        or not published.is_file()
        or not _published_tree_complete(root, dest_root)
    ):
        help_parent = parent / "tracelab-help"
        help_parent.mkdir(parents=True, exist_ok=True)
        staging = help_parent / f".{stamp}-{os.getpid()}-tmp"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(
            root,
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            symlinks=False,
        )
        try:
            if dest_root.exists():
                shutil.rmtree(dest_root)
            staging.rename(dest_root)
        except OSError:
            # The destination can already exist if two opens race. Fill it
            # in place instead of failing the GUI thread.
            shutil.copytree(
                staging,
                dest_root,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                symlinks=False,
                dirs_exist_ok=True,
            )
            shutil.rmtree(staging, ignore_errors=True)
        _remove_older_help_stamps(parent, stamp)
    if published.is_symlink() or not published.is_file():
        raise OSError(f"help publish did not create a real file: {published}")
    if dest_parent is None:
        _PUBLISHED_HELP[stamp] = dest_root
    return published


def _open_in_browser(path: Path) -> bool:
    if sys.platform == "darwin":
        try:
            target = publish_help_for_browser(path)
        except (OSError, ValueError):
            return False
        try:
            # Popen returns as soon as /usr/bin/open is spawned. Waiting on
            # subprocess.run would block the GUI thread for the browser.
            subprocess.Popen(
                ["/usr/bin/open", os.fspath(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        return True

    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(path))))


def open_guide(name: str) -> bool:
    """Open the guide ``name`` in the system default browser.

    Returns True when the file exists and the open was dispatched, False when
    the file is missing (caller may surface a toast). Never raises for a
    missing file — degrades silently so a broken bundle cannot crash the UI.
    """
    path = guide_path(name)
    if not path.is_file():
        return False
    return _open_in_browser(path)
