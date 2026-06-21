from mf4_analyzer.ui._color_utils import is_color_like, to_hex


def test_hex_string_roundtrip():
    assert to_hex("#1769e0") == "#1769e0"


def test_named_color():
    assert to_hex("red") == "#ff0000"


def test_float_tuple():
    assert to_hex((1.0, 0.0, 0.0)) == "#ff0000"


def test_int_tuple():
    assert to_hex((18, 52, 86)) == "#123456"


def test_matplotlib_compat_color_strings():
    assert to_hex("C0") == "#1f77b4"
    assert to_hex("C1") == "#ff7f0e"
    assert to_hex("tab:blue") == "#1f77b4"
    assert to_hex("r") == "#ff0000"
    assert to_hex("g") == "#008000"
    assert to_hex("c") == "#00bfbf"
    assert to_hex("0.5") == "#808080"
    assert to_hex("#abcd") == "#aabbcc"
    assert to_hex("#aabbccdd") == "#aabbcc"
    assert to_hex("none") == "#000000"
    assert to_hex("xkcd:sky blue") == "#75bbfd"


def test_is_color_like_accepts_supported_inputs_and_rejects_invalid_ones():
    assert is_color_like("#1769e0")
    assert is_color_like("red")
    assert is_color_like((1.0, 0.0, 0.0))
    assert is_color_like((18, 52, 86))
    assert is_color_like("C0")
    assert is_color_like("tab:orange")
    assert is_color_like("#abcd")
    assert is_color_like("#aabbccdd")

    assert not is_color_like("not-a-color")
    assert not is_color_like((1.0, 0.0))
    assert not is_color_like(None)
    assert not is_color_like((True, False, False))
