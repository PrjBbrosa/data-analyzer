from pathlib import Path


def test_panel_modes_and_files_align():
    from tools.gen_help_screenshots import PANEL_MODES, PANEL_FILES
    assert PANEL_MODES == ("time", "fft", "fft_time", "order")
    # 每个 mode 都有对应的目标 *-panel.png 文件名
    assert set(PANEL_FILES) == set(PANEL_MODES)
    assert PANEL_FILES["time"] == "time-panel.png"
    assert PANEL_FILES["fft_time"] == "ffttime-panel.png"


def test_synthetic_csv_has_rpm_and_signal():
    from tools.gen_help_screenshots import build_synthetic_csv
    path = build_synthetic_csv()
    assert path.exists()
    header = path.read_text(encoding="utf-8").splitlines()[0]
    for col in ("time", "rpm", "vib", "torque"):
        assert col in header, f"synthetic CSV missing column: {col}"


def test_staging_dir_is_under_output_not_assets():
    from tools.gen_help_screenshots import STAGING_DIR, ASSETS_DIR
    assert STAGING_DIR.parts[-2:] == ("output", "help-shots")
    assert ASSETS_DIR.parts[-3:] == ("mf4_analyzer", "help", "assets")
