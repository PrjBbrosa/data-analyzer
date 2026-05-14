from __future__ import annotations

import argparse
import struct
import time
from typing import Any


CMD_CONNECT = 0xFF
CMD_DISCONNECT = 0xFE
CMD_SHORT_UPLOAD = 0xF4
RESP_OK = 0xFF


def parse_int(text: str) -> int:
    return int(text, 0)


class RawXcpCanProbe:
    def __init__(self, bus: Any, *, cmd_id: int, resp_id: int, timeout: float = 0.5):
        self.bus = bus
        self.cmd_id = cmd_id
        self.resp_id = resp_id
        self.timeout = timeout

    def send(self, payload: bytes) -> None:
        import can  # type: ignore[import-not-found]

        msg = can.Message(
            arbitration_id=self.cmd_id,
            data=payload.ljust(8, b"\x00"),
            is_extended_id=False,
        )
        self.bus.send(msg)

    def recv(self) -> bytes:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=0.05)
            if msg is None:
                continue
            if msg.arbitration_id == self.resp_id:
                data = bytes(msg.data)
                if not data:
                    raise RuntimeError("empty XCP response")
                return data
        raise TimeoutError(f"no XCP response on CAN ID 0x{self.resp_id:X}")

    def command(self, payload: bytes) -> bytes:
        self.send(payload)
        response = self.recv()
        if response[0] != RESP_OK:
            code = response[1] if len(response) > 1 else 0
            raise RuntimeError(
                f"negative XCP response: pid=0x{response[0]:02X}, code=0x{code:02X}"
            )
        return response

    def connect(self) -> bytes:
        return self.command(bytes([CMD_CONNECT, 0x00]))

    def disconnect(self) -> None:
        self.send(bytes([CMD_DISCONNECT]))

    def short_upload(
        self, *, address: int, size: int, address_extension: int = 0
    ) -> bytes:
        payload = struct.pack(
            "<BBBBI", CMD_SHORT_UPLOAD, size, 0x00, address_extension, address
        )
        response = self.command(payload)
        raw = response[1 : 1 + size]
        if len(raw) != size:
            raise RuntimeError(
                f"short XCP SHORT_UPLOAD response: requested size {size} bytes, "
                f"received {len(raw)} bytes"
            )
        return raw


def decode_raw(raw: bytes, dtype: str, endian: str):
    endian_prefix = ">" if endian == "big" else "<"
    formats = {
        "u8": "B",
        "s8": "b",
        "u16": "H",
        "s16": "h",
        "u32": "I",
        "s32": "i",
        "f32": "f",
        "f64": "d",
    }
    fmt = formats[dtype]
    needed = struct.calcsize(endian_prefix + fmt)
    if len(raw) < needed:
        raise ValueError(f"not enough data for {dtype}: {raw.hex()}")
    return struct.unpack(endian_prefix + fmt, raw[:needed])[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 raw XCP CONNECT + SHORT_UPLOAD probe.")
    parser.add_argument("--interface", default="vector")
    parser.add_argument("--channel", default="0")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--app-name", default="CANalyzer")
    parser.add_argument("--cmd-id", type=parse_int, required=True)
    parser.add_argument("--resp-id", type=parse_int, required=True)
    parser.add_argument("--address", type=parse_int, required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--address-extension", type=parse_int, default=0)
    parser.add_argument(
        "--dtype",
        choices=["u8", "s8", "u16", "s16", "u32", "s32", "f32", "f64"],
        default="f32",
    )
    parser.add_argument("--endian", choices=["little", "big"], default="little")
    args = parser.parse_args()

    import can  # type: ignore[import-not-found]

    bus_kwargs = {
        "interface": args.interface,
        "channel": args.channel,
        "bitrate": args.bitrate,
    }
    if args.interface == "vector":
        bus_kwargs["app_name"] = args.app_name

    bus = can.Bus(**bus_kwargs)
    probe = RawXcpCanProbe(bus, cmd_id=args.cmd_id, resp_id=args.resp_id)
    try:
        connect_response = probe.connect()
        print("connect_response:", connect_response.hex())
        raw = probe.short_upload(
            address=args.address,
            size=args.size,
            address_extension=args.address_extension,
        )
        print("raw:", raw.hex())
        print("decoded:", decode_raw(raw, args.dtype, args.endian))
    finally:
        try:
            probe.disconnect()
        finally:
            bus.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
