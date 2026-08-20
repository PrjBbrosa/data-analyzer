"""The Titanium Amber contract is shared, isolated, and QSS-renderable."""
from mf4_analyzer.ui_kit.ultraview_style import (
    ULTRAVIEW_QSS_TOKENS,
    ULTRAVIEW_TITANIUM,
    titanium_color,
)


def test_titanium_amber_core_roles_are_exact_and_separate_from_global_controls():
    assert titanium_color("brand") == "#24697C"
    assert titanium_color("amber") == "#E58F32"
    assert titanium_color("rail_active_start") == "#3C8495"
    assert titanium_color("rail_active_end") == "#F0A44C"
    assert ULTRAVIEW_QSS_TOKENS["UV_RAIL_ACTIVE_START"] == "#3C8495"
    assert ULTRAVIEW_QSS_TOKENS["UV_RAIL_ACTIVE_END"] == "#F0A44C"
    assert ULTRAVIEW_QSS_TOKENS["UV_RAIL_ACTIVE_HOVER"] == "#2F7181"
    assert titanium_color("time_wash") == "#F5F8FF"
    assert titanium_color("time_line") == "#A6C0F5"
    assert titanium_color("danger") == "#C94F4A"
    assert titanium_color("canvas") == "#F7F8F7"
    assert ULTRAVIEW_TITANIUM["surface_solid"] == "#FFFEFD"
    assert "CONTROL_ACCENT" not in ULTRAVIEW_QSS_TOKENS


def test_card_shell_is_translucent_while_preview_content_keeps_its_own_material():
    """The frosted perimeter must expose the board without fading plot pixels."""
    assert ULTRAVIEW_TITANIUM["surface_frost"] == "rgba(255, 255, 254, 118)"
    assert ULTRAVIEW_TITANIUM["surface_frost_edge"] == "rgba(255, 255, 255, 166)"


def test_every_ultraview_qss_token_is_renderable_and_uses_a_named_role():
    assert set(ULTRAVIEW_QSS_TOKENS) >= {
        "UV_CANVAS",
        "UV_SURFACE_SOLID",
        "UV_BRAND",
        "UV_AMBER",
        "UV_RAIL_ACTIVE_START",
        "UV_RAIL_ACTIVE_END",
        "UV_RAIL_ACTIVE_HOVER",
        "UV_SURFACE_SOFT",
        "UV_DANGER",
        "UV_TIME",
        "UV_TIME_LINE",
        "UV_ORDER",
    }
    assert all(str(value).strip() for value in ULTRAVIEW_QSS_TOKENS.values())
