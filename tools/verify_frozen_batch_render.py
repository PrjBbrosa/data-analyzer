"""Launch and verify the batch-render smoke of a Windows onedir executable."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
from PyQt5.QtGui import QImage, QImageReader


TITLE = "单帧振动加速度"
KINDS = ("time", "fft", "fft_time", "order_time")
FORMATS = ("png",)
EXPECTED_NAMES = {
    f"{kind}.{image_format}" for kind in KINDS for image_format in FORMATS
}
TURBO_LOW_RGB = (48, 18, 59)
TURBO_HIGH_RGB = (122, 4, 3)


def _tree_measurement(directory: Path) -> dict[str, object]:
    directory = Path(directory).resolve()
    if directory.name != "_internal" or not directory.is_dir():
        raise ValueError(f"expected an existing _internal directory: {directory}")
    files = tuple(path for path in directory.rglob("*") if path.is_file())
    return {
        "path": str(directory),
        "bytes": sum(path.stat().st_size for path in files),
        "files": len(files),
    }


def _contains_rgb(
    image: QImage, expected: tuple[int, int, int], tolerance: int = 1
) -> int:
    converted = image.convertToFormat(QImage.Format_RGB888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    rows = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.bytesPerLine()
    )
    pixels = rows[:, : converted.width() * 3].reshape(
        converted.height(), converted.width(), 3
    )
    wanted = np.asarray(expected, dtype=np.int16)
    delta = np.abs(pixels.astype(np.int16) - wanted)
    return int(np.count_nonzero(np.all(delta <= tolerance, axis=2)))


def verify_artifacts(
    artifacts: Path, child_json: Path, expected_platform: str
) -> dict[str, object]:
    artifacts = Path(artifacts)
    child = json.loads(Path(child_json).read_text(encoding="utf-8"))
    if child.get("ok") is not True:
        raise RuntimeError(f"render child reported failure: {child}")
    if child.get("title") != TITLE:
        raise RuntimeError("render child did not use the required CJK title")
    qt_qpa_platform = str(child.get("qt_qpa_platform") or "")
    qt_platform_name = str(child.get("qt_platform_name") or "")
    if not qt_qpa_platform or not qt_platform_name:
        raise RuntimeError("render child did not report requested and actual Qt platforms")
    if (
        qt_qpa_platform.lower() != expected_platform.lower()
        or qt_platform_name.lower() != expected_platform.lower()
    ):
        raise RuntimeError(
            f"requested Qt platform {expected_platform!s}, but child reported "
            f"QT_QPA_PLATFORM={qt_qpa_platform!r} and platformName={qt_platform_name!r}"
        )
    cjk_proof = child.get("cjk_proof") or {}
    ink_pixels = int(cjk_proof.get("ink_pixels") or 0)
    empty_ink_pixels = int(cjk_proof.get("empty_ink_pixels") or 0)
    if (
        cjk_proof.get("supports") is not True
        or cjk_proof.get("pass") is not True
        or ink_pixels <= empty_ink_pixels + 120
    ):
        raise RuntimeError(f"render child CJK double proof failed: {cjk_proof}")
    actual_names = {path.name for path in artifacts.iterdir() if path.is_file()}
    if actual_names != EXPECTED_NAMES:
        raise RuntimeError(
            f"expected exactly 4 render artifacts; missing={sorted(EXPECTED_NAMES - actual_names)}, "
            f"extra={sorted(actual_names - EXPECTED_NAMES)}"
        )

    artifact_records: list[dict[str, object]] = []
    for name in sorted(EXPECTED_NAMES):
        path = artifacts / name
        content = path.read_bytes()
        if not content:
            raise RuntimeError(f"empty render artifact: {path}")
        image = QImage(str(path))
        encoded_format = bytes(QImageReader.imageFormat(str(path))).lower()
        if (
            image.isNull()
            or encoded_format != b"png"
            or (image.width(), image.height()) != (640, 360)
        ):
            raise RuntimeError(f"invalid PNG artifact: {path}")
        artifact_records.append(
            {
                "name": name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "width": image.width(),
                "height": image.height(),
            }
        )

    for kind in ("fft_time", "order_time"):
        image = QImage(str(artifacts / f"{kind}.png"))
        if _contains_rgb(image, TURBO_LOW_RGB) < 1_000:
            raise RuntimeError(f"Turbo low sample missing from {kind}.png")
        if _contains_rgb(image, TURBO_HIGH_RGB) < 1_000:
            raise RuntimeError(f"Turbo high sample missing from {kind}.png")

    return {
        "ok": True,
        "title": TITLE,
        "artifact_count": len(artifact_records),
        "artifacts": artifact_records,
        "requested_qt_platform": expected_platform,
        "qt_qpa_platform": qt_qpa_platform,
        "qt_platform_name": qt_platform_name,
        "cjk_proof": cjk_proof,
        "cjk_font_families": child.get("cjk_font_families", []),
        "turbo_samples": {
            "low_rgb": list(TURBO_LOW_RGB),
            "high_rgb": list(TURBO_HIGH_RGB),
        },
    }


def verify_frozen(exe: Path, expected_platform: str) -> dict[str, object]:
    exe = Path(exe).resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"frozen executable not found: {exe}")
    with TemporaryDirectory(prefix="tracelab-frozen-render-") as raw_directory:
        directory = Path(raw_directory)
        artifacts = directory / "outputs"
        child_json = directory / "child.json"
        command = [
            str(exe),
            "--batch-render-runtime-smoke",
            "--output-dir",
            str(artifacts),
            "--json",
            str(child_json),
        ]
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = expected_platform
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=240,
            env=environment,
        )
        if completed.returncode != 0:
            detail = child_json.read_text(encoding="utf-8") if child_json.is_file() else ""
            raise RuntimeError(
                f"frozen render child failed ({completed.returncode}): {detail}"
            )
        evidence = verify_artifacts(artifacts, child_json, expected_platform)
    evidence["runtime"] = "frozen-onedir-executable"
    evidence["executable"] = str(exe)
    evidence["executable_bytes"] = exe.stat().st_size
    evidence["executable_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
    evidence["internal"] = _tree_measurement(exe.parent / "_internal")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--exe", type=Path)
    source.add_argument("--artifacts", type=Path)
    parser.add_argument("--child-json", type=Path)
    parser.add_argument(
        "--platform", choices=("offscreen", "windows"), required=True
    )
    parser.add_argument("--evidence-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.exe is not None:
            evidence = verify_frozen(args.exe, args.platform)
        else:
            if args.child_json is None:
                parser.error("--artifacts requires --child-json")
            evidence = verify_artifacts(
                args.artifacts, args.child_json, args.platform
            )
            evidence["runtime"] = "artifact-validation-only"
    except Exception as exc:
        evidence = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return_code = 1
    else:
        return_code = 0
    args.evidence_json.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_json.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if return_code and sys.stderr is not None:
        sys.stderr.write(f"Frozen batch render verification failed: {evidence['error']}\n")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
