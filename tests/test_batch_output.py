from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.batch_output import (
    OutputPublishRace,
    OutputRollbackIncomplete,
    atomic_write,
    atomic_write_set,
    build_task_output_identity,
    choose_output_paths,
    inspect_output_reservation,
    release_output_reservation,
    reserve_output_paths,
    unicode_slug,
)


class _Source:
    def __init__(self, filepath: Path, label_suffix: str = ""):
        self.filepath = filepath
        self.label_suffix = label_suffix
        self.source_metadata = {}


def test_unicode_slug_keeps_cjk_and_removes_only_path_unsafe_characters():
    assert unicode_slug("振动/通道:左侧") == "振动_通道_左侧"


def test_task_output_identity_is_stable_and_separates_source_and_group(tmp_path):
    first = build_task_output_identity(
        _Source(tmp_path / "a" / "同名.hdf", "1x"),
        file_id=1,
        channel="振动",
        method="fft",
        params={"nfft": 1024},
    )
    repeated = build_task_output_identity(
        _Source(tmp_path / "a" / "同名.hdf", "1x"),
        file_id=99,
        channel="振动",
        method="fft",
        params={"nfft": 1024},
    )
    other_source = build_task_output_identity(
        _Source(tmp_path / "b" / "同名.hdf", "1x"),
        file_id=1,
        channel="振动",
        method="fft",
        params={"nfft": 1024},
    )
    other_group = build_task_output_identity(
        _Source(tmp_path / "a" / "同名.hdf", "2x"),
        file_id=1,
        channel="振动",
        method="fft",
        params={"nfft": 1024},
    )

    assert first == repeated
    assert first.task_id != other_source.task_id
    assert first.task_id != other_group.task_id
    assert "同名__1x__振动__fft__" in first.stem


def test_choose_output_paths_auto_numbers_without_overwriting(tmp_path):
    (tmp_path / "result.csv").write_text("old", encoding="utf-8")

    paths = choose_output_paths(tmp_path, "result", ("csv", "png"))

    assert paths["csv"].name == "result__2.csv"
    assert paths["png"].name == "result__2.png"
    assert (tmp_path / "result.csv").read_text(encoding="utf-8") == "old"


def test_atomic_write_replaces_only_after_success_and_cleans_own_temp(tmp_path):
    target = tmp_path / "result.csv"

    atomic_write(target, lambda temp: temp.write_text("complete", encoding="utf-8"))

    assert target.read_text(encoding="utf-8") == "complete"
    assert not list(tmp_path.glob(".result.*.csv"))


def test_atomic_write_failure_leaves_no_final_or_temp_file(tmp_path):
    target = tmp_path / "result.csv"

    def fail(temp):
        temp.write_text("partial", encoding="utf-8")
        raise RuntimeError("simulated write failure")

    with pytest.raises(RuntimeError, match="simulated"):
        atomic_write(target, fail)

    assert not target.exists()
    assert not list(tmp_path.glob(".result.*.csv"))


def test_reserve_output_paths_coordinates_auto_numbered_artifact_set(tmp_path):
    (tmp_path / "result.csv").write_text("old", encoding="utf-8")

    reservation = reserve_output_paths(
        tmp_path, "result", ("csv", "png"),
        conflict_policy="auto_number",
    )
    try:
        assert reservation.status == "reserved"
        assert reservation.paths["csv"].name == "result__2.csv"
        assert reservation.paths["png"].name == "result__2.png"
    finally:
        reservation.release()


def test_active_reservation_forces_competing_auto_number_to_next_suffix(tmp_path):
    first = reserve_output_paths(tmp_path, "result", ("csv", "png"))
    second = reserve_output_paths(tmp_path, "result", ("csv", "png"))
    try:
        assert first.paths["csv"].name == "result.csv"
        assert second.paths["csv"].name == "result__2.csv"
        assert second.paths["png"].name == "result__2.png"
    finally:
        second.release()
        first.release()


def test_conflict_error_skip_and_overwrite_have_frozen_task_level_semantics(tmp_path):
    (tmp_path / "result.csv").write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        reserve_output_paths(
            tmp_path, "result", ("csv", "png"), conflict_policy="error",
        )

    skipped = reserve_output_paths(
        tmp_path, "result", ("csv", "png"), conflict_policy="skip",
    )
    assert skipped.status == "skipped"
    assert "manifest" in skipped.warning
    assert skipped.paths["csv"].name == "result.csv"

    overwrite = reserve_output_paths(
        tmp_path, "result", ("csv", "png"), conflict_policy="overwrite",
    )
    try:
        assert overwrite.status == "reserved"
        assert overwrite.paths["csv"].name == "result.csv"
        assert overwrite.paths["png"].name == "result.png"
        assert (tmp_path / "result.csv").read_text(encoding="utf-8") == "old"
    finally:
        overwrite.release()


def test_atomic_write_set_stages_every_writer_before_overwrite_publication(tmp_path):
    csv_path = tmp_path / "result.csv"
    png_path = tmp_path / "result.png"
    csv_path.write_text("old-csv", encoding="utf-8")
    png_path.write_bytes(b"old-png")
    reservation = reserve_output_paths(
        tmp_path, "result", ("csv", "png"), conflict_policy="overwrite",
    )

    def fail_image(path):
        path.write_bytes(b"partial-new-image")
        raise RuntimeError("render failed")

    with pytest.raises(RuntimeError, match="render failed"):
        atomic_write_set(
            reservation,
            {
                "csv": lambda path: path.write_text("new-csv", encoding="utf-8"),
                "png": fail_image,
            },
        )

    assert csv_path.read_text(encoding="utf-8") == "old-csv"
    assert png_path.read_bytes() == b"old-png"
    assert not list(tmp_path.glob(".*.batch-stage.*"))


def test_atomic_write_set_publishes_coordinated_suffix_and_releases_lock(tmp_path):
    (tmp_path / "result.csv").write_text("old", encoding="utf-8")
    reservation = reserve_output_paths(
        tmp_path, "result", ("csv", "png"), conflict_policy="auto_number",
    )

    published = atomic_write_set(
        reservation,
        {
            "csv": lambda path: path.write_text("new", encoding="utf-8"),
            "png": lambda path: path.write_bytes(b"png"),
        },
    )

    assert published["csv"].name == "result__2.csv"
    assert published["png"].name == "result__2.png"
    assert not list(tmp_path.glob(".*.batch-reserve"))


def test_atomic_write_never_replaces_a_target_that_appears_during_write(tmp_path):
    target = tmp_path / "result.csv"

    def race(temp):
        temp.write_text("ours", encoding="utf-8")
        target.write_text("racer", encoding="utf-8")

    with pytest.raises(OutputPublishRace):
        atomic_write(target, race)

    assert target.read_text(encoding="utf-8") == "racer"


def test_atomic_set_rollback_never_unlinks_outsider_replacement(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_output as batch_output

    reservation = reserve_output_paths(
        tmp_path, "result", ("csv", "png"), conflict_policy="auto_number",
    )
    original_publish = batch_output._publish_no_replace

    def publish_with_two_races(temp, target):
        if target.suffix == ".png":
            target.write_bytes(b"outsider-png")
            return original_publish(temp, target)
        original_publish(temp, target)
        target.unlink()
        target.write_text("outsider-csv", encoding="utf-8")

    monkeypatch.setattr(
        batch_output, "_publish_no_replace", publish_with_two_races,
    )

    with pytest.raises(OutputRollbackIncomplete, match="unknown owner"):
        atomic_write_set(
            reservation,
            {
                "csv": lambda path: path.write_text("ours", encoding="utf-8"),
                "png": lambda path: path.write_bytes(b"ours-png"),
            },
        )

    assert (tmp_path / "result.csv").read_text(encoding="utf-8") == "outsider-csv"
    assert (tmp_path / "result.png").read_bytes() == b"outsider-png"


def test_overwrite_rollback_never_restores_over_outsider_replacement(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_output as batch_output

    csv_path = tmp_path / "result.csv"
    png_path = tmp_path / "result.png"
    csv_path.write_text("old-csv", encoding="utf-8")
    png_path.write_bytes(b"old-png")
    reservation = reserve_output_paths(
        tmp_path, "result", ("csv", "png"), conflict_policy="overwrite",
    )
    original_replace = batch_output.os.replace

    def replace_with_outsider(source, target):
        source = Path(source)
        target = Path(target)
        is_publication = ".batch-stage." in source.name
        if is_publication and target == png_path:
            raise OSError("second artifact publish failed")
        result = original_replace(source, target)
        if is_publication and target == csv_path:
            target.unlink()
            target.write_text("outsider-csv", encoding="utf-8")
        return result

    monkeypatch.setattr(batch_output.os, "replace", replace_with_outsider)

    with pytest.raises(OutputRollbackIncomplete, match="unknown owner"):
        atomic_write_set(
            reservation,
            {
                "csv": lambda path: path.write_text("new-csv", encoding="utf-8"),
                "png": lambda path: path.write_bytes(b"new-png"),
            },
        )

    assert csv_path.read_text(encoding="utf-8") == "outsider-csv"
    assert png_path.read_bytes() == b"old-png"


def test_reservation_token_has_inspectable_owner_and_explicit_safe_release(tmp_path):
    first = reserve_output_paths(
        tmp_path, "result", ("csv",), conflict_policy="error",
    )
    info = inspect_output_reservation(first.token_path)

    assert info is not None
    assert info.metadata["schema_version"] == 1
    assert info.metadata["stem"] == "result"
    assert isinstance(info.metadata["pid"], int)
    assert info.metadata["created_at"].endswith("Z")
    with pytest.raises(
        FileExistsError, match="active or stale.*explicit inspect/release",
    ):
        reserve_output_paths(
            tmp_path, "result", ("csv",), conflict_policy="error",
        )

    release_output_reservation(info)
    replacement = reserve_output_paths(
        tmp_path, "result", ("csv",), conflict_policy="error",
    )
    replacement.release()
    first.release()


def test_explicit_reservation_release_refuses_changed_token(tmp_path):
    reservation = reserve_output_paths(
        tmp_path, "result", ("csv",), conflict_policy="error",
    )
    info = inspect_output_reservation(reservation.token_path)
    reservation.token_path.unlink()
    reservation.token_path.write_text("replacement owner", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed since inspection"):
        release_output_reservation(info)

    assert reservation.token_path.read_text(encoding="utf-8") == "replacement owner"
    reservation.release()


def test_reservation_inspection_refuses_non_token_path(tmp_path):
    unrelated = tmp_path / "measurement.csv"
    unrelated.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="batch-reserve"):
        inspect_output_reservation(unrelated)

    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_automatic_reservation_release_never_unlinks_replaced_token(tmp_path):
    reservation = reserve_output_paths(
        tmp_path, "result", ("csv",), conflict_policy="error",
    )
    reservation.token_path.unlink()
    reservation.token_path.write_text("outsider token", encoding="utf-8")

    reservation.release()

    assert reservation.token_path.read_text(encoding="utf-8") == "outsider token"
    reservation.token_path.unlink()
