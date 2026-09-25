"""macOS browsers cannot read a help page that still lives in Downloads."""
from pathlib import Path

import pytest

from mf4_analyzer.help import publish_help_for_browser


def test_publish_help_copies_page_and_asset_outside_the_source_tree(tmp_path):
    root = tmp_path / "Downloads" / "data analyzer" / "help"
    assets = root / "assets"
    assets.mkdir(parents=True)
    page = root / "TraceLab-使用说明.html"
    page.write_text("<img src='assets/shot.png'>使用说明", encoding="utf-8")
    (assets / "shot.png").write_bytes(b"png")

    published = publish_help_for_browser(
        page,
        root=root,
        dest_parent=tmp_path / "browser-temp",
    )

    assert published.is_file()
    assert not published.is_symlink()
    assert published.parent.parent == tmp_path / "browser-temp" / "tracelab-help"
    assert "Downloads" not in published.parts
    assert published.read_text(encoding="utf-8") == page.read_text(encoding="utf-8")
    assert (published.parent / "assets" / "shot.png").read_bytes() == b"png"


def test_open_guide_on_macos_opens_the_published_copy(monkeypatch, tmp_path):
    if __import__("sys").platform != "darwin":
        pytest.skip("macOS hands the published path to /usr/bin/open")
    import mf4_analyzer.help as help_module

    source = tmp_path / "help" / "TraceLab-使用说明.html"
    source.parent.mkdir()
    source.write_text("manual", encoding="utf-8")
    published = tmp_path / "visible" / "TraceLab-使用说明.html"
    published.parent.mkdir()
    published.write_text("manual", encoding="utf-8")
    opened = []

    monkeypatch.setattr(help_module, "guide_path", lambda name: source)
    monkeypatch.setattr(help_module, "publish_help_for_browser", lambda path: published)

    def fake_run(command, **kwargs):
        opened.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(help_module.subprocess, "run", fake_run)

    assert help_module.open_guide("manual") is True
    assert opened == [["/usr/bin/open", str(published)]]


def test_open_guide_reports_a_missing_file_without_publishing(monkeypatch, tmp_path):
    import mf4_analyzer.help as help_module

    monkeypatch.setattr(
        help_module,
        "guide_path",
        lambda name: tmp_path / "missing.html",
    )

    def fail_publish(path):
        raise AssertionError("missing help must not be published")

    monkeypatch.setattr(help_module, "publish_help_for_browser", fail_publish)
    assert help_module.open_guide("manual") is False
