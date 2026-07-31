from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "matplotlib_frozen_contract.py"


def _run_contract(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *(str(argument) for argument in arguments)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_pyinstaller_contract_reports_headless_backend_and_precise_exclusions():
    completed = _run_contract("--pyinstaller-excludes-json")

    assert completed.returncode == 0, completed.stderr
    contract = json.loads(completed.stdout)
    assert contract["environment"] == {"MPLBACKEND": "Agg"}
    excluded = contract["excluded_modules"]
    for module in (
        "matplotlib.backends.backend_qt",
        "matplotlib.backends.backend_qt5agg",
        "matplotlib.backends.backend_qtagg",
        "matplotlib.backends.backend_tkagg",
        "matplotlib.backends.backend_wxagg",
        "matplotlib.backends.backend_gtk3agg",
        "matplotlib.backends.backend_gtk4agg",
        "matplotlib.backends.backend_macosx",
        "matplotlib.backends.backend_webagg",
        "matplotlib.backends.backend_nbagg",
        "matplotlib.tests",
        "tkinter",
        "fontTools.qu2cu",
        "fontTools.cu2qu",
        "fontTools.ufoLib",
        "fontTools.voltLib",
        "fontTools.mtiLib",
        "fontTools.merge",
    ):
        assert module in excluded
    assert "matplotlib.backends.backend_agg" not in excluded
    assert "mpl_toolkits" not in excluded


def test_prune_keeps_only_four_dejavu_ttf_and_preserves_pdf_font_data(tmp_path):
    internal = tmp_path / "_internal"
    mpl_data = internal / "matplotlib" / "mpl-data"
    ttf = mpl_data / "fonts" / "ttf"
    afm = mpl_data / "fonts" / "afm"
    pdfcorefonts = mpl_data / "fonts" / "pdfcorefonts"
    sample_data = mpl_data / "sample_data"
    ttf.mkdir(parents=True)
    afm.mkdir(parents=True)
    pdfcorefonts.mkdir(parents=True)
    sample_data.mkdir(parents=True)
    keep = {
        "DejaVuSans.ttf": b"a",
        "DejaVuSans-Bold.ttf": b"bb",
        "DejaVuSans-Oblique.ttf": b"ccc",
        "DejaVuSans-BoldOblique.ttf": b"dddd",
    }
    for name, content in {
        **keep,
        "DejaVuSansMono.ttf": b"remove-me",
        "STIXGeneral.ttf": b"also-remove",
    }.items():
        (ttf / name).write_bytes(content)
    (afm / "keep.afm").write_bytes(b"afm")
    (pdfcorefonts / "keep.afm").write_bytes(b"pdfcore")
    (sample_data / "remove.dat").write_bytes(b"sample")
    (internal / "unrelated.bin").write_bytes(b"unchanged")
    evidence = tmp_path / "prune-evidence.json"

    completed = _run_contract(
        "--prune-internal",
        internal,
        "--evidence-json",
        evidence,
    )

    assert completed.returncode == 0, completed.stderr
    assert {path.name for path in ttf.iterdir()} == set(keep)
    assert not sample_data.exists()
    assert (afm / "keep.afm").read_bytes() == b"afm"
    assert (pdfcorefonts / "keep.afm").read_bytes() == b"pdfcore"
    assert (internal / "unrelated.bin").read_bytes() == b"unchanged"
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert record["before"] == {"bytes": 55, "files": 10}
    assert record["after"] == {"bytes": 29, "files": 7}
    assert record["removed"] == {"bytes": 26, "files": 3}
    assert record["kept_ttf"] == sorted(keep)
    assert record["sample_data_removed"] is True


def test_both_windows_builders_use_the_same_matplotlib_contract_and_prune_gate():
    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
        assert "$env:MPLBACKEND = \"Agg\"" in text
        assert "matplotlib_frozen_contract.py" in text
        assert "--pyinstaller-excludes-json" in text
        assert "--prune-internal" in text
        assert "--evidence-json" in text


def test_both_windows_builders_gate_on_the_frozen_twelve_output_render_smoke():
    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
        assert "verify_frozen_batch_render.py" in text
        assert "--exe" in text
        assert "batch-render-smoke.json" in text
        assert "Frozen batch render smoke failed" in text
