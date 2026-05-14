#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mf4_analyzer.acquisition.preflight import analyze_mf4


def _run() -> int:
    parser = argparse.ArgumentParser(description="Run single-file MF4 acquisition preflight.")
    parser.add_argument("mf4")
    parser.add_argument("--expected-channel", action="append", default=[])
    parser.add_argument("--sha256", default="")
    parser.add_argument(
        "--require-exists",
        action="store_true",
        help="exit 2 if mf4 path does not exist (default: exit 0 with a skip note)",
    )
    parser.add_argument("--vehicle", default="")
    parser.add_argument("--signal-config-root", default="")
    args = parser.parse_args()

    p = Path(args.mf4)
    if not p.exists():
        msg = f"skip: {p} does not exist"
        if args.require_exists:
            print(msg, file=sys.stderr)
            return 2
        print(msg)
        return 0

    result = analyze_mf4(
        p,
        expected_channels=tuple(args.expected_channel),
        expected_sha256=args.sha256 or None,
        signal_config_root=args.signal_config_root or None,
        vehicle=args.vehicle,
    )
    print(result.to_json())
    return 0 if result.ok else 1


def main() -> int:
    try:
        return _run()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in input: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
