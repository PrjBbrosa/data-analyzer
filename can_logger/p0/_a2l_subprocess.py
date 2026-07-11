"""Subprocess entrypoint for crash-isolated pya2l parsing."""

from __future__ import annotations

import argparse
import os
import pickle
import sys

from can_logger.p0.a2l_probe import _load_measurement_summary_inprocess


def _write_stdout(payload: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(payload)
        stream.flush()
        return
    os.write(1, payload)


def _write_stderr(message: str) -> None:
    payload = message.encode("utf-8", errors="replace")
    stream = getattr(sys.stderr, "buffer", None)
    if stream is not None:
        stream.write(payload)
        stream.flush()
        return
    os.write(2, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse A2L in an isolated subprocess.")
    parser.add_argument("a2l_path")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        summary = _load_measurement_summary_inprocess(args.a2l_path, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        _write_stderr(f"A2L parse failed: {exc}\n")
        return 1

    _write_stdout(pickle.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
