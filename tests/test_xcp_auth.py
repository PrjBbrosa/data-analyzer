"""Seed&Key auth flow tests for locked XCP DAQ resources."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _connect_resp(resource_byte: int) -> MagicMock:
    return MagicMock(resource=resource_byte)


def test_unlocked_daq_skips_auth() -> None:
    from mf4_analyzer.acquisition_capture.xcp_auth import unlock_resources_if_needed

    master = MagicMock()
    unlock_resources_if_needed(
        master=master,
        connect_response=_connect_resp(0x00),
        seed_and_key_dll=None,
    )

    master.getSeed.assert_not_called()
    master.unlock.assert_not_called()


def test_locked_daq_without_dll_raises_xcp_auth_error() -> None:
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        XcpAuthError,
        unlock_resources_if_needed,
    )

    with pytest.raises(XcpAuthError, match="no seed&key DLL configured"):
        unlock_resources_if_needed(
            master=MagicMock(),
            connect_response=_connect_resp(0x04),
            seed_and_key_dll=None,
        )


def test_locked_daq_with_missing_dll_path_raises() -> None:
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        XcpAuthError,
        unlock_resources_if_needed,
    )

    with pytest.raises(XcpAuthError, match="DLL not found"):
        unlock_resources_if_needed(
            master=MagicMock(),
            connect_response=_connect_resp(0x04),
            seed_and_key_dll="C:/does/not/exist/seed.dll",
        )


def test_locked_daq_with_bitness_mismatch_raises(tmp_path) -> None:
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        XcpAuthError,
        unlock_resources_if_needed,
    )

    fake = tmp_path / "seed32.dll"
    fake.write_bytes(b"\x00" * 16)
    with patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll",
        side_effect=OSError("[WinError 193] is not a valid Win32 application"),
    ):
        with pytest.raises(XcpAuthError, match="bitness mismatch|not a valid"):
            unlock_resources_if_needed(
                master=MagicMock(),
                connect_response=_connect_resp(0x04),
                seed_and_key_dll=str(fake),
            )


def test_locked_daq_happy_path_unlocks(tmp_path) -> None:
    from mf4_analyzer.acquisition_capture.xcp_auth import unlock_resources_if_needed

    fake = tmp_path / "seed64.dll"
    fake.write_bytes(b"\x00" * 16)
    master = MagicMock()
    master.getSeed.return_value = b"\x01\x02\x03\x04"

    with patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll",
        return_value=MagicMock(),
    ), patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._compute_key_from_seed",
        return_value=b"\xDE\xAD\xBE\xEF",
    ):
        unlock_resources_if_needed(
            master=master,
            connect_response=_connect_resp(0x04),
            seed_and_key_dll=str(fake),
        )

    master.getSeed.assert_called_with(resource_id=0x02)
    master.unlock.assert_called_with(resource_id=0x02, key=b"\xDE\xAD\xBE\xEF")


def test_locked_daq_ecu_rejects_unlock_raises() -> None:
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        XcpAuthError,
        unlock_resources_if_needed,
    )

    master = MagicMock()
    master.getSeed.return_value = b"\x00\x00"
    master.unlock.side_effect = RuntimeError("ERR_ACCESS_DENIED")
    with patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll",
        return_value=MagicMock(),
    ), patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._compute_key_from_seed",
        return_value=b"\x00\x00\x00\x00",
    ), patch("os.path.exists", return_value=True):
        with pytest.raises(XcpAuthError, match="ECU rejected unlock"):
            unlock_resources_if_needed(
                master=master,
                connect_response=_connect_resp(0x04),
                seed_and_key_dll="/any/path.dll",
            )
