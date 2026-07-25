"""Create representative importer files and smoke-test a frozen lite build."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import wave

import av
import h5py
import numpy as np
from scipy.io import savemat


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


def verify(exe: Path) -> int:
    """Run the frozen import child against all generated fixtures."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="tracelab-importer-smoke-") as raw_directory:
        directory = Path(raw_directory)
        paths = create_fixtures(directory)
        output = directory / "result.json"
        command = [str(exe), "--importer-runtime-smoke"]
        for path in paths:
            command.extend(("--import-path", str(path)))
        command.extend(("--json", str(output)))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            sys.stderr.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            return completed.returncode or 1
        try:
            result = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Importer smoke did not produce valid JSON: {exc}", file=sys.stderr)
            return 1
        records = result.get("files")
        if not isinstance(records, list) or len(records) != 4:
            print("Importer smoke did not report all four fixtures", file=sys.stderr)
            return 1
        if any(not isinstance(record, dict) or record.get("channels", 0) <= 0 for record in records):
            print("Importer smoke reported an empty channel set", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.exe.is_file():
        parser.error(f"frozen executable not found: {args.exe}")
    return verify(args.exe)


if __name__ == "__main__":
    raise SystemExit(main())
