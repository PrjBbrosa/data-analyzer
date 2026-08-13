"""Validated, optional UltraView preview sidecar storage (UV-P1-A08/A09)."""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QColor, QImage

from mf4_analyzer.ui.chart_stack.ultraview.preview_sidecar import (
    SIDECAR_FORMAT,
    canonical_ref_hash,
    restore_preview_sidecar,
    save_preview_sidecar,
)
from mf4_analyzer.ui.chart_stack.ultraview.preview_store import PreviewStore
from mf4_analyzer.ui.ultraview_state import PreviewMeta, make_ref


def _image(width: int = 32, height: int = 24, color: str = "#335577") -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(color))
    return image


def _meta(ref, **overrides) -> PreviewMeta:
    values = {
        "ref": ref,
        "captured_at": 1234.5,
        "axis_kind": "time",
        "x_unit": "s",
        "x_range": (0.0, 1.0),
        "y_unit": "Nm",
        "title": "A preview",
        "source_summary": "run-01.mf4",
        "tab_color": "#335577",
    }
    values.update(overrides)
    return PreviewMeta(**values)


def _workspace(*refs):
    """Two Boards deliberately repeat the first ref."""
    return {
        "schema": 2,
        "workspace": {
            "boards": [
                {
                    "placements": [
                        {"slot_id": "primary", **ref.to_dict()} for ref in refs
                    ],
                    "unplaced": [],
                },
                {
                    "placements": [
                        {"slot_id": "primary", **refs[0].to_dict()}
                    ],
                    "unplaced": list(ref.to_dict() for ref in refs[1:]),
                },
            ]
        },
    }


def _png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    assert buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def _manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def test_sidecar_saves_unique_workspace_membership_and_round_trips(qapp, tmp_path):
    first = make_ref("time", "view-a")
    second = make_ref("fft", "view-a")
    store = PreviewStore()
    assert store.publish(first, _image(), digest="digest-a", meta=_meta(first))
    assert store.publish(second, _image(color="#884422"), digest="digest-b", meta=_meta(second))

    project = tmp_path / "session.tlproj"
    saved = save_preview_sidecar(project, _workspace(first, second), store)

    assert saved.ok
    assert saved.descriptor is not None
    assert saved.saved_refs == (first, second)
    assert saved.descriptor["format"] == SIDECAR_FORMAT
    assert not Path(saved.descriptor["path"]).is_absolute()
    archive = tmp_path / saved.descriptor["path"]
    assert archive.is_file()

    with zipfile.ZipFile(archive) as bundle:
        manifest_bytes = bundle.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        assert manifest["format"] == SIDECAR_FORMAT
        assert len(manifest["entries"]) == 2
        assert {
            entry["image"] for entry in manifest["entries"]
        } == {
            f"images/{canonical_ref_hash(first)}.png",
            f"images/{canonical_ref_hash(second)}.png",
        }
    assert saved.descriptor["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()

    restored = PreviewStore()
    loaded = restore_preview_sidecar(
        project,
        _workspace(first, second),
        restored,
        saved.descriptor,
    )
    assert loaded.ok
    assert loaded.loaded_refs == (first, second)
    assert restored.get(first).captured_digest == "digest-a"
    assert restored.get(first).title == "A preview"
    assert restored.image_valid(restored.get(second).image)


def test_workspace_membership_reads_p2_free_grid_placements(qapp, tmp_path):
    ref = make_ref("time", "free-grid-view")
    payload = {
        "schema": 3,
        "workspace": {
            "boards": [
                {
                    "layout_mode": "free_grid",
                    "free_grid": {
                        "placements": [
                            {
                                "section": ref.section,
                                "view_id": ref.view_id,
                                "column": 0,
                                "row": 0,
                                "column_span": 6,
                                "row_span": 4,
                            }
                        ]
                    },
                    "unplaced": [],
                }
            ]
        },
    }
    store = PreviewStore()
    assert store.publish(ref, _image(), digest="free", meta=_meta(ref))
    result = save_preview_sidecar(tmp_path / "session.tlproj", payload, store)

    assert result.ok
    assert result.saved_refs == (ref,)


def test_sidecar_restore_rejects_traversal_and_bad_manifest_hash(qapp, tmp_path):
    ref = make_ref("time", "view-a")
    store = PreviewStore()
    assert store.publish(ref, _image(), digest="digest", meta=_meta(ref))
    project = tmp_path / "session.tlproj"
    saved = save_preview_sidecar(project, _workspace(ref), store)
    assert saved.descriptor is not None

    traversal = dict(saved.descriptor, path="../outside.uvpz")
    restored = PreviewStore()
    result = restore_preview_sidecar(project, _workspace(ref), restored, traversal)
    assert not result.ok
    assert result.loaded_refs == ()
    assert {warning.code for warning in result.warnings} == {"sidecar_path_invalid"}

    bad_hash = dict(saved.descriptor, manifest_sha256="0" * 64)
    result = restore_preview_sidecar(project, _workspace(ref), restored, bad_hash)
    assert not result.ok
    assert {warning.code for warning in result.warnings} == {"manifest_hash_mismatch"}
    assert restored.get(ref) is None


def test_sidecar_restore_rejects_symlinked_sidecar_directory(qapp, tmp_path):
    ref = make_ref("time", "view-a")
    store = PreviewStore()
    assert store.publish(ref, _image(), digest="digest", meta=_meta(ref))
    project = tmp_path / "session.tlproj"
    saved = save_preview_sidecar(project, _workspace(ref), store)
    assert saved.descriptor is not None
    original_dir = Path(f"{project}.ultraview")
    moved_dir = tmp_path / "real-sidecar"
    original_dir.rename(moved_dir)
    try:
        os.symlink(moved_dir, original_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"filesystem does not support symlink test: {exc}")

    result = restore_preview_sidecar(
        project,
        _workspace(ref),
        PreviewStore(),
        saved.descriptor,
    )
    assert not result.ok
    assert {warning.code for warning in result.warnings} == {"sidecar_missing"}


def test_sidecar_rejects_only_the_bad_png_and_keeps_other_valid_refs(qapp, tmp_path):
    first = make_ref("time", "view-a")
    second = make_ref("fft", "view-b")
    project = tmp_path / "session.tlproj"
    sidecar_dir = Path(f"{project}.ultraview")
    sidecar_dir.mkdir()
    generation = "generation123"
    archive = sidecar_dir / f"{generation}.uvpz"
    first_png = _png_bytes(_image())
    second_png = _png_bytes(_image(color="#aa3322"))
    entries = []
    for ref, image_bytes, digest in (
        (first, first_png, "first"),
        (second, second_png, "second"),
    ):
        entries.append(
            {
                "ref": ref.to_dict(),
                "image": f"images/{canonical_ref_hash(ref)}.png",
                "captured_digest": digest,
                "meta": {
                    "captured_at": 1.0,
                    "axis_kind": "time",
                    "x_unit": "s",
                    "x_range": [0.0, 1.0],
                    "y_unit": "Nm",
                    "title": ref.view_id,
                    "source_summary": "source",
                    "tab_color": "#123456",
                },
                "width": 32,
                "height": 24,
                "bytes": len(image_bytes),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
        )
    manifest = {"format": SIDECAR_FORMAT, "generation": generation, "entries": entries}
    manifest_bytes = _manifest_bytes(manifest)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", manifest_bytes)
        bundle.writestr(entries[0]["image"], first_png)
        bundle.writestr(entries[1]["image"], second_png + b"tampered")

    descriptor = {
        "format": SIDECAR_FORMAT,
        "path": archive.relative_to(tmp_path).as_posix(),
        "generation": generation,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    restored = PreviewStore()
    result = restore_preview_sidecar(project, _workspace(first, second), restored, descriptor)

    assert result.loaded_refs == (first,)
    assert result.rejected_refs == (second,)
    assert restored.get(first) is not None
    assert restored.get(second) is None
    assert {warning.code for warning in result.warnings} == {"image_hash_mismatch"}


def test_sidecar_atomic_failure_preserves_old_generation_and_removes_own_temp(
    qapp, tmp_path, monkeypatch
):
    ref = make_ref("time", "view-a")
    store = PreviewStore()
    assert store.publish(ref, _image(), digest="digest", meta=_meta(ref))
    project = tmp_path / "session.tlproj"
    sidecar_dir = Path(f"{project}.ultraview")
    sidecar_dir.mkdir()
    final = sidecar_dir / "known-generation.uvpz"
    final.write_bytes(b"previous-generation")

    def fail_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.ultraview.preview_sidecar.os.replace",
        fail_replace,
    )
    result = save_preview_sidecar(
        project,
        _workspace(ref),
        store,
        generation="known-generation",
    )

    assert not result.ok
    assert result.descriptor is None
    assert final.read_bytes() == b"previous-generation"
    assert not list(sidecar_dir.glob(".*.tmp"))
    assert {warning.code for warning in result.warnings} == {"sidecar_write_failed"}


def test_sidecar_module_has_no_compute_or_window_imports():
    path = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui" / "chart_stack" / "ultraview" / "preview_sidecar.py"
    source = path.read_text(encoding="utf-8")
    forbidden = ("MainWindow", "ultraview_coordinator", "batch_compute", "do_fft", "do_frf")
    assert not any(token in source for token in forbidden)
