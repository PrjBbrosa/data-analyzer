"""Expose vendored native acquisition packages to the frozen app import path."""

from pathlib import Path
import sys


base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
for vendor_name in ("_vendor_pya2l", "_vendor_pyxcp"):
    vendor = base / vendor_name
    if vendor.exists():
        vendor_text = str(vendor)
        if vendor_text not in sys.path:
            sys.path.insert(0, vendor_text)
