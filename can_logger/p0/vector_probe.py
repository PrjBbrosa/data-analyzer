"""Vector hardware access probe.

python-can is imported lazily so this module can be imported on macOS/Linux for
static checks without the Vector driver.
"""
from __future__ import annotations

import argparse
import sys


def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "Vector interface is only supported on Windows; current platform: "
            f"{sys.platform}"
        )


def list_vector_channels() -> list:
    _ensure_windows()
    from can.interfaces import vector  # type: ignore[import-not-found]

    return list(vector.get_channel_configs())


def open_vector_bus(*, channel: int, bitrate: int, app_name: str):
    _ensure_windows()
    import can  # type: ignore[import-not-found]

    return can.Bus(interface="vector", channel=channel, bitrate=bitrate, app_name=app_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe python-can Vector access.")
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--app-name", default="CANalyzer")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    if sys.platform != "win32":
        print(
            "Vector interface is expected to run on Windows; current platform:",
            sys.platform,
        )
        return 2

    channels = list_vector_channels()
    print(f"vector_channels: {len(channels)}")
    for ch in channels:
        print(ch)

    if args.open:
        bus = open_vector_bus(
            channel=args.channel, bitrate=args.bitrate, app_name=args.app_name
        )
        try:
            print("vector_open: ok")
        finally:
            bus.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
