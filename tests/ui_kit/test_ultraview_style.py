"""The UltraView visual contract is shared, isolated, and QSS-renderable."""
from mf4_analyzer.ui_kit.ultraview_style import (
    ULTRAVIEW_PALETTE,
    ULTRAVIEW_QSS_TOKENS,
    ULTRAVIEW_TITANIUM,
    titanium_color,
    ultraview_color,
)


def test_selected_blue_roles_are_exact_and_separate_from_warning():
    assert ultraview_color("selected") == "#4262FF"
    assert ultraview_color("selected_wash") == "#E9EDFF"
    assert ultraview_color("selected_hover") == "#DDE3FF"
    assert ultraview_color("selected_line") == "#BDC9FF"
    assert ULTRAVIEW_QSS_TOKENS["UV_SELECTED"] == "#4262FF"
    assert ULTRAVIEW_QSS_TOKENS["UV_SELECTED_WASH"] == "#E9EDFF"
    assert ULTRAVIEW_QSS_TOKENS["UV_WARNING"] == "#DC861F"
    assert ULTRAVIEW_QSS_TOKENS["UV_SELECTED"] != ULTRAVIEW_QSS_TOKENS["UV_WARNING"]
    assert titanium_color("brand") == "#24697C"
    assert titanium_color("time_wash") == "#F5F8FF"
    assert titanium_color("danger") == "#C94F4A"
    assert titanium_color("canvas") == "#F7F8F7"
    assert ULTRAVIEW_PALETTE["surface_solid"] == "#FFFEFD"
    assert ULTRAVIEW_TITANIUM is ULTRAVIEW_PALETTE
    assert "CONTROL_ACCENT" not in ULTRAVIEW_QSS_TOKENS
    assert "UV_AMBER" not in ULTRAVIEW_QSS_TOKENS
    assert "UV_RAIL_ACTIVE_START" not in ULTRAVIEW_QSS_TOKENS


def test_card_shell_is_translucent_while_preview_content_keeps_its_own_material():
    """The frosted perimeter must expose the board without fading plot pixels."""
    assert ULTRAVIEW_PALETTE["surface_frost"] == "rgba(255, 255, 254, 118)"
    assert ULTRAVIEW_PALETTE["surface_frost_edge"] == "rgba(255, 255, 255, 166)"


def test_every_ultraview_qss_token_is_renderable_and_uses_a_named_role():
    assert set(ULTRAVIEW_QSS_TOKENS) >= {
        "UV_CANVAS",
        "UV_SURFACE_SOLID",
        "UV_BRAND",
        "UV_SELECTED",
        "UV_SELECTED_WASH",
        "UV_SELECTED_HOVER",
        "UV_SELECTED_LINE",
        "UV_WARNING",
        "UV_SURFACE_SOFT",
        "UV_DANGER",
        "UV_TIME",
        "UV_TIME_LINE",
        "UV_ORDER",
    }
    assert all(str(value).strip() for value in ULTRAVIEW_QSS_TOKENS.values())
