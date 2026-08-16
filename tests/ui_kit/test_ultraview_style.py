"""The Titanium Amber contract is shared, isolated, and QSS-renderable."""
from mf4_analyzer.ui_kit.ultraview_style import (
    ULTRAVIEW_QSS_TOKENS,
    ULTRAVIEW_TITANIUM,
    titanium_color,
)


def test_titanium_amber_core_roles_are_exact_and_separate_from_global_controls():
    assert titanium_color("brand") == "#24697C"
    assert titanium_color("amber") == "#E58F32"
    assert titanium_color("danger") == "#C94F4A"
    assert titanium_color("canvas") == "#F7F8F7"
    assert ULTRAVIEW_TITANIUM["surface_solid"] == "#FFFEFD"
    assert "CONTROL_ACCENT" not in ULTRAVIEW_QSS_TOKENS


def test_every_ultraview_qss_token_is_renderable_and_uses_a_named_role():
    assert set(ULTRAVIEW_QSS_TOKENS) >= {
        "UV_CANVAS",
        "UV_SURFACE_SOLID",
        "UV_BRAND",
        "UV_AMBER",
        "UV_DANGER",
        "UV_TIME",
        "UV_ORDER",
    }
    assert all(str(value).strip() for value in ULTRAVIEW_QSS_TOKENS.values())
