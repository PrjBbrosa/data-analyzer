"""Shared headless Matplotlib packaging and frozen-data pruning contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


REQUIRED_TTF_FILES = frozenset(
    {
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSans-Oblique.ttf",
        "DejaVuSans-BoldOblique.ttf",
    }
)
OPTIONAL_TTF_FILES = frozenset({"LastResortHE-Regular.ttf"})

EXCLUDED_MODULES = (
    "matplotlib.backends.backend_qt",
    "matplotlib.backends.backend_qt5",
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_qt5cairo",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_qtcairo",
    "matplotlib.backends.qt_compat",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends._backend_tk",
    "matplotlib.backends.backend_wx",
    "matplotlib.backends.backend_wxagg",
    "matplotlib.backends.backend_wxcairo",
    "matplotlib.backends.backend_gtk3",
    "matplotlib.backends.backend_gtk3agg",
    "matplotlib.backends.backend_gtk3cairo",
    "matplotlib.backends.backend_gtk4",
    "matplotlib.backends.backend_gtk4agg",
    "matplotlib.backends.backend_gtk4cairo",
    "matplotlib.backends.backend_macosx",
    "matplotlib.backends.backend_webagg",
    "matplotlib.backends.backend_webagg_core",
    "matplotlib.backends.backend_nbagg",
    "matplotlib.tests",
    "tkinter",
    "_tkinter",
    "fontTools.qu2cu",
    "fontTools.cu2qu",
    "fontTools.ufoLib",
    "fontTools.voltLib",
    "fontTools.mtiLib",
    "fontTools.merge",
)


def packaging_contract() -> dict[str, object]:
    return {
        "environment": {"MPLBACKEND": "Agg"},
        "excluded_modules": list(EXCLUDED_MODULES),
    }


def _tree_measurement(directory: Path) -> dict[str, int]:
    files = [path for path in directory.rglob("*") if path.is_file()]
    return {
        "bytes": sum(path.stat().st_size for path in files),
        "files": len(files),
    }


def prune_internal(internal: Path, evidence_json: Path) -> dict[str, object]:
    internal = internal.resolve()
    if internal.name != "_internal" or not internal.is_dir():
        raise ValueError(f"expected an existing _internal directory: {internal}")
    mpl_data = internal / "matplotlib" / "mpl-data"
    ttf_directory = mpl_data / "fonts" / "ttf"
    afm_directory = mpl_data / "fonts" / "afm"
    pdfcorefonts_directory = mpl_data / "fonts" / "pdfcorefonts"
    for required in (ttf_directory, afm_directory, pdfcorefonts_directory):
        if not required.is_dir():
            raise FileNotFoundError(f"required Matplotlib font data missing: {required}")

    existing_ttf = {path.name for path in ttf_directory.iterdir() if path.is_file()}
    missing = REQUIRED_TTF_FILES - existing_ttf
    if missing:
        raise FileNotFoundError(
            "required Matplotlib TTF files missing: " + ", ".join(sorted(missing))
        )

    kept_contract = REQUIRED_TTF_FILES | (OPTIONAL_TTF_FILES & existing_ttf)
    before = _tree_measurement(internal)
    sample_data = mpl_data / "sample_data"
    sample_data_removed = sample_data.exists()
    if sample_data_removed:
        shutil.rmtree(sample_data)
    for path in ttf_directory.iterdir():
        if path.is_file() and path.name not in kept_contract:
            path.unlink()

    kept_ttf = sorted(path.name for path in ttf_directory.iterdir() if path.is_file())
    if set(kept_ttf) != kept_contract:
        raise RuntimeError(f"unexpected post-prune TTF set: {kept_ttf}")
    if not afm_directory.is_dir() or not pdfcorefonts_directory.is_dir():
        raise RuntimeError("AFM/pdfcorefonts must survive Matplotlib pruning")

    after = _tree_measurement(internal)
    record: dict[str, object] = {
        "internal": str(internal),
        "before": before,
        "after": after,
        "removed": {
            "bytes": before["bytes"] - after["bytes"],
            "files": before["files"] - after["files"],
        },
        "kept_ttf": kept_ttf,
        "sample_data_removed": sample_data_removed,
        "afm_preserved": True,
        "pdfcorefonts_preserved": True,
    }
    evidence_json.parent.mkdir(parents=True, exist_ok=True)
    evidence_json.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyinstaller-excludes-json", action="store_true")
    parser.add_argument("--prune-internal", type=Path)
    parser.add_argument("--evidence-json", type=Path)
    args = parser.parse_args(argv)
    if args.pyinstaller_excludes_json:
        print(json.dumps(packaging_contract()))
        return 0
    if args.prune_internal is not None:
        if args.evidence_json is None:
            parser.error("--prune-internal requires --evidence-json")
        record = prune_internal(args.prune_internal, args.evidence_json)
        print(json.dumps(record, ensure_ascii=False))
        return 0
    parser.error("select --pyinstaller-excludes-json or --prune-internal")


if __name__ == "__main__":
    raise SystemExit(main())
