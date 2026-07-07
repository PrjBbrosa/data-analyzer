from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_GUIDE = REPO_ROOT / "docs/analyzer/user-guide/acquisition-cockpit-guide.html"


def test_acquisition_user_guide_exists_with_operator_flow():
    html = DOC_GUIDE.read_text(encoding="utf-8")

    for text in (
        "MF4 采集 Cockpit 使用说明",
        "三击",
        "A2L",
        "传输",
        "采样事件",
        "批量",
        "1ms",
        "10ms",
        "Stop &amp; 复盘",
        "在 Analyzer 打开",
    ):
        assert text in html


def test_help_registry_includes_acquisition_guide():
    from mf4_analyzer.help import guide_path

    path = guide_path("acquisition")
    assert path.name == "acquisition-cockpit-guide.html"
    assert path.exists()


def test_cockpit_help_button_opens_acquisition_guide(qtbot, monkeypatch):
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

    opened: list[str] = []

    def fake_open_guide(name: str) -> bool:
        opened.append(name)
        return True

    monkeypatch.setattr("mf4_analyzer.help.open_guide", fake_open_guide)

    window = CockpitMainWindow()
    qtbot.addWidget(window)
    try:
        button = window.findChild(type(window._settings_btn), "cockpitHelpButton")
        assert button is not None
        button.click()
        assert opened == ["acquisition"]
    finally:
        window.close()
