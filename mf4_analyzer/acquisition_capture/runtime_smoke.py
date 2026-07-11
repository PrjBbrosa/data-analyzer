"""Non-GUI frozen/source smoke for the pinned acquisition runtime."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any


def run(output: Path) -> int:
    report: dict[str, Any] = {"ok": False, "frozen": False, "versions": {}, "error": None}
    try:
        import sys

        report["frozen"] = bool(getattr(sys, "frozen", False))
        report["versions"] = {
            "python-can": importlib.metadata.version("python-can"),
            "pyxcp": importlib.metadata.version("pyxcp"),
        }
        if report["versions"] != {"python-can": "4.6.1", "pyxcp": "0.29.10"}:
            raise RuntimeError(f"pinned acquisition versions differ: {report['versions']}")
        module = importlib.import_module("py" + "xcp.master")
        if not callable(getattr(module, "Master", None)):
            raise RuntimeError("pyxcp Master is unavailable")
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001 - JSON captures exact frozen failure
        report["error"] = str(exc)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2
