"""Qt-free UltraView domain core.

Layout:

* :mod:`mf4_analyzer.ultraview_core.model` — identity, Board/Workspace,
  author DTOs, and stable constants
* :mod:`mf4_analyzer.ultraview_core.grid_geometry` — ``GridMetrics``,
  rect↔pixel mapping, overlap/containment primitives
* :mod:`mf4_analyzer.ultraview_core.board_ops` — Board/workspace CRUD and
  placement mutators
* :mod:`mf4_analyzer.ultraview_core.author_ops` — live author mutators and
  Board-edit apply
* :mod:`mf4_analyzer.ultraview_core.presentation` — status, filter, and
  axis facts
* :mod:`mf4_analyzer.ultraview_core.serialization` — schema legalize,
  migration, opaque passthrough, and the Board-payload hasher

New domain code imports these modules directly. ``ui.ultraview_state`` is
the compatibility re-export façade. This package must not import Qt,
``mf4_analyzer.ui``, ``chart_stack``, MainWindow, compositor, or Card Fit.
"""
