"""Passive CAN sniff for VN1630 bench bring-up (scratch diagnostic).

Opens the Vector bus at a given bitrate and listens for N seconds, then
prints how many frames were seen and which CAN IDs. Run this BEFORE any
XCP / Test Connection to confirm:
  * physical layer + termination are OK,
  * the VN1630 bitrate matches the bench (PCAN) bitrate,
  * the bus is actually alive (PCAN + ECU are talking).

NOTE: this opens the VN1630 as a normal CAN node (it will ACK frames,
which is normal and required). Make SURE --bitrate matches the bench, or
a mismatched node emits error frames and can disturb the bus.

You will NOT see the ECU's XCP response ID here (e.g. 0x6C9). XCP only
answers AFTER an XCP CONNECT, which the cockpit's "Test Connection" does
— passive sniffing alone never triggers it. This step only proves the
bus is healthy at the right bitrate.

Run:
    .\\.venv\\Scripts\\python.exe _can_sniff.py --bitrate 500000 --seconds 5
"""
from __future__ import annotations

import argparse
import time
from collections import Counter


def main() -> None:
    p = argparse.ArgumentParser(description="Passive CAN sniff (VN1630).")
    p.add_argument("--app-name", default="Python")
    p.add_argument("--channel", type=int, default=0)
    p.add_argument("--bitrate", type=int, default=500000)
    p.add_argument("--seconds", type=float, default=5.0)
    args = p.parse_args()

    import can  # python-can; vector backend resolved by interface=

    print(
        f"opening vector app={args.app_name} ch={args.channel} "
        f"bitrate={args.bitrate} (normal node) ..."
    )
    bus = can.Bus(
        interface="vector",
        app_name=args.app_name,
        channel=args.channel,
        bitrate=args.bitrate,
    )

    counts: Counter[int] = Counter()
    total = 0
    errors = 0
    fd_seen = False
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            msg = bus.recv(timeout=0.2)
            if msg is None:
                continue
            if getattr(msg, "is_error_frame", False):
                errors += 1
                continue
            total += 1
            counts[msg.arbitration_id] += 1
            if getattr(msg, "is_fd", False):
                fd_seen = True
    finally:
        try:
            bus.shutdown()
        except Exception:
            pass

    print(
        f"\n=== {total} data frames in {args.seconds:.0f}s, "
        f"{len(counts)} unique IDs, error_frames={errors}, "
        f"CAN-FD seen={fd_seen} ==="
    )
    if errors and not total:
        print(
            "  ONLY error frames -> bitrate almost certainly WRONG. "
            "Set --bitrate to the bench/PCAN value (try 500000 / 250000)."
        )
        return
    if not total:
        print(
            "  NO FRAMES. Check: bitrate match, CAN_H/CAN_L wiring + 120ohm "
            "termination, ECU/PCAN powered, right channel."
        )
        return
    print("  IDs seen (id x count):")
    for arb_id, n in sorted(counts.items()):
        ext = arb_id > 0x7FF
        width = 8 if ext else 3
        tag = "  [ext]" if ext else ""
        print(f"    0x{arb_id:0{width}X}  x{n}{tag}")


if __name__ == "__main__":
    main()
