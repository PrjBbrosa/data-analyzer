"""Qt-free visual-token contract for future UltraView authoring widgets."""
from __future__ import annotations

from mf4_analyzer.ui.chart_stack.ultraview import author_style


def test_sticky_palette_is_complete_unique_and_readable_in_both_themes():
    assert author_style.STICKY_PALETTE_TOKENS == (
        "yellow", "gold", "orange", "red",
        "pink", "magenta", "periwinkle", "purple",
        "cyan", "blue", "teal", "green",
        "lime", "chartreuse", "gray", "black",
    )
    assert len(set(author_style.STICKY_PALETTE_TOKENS)) == 16

    for theme in ("light", "dark"):
        for token in author_style.STICKY_PALETTE_TOKENS:
            fill, border, foreground = author_style.sticky_colors(token, theme)
            assert all(
                0 <= component <= 255
                for color in (fill, border, foreground)
                for component in color
            )
            assert author_style.contrast_ratio(fill, foreground) >= 4.5, (theme, token)
            assert border != fill, (theme, token)


def test_invalid_palette_and_theme_inputs_have_deterministic_safe_fallbacks():
    assert author_style.sticky_colors("not-a-palette", "not-a-theme") == author_style.sticky_colors(
        "yellow", "light"
    )
    assert author_style.ink_color("transparent", "dark") == author_style.ink_color("ink", "dark")
    assert author_style.ink_color([], "dark") == author_style.ink_color("ink", "dark")
    assert author_style.normalize_sticky_palette(None) == "yellow"
    assert author_style.normalize_ink_palette(None) == "ink"
    assert author_style.TRANSPARENT_RGBA == (0, 0, 0, 0)


def test_pen_and_highlighter_share_rgb_but_highlighter_has_fixed_alpha():
    pen = author_style.pen_color("blue", tool="pen")
    highlighter = author_style.pen_color("blue", tool="highlighter")

    assert pen[:3] == highlighter[:3]
    assert pen[3] == 255
    assert highlighter[3] == author_style.HIGHLIGHTER_ALPHA == 89
    assert author_style.pen_color("bad", tool="unknown") == author_style.pen_color(
        "ink", tool="pen"
    )


def test_font_roles_are_cjk_aware_and_unknown_role_falls_back_to_sans():
    assert author_style.FONT_ROLES == ("sans", "serif", "mono")
    assert author_style.font_candidates("sans")[0] == "Noto Sans CJK SC"
    assert "Noto Serif CJK SC" in author_style.font_candidates("serif")
    assert "Noto Sans Mono CJK SC" in author_style.font_candidates("mono")
    assert author_style.normalize_font_role("unknown") == "sans"
    assert author_style.font_candidates("unknown") == author_style.font_candidates("sans")


def test_author_style_contract_remains_qt_free():
    source = author_style.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    assert "PyQt" not in text
    assert "QColor" not in text
