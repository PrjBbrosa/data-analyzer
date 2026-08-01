from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from mf4_analyzer.batch_render import BatchSeries


def _series(*, panel: int = 0, size: int = 3) -> BatchSeries:
    return BatchSeries(
        x=np.arange(size, dtype=float),
        y=np.arange(size, dtype=float) + 10.0,
        label="source / signal",
        unit="m/s2",
        x_unit="s",
        linestyle="--",
        panel=panel,
    )


def test_spool_round_trip_preserves_arrays_metadata_and_uses_mmap(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_series_spool as spool_module
    from mf4_analyzer.batch_series_spool import BatchSeriesSpool

    mmap_modes = []
    real_load = spool_module.np.load

    def recording_load(*args, **kwargs):
        mmap_modes.append(kwargs.get("mmap_mode"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(spool_module.np, "load", recording_load)
    original = _series(panel=2)

    with BatchSeriesSpool(directory=tmp_path) as spool:
        refs = spool.append("group", "task", (original,))
        loaded = spool.load(refs)

        assert refs[0].x_path.suffix == refs[0].y_path.suffix == ".npy"
        assert refs[0].label == original.label
        assert refs[0].unit == original.unit
        assert refs[0].x_unit == original.x_unit
        assert refs[0].linestyle == original.linestyle
        assert refs[0].panel == original.panel
        assert refs[0].nbytes == original.x.nbytes + original.y.nbytes
        with pytest.raises(FrozenInstanceError):
            refs[0].label = "mutated"
        np.testing.assert_array_equal(loaded[0].x, original.x)
        np.testing.assert_array_equal(loaded[0].y, original.y)
        assert mmap_modes == ["r", "r"]


def test_spool_context_cleanup_removes_only_its_private_directory(tmp_path):
    from mf4_analyzer.batch_series_spool import BatchSeriesSpool

    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")

    with BatchSeriesSpool(directory=tmp_path) as spool:
        refs = spool.append("group", "task", (_series(),))
        private_directory = refs[0].x_path.parent
        assert private_directory.parent == tmp_path
        assert private_directory.is_dir()

    assert not private_directory.exists()
    assert sibling.read_text(encoding="utf-8") == "keep"


def test_spool_context_cleanup_runs_after_exception(tmp_path):
    from mf4_analyzer.batch_series_spool import BatchSeriesSpool

    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")
    private_directory = None

    with pytest.raises(RuntimeError, match="boom"):
        with BatchSeriesSpool(directory=tmp_path) as spool:
            refs = spool.append("group", "task", (_series(),))
            private_directory = refs[0].x_path.parent
            raise RuntimeError("boom")

    assert private_directory is not None and not private_directory.exists()
    assert sibling.exists()


def test_group_payload_limit_is_checked_before_any_array_write(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_series_spool as spool_module

    monkeypatch.setattr(spool_module, "_MAX_GROUP_PAYLOAD_BYTES", 1)

    def forbidden_save(*_args, **_kwargs):
        pytest.fail("oversized payload must be rejected before np.save")

    monkeypatch.setattr(spool_module.np, "save", forbidden_save)
    with spool_module.BatchSeriesSpool(directory=tmp_path) as spool:
        with pytest.raises(ValueError, match="group payload"):
            spool.append("group", "task", (_series(size=1),))


def test_run_spool_limit_is_checked_before_appending_next_payload(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_series_spool as spool_module

    monkeypatch.setattr(spool_module, "_MAX_GROUP_PAYLOAD_BYTES", 1024)
    monkeypatch.setattr(spool_module, "_MAX_SPOOL_BYTES", 31)
    save_calls = []
    real_save = spool_module.np.save

    def recording_save(*args, **kwargs):
        save_calls.append(args[0])
        return real_save(*args, **kwargs)

    monkeypatch.setattr(spool_module.np, "save", recording_save)
    with spool_module.BatchSeriesSpool(directory=tmp_path) as spool:
        spool.append("first", "task-1", (_series(size=1),))
        with pytest.raises(ValueError, match="run spool"):
            spool.append("second", "task-2", (_series(size=1),))

    assert len(save_calls) == 2


def test_group_member_and_subplot_panel_limits_are_enforced_before_write(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_series_spool as spool_module

    monkeypatch.setattr(spool_module, "_MAX_GROUP_MEMBERS", 1)
    monkeypatch.setattr(spool_module, "_MAX_SUBPLOT_PANELS", 1)
    with spool_module.BatchSeriesSpool(directory=tmp_path) as spool:
        spool.append("members", "task-1", (_series(),))
        with pytest.raises(ValueError, match="group members"):
            spool.append("members", "task-2", (_series(),))
        with pytest.raises(ValueError, match="subplot panels"):
            spool.append(
                "panels",
                "task-3",
                (_series(panel=0), _series(panel=1)),
            )


def test_spool_ignores_all_empty_sparse_series_when_counting_active_panels(
    tmp_path,
):
    from mf4_analyzer.batch_series_spool import BatchSeriesSpool

    empty_series = tuple(
        _series(panel=panel, size=0)
        for panel in (1, 4, 8, 15, 16, 23, 42, 81, 100)
    )

    with BatchSeriesSpool(directory=tmp_path) as spool:
        refs = spool.append("all-empty", "task", empty_series)

    assert len(refs) == 9
    assert all(ref.nbytes == 0 for ref in refs)


def test_spool_allows_exact_member_and_active_panel_limits(tmp_path):
    from mf4_analyzer.batch_series_spool import BatchSeriesSpool

    with BatchSeriesSpool(directory=tmp_path) as spool:
        for member in range(32):
            spool.append("members", f"task-{member}", ())
        with pytest.raises(ValueError, match="group members"):
            spool.append("members", "task-32", ())

        refs = spool.append(
            "panels",
            "task",
            tuple(_series(panel=panel, size=1) for panel in range(8)),
        )
        with pytest.raises(ValueError, match="subplot panels"):
            spool.append("panels", "task-2", (_series(panel=8, size=1),))

    assert len(refs) == 8


def test_spool_allows_exact_group_and_run_byte_limits(tmp_path, monkeypatch):
    import mf4_analyzer.batch_series_spool as spool_module

    # A one-sample float64 X/Y pair is exactly 16 payload bytes. Two distinct
    # groups therefore exercise exact 16-byte group and 32-byte run limits
    # without allocating or writing a large fixture.
    monkeypatch.setattr(spool_module, "_MAX_GROUP_PAYLOAD_BYTES", 16)
    monkeypatch.setattr(spool_module, "_MAX_SPOOL_BYTES", 32)

    with spool_module.BatchSeriesSpool(directory=tmp_path) as spool:
        first = spool.append("group-1", "task-1", (_series(size=1),))
        second = spool.append("group-2", "task-2", (_series(size=1),))
        with pytest.raises(ValueError, match="group payload"):
            spool.append("group-1", "task-3", (_series(size=1),))
        with pytest.raises(ValueError, match="run spool"):
            spool.append("group-3", "task-4", (_series(size=1),))

    assert first[0].nbytes == second[0].nbytes == 16
