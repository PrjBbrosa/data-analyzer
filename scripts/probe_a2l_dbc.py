"""Probe an A2L and/or DBC file on macOS.

Combines three checks:
  1. A2L parses via pya2l, lists sample MEASUREMENTs (name/addr/type/unit).
  2. IF_DATA XCP transport block is grepped from the raw A2L
     (CMD_ID / RESP_ID / BYTE_ORDER etc.) — needed later on Windows to
     connect XCP to the ECU.
  3. DBC parses via cantools, lists sample frames+signals.

Usage:
  .venv/bin/python scripts/probe_a2l_dbc.py --a2l path/to.a2l
  .venv/bin/python scripts/probe_a2l_dbc.py --dbc path/to.dbc
  .venv/bin/python scripts/probe_a2l_dbc.py --a2l ... --dbc ... --limit 30
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def probe_a2l(path: Path, limit: int) -> None:
    from can_logger.p0.a2l_probe import load_measurement_summary

    print(f"\n=== A2L: {path} ===")
    summary = load_measurement_summary(str(path), limit=limit)
    print(f"total measurements: {summary.total_measurements}")
    print(f"sample (first {len(summary.measurements)}):")
    print(f"  {'name':<40} {'address':<12} {'datatype':<12} {'unit':<10} conversion")
    for m in summary.measurements:
        print(
            f"  {m.name[:40]:<40} 0x{m.address:08X}   "
            f"{m.datatype[:12]:<12} {m.unit[:10]:<10} {m.conversion}"
        )


def probe_a2l_xcp(path: Path) -> None:
    print(f"\n=== A2L XCP transport ({path.name}) ===")
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError as exc:
        print(f"  !! cannot read: {exc}")
        return

    # IF_DATA XCP ... /end IF_DATA — multi-line, case-sensitive per ASAM.
    matches = re.findall(
        r"/begin\s+IF_DATA\s+XCP\b.*?/end\s+IF_DATA",
        text,
        re.DOTALL,
    )
    if not matches:
        print("  (no IF_DATA XCP block found — A2L may be CAL-only / pre-XCP)")
        return

    for i, block in enumerate(matches):
        print(f"--- IF_DATA XCP block #{i + 1} (truncated to 60 lines) ---")
        for line in block.splitlines()[:60]:
            print(f"  {line.rstrip()}")


def probe_dbc(path: Path, limit: int) -> None:
    import cantools

    print(f"\n=== DBC: {path} ===")
    db = cantools.database.load_file(str(path))
    msgs = db.messages
    total_signals = sum(len(m.signals) for m in msgs)
    print(f"messages: {len(msgs)}   signals: {total_signals}   nodes: {len(db.nodes)}")
    print(f"sample (first {min(limit, len(msgs))} messages):")
    for m in msgs[:limit]:
        sigs = ", ".join(s.name for s in m.signals[:6])
        more = "" if len(m.signals) <= 6 else f", +{len(m.signals) - 6} more"
        print(
            f"  0x{m.frame_id:03X} {m.name:<32} len={m.length} dlc={m.length} "
            f"signals=[{sigs}{more}]"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--a2l", type=Path, help="path to .a2l file")
    parser.add_argument("--dbc", type=Path, help="path to .dbc file")
    parser.add_argument("--limit", type=int, default=20,
                        help="rows to print per file (default 20)")
    args = parser.parse_args()

    if not args.a2l and not args.dbc:
        parser.error("supply --a2l and/or --dbc")

    if args.a2l:
        if not args.a2l.exists():
            print(f"!! A2L not found: {args.a2l}", file=sys.stderr)
            return 2
        probe_a2l(args.a2l, args.limit)
        probe_a2l_xcp(args.a2l)

    if args.dbc:
        if not args.dbc.exists():
            print(f"!! DBC not found: {args.dbc}", file=sys.stderr)
            return 2
        probe_dbc(args.dbc, args.limit)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
