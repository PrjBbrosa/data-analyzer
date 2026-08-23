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


def test_resolve_swatch_uses_explicit_role_not_token_guessing():
    ink = author_style.resolve_swatch("ink", "ink")
    sticky = author_style.resolve_swatch("sticky", "yellow")
    assert ink.rgb == author_style.ink_color("ink")
    assert sticky.rgb == author_style.sticky_colors("yellow")[0]
    assert ink.rgb != sticky.rgb
    guessed = author_style.resolve_swatch("ink", "not-a-token")
    assert guessed.fallback is True
    assert guessed.rgb == author_style.ink_color("ink")
    assert guessed.rgb != author_style.sticky_colors("yellow")[0]


def test_resolve_swatch_roles_cover_legal_unknown_and_transparent():
    for role in author_style.SWATCH_ROLES:
        appearance = author_style.resolve_swatch(role, "unknown-token")
        assert appearance.role == role
        assert appearance.fallback is True
        assert appearance.transparent is False
    fill = author_style.resolve_swatch("fill", None)
    assert fill.transparent is True
    assert fill.hatch is True
    assert fill.checker is True
    assert fill.tooltip == "透明"
    assert fill.rgb == author_style.TRANSPARENT_SWATCH_RGB
    named = author_style.resolve_swatch("fill", "transparent")
    assert named.transparent is True
    text = author_style.resolve_swatch("text", "blue")
    stroke = author_style.resolve_swatch("stroke", "blue")
    assert text.rgb == author_style.ink_color("blue")
    assert stroke.rgb == text.rgb


def test_unknown_swatch_role_is_not_guessed():
    try:
        author_style.resolve_swatch("palette", "ink")
    except ValueError as exc:
        assert "swatch_role" in str(exc)
    else:
        raise AssertionError("unknown swatch_role must not silently succeed")
