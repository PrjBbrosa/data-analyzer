from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment["MPLBACKEND"] = "Agg"
    return environment


def test_group_acceptance_cli_proves_modes_linkage_and_deleted_image_resume(
    tmp_path,
):
    output_directory = tmp_path / "acceptance"
    result_json = tmp_path / "acceptance.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mf4_analyzer.batch_time_group_acceptance",
            "--output-dir",
            str(output_directory),
            "--result-json",
            str(result_json),
        ],
        cwd=ROOT,
        env=_source_environment(),
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(result_json.read_text(encoding="utf-8"))
    assert evidence["status"] == "success"
    assert evidence["source_count"] == 2
    assert {Path(path).suffix for path in evidence["source_paths"]} == {".csv"}
    assert all(Path(path).is_file() for path in evidence["source_paths"])
    assert evidence["modes"] == {
        "none": {
            "data_count": 4,
            "group_count": 0,
            "image_count": 4,
            "member_linkage": True,
            "task_count": 4,
        },
        "source": {
            "data_count": 4,
            "group_count": 2,
            "image_count": 2,
            "member_linkage": True,
            "task_count": 4,
        },
        "channel": {
            "data_count": 4,
            "group_count": 2,
            "image_count": 2,
            "member_linkage": True,
            "task_count": 4,
        },
    }
    assert evidence["resume"] == {
        "csv_bytes_unchanged": True,
        "csv_mtimes_unchanged": True,
        "deleted_image_recreated": True,
        "resumed_task_count": 4,
    }
    generated_paths = [Path(path) for path in evidence["generated_paths"]]
    assert generated_paths
    assert len(generated_paths) == len(set(generated_paths))
    assert all(path.is_file() and path.stat().st_size > 0 for path in generated_paths)
