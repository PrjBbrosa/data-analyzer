"""Validate the complete packaged palette catalog without Qt or numpy."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mf4_analyzer.colormaps import (  # noqa: E402
    ColormapResourceError,
    validate_colormap_resources,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-hashes", action="store_true", help="Print validated RGB byte SHA-256 hashes")
    args = parser.parse_args(argv)
    try:
        specs = validate_colormap_resources()
    except (ColormapResourceError, OSError) as exc:
        print(f"Colormap validation failed: {exc}", file=sys.stderr)
        return 1
    if args.print_hashes:
        for spec in specs:
            if spec.rgb_sha256:
                print(f"{spec.id}  {spec.rgb_sha256}")
    print(f"Validated {len(specs)} heatmap colormaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
