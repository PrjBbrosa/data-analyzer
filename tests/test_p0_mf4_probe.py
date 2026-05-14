import pytest

from can_logger.p0.mf4_probe import write_single_signal_mf4
from mf4_analyzer.io.loader import DataLoader


def test_p0_written_mf4_loads_through_existing_loader(tmp_path):
    out = tmp_path / "p0_single_signal.mf4"

    written = write_single_signal_mf4(
        out,
        signal_name="EngineSpeed",
        unit="rpm",
        timestamps=[0.0, 0.01, 0.02],
        samples=[1000.0, 1010.0, 1020.0],
    )

    assert written == out
    assert out.exists()

    df, channels, units = DataLoader.load_mf4(str(out))

    assert "EngineSpeed" in channels
    assert units["EngineSpeed"] == "rpm"
    assert list(df["EngineSpeed"]) == pytest.approx([1000.0, 1010.0, 1020.0])
