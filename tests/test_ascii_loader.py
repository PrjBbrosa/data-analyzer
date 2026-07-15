"""Evidence-based ASCII loader coverage."""

import pytest

from mf4_analyzer.io.loader import DataLoader


def _fixed_width_text(*, signature=True, interval=True):
    lines = [
        "WinWertASCIIDaten" if signature else "Generic fixed-width export",
        "2026-07-15\tcapture.asc",
        "capture",
        "",
        "",
        "",
        "0.000500" if interval else "metadata",
        "0",
        "2",
        f"{8:17}{8:17}",
        f"{0:17}{0:17}",
        f"{'Load':>17}{'Speed':>17}",
        f"{'Nm':>17}{'rpm':>17}",
    ]
    lines.extend(
        f"{float(i):17.6E}{float(i * 10):17.6E}"
        for i in range(8)
    )
    return "\n".join(lines) + "\n"


def test_load_ascii_keeps_delimited_time_table(tmp_path):
    path = tmp_path / "table.asc"
    path.write_text("Time\tSpeed\n0.0\t10\n0.1\t11\n", encoding="utf-8")

    data, channels, units, fs, metadata = DataLoader.load_ascii(path)

    assert channels == ["Time", "Speed"]
    assert list(data["Speed"]) == [10, 11]
    assert units == {}
    assert fs is None
    assert metadata["ascii_kind"] == "delimited"


def test_load_ascii_reads_verified_fixed_width_metadata(tmp_path):
    path = tmp_path / "fixed.asc"
    path.write_text(_fixed_width_text(), encoding="utf-8")

    data, channels, units, fs, metadata = DataLoader.load_ascii(path)

    assert channels == ["Load", "Speed"]
    assert list(data.iloc[0]) == [0.0, 0.0]
    assert units == {"Load": "Nm", "Speed": "rpm"}
    assert fs == pytest.approx(2000.0)
    assert metadata["ascii_kind"] == "fixed_width"
    assert metadata["ascii_confidence"] == "high"


def test_load_ascii_rejects_fixed_width_without_time_evidence(tmp_path):
    path = tmp_path / "unknown_rate.asc"
    path.write_text(_fixed_width_text(signature=False, interval=False), encoding="utf-8")

    with pytest.raises(ValueError, match="sampling rate"):
        DataLoader.load_ascii(path)


def test_load_ascii_does_not_mistake_unheaded_numeric_text_for_table(tmp_path):
    path = tmp_path / "numbers.asc"
    path.write_text("\n".join("1.0 2.0" for _ in range(8)), encoding="utf-8")

    with pytest.raises(ValueError, match="ASCII"):
        DataLoader.load_ascii(path)
