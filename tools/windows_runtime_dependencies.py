"""CLI bridge from the frozen-import dependency contract to PowerShell.

It intentionally imports only the standard library plus the contract module,
so it is safe to run before PyInstaller and before optional import packages are
installed in a fresh Windows build virtual environment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mf4_analyzer.io.runtime_dependencies import (  # noqa: E402
    pyinstaller_collection_args,
    validate_windows_packaging_contract,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyinstaller-args-json", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--build-script", type=Path, action="append", default=[])
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args(argv)

    if args.pyinstaller_args_json:
        print(json.dumps(pyinstaller_collection_args(), ensure_ascii=False))

    if args.verify:
        if args.requirements is None or not args.build_script:
            parser.error("--verify requires --requirements and at least one --build-script")
        failures = validate_windows_packaging_contract(
            args.requirements,
            args.build_script,
            require_installed=args.require_installed,
        )
        if failures:
            for failure in failures:
                print(f"Windows packaging contract: {failure}", file=sys.stderr)
            return 1
        print("Windows packaging contract: OK")

    if not args.pyinstaller_args_json and not args.verify:
        parser.error("choose --pyinstaller-args-json and/or --verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
