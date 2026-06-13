# tests/ui/test_mdf_open.py
"""MDF v3 (.mdf) support — the UI dispatch must route .mdf to load_mf4,
not the CSV fallback. See docs/reports/2026-06-12-mf4-association-mdf-comment-feasibility.md
problem #2 ("新增 mdf 格式支持")."""
from tests._helpers.mf4_factory import write_single_channel_mdf


def test_load_one_routes_mdf_to_mf4_loader(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    mdf = write_single_channel_mdf(tmp_path / "v3.mdf", name="rpm", unit="rpm")
    mw = MainWindow()
    mw._load_one(str(mdf))

    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert "rpm" in fd.channels
