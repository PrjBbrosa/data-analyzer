"""Launch and verify the batch-render smoke of a Windows onedir executable."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from PIL import Image


TITLE = "单帧振动加速度"
KINDS = ("time", "fft", "fft_time", "order_time")
FORMATS = ("png", "pdf", "svg")
EXPECTED_NAMES = {
    f"{kind}.{image_format}" for kind in KINDS for image_format in FORMATS
}
TURBO_LOW_RGB = (48, 18, 59)
TURBO_HIGH_RGB = (122, 4, 3)


def _require_program(name: str) -> Path:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required PDF verification program not found: {name}")
    return Path(resolved)


def _poppler_program(name: str) -> Path:
    if name == "pdftocairo":
        pdftotext = _require_program("pdftotext")
        sibling = pdftotext.with_name("pdftocairo.exe")
        if sibling.is_file():
            return sibling
    return _require_program(name)


def _run_checked(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command!r}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed


def _contains_rgb(pixels, expected: tuple[int, int, int], tolerance: int = 1) -> int:
    return sum(
        1
        for pixel in pixels
        if all(abs(int(actual) - wanted) <= tolerance for actual, wanted in zip(pixel, expected))
    )


def verify_artifacts(artifacts: Path, child_json: Path) -> dict[str, object]:
    artifacts = Path(artifacts)
    child = json.loads(Path(child_json).read_text(encoding="utf-8"))
    if child.get("ok") is not True:
        raise RuntimeError(f"render child reported failure: {child}")
    if child.get("title") != TITLE:
        raise RuntimeError("render child did not use the required CJK title")
    glyph_warnings = child.get("glyph_warnings")
    if glyph_warnings != []:
        raise RuntimeError(f"render child reported missing glyphs: {glyph_warnings}")
    actual_names = {path.name for path in artifacts.iterdir() if path.is_file()}
    if actual_names != EXPECTED_NAMES:
        raise RuntimeError(
            f"expected exactly 12 render artifacts; missing={sorted(EXPECTED_NAMES - actual_names)}, "
            f"extra={sorted(actual_names - EXPECTED_NAMES)}"
        )

    artifact_records: list[dict[str, object]] = []
    for name in sorted(EXPECTED_NAMES):
        path = artifacts / name
        content = path.read_bytes()
        if not content:
            raise RuntimeError(f"empty render artifact: {path}")
        suffix = path.suffix.lower()
        if suffix == ".png":
            with Image.open(path) as image:
                image.load()
                if image.format != "PNG" or image.size != (640, 360):
                    raise RuntimeError(f"invalid PNG artifact: {path}")
        elif suffix == ".svg":
            root = ElementTree.parse(path).getroot()
            namespace = {"svg": "http://www.w3.org/2000/svg"}
            svg_text = "\n".join(
                "".join(node.itertext())
                for node in root.findall(".//svg:text", namespace)
            )
            if TITLE not in svg_text or "$raw$" not in svg_text:
                raise RuntimeError(f"SVG lost selectable literal/CJK text: {path}")
        else:
            if not content.startswith(b"%PDF-") or not content.rstrip().endswith(b"%%EOF"):
                raise RuntimeError(f"invalid PDF artifact: {path}")
        artifact_records.append(
            {
                "name": name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    pdftotext = _poppler_program("pdftotext")
    pdftocairo = _poppler_program("pdftocairo")
    extracted_pdf_text: dict[str, str] = {}
    with TemporaryDirectory(prefix="tracelab-pdf-visual-") as raw_directory:
        visual_directory = Path(raw_directory)
        for kind in KINDS:
            pdf = artifacts / f"{kind}.pdf"
            extracted = _run_checked(
                [str(pdftotext), "-enc", "UTF-8", str(pdf), "-"]
            ).stdout
            if TITLE not in extracted or "\ufffd" in extracted or "□" in extracted:
                raise RuntimeError(f"PDF text is missing CJK or contains tofu: {pdf}")
            extracted_pdf_text[kind] = extracted
            output_prefix = visual_directory / kind
            _run_checked(
                [
                    str(pdftocairo),
                    "-png",
                    "-r",
                    "72",
                    "-singlefile",
                    str(pdf),
                    str(output_prefix),
                ]
            )
            with Image.open(output_prefix.with_suffix(".png")) as image:
                grayscale = image.convert("L")
                low, high = grayscale.getextrema()
                if image.width < 320 or image.height < 320 or high - low < 20:
                    raise RuntimeError(f"PDF rasterized to an empty/invalid image: {pdf}")

    for kind in ("fft_time", "order_time"):
        with Image.open(artifacts / f"{kind}.png") as image:
            pixels = list(image.convert("RGB").getdata())
        if _contains_rgb(pixels, TURBO_LOW_RGB) < 1_000:
            raise RuntimeError(f"Turbo low sample missing from {kind}.png")
        if _contains_rgb(pixels, TURBO_HIGH_RGB) < 1_000:
            raise RuntimeError(f"Turbo high sample missing from {kind}.png")

    return {
        "ok": True,
        "title": TITLE,
        "artifact_count": len(artifact_records),
        "artifacts": artifact_records,
        "cjk_glyph_warnings": glyph_warnings,
        "cjk_font_families": child.get("cjk_font_families", []),
        "pdf_text_extractable": True,
        "pdf_visual_nonempty": True,
        "pdf_text": extracted_pdf_text,
        "turbo_samples": {
            "low_rgb": list(TURBO_LOW_RGB),
            "high_rgb": list(TURBO_HIGH_RGB),
        },
    }


def verify_frozen(exe: Path) -> dict[str, object]:
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
        completed = subprocess.run(command, capture_output=True, timeout=240)
        if completed.returncode != 0:
            detail = child_json.read_text(encoding="utf-8") if child_json.is_file() else ""
            raise RuntimeError(
                f"frozen render child failed ({completed.returncode}): {detail}"
            )
        evidence = verify_artifacts(artifacts, child_json)
    evidence["runtime"] = "frozen-onedir-executable"
    evidence["executable"] = str(exe)
    evidence["executable_bytes"] = exe.stat().st_size
    evidence["executable_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--exe", type=Path)
    source.add_argument("--artifacts", type=Path)
    parser.add_argument("--child-json", type=Path)
    parser.add_argument("--evidence-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.exe is not None:
            evidence = verify_frozen(args.exe)
        else:
            if args.child_json is None:
                parser.error("--artifacts requires --child-json")
            evidence = verify_artifacts(args.artifacts, args.child_json)
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
