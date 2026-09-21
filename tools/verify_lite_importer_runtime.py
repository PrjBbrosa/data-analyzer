"""Create representative importer files and smoke-test a frozen lite build."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
import traceback
from tempfile import TemporaryDirectory
import wave

import av
import h5py
import numpy as np
from scipy.io import savemat

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mf4_analyzer.frozen_evidence_paths import (  # noqa: E402
    UnsafeEvidencePath,
    canonical_path,
    reject_aliased_evidence,
)

_IMPORTER_EVIDENCE_MESSAGE = (
    "evidence JSON must not alias the frozen executable, an input fixture, "
    "or the child result JSON"
)
_FIXTURE_NAMES = ("legacy.mat", "sample-v73.mat", "sample.wav", "sample.mp4")


def create_fixtures(directory: Path) -> tuple[Path, Path, Path, Path]:
    """Create MAT, WAV, and MP4-with-audio fixtures in ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    time = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    signal = np.array([1.0, 2.0, 3.0], dtype=np.float64)

    legacy_mat = directory / "legacy.mat"
    savemat(legacy_mat, {"time": time, "signal": signal})

    hdf5_mat = directory / "sample-v73.mat"
    with h5py.File(hdf5_mat, "w", userblock_size=512) as handle:
        handle.create_dataset("time", data=time)
        handle.create_dataset("signal", data=signal)
    with hdf5_mat.open("r+b") as handle:
        header = b"MATLAB 7.3 MAT-file, Platform: TraceLab importer smoke"
        handle.write(header.ljust(124, b" "))
        handle.write(b"\x00\x02IM")

    wav = directory / "sample.wav"
    pcm = (np.array([0.0, 0.25, -0.25, 0.0]) * 32767).astype("<i2")
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(pcm.tobytes())

    mp4 = directory / "sample.mp4"
    with av.open(str(mp4), "w") as container:
        stream = container.add_stream("aac", rate=48_000)
        stream.layout = "mono"
        samples = np.zeros((1, 2_048), dtype=np.float32)
        for start in range(0, samples.shape[1], 1_024):
            frame = av.AudioFrame.from_ndarray(
                samples[:, start : start + 1_024], format="fltp", layout="mono"
            )
            frame.sample_rate = 48_000
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    return legacy_mat, hdf5_mat, wav, mp4


def _planned_protected_files(exe: Path, directory: Path) -> tuple[Path, ...]:
    fixtures = directory / "fixtures"
    return (
        canonical_path(exe),
        canonical_path(directory / "result.json"),
        *(canonical_path(fixtures / name) for name in _FIXTURE_NAMES),
    )


def _reject_evidence_target(
    evidence_json: Path | None,
    exe: Path,
    directory: Path | None,
) -> None:
    if evidence_json is None:
        return
    protected = (canonical_path(exe),)
    if directory is not None:
        protected = _planned_protected_files(exe, directory)
    reject_aliased_evidence(
        canonical_path(evidence_json),
        protected,
        message=_IMPORTER_EVIDENCE_MESSAGE,
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _best_effort_write(stream, text: str) -> None:
    if stream is None:
        return
    try:
        stream.write(text)
    except Exception:
        return


def _evaluate_result(output: Path) -> tuple[int, dict[str, object]]:
    try:
        result = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return 1, {"ok": False, "error": f"Importer smoke did not produce valid JSON: {exc}"}
    records = result.get("files")
    if not isinstance(records, list) or len(records) != 4:
        return 1, {
            "ok": False,
            "error": "Importer smoke did not report all four fixtures",
            "result": result,
        }
    if any(not isinstance(record, dict) or record.get("channels", 0) <= 0 for record in records):
        return 1, {
            "ok": False,
            "error": "Importer smoke reported an empty channel set",
            "result": result,
        }
    return 0, {"ok": True, "result": result}


def verify(
    exe: Path,
    *,
    diagnostics_dir: Path | None = None,
    evidence_json: Path | None = None,
    timeout: float = 60,
) -> int:
    """Run the frozen import child against all generated fixtures.

    Probe truth is the exit code plus ``result.json``. Console streams are
    best-effort and must not be required for a windowed executable.
    """
    exe = canonical_path(exe)
    if evidence_json is not None:
        evidence_json = canonical_path(evidence_json)
    if diagnostics_dir is not None:
        diagnostics_dir = canonical_path(diagnostics_dir)
    try:
        _reject_evidence_target(evidence_json, exe, diagnostics_dir)
    except UnsafeEvidencePath as exc:
        _best_effort_write(sys.stderr, f"{exc}\n")
        return 2
    if diagnostics_dir is not None:
        diagnostics_dir.mkdir(parents=True, exist_ok=False)
    workspace = (
        nullcontext(diagnostics_dir) if diagnostics_dir is not None
        else TemporaryDirectory(prefix="tracelab-importer-smoke-")
    )
    evidence: dict[str, object] = {"ok": False, "runtime": "frozen-importer-smoke"}
    return_code = 1
    with workspace as raw_directory:
        directory = Path(raw_directory)
        try:
            _reject_evidence_target(evidence_json, exe, directory)
        except UnsafeEvidencePath as exc:
            _best_effort_write(sys.stderr, f"{exc}\n")
            return 2
        fixtures_dir = directory / "fixtures"
        paths = create_fixtures(fixtures_dir)
        output = directory / "result.json"
        command = [str(exe), "--importer-runtime-smoke"]
        for path in paths:
            command.extend(("--import-path", str(path)))
        command.extend(("--json", str(output)))
        _write_json(
            directory / "command.json",
            {"argv": command, "timeout_seconds": timeout},
        )
        try:
            with (directory / "stdout.log").open("wb") as stdout, (
                directory / "stderr.log"
            ).open("wb") as stderr:
                completed = subprocess.run(
                    command, stdout=stdout, stderr=stderr, timeout=timeout,
                )
        except subprocess.TimeoutExpired as exc:
            _write_json(
                directory / "timeout.json",
                {
                    "timed_out": True,
                    "timeout_seconds": timeout,
                    "command": command,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            evidence = {
                "ok": False,
                "timed_out": True,
                "timeout_seconds": timeout,
                "error": f"{type(exc).__name__}: {exc}",
                "result_json": str(output),
                "fixtures": [str(path) for path in paths],
            }
            return_code = 1
        except Exception as exc:
            evidence = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            return_code = 1
        else:
            if completed.returncode != 0:
                detail = output.read_text(encoding="utf-8") if output.is_file() else ""
                evidence = {
                    "ok": False,
                    "exit_code": completed.returncode,
                    "error": (
                        f"frozen importer child failed ({completed.returncode}): {detail}"
                    ),
                    "result_json": str(output),
                    "fixtures": [str(path) for path in paths],
                }
                return_code = completed.returncode or 1
            else:
                return_code, evidence = _evaluate_result(output)
                evidence["exit_code"] = completed.returncode
                evidence["result_json"] = str(output)
                evidence["fixtures"] = [str(path) for path in paths]
        evidence.setdefault("runtime", "frozen-importer-smoke")
        evidence["executable"] = str(exe)
        if evidence_json is not None:
            _write_json(Path(evidence_json), evidence)
        elif diagnostics_dir is not None:
            _write_json(directory / "evidence.json", evidence)
        if evidence.get("ok") is True:
            _best_effort_write(
                sys.stdout,
                json.dumps(evidence.get("result"), ensure_ascii=False) + "\n",
            )
        else:
            _best_effort_write(
                sys.stderr,
                f"Frozen importer verification failed: {evidence.get('error')}\n",
            )
        return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="New directory retaining fixtures, child logs, result JSON, and timeout evidence",
    )
    parser.add_argument("--evidence-json", type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    if not args.exe.is_file():
        parser.error(f"frozen executable not found: {args.exe}")
    try:
        _reject_evidence_target(args.evidence_json, args.exe, args.diagnostics_dir)
    except UnsafeEvidencePath as exc:
        parser.error(str(exc))
    return verify(
        args.exe,
        diagnostics_dir=args.diagnostics_dir,
        evidence_json=args.evidence_json,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
