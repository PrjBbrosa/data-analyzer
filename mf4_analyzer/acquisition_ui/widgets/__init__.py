"""Cockpit Qt widgets package.

Stage 4 contents:

- :mod:`live_downsampler` — pure-Python min/max bin reducer for sparklines.
- :mod:`health_strip` — five-chip strip bound to ``HealthSnapshot``.
- :mod:`left_pane` — A2L measurement search/filter/raster panel.
- :mod:`live_cards` — per-signal sparkline + stats cards.
- :mod:`right_panel` — disconnected / idle / recording variants.

Everything except :mod:`live_downsampler` is Qt-bound; the downsampler
stays pure-Python so the sparkline contract can be pinned by a unit
test that doesn't require ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations
