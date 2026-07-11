#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path

from mf4_analyzer.app import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--acquisition-runtime-smoke", action="store_true")
    parser.add_argument("--json", type=Path)
    args, _unknown = parser.parse_known_args()
    if args.acquisition_runtime_smoke:
        if args.json is None:
            raise SystemExit("--acquisition-runtime-smoke requires --json <path>")
        from mf4_analyzer.acquisition_capture.runtime_smoke import run

        raise SystemExit(run(args.json))
    main()
