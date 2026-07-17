from pathlib import Path


def test_panel_modes_and_files_align():
    from tools.gen_help_screenshots import PANEL_MODES, PANEL_FILES
    assert PANEL_MODES == ("time", "fft", "fft_time", "order")
    # 每个 mode 都有对应的目标 *-panel.png 文件名
    assert set(PANEL_FILES) == set(PANEL_MODES)
    assert PANEL_FILES["time"] == "time-panel.png"
    assert PANEL_FILES["fft_time"] == "ffttime-panel.png"


def test_synthetic_csv_has_eps_channels():
    from tools.gen_help_screenshots import build_synthetic_csv
    path = build_synthetic_csv()
    assert path.exists()
    header = path.read_text(encoding="utf-8").splitlines()[0]
    # EPS-domain names matching the shipped assets (order base = 电机转速)
    for col in ("time", "电机转速", "方向盘扭矩", "电机扭矩"):
        assert col in header, f"synthetic CSV missing column: {col}"


def test_staging_dir_is_under_output_not_assets():
    from tools.gen_help_screenshots import STAGING_DIR, ASSETS_DIR
    assert STAGING_DIR.parts[-2:] == ("output", "help-shots")
    assert ASSETS_DIR.parts[-3:] == ("mf4_analyzer", "help", "assets")


def test_import_screenshot_uses_real_checked_in_samples():
    from tools.gen_help_screenshots import EXTRA_FILES, IMPORT_SAMPLES

    assert EXTRA_FILES == {"imports": "imports-panel.png"}
    assert [path.suffix for path in IMPORT_SAMPLES] == [".wwt", ".zfd", ".mat"]
    assert all(path.exists() for path in IMPORT_SAMPLES)


def test_analysis_wait_uses_job_service_not_retired_window_callbacks():
    source = (Path(__file__).resolve().parents[1] / "tools" /
              "gen_help_screenshots.py").read_text(encoding="utf-8")

    assert "_analysis_jobs.is_running(section)" in source
    assert "_on_fft_time_finished" not in source
    assert "_on_order_finished" not in source


def test_screenshot_generator_isolates_persistent_settings():
    source = (Path(__file__).resolve().parents[1] / "tools" /
              "gen_help_screenshots.py").read_text(encoding="utf-8")

    assert "_install_isolated_qsettings" in source
    assert "QSettings.IniFormat" in source
