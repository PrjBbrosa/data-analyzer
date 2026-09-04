from pathlib import Path


def test_panel_modes_and_files_align():
    from tools.gen_help_screenshots import PANEL_MODES, PANEL_FILES
    assert PANEL_MODES == ("time", "fft", "fft_time", "order", "ultraview")
    # 每个 mode 都有对应的目标 *-panel.png 文件名
    assert set(PANEL_FILES) == set(PANEL_MODES)
    assert PANEL_FILES["time"] == "time-panel.png"
    assert PANEL_FILES["fft_time"] == "ffttime-panel.png"
    assert PANEL_FILES["ultraview"] == "ultraview-panel.png"


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


def test_import_screenshot_builds_clean_checkout_parser_samples(tmp_path):
    from mf4_analyzer.io.loader import DataLoader
    from tools.gen_help_screenshots import (
        EXTRA_FILES, IMPORT_SAMPLE_SUFFIXES, build_import_samples,
    )

    assert EXTRA_FILES == {"imports": "imports-panel.png"}
    samples = build_import_samples(tmp_path)
    assert tuple(path.suffix for path in samples) == IMPORT_SAMPLE_SUFFIXES
    assert all(path.exists() for path in samples)
    for loader, path in zip(
        (DataLoader.load_wwt, DataLoader.load_zfd, DataLoader.load_mat), samples,
    ):
        assert loader(path), f"generated parser fixture did not load: {path.name}"

    source = (Path(__file__).resolve().parents[1] / "tools" /
              "gen_help_screenshots.py").read_text(encoding="utf-8")
    assert "testdoc" not in source


def test_analysis_wait_uses_job_service_not_retired_window_callbacks():
    source = (Path(__file__).resolve().parents[1] / "tools" /
              "gen_help_screenshots.py").read_text(encoding="utf-8")

    assert "_analysis_jobs.is_running(section)" in source
    assert "_analysis_jobs.finished.connect(on_finished)" in source
    assert "_attach_files_to_active_context" in source
    assert "_on_fft_time_finished" not in source
    assert "_on_order_finished" not in source


def test_screenshot_generator_isolates_persistent_settings():
    source = (Path(__file__).resolve().parents[1] / "tools" /
              "gen_help_screenshots.py").read_text(encoding="utf-8")

    assert "_install_isolated_qsettings" in source
    assert "QSettings.IniFormat" in source


def test_screenshot_generator_marks_demo_session_clean_before_close():
    source = (Path(__file__).resolve().parents[1] / "tools" /
              "gen_help_screenshots.py").read_text(encoding="utf-8")

    mark_clean = source.index("win._project_dirty.mark_saved()")
    close_window = source.index("win.close()")
    assert mark_clean < close_window
