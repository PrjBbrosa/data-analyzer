"""PreviewStore pixel budget, DPR ingest, and derived status (UV-A04/A16/A29)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt5 import sip
from PyQt5.QtGui import QColor, QImage, QPixmap

from mf4_analyzer.ui.chart_stack.ultraview import (
    MAX_PREVIEW_PIXELS,
    MAX_PREVIEW_RAW_EDGE,
    PreviewRecord,
    PreviewStore,
)
from mf4_analyzer.ui.chart_stack.ultraview.preview_store import (
    PREVIEW_RECORD_OVERHEAD_BYTES,
    RESIDENCY_TIER_ACTIVE_PLACED,
    RESIDENCY_TIER_FOCUS,
    RESIDENCY_TIER_INACTIVE_PLACED,
    ResidencyRequest,
)
from mf4_analyzer.ui.ultraview_state import (
    PreviewMeta,
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    derive_preview_status,
    make_ref,
)


def _ref(view_id: str = "view-a", section: str = "time"):
    return make_ref(section, view_id)


def _meta(ref, **kwargs) -> PreviewMeta:
    payload = {
        "ref": ref,
        "axis_kind": "time",
        "x_unit": "s",
        "x_range": (0.0, 1.0),
        "y_unit": "Nm",
        "title": "View A",
        "source_summary": "file.mf4",
        "tab_color": "#1769e0",
    }
    payload.update(kwargs)
    return PreviewMeta(**payload)


def _image(width: int, height: int, *, dpr: float = 1.0, color: str = "#336699") -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(color))
    image.setDevicePixelRatio(dpr)
    return image


def _pixmap(width: int, height: int, *, dpr: float = 1.0) -> QPixmap:
    pix = QPixmap(width, height)
    pix.fill(QColor("#cc3333"))
    pix.setDevicePixelRatio(dpr)
    return pix


def _status(store: PreviewStore, ref, *, exists: bool = True, current_digest: str | None):
    record = store.get(ref)
    return derive_preview_status(
        exists,
        store.image_valid(None if record is None else record.image),
        None if record is None else record.captured_digest,
        current_digest,
    )


def test_preview_store_does_not_connect_destroyed():
    path = (
        Path(__file__).resolve().parents[2]
        / "mf4_analyzer"
        / "ui"
        / "chart_stack"
        / "ultraview"
        / "preview_store.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "destroyed.connect" not in source


def test_preview_store_does_not_import_page_or_compute():
    path = (
        Path(__file__).resolve().parents[2]
        / "mf4_analyzer"
        / "ui"
        / "chart_stack"
        / "ultraview"
        / "preview_store.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    forbidden = {"page", "layouts", "widgets", "compositor", "MainWindow", "numpy"}
    assert forbidden.isdisjoint(imported)


def test_dpr_normalization_and_minimum_valid_dimensions(qapp):
    store = PreviewStore()
    hidpi_ref = _ref("hidpi")
    assert store.publish(
        hidpi_ref,
        _pixmap(200, 100, dpr=2.0),
        digest="dpr-2",
        meta=_meta(hidpi_ref),
    )
    record = store.get(hidpi_ref)
    assert record is not None
    assert isinstance(record.image, QImage)
    assert abs(record.image.devicePixelRatioF() - 1.0) < 1e-9
    assert record.image.width() == 200
    assert record.image.height() == 100
    assert record.image.format() == QImage.Format_ARGB32_Premultiplied

    dpr1_ref = _ref("dpr1")
    assert store.publish(
        dpr1_ref,
        _image(64, 48, dpr=1.0),
        digest="dpr-1",
        meta=_meta(dpr1_ref),
    )
    dpr1 = store.get(dpr1_ref)
    assert dpr1 is not None
    assert dpr1.image.width() == 64
    assert dpr1.image.height() == 48
    assert abs(dpr1.image.devicePixelRatioF() - 1.0) < 1e-9

    tiny_ref = _ref("tiny")
    assert store.publish(tiny_ref, None, digest="none", meta=_meta(tiny_ref)) is False
    assert store.publish(tiny_ref, QImage(), digest="null", meta=_meta(tiny_ref)) is False
    assert store.publish(tiny_ref, _image(1, 1), digest="1x1", meta=_meta(tiny_ref)) is False
    assert store.publish(tiny_ref, _image(7, 100), digest="7x100", meta=_meta(tiny_ref)) is False
    assert store.publish(tiny_ref, _image(100, 7), digest="100x7", meta=_meta(tiny_ref)) is False
    assert store.get(tiny_ref) is None
    assert store.stats().rejections == 5

    min_ref = _ref("min-edge")
    assert store.publish(min_ref, _image(8, 8), digest="8x8", meta=_meta(min_ref))
    min_rec = store.get(min_ref)
    assert min_rec is not None
    assert min_rec.image.width() == 8
    assert min_rec.image.height() == 8

    edge_ref = _ref("edge-1600")
    assert store.publish(
        edge_ref,
        _image(1601, 800),
        digest="edge",
        meta=_meta(edge_ref),
    )
    edge = store.get(edge_ref)
    assert edge is not None
    assert max(edge.image.width(), edge.image.height()) == MAX_PREVIEW_RAW_EDGE
    assert edge.image.width() <= MAX_PREVIEW_RAW_EDGE
    assert edge.image.height() <= MAX_PREVIEW_RAW_EDGE
    assert abs(edge.image.width() / edge.image.height() - 1601 / 800) < 0.02


def test_failed_publish_does_not_overwrite_last_valid_image(qapp):
    store = PreviewStore()
    ref = _ref("keep")
    assert store.publish(ref, _image(32, 24), digest="good", meta=_meta(ref, title="Good"))
    before = store.get(ref)
    assert before is not None
    assert store.publish(ref, _image(1, 1), digest="bad", meta=_meta(ref, title="Bad")) is False
    after = store.get(ref)
    assert after is before
    assert after.captured_digest == "good"
    assert after.title == "Good"
    assert after.image is not None
    assert after.image.width() == 32
    assert after.image.height() == 24
    assert store.stats().rejections == 1


def test_status_is_derived_and_never_optimistically_fresh(qapp):
    store = PreviewStore()
    ref = _ref("status")
    assert store.publish(ref, _image(16, 16), digest="abc", meta=_meta(ref))
    record = store.get(ref)
    assert record is not None
    assert "status" not in PreviewRecord.__dataclass_fields__
    assert _status(store, ref, current_digest="abc") == STATUS_FRESH
    assert _status(store, ref, current_digest="xyz") == STATUS_STALE
    assert _status(store, ref, current_digest=None) == STATUS_STALE
    assert _status(store, ref, exists=False, current_digest="abc") == STATUS_ORPHANED

    record.image = None
    assert _status(store, ref, current_digest="abc") == STATUS_MISSING
    assert _status(store, ref, current_digest=None) == STATUS_MISSING


def test_raw_pixel_budget_lru_stats_and_symmetric_clear(qapp):
    store = PreviewStore()
    dropped = []
    store.images_dropped.connect(lambda refs: dropped.extend(refs))
    refs = [_ref(f"lru-{i}") for i in range(8)]
    for ref in refs:
        assert store.publish(
            ref,
            _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
            digest=ref.view_id,
            meta=_meta(ref, title=ref.view_id),
        )
    stats = store.stats()
    assert stats.raw_pixels <= MAX_PREVIEW_PIXELS
    assert stats.records == 8
    assert stats.images == 6
    assert stats.evictions == 2
    assert stats.estimated_bytes == (
        stats.raw_pixels * 4 + stats.records * PREVIEW_RECORD_OVERHEAD_BYTES
    )
    assert store.get(refs[0]).image is None
    assert store.get(refs[1]).image is None
    assert store.image_valid(store.get(refs[0]).image) is False
    assert _status(store, refs[0], current_digest="lru-0") == STATUS_MISSING
    assert store.get(refs[0]).title == "lru-0"
    assert store.get(refs[0]).captured_digest == "lru-0"
    for ref in refs[2:]:
        assert store.image_valid(store.get(ref).image)
    assert refs[0] in dropped
    assert refs[1] in dropped

    store.clear()
    cleared = store.stats()
    assert cleared.records == 0
    assert cleared.images == 0
    assert cleared.raw_pixels == 0
    assert cleared.estimated_bytes == 0
    assert cleared.evictions == 0
    assert cleared.rejections == 0
    assert store.get(refs[7]) is None


def test_pinned_images_are_preferred_over_lru_unpinned(qapp):
    store = PreviewStore()
    pinned = [_ref(f"pin-{i}") for i in range(6)]
    store.set_pinned_refs(set(pinned))
    for ref in pinned:
        assert store.publish(
            ref,
            _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
            digest=ref.view_id,
            meta=_meta(ref),
        )
    extra = _ref("unpinned-new")
    older = _ref("unpinned-old")
    assert store.publish(
        older,
        _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
        digest="old",
        meta=_meta(older),
    )
    assert store.get(older).image is None
    assert store.stats().evictions == 1
    for ref in pinned:
        assert store.image_valid(store.get(ref).image)

    store.touch(pinned[0])
    assert store.publish(
        extra,
        _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
        digest="new",
        meta=_meta(extra),
    )
    assert store.get(extra).image is None
    for ref in pinned:
        assert store.image_valid(store.get(ref).image)


def test_pinned_over_budget_shrinks_proportionally(qapp):
    store = PreviewStore()
    refs = [_ref(f"shrink-{i}") for i in range(7)]
    store.set_pinned_refs(set(refs))
    for ref in refs:
        assert store.publish(
            ref,
            _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
            digest=ref.view_id,
            meta=_meta(ref),
        )
    stats = store.stats()
    assert stats.images == 7
    assert stats.raw_pixels <= MAX_PREVIEW_PIXELS
    assert stats.evictions == 0
    for ref in refs:
        image = store.get(ref).image
        assert image is not None
        assert max(image.width(), image.height()) < MAX_PREVIEW_RAW_EDGE
        assert store.image_valid(image)


def test_residency_requests_coalesce_shared_refs_without_board_weight(qapp):
    store = PreviewStore()
    refs = [_ref(f"shared-{index}") for index in range(12)]
    # Twenty Boards repeatedly request the same 12 refs.  The Board/slot has
    # deliberately already been removed by the caller before reaching Store.
    requests = []
    for _board in range(20):
        for ref in refs:
            requests.append(
                ResidencyRequest(
                    ref,
                    tier=RESIDENCY_TIER_INACTIVE_PLACED,
                    target_size=(200, 100),
                )
            )
    # A focus request for one of those references must win without another
    # image identity or an aggregate 20-times target budget.
    requests.append(
        ResidencyRequest(
            refs[0], tier=RESIDENCY_TIER_FOCUS, target_size=(640, 480)
        )
    )
    store.set_residency_requests(requests)
    for ref in refs:
        assert store.publish(ref, _image(64, 48), digest=ref.view_id, meta=_meta(ref))

    assert store.stats().records == 12
    assert store.stats().images == 12
    assert store.stats().residency_refs == 12
    request = store.residency_request(refs[0])
    assert request is not None
    assert request.tier == RESIDENCY_TIER_FOCUS
    assert request.target_size == (640, 480)


def test_residency_evicts_inactive_before_active_and_validates_requests(qapp):
    store = PreviewStore()
    active = [_ref(f"active-{index}") for index in range(6)]
    inactive = _ref("inactive")
    store.set_residency_requests(
        [
            *(
                ResidencyRequest(ref, RESIDENCY_TIER_ACTIVE_PLACED)
                for ref in active
            ),
            ResidencyRequest(inactive, RESIDENCY_TIER_INACTIVE_PLACED),
        ]
    )
    for ref in active:
        assert store.publish(
            ref,
            _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
            digest=ref.view_id,
            meta=_meta(ref),
        )
    assert store.publish(
        inactive,
        _image(MAX_PREVIEW_RAW_EDGE, MAX_PREVIEW_RAW_EDGE),
        digest=inactive.view_id,
        meta=_meta(inactive),
    )
    assert store.get(inactive).image is None
    assert all(store.image_valid(store.get(ref).image) for ref in active)

    with pytest.raises(ValueError, match="tier"):
        store.set_residency_requests([ResidencyRequest(active[0], tier=99)])
    with pytest.raises(ValueError, match="target_size"):
        store.set_residency_requests(
            [ResidencyRequest(active[0], target_size=(7, 100))]
        )


def test_drop_clear_and_destroy_release_images(qapp):
    store = PreviewStore()
    keep = _ref("keep")
    gone = _ref("gone")
    assert store.publish(keep, _image(32, 32), digest="keep", meta=_meta(keep))
    assert store.publish(gone, _image(32, 32), digest="gone", meta=_meta(gone))
    store.drop(gone)
    assert store.get(gone) is None
    assert store.get(keep) is not None

    cleared = PreviewStore()
    extra = _ref("clear-me")
    assert cleared.publish(extra, _image(32, 32), digest="c", meta=_meta(extra))
    held_clear = cleared.get(extra)
    cleared.clear()
    assert cleared.get(extra) is None
    assert held_clear.image is None

    cleared.clear()
    assert cleared.get(extra) is None

    held = store.get(keep)
    assert held is not None
    assert held.image is not None
    sip.delete(store)
    assert sip.isdeleted(store)
    # Destroy must not run a Python callback that mutates QImage records.
    # Pixels are released only by an explicit clear() while the QObject lives.
    assert held.image is not None
    assert not held.image.isNull()
