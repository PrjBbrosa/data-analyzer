import pytest


def test_xcp_probe_imports_on_any_platform():
    from can_logger.p0 import xcp_short_upload_probe  # noqa: F401


def test_decode_raw_independent_of_hardware():
    """decode_raw is pure: must work on macOS without can/pyxcp installed."""
    from can_logger.p0.xcp_short_upload_probe import decode_raw

    assert decode_raw(b"\x00\x00\x80\x3f", "f32", "little") == pytest.approx(1.0)
    assert decode_raw(b"\xff\xff\xff\xff", "u32", "little") == 0xFFFFFFFF


def test_short_upload_rejects_short_positive_response():
    from can_logger.p0.xcp_short_upload_probe import RawXcpCanProbe

    class ShortResponseProbe(RawXcpCanProbe):
        def command(self, payload: bytes) -> bytes:
            return b"\xff\x34\x12"

    probe = ShortResponseProbe(object(), cmd_id=0x7E1, resp_id=0x7E9)

    with pytest.raises(RuntimeError, match="(?i)short|incomplete|not enough|size"):
        probe.short_upload(address=0x1000, size=4)
