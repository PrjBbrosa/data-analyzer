"""Expose vendored pyxcp package data to the frozen app import path."""

from pathlib import Path
import sys


base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
vendor = base / "_vendor_pyxcp"
if vendor.exists():
    vendor_text = str(vendor)
    if vendor_text not in sys.path:
        sys.path.insert(0, vendor_text)
