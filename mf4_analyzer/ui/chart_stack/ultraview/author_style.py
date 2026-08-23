"""Qt-free visual tokens for UltraView authoring objects.

The persistent Board schema stores palette *names*, never platform-specific
colour strings or installed font names.  Screen widgets and the PNG compositor
must both resolve those names through this module so a saved sticky, stroke, or
text box has the same semantic appearance everywhere.  Keeping the contract
Qt-free also lets state and export-adjacent tests run without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, TypeAlias


RGB: TypeAlias = tuple[int, int, int]
RGBA: TypeAlias = tuple[int, int, int, int]
Theme: TypeAlias = Literal["light", "dark"]

LIGHT_THEME: Final = "light"
DARK_THEME: Final = "dark"
DEFAULT_THEME: Final[Theme] = LIGHT_THEME

INK_TOKEN: Final = "ink"
TRANSPARENT_TOKEN: Final = "transparent"
DEFAULT_STICKY_PALETTE: Final = "yellow"
DEFAULT_INK_PALETTE: Final = INK_TOKEN
DEFAULT_FILL_PALETTE: Final = "yellow"
HIGHLIGHTER_ALPHA: Final = 89  # round(255 × 0.35); the persisted contract is 35%.
SWATCH_ROLES: Final[tuple[str, ...]] = ("sticky", "ink", "fill", "stroke", "text")
SWATCH_ROLE_STICKY: Final = "sticky"
SWATCH_ROLE_INK: Final = "ink"
SWATCH_ROLE_FILL: Final = "fill"
SWATCH_ROLE_STROKE: Final = "stroke"
SWATCH_ROLE_TEXT: Final = "text"
TRANSPARENT_SWATCH_RGB: Final[RGB] = (255, 255, 255)
TRANSPARENT_SWATCH_BORDER: Final[RGB] = (32, 48, 56)
TRANSPARENT_SWATCH_HATCH: Final[RGB] = (220, 38, 38)

# Ordered exactly as the 4×4 Sticky popover.  The two yellow/lime neighbours
# intentionally remain separate tokens: a Board stores the author's choice,
# not a nearest-colour approximation.
STICKY_PALETTE_TOKENS: Final[tuple[str, ...]] = (
    "yellow",
    "gold",
    "orange",
    "red",
    "pink",
    "magenta",
    "periwinkle",
    "purple",
    "cyan",
    "blue",
    "teal",
    "green",
    "lime",
    "chartreuse",
    "gray",
    "black",
)

# (fill, border, foreground), RGB only.  Light variants use Titanium's dark
# ink; dark variants use near-white ink.  Values are deliberately explicit so
# PNG output does not depend on a QPalette or a machine colour profile.
_STICKY_LIGHT: Final[dict[str, tuple[RGB, RGB, RGB]]] = {
    "yellow": ((255, 244, 153), (203, 157, 0), (24, 48, 57)),
    "gold": ((255, 228, 92), (204, 151, 0), (24, 48, 57)),
    "orange": ((255, 180, 110), (206, 107, 34), (24, 48, 57)),
    "red": ((255, 151, 158), (202, 72, 83), (24, 48, 57)),
    "pink": ((248, 194, 231), (190, 90, 151), (24, 48, 57)),
    "magenta": ((239, 158, 225), (180, 67, 165), (24, 48, 57)),
    "periwinkle": ((169, 194, 244), (81, 111, 199), (24, 48, 57)),
    "purple": ((189, 169, 246), (121, 85, 199), (24, 48, 57)),
    "cyan": ((138, 221, 242), (0, 140, 174), (24, 48, 57)),
    "blue": ((135, 182, 243), (56, 113, 207), (24, 48, 57)),
    "teal": ((114, 220, 208), (13, 143, 127), (24, 48, 57)),
    "green": ((103, 220, 131), (35, 151, 75), (24, 48, 57)),
    "lime": ((204, 240, 145), (105, 151, 34), (24, 48, 57)),
    "chartreuse": ((185, 236, 96), (110, 158, 20), (24, 48, 57)),
    "gray": ((239, 241, 243), (131, 140, 146), (24, 48, 57)),
    "black": ((36, 38, 40), (13, 15, 17), (255, 255, 255)),
}

_STICKY_DARK: Final[dict[str, tuple[RGB, RGB, RGB]]] = {
    "yellow": ((95, 75, 20), (174, 139, 29), (255, 255, 255)),
    "gold": ((99, 72, 16), (183, 132, 25), (255, 255, 255)),
    "orange": ((104, 57, 23), (188, 103, 43), (255, 255, 255)),
    "red": ((112, 45, 50), (193, 79, 89), (255, 255, 255)),
    "pink": ((103, 48, 84), (184, 91, 151), (255, 255, 255)),
    "magenta": ((100, 38, 93), (178, 71, 165), (255, 255, 255)),
    "periwinkle": ((49, 68, 117), (94, 123, 208), (255, 255, 255)),
    "purple": ((72, 51, 122), (132, 96, 208), (255, 255, 255)),
    "cyan": ((19, 75, 93), (18, 146, 177), (255, 255, 255)),
    "blue": ((34, 70, 125), (66, 122, 211), (255, 255, 255)),
    "teal": ((16, 85, 78), (27, 150, 132), (255, 255, 255)),
    "green": ((25, 95, 48), (48, 158, 82), (255, 255, 255)),
    "lime": ((65, 88, 25), (115, 158, 42), (255, 255, 255)),
    "chartreuse": ((62, 90, 14), (119, 163, 28), (255, 255, 255)),
    "gray": ((75, 80, 83), (151, 159, 164), (255, 255, 255)),
    "black": ((16, 19, 21), (84, 91, 96), (255, 255, 255)),
}

STICKY_PALETTES = MappingProxyType({
    LIGHT_THEME: MappingProxyType(_STICKY_LIGHT),
    DARK_THEME: MappingProxyType(_STICKY_DARK),
})

# Saturated paint colours are separate from Sticky fills.  A ``blue`` pen must
# remain legible rather than draw with the pale fill of a blue Sticky.
_INK_LIGHT: Final[dict[str, RGB]] = {
    INK_TOKEN: (24, 48, 57),
    "yellow": (183, 137, 0),
    "gold": (187, 131, 0),
    "orange": (204, 99, 32),
    "red": (197, 60, 73),
    "pink": (185, 74, 143),
    "magenta": (174, 55, 160),
    "periwinkle": (77, 105, 194),
    "purple": (116, 78, 194),
    "cyan": (0, 134, 170),
    "blue": (54, 112, 205),
    "teal": (14, 142, 126),
    "green": (36, 151, 75),
    "lime": (105, 150, 33),
    "chartreuse": (111, 157, 20),
    "gray": (92, 102, 109),
    "black": (36, 38, 40),
}

_INK_DARK: Final[dict[str, RGB]] = {
    INK_TOKEN: (235, 241, 243),
    "yellow": (242, 195, 55),
    "gold": (245, 184, 48),
    "orange": (244, 146, 75),
    "red": (239, 112, 124),
    "pink": (234, 126, 185),
    "magenta": (224, 107, 208),
    "periwinkle": (137, 162, 239),
    "purple": (165, 132, 237),
    "cyan": (65, 184, 216),
    "blue": (108, 157, 235),
    "teal": (64, 186, 166),
    "green": (85, 191, 111),
    "lime": (164, 199, 79),
    "chartreuse": (172, 205, 70),
    "gray": (182, 191, 196),
    "black": (220, 225, 228),
}

INK_COLORS = MappingProxyType({
    LIGHT_THEME: MappingProxyType(_INK_LIGHT),
    DARK_THEME: MappingProxyType(_INK_DARK),
})
TRANSPARENT_RGBA: Final[RGBA] = (0, 0, 0, 0)

FONT_ROLES: Final[tuple[str, ...]] = ("sans", "serif", "mono")
_FONT_CANDIDATES: Final[dict[str, tuple[str, ...]]] = {
    "sans": (
        "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei UI",
        "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Segoe UI",
        "Arial", "sans-serif",
    ),
    "serif": (
        "Noto Serif CJK SC", "Songti SC", "STSong", "SimSun",
        "Times New Roman", "serif",
    ),
    "mono": (
        "Sarasa Mono SC", "Noto Sans Mono CJK SC", "Noto Sans Mono",
        "Microsoft YaHei UI", "PingFang SC", "Menlo", "Consolas",
        "Courier New", "monospace",
    ),
}
FONT_CANDIDATES = MappingProxyType(_FONT_CANDIDATES)


@dataclass(frozen=True)
class SwatchAppearance:
    """Qt-free visible colour for one toolbar/picker swatch."""

    role: str
    token: object
    rgb: RGB
    rgba: RGBA
    border: RGB
    foreground: RGB
    transparent: bool
    hatch: bool
    checker: bool
    tooltip: str
    fallback: bool


def normalize_theme(theme: object) -> Theme:
    """Return a supported theme name; malformed input deterministically falls back."""
    return DARK_THEME if theme == DARK_THEME else LIGHT_THEME


def normalize_sticky_palette(token: object) -> str:
    """Return a saved Sticky token, falling back to the default yellow note."""
    if isinstance(token, str) and token in STICKY_PALETTE_TOKENS:
        return token
    return DEFAULT_STICKY_PALETTE


def normalize_ink_palette(token: object) -> str:
    """Return a valid opaque paint token; arbitrary/transparent paint is not valid."""
    return token if isinstance(token, str) and token in _INK_LIGHT else DEFAULT_INK_PALETTE


def sticky_colors(token: object, theme: object = DEFAULT_THEME) -> tuple[RGB, RGB, RGB]:
    """Return ``(fill, border, foreground)`` for one Sticky palette token."""
    return STICKY_PALETTES[normalize_theme(theme)][normalize_sticky_palette(token)]


def ink_color(token: object, theme: object = DEFAULT_THEME) -> RGB:
    """Resolve a semantic ink/shape/stroke colour to an opaque RGB tuple."""
    return INK_COLORS[normalize_theme(theme)][normalize_ink_palette(token)]


def pen_color(token: object, *, tool: object = "pen", theme: object = DEFAULT_THEME) -> RGBA:
    """Resolve Pen or Highlighter paint; Highlighter has the fixed 35% alpha."""
    red, green, blue = ink_color(token, theme)
    alpha = HIGHLIGHTER_ALPHA if tool == "highlighter" else 255
    return red, green, blue, alpha


def normalize_swatch_role(role: object) -> str:
    """Return a supported swatch role; unknown input is a programming error at the call site."""
    checked = str(role or "")
    if checked in SWATCH_ROLES:
        return checked
    raise ValueError(f"unknown swatch_role: {role!r}")


def is_transparent_token(token: object) -> bool:
    """True for the persisted empty/None fill token or the explicit transparent name."""
    if token is None:
        return True
    if isinstance(token, str) and token.strip().lower() in {TRANSPARENT_TOKEN, "", "none"}:
        return True
    return False


def resolve_swatch(
    role: object,
    token: object,
    theme: object = DEFAULT_THEME,
) -> SwatchAppearance:
    """Map ``(swatch_role, token)`` to a visible RGB/RGBA description.

    Callers must pass the role explicitly. Token strings are never used to
    guess Sticky vs ink vs fill. Unknown tokens use that role's stable
    fallback instead of crossing into another palette.
    """
    checked_role = normalize_swatch_role(role)
    checked_theme = normalize_theme(theme)
    if checked_role == SWATCH_ROLE_FILL and is_transparent_token(token):
        return SwatchAppearance(
            role=checked_role,
            token=token,
            rgb=TRANSPARENT_SWATCH_RGB,
            rgba=TRANSPARENT_RGBA,
            border=TRANSPARENT_SWATCH_BORDER,
            foreground=TRANSPARENT_SWATCH_HATCH,
            transparent=True,
            hatch=True,
            checker=True,
            tooltip="透明",
            fallback=False,
        )
    fallback = False
    if checked_role == SWATCH_ROLE_STICKY:
        normalized = normalize_sticky_palette(token)
        fallback = normalized != token
        fill, border, foreground = sticky_colors(normalized, checked_theme)
        tooltip = str(normalized)
    elif checked_role == SWATCH_ROLE_FILL:
        if isinstance(token, str) and token in STICKY_PALETTE_TOKENS:
            normalized = token
        else:
            normalized = DEFAULT_FILL_PALETTE
            fallback = True
        fill, border, foreground = sticky_colors(normalized, checked_theme)
        tooltip = str(normalized)
    else:
        normalized = normalize_ink_palette(token)
        fallback = normalized != token
        fill = ink_color(normalized, checked_theme)
        border = fill
        _, _, foreground = sticky_colors("gray", checked_theme)
        tooltip = str(normalized)
    red, green, blue = fill
    return SwatchAppearance(
        role=checked_role,
        token=token,
        rgb=fill,
        rgba=(red, green, blue, 255),
        border=border,
        foreground=foreground,
        transparent=False,
        hatch=False,
        checker=False,
        tooltip=tooltip,
        fallback=fallback,
    )


def normalize_font_role(role: object) -> str:
    """Return one persisted cross-platform font role, defaulting to ``sans``."""
    return role if isinstance(role, str) and role in FONT_ROLES else "sans"


def font_candidates(role: object) -> tuple[str, ...]:
    """Return the ordered CJK-aware family candidate stack for a font role."""
    return FONT_CANDIDATES[normalize_font_role(role)]


def relative_luminance(color: RGB) -> float:
    """WCAG relative luminance for an RGB tuple, useful in Qt-free token tests."""
    channels = tuple(_linear_channel(component) for component in color)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: RGB, second: RGB) -> float:
    """Return the WCAG contrast ratio between two opaque RGB colours."""
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _linear_channel(component: int) -> float:
    normalized = max(0, min(255, int(component))) / 255.0
    return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4


__all__ = [
    "DARK_THEME",
    "DEFAULT_FILL_PALETTE",
    "DEFAULT_INK_PALETTE",
    "DEFAULT_STICKY_PALETTE",
    "DEFAULT_THEME",
    "FONT_CANDIDATES",
    "FONT_ROLES",
    "HIGHLIGHTER_ALPHA",
    "INK_COLORS",
    "INK_TOKEN",
    "LIGHT_THEME",
    "RGB",
    "RGBA",
    "STICKY_PALETTES",
    "STICKY_PALETTE_TOKENS",
    "SWATCH_ROLES",
    "SWATCH_ROLE_FILL",
    "SWATCH_ROLE_INK",
    "SWATCH_ROLE_STICKY",
    "SWATCH_ROLE_STROKE",
    "SWATCH_ROLE_TEXT",
    "SwatchAppearance",
    "TRANSPARENT_RGBA",
    "TRANSPARENT_SWATCH_BORDER",
    "TRANSPARENT_SWATCH_HATCH",
    "TRANSPARENT_SWATCH_RGB",
    "TRANSPARENT_TOKEN",
    "contrast_ratio",
    "font_candidates",
    "ink_color",
    "is_transparent_token",
    "normalize_font_role",
    "normalize_ink_palette",
    "normalize_sticky_palette",
    "normalize_swatch_role",
    "normalize_theme",
    "pen_color",
    "relative_luminance",
    "resolve_swatch",
    "sticky_colors",
]
