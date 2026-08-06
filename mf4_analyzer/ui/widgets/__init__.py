"""Reusable widgets: StatisticsPanel, MultiFileChannelWidget, Toast.

This package is a thin compatibility facade: every name below used to live in
this file, and consumers across ``ui/``, ``scripts/``, ``tools/`` and the test
suite still import them from ``mf4_analyzer.ui.widgets``.  The Qt symbols and
``hints`` are re-exported because tests monkeypatch them through this namespace
(patching an attribute *on* the imported class/module object, which is global).

``icon_device_pixel_ratio`` is the exception: ``_swatch_pixmap`` reads it from
``._swatches`` globals, so patching it here does NOT affect rendering -- patch
``mf4_analyzer.ui.widgets._swatches.icon_device_pixel_ratio`` instead.
"""
from PyQt5.QtWidgets import QMenu, QMessageBox  # noqa: F401

from ...ui_kit.icons import icon_device_pixel_ratio  # noqa: F401
from .. import hints  # noqa: F401
from ._swatches import _fmt_rate, _swatch_icon, _swatch_pixmap  # noqa: F401
from .channel_tree import (  # noqa: F401
    INTERNAL_FILE_FIDS_MIME,
    MultiFileChannelWidget,
)
from .stats import StatisticsPanel, StatsStrip  # noqa: F401
from .toast import Toast  # noqa: F401
