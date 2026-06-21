"""Qt-native color helpers for UI dialogs."""

from numbers import Integral, Real
import re

from PyQt5.QtGui import QColor


_TABLEAU_COLORS = {
    "tab:blue": "#1f77b4",
    "tab:orange": "#ff7f0e",
    "tab:green": "#2ca02c",
    "tab:red": "#d62728",
    "tab:purple": "#9467bd",
    "tab:brown": "#8c564b",
    "tab:pink": "#e377c2",
    "tab:gray": "#7f7f7f",
    "tab:grey": "#7f7f7f",
    "tab:olive": "#bcbd22",
    "tab:cyan": "#17becf",
}
_CYCLE_COLORS = {
    f"C{i}": color
    for i, color in enumerate(
        [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
        ]
    )
}
_BASE_COLORS = {
    "b": "#0000ff",
    "g": "#008000",
    "r": "#ff0000",
    "c": "#00bfbf",
    "m": "#bf00bf",
    "y": "#bfbf00",
    "k": "#000000",
    "w": "#ffffff",
}
_XKCD_COMPAT_COLORS = {
    "xkcd:sky blue": "#75bbfd",
}
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _is_number(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _sequence_is_0_to_1(vals) -> bool:
    return all(_is_number(v) and 0.0 <= float(v) <= 1.0 for v in vals)


def _sequence_is_0_to_255_int(vals) -> bool:
    return all(
        isinstance(v, Integral) and not isinstance(v, bool) and 0 <= int(v) <= 255
        for v in vals
    )


def _qcolor_from_sequence(vals) -> QColor:
    if not 3 <= len(vals) <= 4:
        raise ValueError(f"invalid color tuple length: {len(vals)}")
    if _sequence_is_0_to_1(vals):
        return QColor.fromRgbF(*[float(v) for v in vals])
    if _sequence_is_0_to_255_int(vals):
        return QColor(*[int(v) for v in vals])
    raise ValueError(f"invalid color tuple: {tuple(vals)!r}")


def _hex_to_rgb(text: str) -> str:
    match = _HEX_RE.match(text)
    if match is None:
        raise ValueError(f"invalid hex color: {text!r}")
    value = match.group(1).lower()
    if len(value) in (3, 4):
        return "#" + "".join(ch * 2 for ch in value[:3])
    return "#" + value[:6]


def _matplotlib_string_to_hex(text: str) -> str | None:
    key = text.strip()
    if not key:
        return None
    if key.lower() == "none":
        return "#000000"
    if key.startswith("#"):
        return _hex_to_rgb(key)
    if key in _CYCLE_COLORS:
        return _CYCLE_COLORS[key]
    lowered = key.lower()
    if lowered in _TABLEAU_COLORS:
        return _TABLEAU_COLORS[lowered]
    if lowered in _BASE_COLORS:
        return _BASE_COLORS[lowered]
    if lowered in _XKCD_COMPAT_COLORS:
        return _XKCD_COMPAT_COLORS[lowered]
    try:
        gray = float(key)
    except ValueError:
        return None
    if 0.0 <= gray <= 1.0:
        value = int(round(gray * 255))
        return f"#{value:02x}{value:02x}{value:02x}"
    return None


def to_hex(color) -> str:
    """Return ``#rrggbb`` for the color inputs accepted by chart dialogs."""
    if isinstance(color, (tuple, list)):
        qcolor = _qcolor_from_sequence(list(color))
    elif isinstance(color, QColor):
        qcolor = QColor(color)
    else:
        if color is None:
            raise ValueError("invalid color: None")
        text = str(color)
        compat = _matplotlib_string_to_hex(text)
        if compat is not None:
            return compat
        qcolor = QColor(text)
    if not qcolor.isValid():
        raise ValueError(f"invalid color: {color!r}")
    return qcolor.name()


def is_color_like(color) -> bool:
    try:
        to_hex(color)
    except Exception:
        return False
    return True


__all__ = ["is_color_like", "to_hex"]
