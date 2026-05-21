"""Subprocess entrypoint for crash-isolated pya2l parsing."""

from __future__ import annotations

import argparse
import pickle
import sys

from can_logger.p0.a2l_probe import _load_measurement_summary_inprocess


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse A2L in an isolated subprocess.")
    parser.add_argument("a2l_path")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        summary = _load_measurement_summary_inprocess(args.a2l_path, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"A2L parse failed: {exc}", file=sys.stderr)
        return 1

    sys.stdout.buffer.write(pickle.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
