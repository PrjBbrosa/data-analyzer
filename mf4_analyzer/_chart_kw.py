"""Chart-layout constants shared across layers.

Lives at the package root because both the ui layer
(`ui/canvases.py`, `ui/main_window.py`) and a non-ui layer
(`batch.py`, which writes matplotlib PNGs without involving Qt
canvases) consume the same compactness constants. Keeping them under
`ui/` would force `batch.py` to import "up" into `ui`, violating the
package's dependency rules. See
``docs/lessons-learned/refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md``.

CHART_TIGHT_LAYOUT_KW
    Tight margins for non-spectrogram canvases. Default tight_layout
    pad is 1.08x font size which is loose for the Chinese fonts we
    use; pinning pad/h_pad/w_pad gives a denser layout.

SPECTROGRAM_SUBPLOT_ADJUST
    Explicit subplot box for SpectrogramCanvas. Must be applied via
    fig.subplots_adjust AFTER fig.colorbar(...) so colorbar geometry
    is already in place.

AXIS_HIT_MARGIN_PX
    Pixel margin around an axes for hit-detection of the axis-edit
    affordance (double-click / hover cursor swap).
"""

CHART_TIGHT_LAYOUT_KW = dict(pad=0.4, h_pad=0.6, w_pad=0.4)
SPECTROGRAM_SUBPLOT_ADJUST = dict(
    left=0.07, right=0.93, top=0.97, bottom=0.09,
)
AXIS_HIT_MARGIN_PX = 45

__all__ = [
    'CHART_TIGHT_LAYOUT_KW',
    'SPECTROGRAM_SUBPLOT_ADJUST',
    'AXIS_HIT_MARGIN_PX',
]
