import sys

import pytest


def test_xcp_probe_imports_on_any_platform():
    from can_logger.p0 import xcp_short_upload_probe  # noqa: F401


def test_decode_raw_independent_of_hardware():
    """decode_raw is pure: must work on macOS without can/pyxcp installed."""
    from can_logger.p0.xcp_short_upload_probe import decode_raw

    assert decode_raw(b"\x00\x00\x80\x3f", "f32", "little") == pytest.approx(1.0)
    assert decode_raw(b"\xff\xff\xff\xff", "u32", "little") == 0xFFFFFFFF
