"""Qt-free UltraView domain core.

Wave 5 Task 5.4 adds :mod:`mf4_analyzer.ultraview_core.serialization`
(schema legalize/migration, opaque passthrough, payload codec). Family 4
added :mod:`mf4_analyzer.ultraview_core.presentation`. Family 2 added
:mod:`mf4_analyzer.ultraview_core.author_ops`. Family 1 added
:mod:`mf4_analyzer.ultraview_core.board_ops`. Task 5.2 added
:mod:`mf4_analyzer.ultraview_core.model`. Task 5.1 added
:mod:`mf4_analyzer.ultraview_core.grid_geometry`.

This package must not import Qt, ``mf4_analyzer.ui``, ``chart_stack``,
MainWindow, compositor, or Card Fit.
"""
