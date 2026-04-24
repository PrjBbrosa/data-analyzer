"""Per-file color palette constants.

Lives at the package root because both the io layer
(`FileData.get_color_palette`) and the ui layer (canvases/widgets)
need it. Keeping it under `ui/` would create an io -> ui import,
violating the dependency rules in the design spec.
"""

FILE_PALETTES = [
    ['#2563eb', '#059669', '#dc2626', '#ea580c', '#0891b2', '#7c3aed', '#be123c', '#64748b'],
    ['#0f9f8f', '#1d4ed8', '#d97706', '#9333ea', '#0284c7', '#16a34a', '#e11d48', '#475569'],
    ['#3b82f6', '#10b981', '#ef4444', '#f97316', '#06b6d4', '#8b5cf6', '#f43f5e', '#334155'],
    ['#1e40af', '#047857', '#b91c1c', '#c2410c', '#0e7490', '#6d28d9', '#9f1239', '#475569'],
    ['#60a5fa', '#34d399', '#f87171', '#fb923c', '#22d3ee', '#a78bfa', '#fb7185', '#64748b'],
]

__all__ = ['FILE_PALETTES']
