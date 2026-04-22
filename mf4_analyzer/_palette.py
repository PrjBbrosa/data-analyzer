"""Per-file color palette constants.

Lives at the package root because both the io layer
(`FileData.get_color_palette`) and the ui layer (canvases/widgets)
need it. Keeping it under `ui/` would create an io -> ui import,
violating the dependency rules in the design spec.
"""

FILE_PALETTES = [
    ['#1f77b4', '#4a9fd4', '#7ec7f2', '#b0e0ff'],
    ['#ff7f0e', '#ffaa4d', '#ffc87c', '#ffe5b4'],
    ['#2ca02c', '#5cd35c', '#8de68d', '#bef9be'],
    ['#d62728', '#e85a5a', '#f08c8c', '#f8bebe'],
    ['#9467bd', '#b591d1', '#d5b9e5', '#f0e0f9'],
]

__all__ = ['FILE_PALETTES']
